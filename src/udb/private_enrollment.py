"""Owner-approved private Windows onboarding without a one-time invite code.

The Windows machine creates its own enrollment proof and device token. Only a
separately authenticated relay administrator may approve a request. No admin
key, OAuth grant, approval action or terminal/desktop permission is embedded.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .cloud_agent import CLOUD_USER_AGENT
from .cloud_pair import NoRedirect, validate_origin
from .cloud_secrets import remove_device_token, save_device_token
from .onboarding import attended_console, paired_cloud

# The *address* is not a secret. Server enrollment remains OFF by default.
PRIVATE_RELAY = "https://udb-private-relay-staging.hkhoinguyen72.workers.dev"
ENROLLMENT_SECONDS = 600


def _request_json(opener, url, *, method="GET", data=None, proof=None):
    headers = {"User-Agent": CLOUD_USER_AGENT, "Accept": "application/json"}
    if proof:
        headers["Authorization"] = "Bearer " + proof
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        url,
        method=method,
        headers=headers,
        data=None if data is None else json.dumps(data).encode("ascii"),
    )
    with opener.open(request, timeout=20) as response:
        body = response.read(4097)
        if len(body) > 4096:
            raise ValueError("Oversized enrollment response")
        return response.status, json.loads(body)


def enroll_device(home: Path, relay=PRIVATE_RELAY, *, opener=None, pause=None):
    """Register a new device only after a server-side owner approval.

    No retries after an ambiguous approval response, and no local token until
    remote registration is confirmed. Device token is never sent in plaintext.
    """
    if not attended_console():
        raise ValueError("Enrollment requires a local Windows console with an owner")
    home = Path(home)
    if paired_cloud(home) or (home / "cloud-pairing.json").exists():
        raise ValueError("This Windows profile is already paired; do not overwrite it")
    if (home / "cloud-device-token").exists():
        raise ValueError("Existing device credential detected; revoke/repair before retry")
    relay = validate_origin(relay, "0" * 32)
    opener = opener or build_opener(NoRedirect())
    pause = pause or time.sleep

    secret = secrets.token_hex(32)
    request_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    # Friendly and ASCII-only, never transmit the Windows username or home path.
    status, result = _request_json(
        opener,
        relay + "/v1/enrollments",
        method="POST",
        data={
            "request_secret_sha256": request_hash,
            "device_token_sha256": token_hash,
            "device_name": "Windows UDB",
        },
    )
    if status != 201 or not isinstance(result, dict) or result.get("state") != "pending":
        raise ValueError("Relay did not accept a new enrollment request")
    device_id = result.get("device_id")
    if not isinstance(device_id, str):
        raise ValueError("Invalid enrollment response")
    # Existing device_url validates hexadecimal IDs; never let the relay
    # control the destination for Credential Manager or a local file.
    validate_origin(relay, device_id)
    approval_code = request_hash[:10].upper()
    print("UDB enrollment request sent; owner approval required.")
    print("Device ID: " + device_id)
    print("Verification code (show ONLY to the relay administrator): " + approval_code)
    print("No administrator key or invitation is required on this Windows machine.")
    deadline = time.monotonic() + ENROLLMENT_SECONDS
    while time.monotonic() < deadline:
        pause(min(4.0, max(0.0, deadline - time.monotonic())))
        try:
            status, state = _request_json(
                opener,
                relay + "/v1/enrollments/" + device_id + "/status",
                proof=secret,
            )
        except HTTPError as exc:
            if exc.code in (403, 404, 410):
                raise ValueError("Enrollment rejected, disabled or expired") from None
            raise RuntimeError("Enrollment status unknown; verify with administrator") from None
        except (OSError, ValueError, URLError):
            raise RuntimeError("Enrollment status unknown; check the device before retrying") from None
        if status != 200 or not isinstance(state, dict) or state.get("device_id") != device_id:
            raise RuntimeError("Invalid enrollment state")
        if state.get("state") == "pending":
            continue
        if state.get("state") == "approved":
            try:
                save_device_token(home, device_id, token)
                pairing = home / "cloud-pairing.json"
                home.mkdir(parents=True, exist_ok=True)
                with pairing.open("x", encoding="utf-8") as stream:
                    json.dump({"relay": relay, "device_id": device_id}, stream)
                    stream.write("\n")
            except BaseException:
                remove_device_token(home, device_id)
                (home / "cloud-pairing.json").unlink(missing_ok=True)
                raise RuntimeError(
                    "Local credential save failed; ask the administrator to revoke the device"
                ) from None
            print("Device approved and locally paired. ChatGPT OAuth is still required.")
            return device_id
        if state.get("state") == "registering":
            continue
        raise ValueError("Enrollment was rejected or could not complete")
    raise TimeoutError("Enrollment approval expired; ask administrator to check first")


def run(settings, relay=PRIVATE_RELAY) -> int:
    try:
        enroll_device(settings.home, relay)
    except (ValueError, RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        # Do not print low-level HTTP details or request/device secrets.
        print("UDB: enrollment incomplete. " + str(exc))
        return 2
    return 0
