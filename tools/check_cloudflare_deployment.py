"""Read-only live Cloudflare readiness check. No admin/device/OAuth token sent.

This verifies HTTP routing and OAuth challenge only. It does NOT prove a Windows
device, local UDB grant, ChatGPT login or command execution is connected.
"""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from udb.cloud_agent import device_url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(relay: str, device_id: str, opener=None) -> dict:
    # Refuse non-Cloudflare origins before sending even an unauthenticated probe.
    device_url(relay, device_id)
    origin = relay.rstrip("/")
    opener = opener or build_opener(NoRedirect())
    resource = origin + "/v1/devices/" + device_id + "/mcp"
    metadata = origin + "/.well-known/oauth-protected-resource/v1/devices/" + device_id + "/mcp"
    report = {
        "health": "unverified",
        "oauth_metadata": "unverified",
        "unauthorized_access": "unverified",
        "windows_device": "not_tested",
        "chatgpt_oauth": "not_tested",
    }

    def read_json(url):
        with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=8) as response:
            if response.status != 200:
                raise ValueError("Unexpected HTTP status")
            data = response.read(2049)
            if len(data) > 2048:
                raise ValueError("Oversized health or metadata response")
            return json.loads(data)

    if read_json(origin + "/health") != {
        "status": "ok",
        "kind": "private-relay-prototype",
    }:
        raise ValueError("Unexpected Cloudflare health response")
    report["health"] = "ok"
    metadata_value = read_json(metadata)
    if metadata_value.get("resource") != resource or not metadata_value.get(
        "authorization_servers"
    ):
        raise ValueError("Invalid OAuth protected resource metadata")
    report["oauth_metadata"] = "ok"

    request = Request(
        resource,
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener.open(request, timeout=8)
    except HTTPError as exc:
        if exc.code != 401 or "resource_metadata=" not in exc.headers.get(
            "WWW-Authenticate", ""
        ):
            raise ValueError("Unauthenticated MCP request was not blocked") from None
    else:
        raise ValueError("Unauthenticated MCP request unexpectedly succeeded")
    report["unauthorized_access"] = "blocked"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", required=True, help="https://name.workers.dev")
    parser.add_argument("--device-id", required=True, help="32-character device ID")
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.relay, args.device_id), indent=2))
        return 0
    except (ValueError, HTTPError, URLError, OSError) as exc:
        print(json.dumps({"result": "failed", "reason": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
