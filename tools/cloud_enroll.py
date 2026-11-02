"""Attended developer-only bootstrap for the private Cloudflare relay.

This is not the final one-click OAuth enrollment. Keep UDB_ADMIN_KEY secret;
the local user's device token is written only after server registration succeeds.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from udb.cloud_pair import NoRedirect, validate_origin
from udb.cloud_secrets import remove_device_token, save_device_token


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay", required=True, help="https://<worker>.workers.dev")
    parser.add_argument(
        "--home",
        default=os.path.join(
            os.environ.get("LOCALAPPDATA", str(Path.home())), "UniversalDesktopBridge"
        ),
    )
    args = parser.parse_args()
    try:
        relay = validate_origin(args.relay, "0" * 32)
    except ValueError:
        parser.error("Expected a plain HTTPS workers.dev relay origin")
    secret = os.environ.get("UDB_ADMIN_KEY") or getpass.getpass(
        "Owner admin key (hidden): "
    )
    if len(secret) < 32:
        parser.error("Admin secret must have at least 32 characters")
    home = Path(args.home)
    token_path = home / "cloud-device-token"
    pairing_path = home / "cloud-pairing.json"
    if token_path.exists() or pairing_path.exists():
        raise RuntimeError("Existing pairing found; refusing to overwrite credentials")
    device_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(48)
    body = json.dumps(
        {"device_token_sha256": hashlib.sha256(token.encode()).hexdigest()}
    ).encode()
    request = Request(
        relay + "/v1/admin/devices/" + device_id,
        data=body,
        method="PUT",
        headers={
            "Authorization": "Bearer " + secret,
            "Content-Type": "application/json",
        },
    )
    try:
        # The shared admin bearer must never follow a server redirect.
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200 or not json.load(response).get("registered"):
                raise RuntimeError("Cloudflare enrollment was not confirmed")
    except HTTPError as error:
        raise RuntimeError("Enrollment rejected: HTTP " + str(error.code)) from None
    except OSError:
        raise RuntimeError(
            "Enrollment outcome unknown; check and revoke remote registration "
            "before retrying."
        ) from None
    home.mkdir(parents=True, exist_ok=True)
    try:
        save_device_token(home, device_id, token)
        with pairing_path.open("x", encoding="utf-8") as file:
            json.dump({"relay": relay, "device_id": device_id}, file)
    except BaseException:
        remove_device_token(home, device_id)
        pairing_path.unlink(missing_ok=True)
        raise
    print("Device enrolled. Run: udb cloud-agent")
    print("Token was saved privately under the current user's UDB home.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
