"""Approve UDB private enrollment on a TRUSTED administrator workstation.

This tool never writes the UDB admin key to disk/arguments/logs; it is not
included in an end-user installer. Match the code displayed by the *physical*
new machine before approving. No device/ChatGPT permission is granted here.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from udb.cloud_pair import NoRedirect
from udb.private_enrollment import PRIVATE_RELAY

DEVICE_ID = re.compile(r"[a-f0-9]{32}\Z")
CODE = re.compile(r"[A-F0-9]{10}\Z")


def request_admin(method, path, key, *, body=None, opener=None):
    url = PRIVATE_RELAY + path
    headers = {
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "User-Agent": "UDB-Private-Enrollment-Admin/1",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        url,
        method=method,
        headers=headers,
        data=None if body is None else json.dumps(body).encode("ascii"),
    )
    with (opener or build_opener(NoRedirect())).open(request, timeout=20) as response:
        raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError("Oversized relay response")
        return response.status, json.loads(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description="UDB relay owner approval (private)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List pending device requests")
    group.add_argument("--approve", metavar="DEVICE_ID", help="Approve one device")
    group.add_argument("--reject", metavar="DEVICE_ID", help="Deny a pending request")
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("Use an attended administrator terminal, not an unattended script.", file=sys.stderr)
        return 2
    device_id = args.approve or args.reject
    if device_id and not DEVICE_ID.fullmatch(device_id):
        print("Invalid device ID.", file=sys.stderr)
        return 2
    print("Relay: " + PRIVATE_RELAY)
    key = getpass.getpass("Relay administrator key (hidden, not saved): ")
    if len(key) < 32 or any(c.isspace() for c in key):
        print("Invalid administrator credential.", file=sys.stderr)
        return 2
    try:
        if args.list:
            status, response = request_admin("GET", "/v1/admin/enrollments", key)
            if status != 200:
                return 2
            for item in response.get("requests", []):
                print(
                    item["device_id"] + "  " + item["device_name"] +
                    "  [" + item["state"] + "]"
                )
            return 0
        if args.approve:
            print("Compare this device ID and the 10-character code on the NEW Windows machine.")
            code = input("Verification code shown on that machine: ").strip().upper()
            if not CODE.fullmatch(code):
                print("Invalid verification code.", file=sys.stderr)
                return 2
            status, result = request_admin(
                "POST", "/v1/admin/enrollments/" + device_id + "/approve",
                key, body={"code": code},
            )
            if status == 200 and result == {"approved": True, "device_id": device_id}:
                print("Approved. Windows will finish securely without an invitation code.")
                return 0
            return 2
        confirmation = input("Type REJECT to deny this pending device: ").strip()
        if confirmation != "REJECT":
            print("Canceled.")
            return 2
        status, data = request_admin(
            "DELETE", "/v1/admin/enrollments/" + device_id, key,
        )
        if status == 200 and data == {"rejected": True}:
            print("Request rejected.")
            return 0
        return 2
    except HTTPError as error:
        print(
            f"Relay rejected request (HTTP {error.code}); no automatic retry.",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print("Relay response unavailable or invalid; verify before retry.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
