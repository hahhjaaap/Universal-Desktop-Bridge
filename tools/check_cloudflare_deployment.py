"""Read-only Cloudflare relay/OAuth preflight: never sends credentials.

It checks public HTTP routing and unauthenticated denial only, not an actual
Windows device, local permission, OAuth consent, or ChatGPT tool invocation.
"""

from __future__ import annotations

import argparse
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from udb.cloud_agent import CLOUD_USER_AGENT, device_url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(relay: str, device_id: str, opener=None, *, auth_mode="jwt") -> dict:
    if auth_mode not in {"jwt", "cloudflare-access"}:
        raise ValueError("Unknown authentication mode")
    # Reject unexpected origins before making any unauthenticated network call.
    device_url(relay, device_id)
    origin = relay.rstrip("/")
    opener = opener or build_opener(NoRedirect())
    resource = origin + "/v1/devices/" + device_id + "/mcp"
    metadata = (
        origin
        + "/.well-known/oauth-protected-resource/v1/devices/"
        + device_id
        + "/mcp"
    )
    report = {
        "auth_mode_checked": auth_mode,
        "health": "unverified",
        "oauth_metadata": "unverified",
        "unauthorized_access": "unverified",
        "windows_device": "not_tested",
        "chatgpt_oauth": "not_tested",
    }

    def read_json(url):
        with opener.open(
            Request(
                url,
                headers={"Accept": "application/json", "User-Agent": CLOUD_USER_AGENT},
            ),
            timeout=8,
        ) as response:
            if response.status != 200:
                raise ValueError("Unexpected HTTP status")
            data = response.read(2049)
            if len(data) > 2048:
                raise ValueError("Oversized health or metadata response")
            return json.loads(data), getattr(response, "headers", {})

    health, headers = read_json(origin + "/health")
    if health != {"status": "ok", "kind": "private-relay-prototype"}:
        raise ValueError("Unexpected Cloudflare health response")
    report["health"] = "ok"

    if auth_mode == "jwt":
        metadata_value, _ = read_json(metadata)
        if metadata_value.get("resource") != resource or not metadata_value.get(
            "authorization_servers"
        ):
            raise ValueError("Invalid OAuth protected resource metadata")
        report["oauth_metadata"] = "ok"
    else:
        if headers.get("X-UDB-Access-OAuth-Capable") != "1":
            raise ValueError("Access-aware Worker code has not been deployed")
        # Cloudflare owns managed-OAuth discovery at the edge, not the Worker's
        # manually configured external RS256-JWT resource metadata.
        report["oauth_metadata"] = "edge_challenge_required"

    request = Request(
        resource,
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={
            "Content-Type": "application/json",
            "User-Agent": CLOUD_USER_AGENT,
        },
        method="POST",
    )
    try:
        opener.open(request, timeout=8)
    except HTTPError as exc:
        challenge = exc.headers.get("WWW-Authenticate", "")
        if exc.code != 401 or "resource_metadata=" not in challenge:
            raise ValueError("Expected OAuth authentication challenge") from None
        if auth_mode == "cloudflare-access":
            # A 403, an internal JWT challenge, or a fake string containing
            # "cloudflare" cannot establish Managed OAuth readiness. Fetch
            # the well-known resource document from this same HTTPS origin.
            match = re.search(r'resource_metadata="([^"]+)"', challenge)
            if not match:
                raise ValueError("Missing Cloudflare resource metadata URL") from None
            metadata_url = match.group(1)
            parsed = urlsplit(metadata_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != urlsplit(origin).netloc
                or parsed.path != "/.well-known/cloudflare-access-protected-resource/"
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Untrusted Cloudflare resource metadata URL") from None
            access_metadata, _ = read_json(metadata_url)
            if not isinstance(access_metadata, dict):
                raise ValueError("Invalid Cloudflare Access metadata type") from None
            team = access_metadata.get("team_domain")
            if not isinstance(team, str):
                raise ValueError("Missing Cloudflare Access team domain") from None
            team_host = team.removeprefix("https://")
            if not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com",
                team_host,
            ):
                raise ValueError("Invalid Cloudflare Access team domain") from None
            servers = access_metadata.get("authorization_servers")
            if not isinstance(servers, list) or not all(
                isinstance(value, str) for value in servers
            ):
                raise ValueError("Invalid Cloudflare authorization servers") from None
            resource_id = access_metadata.get("resource")
            if (
                access_metadata.get("protected") is not True
                or not isinstance(resource_id, str)
                or resource_id not in {origin, resource}
                or "https://" + team_host not in servers
            ):
                raise ValueError(
                    "Invalid Cloudflare Access resource metadata"
                ) from None
            report["oauth_metadata"] = "cloudflare_access_metadata"
    else:
        raise ValueError("Unauthenticated MCP request unexpectedly succeeded")
    report["unauthorized_access"] = "blocked"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", required=True, help="https://name.workers.dev")
    parser.add_argument("--device-id", required=True, help="32-character device ID")
    parser.add_argument(
        "--auth-mode",
        choices=("jwt", "cloudflare-access"),
        default="jwt",
        help="Identity layer to check (default: jwt)",
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                check(args.relay, args.device_id, auth_mode=args.auth_mode), indent=2
            )
        )
        return 0
    except (ValueError, HTTPError, URLError, OSError) as exc:
        print(json.dumps({"result": "failed", "reason": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
