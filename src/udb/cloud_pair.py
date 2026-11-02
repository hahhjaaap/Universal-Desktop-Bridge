"""Owner-attended one-time pairing without sharing the cloud administrator key.

This is a temporary CLI enrollment workflow, not the final GUI/OAuth flow.
No local UDB computer permissions are granted by pairing.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import secrets
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .cloud_agent import device_url
from .cloud_secrets import remove_device_token, save_device_token

_HEX64 = re.compile(r"[a-f0-9]{64}\Z")


class NoRedirect(HTTPRedirectHandler):
    """Never follow remote redirects with a bearer pairing code."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_origin(value: str, device_id: str) -> str:
    """Only Cloudflare TLS endpoints are accepted by this prototype."""
    device_url(value, device_id)
    parsed = urlsplit(value)
    if not parsed.hostname or not parsed.hostname.endswith(".workers.dev"):
        raise ValueError("Pairing requires an HTTPS Cloudflare workers.dev origin")
    return value.rstrip("/")


def claim_device(
    home: Path,
    relay: str,
    device_id: str,
    pairing_code: str,
    opener=None,
) -> None:
    """Claim once, then save the random per-device token in owner-local storage."""
    relay = validate_origin(relay, device_id)
    if not _HEX64.fullmatch(pairing_code):
        raise ValueError("Invalid pairing invitation")
    home = Path(home)
    token_path = home / "cloud-device-token"
    pairing_path = home / "cloud-pairing.json"
    if token_path.exists() or pairing_path.exists():
        raise ValueError("UDB is already paired on this Windows profile")
    home.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    request = Request(
        relay + "/v1/devices/" + device_id + "/claim",
        data=json.dumps({"device_token_sha256": digest}).encode("ascii"),
        method="POST",
        headers={
            "Authorization": "Bearer " + pairing_code,
            "Content-Type": "application/json",
        },
    )
    opener = opener if opener is not None else build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            result = json.load(response)
            if response.status != 201 or result != {"registered": True}:
                raise ValueError("Cloud pairing was not confirmed")
    except HTTPError as error:
        raise ValueError(
            "Cloud pairing rejected. Invitation may be expired or used."
        ) from error
    # The remote claim is now consumed. Never replay it after a write failure.
    try:
        save_device_token(home, device_id, token)
        with pairing_path.open("x", encoding="utf-8") as stream:
            json.dump({"relay": relay, "device_id": device_id}, stream)
    except BaseException:
        remove_device_token(home, device_id)
        pairing_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Local storage failed after pairing; administrator must revoke the device."
        ) from None


def run(settings) -> int:
    """Run only in an attended local terminal; never accept codes via CLI args."""
    print("UDB Cloud: pair a device using a one-time invitation from its owner.")
    relay = input("Cloudflare Worker HTTPS origin: ").strip()
    device_id = input("Invitation device ID: ").strip()
    code = getpass.getpass("One-time pairing code (hidden): ").strip()
    claim_device(settings.home, relay, device_id, code)
    print("Device paired. Run 'udb cloud-agent' to test the private relay.")
    print("No Windows access or ChatGPT plugin permissions were changed.")
    return 0
