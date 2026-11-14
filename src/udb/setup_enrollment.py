"""Resumable v2 private enrollment; all recovery secrets stay in Credential Manager."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from urllib.request import build_opener

from . import cloud_secrets, credentials
from .cloud_pair import NoRedirect, validate_origin
from .config import checked
from .onboarding import paired_cloud
from .private_enrollment import PRIVATE_RELAY, _request_json


class EnrollmentError(ValueError):
    pass


def missing_credential(error):
    return (
        isinstance(error, FileNotFoundError)
        or getattr(error, "winerror", None) == 1168
        or bool(error.args and error.args[0] == 1168)
    )


class PendingStore:
    def __init__(self, home):
        identity = str(checked(home)).casefold()
        self.target = (
            "UniversalDesktopBridge/Enrollment/"
            + hashlib.sha256(identity.encode()).hexdigest()
        )

    def load(self):
        try:
            encoded = credentials.load_key(target=self.target)
        except Exception as error:
            if missing_credential(error):
                return None
            raise
        try:
            value = json.loads(base64.urlsafe_b64decode(encoded).decode("ascii"))
            if (
                not isinstance(value, dict)
                or set(value) != {"id", "proof", "token", "relay"}
                or value["relay"] != PRIVATE_RELAY
                or len(value["proof"]) != 64
                or any(c not in "0123456789abcdef" for c in value["proof"])
            ):
                raise EnrollmentError()
            validate_origin(value["relay"], value["id"])
            cloud_secrets.validate_token(value["token"])
            return value
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise EnrollmentError(
                "Saved enrollment recovery is invalid; owner repair required"
            ) from None

    def save_new(self, value):
        if self.load() is not None:
            raise EnrollmentError("An enrollment is already pending; resume it instead")
        encoded = base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode("ascii")
        ).decode("ascii")
        credentials.save_key(encoded, target=self.target)


def commit_pairing(home, pending):
    """Never replace or delete an existing device credential or pairing file."""
    home = checked(home)
    pair = home / "cloud-pairing.json"
    if pair.exists():
        if paired_cloud(home) != (pending["relay"], pending["id"]):
            raise EnrollmentError("Existing pairing differs; refusing to overwrite")
    try:
        if (
            not cloud_secrets.on_windows()
            and not cloud_secrets.token_file(home).exists()
        ):
            existing = None
        else:
            existing = cloud_secrets.load_device_token(home, pending["id"])
    except Exception as error:
        if not missing_credential(error):
            raise
        existing = None
    if existing is not None and existing != pending["token"]:
        raise EnrollmentError(
            "Existing device credential differs; owner repair required"
        )
    if existing is None:
        cloud_secrets.save_device_token(home, pending["id"], pending["token"])
    if pair.exists():
        return
    home.mkdir(parents=True, exist_ok=True)
    temporary = checked(home / (".pairing-" + uuid.uuid4().hex + ".tmp"))
    try:
        with temporary.open("x", encoding="ascii") as stream:
            json.dump({"relay": pending["relay"], "device_id": pending["id"]}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-replace publication on Windows and Linux. Recovery retains
        # the same credential even if publication fails or the process dies.
        os.link(temporary, pair)
    finally:
        temporary.unlink(missing_ok=True)


def enroll(
    home,
    *,
    opener=None,
    store=None,
    browser=None,
    pause=time.sleep,
    clock=time.monotonic,
    wait=600,
):
    home = checked(home)
    if paired_cloud(home):
        raise EnrollmentError("Already paired; enrollment must not run")
    if cloud_secrets.token_file(home).exists():
        raise EnrollmentError(
            "Existing legacy credential detected; owner repair required"
        )
    store = store or PendingStore(home)
    opener = opener or build_opener(NoRedirect())
    pending = store.load()
    if pending is None:
        pending = {
            "id": secrets.token_hex(16),
            "proof": secrets.token_hex(32),
            "token": secrets.token_urlsafe(48),
            "relay": PRIVATE_RELAY,
        }
        store.save_new(pending)  # BEFORE any network side effect.
    relay, device_id = pending["relay"], pending["id"]
    fingerprint = hashlib.sha256(pending["proof"].encode("ascii")).hexdigest()
    status, result = _request_json(
        opener,
        relay + "/v1/setup/enrollments",
        method="POST",
        data={
            "request_id": device_id,
            "request_secret_sha256": fingerprint,
            "device_token_sha256": hashlib.sha256(
                pending["token"].encode("ascii")
            ).hexdigest(),
            "device_name": "Windows UDB",
        },
    )
    if (
        status != 201
        or not isinstance(result, dict)
        or result.get("device_id") != device_id
    ):
        raise EnrollmentError("Enrollment response did not match the saved request")
    print("Approve this Windows device in your browser.")
    print("Device: " + device_id + "  Fingerprint: " + fingerprint[:10].upper())
    approval_url = (
        relay
        + "/v1/setup/enrollments/"
        + device_id
        + "/approval?code="
        + fingerprint[:10].upper()
    )
    if browser and not browser(approval_url):
        print("Open the owner approval page: " + approval_url)
    deadline = clock() + wait
    while clock() < deadline:
        _, state = _request_json(
            opener,
            relay + "/v1/setup/enrollments/" + device_id + "/status",
            proof=pending["proof"],
        )
        if not isinstance(state, dict) or state.get("device_id") != device_id:
            raise EnrollmentError("Enrollment status did not match this Windows device")
        if state.get("state") == "approved":
            commit_pairing(home, pending)
            return device_id
        if state.get("state") == "rejected":
            raise EnrollmentError(
                "Owner rejected this device; no pairing or permission was saved"
            )
        if state.get("state") not in ("pending", "registering"):
            raise EnrollmentError("Unexpected enrollment state; saved request retained")
        pause(min(4, max(0, deadline - clock())))
    raise TimeoutError("Approval is still pending. Run udb setup again to resume.")
