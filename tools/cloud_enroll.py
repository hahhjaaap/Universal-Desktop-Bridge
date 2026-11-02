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
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay", required=True, help="https://<worker>.workers.dev")
    parser.add_argument("--home", default=os.path.join(os.environ.get(
        "LOCALAPPDATA", str(Path.home())), "UniversalDesktopBridge"))
    args = parser.parse_args()
    url = urlsplit(args.relay)
    if (url.scheme != "https" or url.path not in ("", "/") or url.query or url.fragment
            or url.username or url.password or not url.hostname or url.port not in (None, 443)):
        parser.error("Expected a plain HTTPS Cloudflare relay origin")
    secret = os.environ.get("UDB_ADMIN_KEY") or getpass.getpass("Owner admin key (hidden): ")
    if len(secret) < 32:
        parser.error("Admin secret must have at least 32 characters")
    device_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(48)
    body = json.dumps({"device_token_sha256": hashlib.sha256(token.encode()).hexdigest()}).encode()
    request = Request(args.relay.rstrip("/") + "/v1/admin/devices/" + device_id,
        data=body, method="PUT", headers={"Authorization": "Bearer " + secret,
            "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 200 or not json.load(response).get("registered"):
                raise RuntimeError("Cloudflare enrollment was not confirmed")
    except HTTPError as error:
        raise RuntimeError("Enrollment rejected: HTTP " + str(error.code)) from None
    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    token_path = home / "cloud-device-token"
    pairing_path = home / "cloud-pairing.json"
    if token_path.exists() or pairing_path.exists():
        raise RuntimeError("Existing pairing found; refusing to overwrite credentials")
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as file:
        file.write(token + "\n")
    try:
        with pairing_path.open("x", encoding="utf-8") as file:
            json.dump({"relay": args.relay.rstrip("/"), "device_id": device_id}, file)
    except BaseException:
        token_path.unlink(missing_ok=True)
        raise
    print("Device enrolled. Run: udb cloud-agent")
    print("Token was saved privately under the current user's UDB home.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
