"""Compare public Worker capabilities without reading secrets or changing pairing.

This developer diagnostic issues at most two unauthenticated GET /health
requests. It does not probe device paths or authenticate ChatGPT/Windows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from udb.cloud_agent import CLOUD_USER_AGENT, device_url
from udb.cloud_preflight import NoRedirect
from udb.config import default_home
from udb.owner_command import CommandError, read_object


def _origin(value: str, *, staging: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 500 or value.strip() != value:
        raise ValueError("invalid_relay")
    try:
        url = urlsplit(value)
        host = url.hostname
        if (
            url.scheme != "https"
            or host is None
            or not host.endswith(".workers.dev")
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.port not in (None, 443)
        ):
            raise ValueError("invalid_relay")
        # A dedicated staging Worker is required; never probe production
        # using an argument accidentally passed as "staging".
        if staging and "staging" not in host.split(".")[0].split("-"):
            raise ValueError("invalid_staging_relay")
    except ValueError:
        raise ValueError("invalid_staging_relay" if staging else "invalid_relay") from None
    return f"https://{host}"


def _public_health(opener, origin: str) -> dict[str, str]:
    report = {
        "health": "unverified",
        "project_read": "unverified",
        "access_oauth": "unverified",
    }
    try:
        with opener.open(
            Request(
                origin + "/health",
                headers={"Accept": "application/json", "User-Agent": CLOUD_USER_AGENT},
                method="GET",
            ),
            timeout=8,
        ) as response:
            if response.status != 200:
                return report
            body = response.read(2049)
            if len(body) > 2048 or json.loads(body) != {
                "status": "ok",
                "kind": "private-relay-prototype",
            }:
                return report
            headers = getattr(response, "headers", {})
            return {
                "health": "ok",
                "project_read": (
                    "advertised"
                    if headers.get("X-UDB-Project-Read-Capable") == "1"
                    else "not_advertised"
                ),
                "access_oauth": (
                    "advertised"
                    if headers.get("X-UDB-Access-OAuth-Capable") == "1"
                    else "not_advertised"
                ),
            }
    except (HTTPError, URLError, OSError, ValueError, TypeError, UnicodeError):
        return report


def compare(home: Path, staging_relay: str, opener=None) -> dict:
    """Never emit relay hosts, project names, device IDs or file contents."""
    staging = _origin(staging_relay, staging=True)
    try:
        pairing = read_object(home / "cloud-pairing.json", 2048)
        relay, device_id = pairing["relay"], pairing["device_id"]
        device_url(relay, device_id)  # Existing Cloud Agent validation.
        paired = _origin(relay)
    except (OSError, ValueError, TypeError, KeyError, CommandError):
        return {
            "result": "failed",
            "reason": "pairing_missing_or_invalid",
            "authenticated_read": "not_tested",
        }

    opener = opener or build_opener(NoRedirect())
    same = paired == staging
    stage_health = _public_health(opener, staging)
    paired_health = stage_health if same else _public_health(opener, paired)
    return {
        "result": "public_health_compared",
        "pairing_matches_staging": same,
        "staging_worker": stage_health,
        "paired_worker": paired_health,
        "next_stage": (
            "verify_authenticated_staging_read"
            if same and stage_health["project_read"] == "advertised"
            else "create_separate_staging_pairing"
            if not same
            else "review_staging_worker_deployment"
        ),
        "authenticated_read": "not_tested",
        "device_owner": "not_tested",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staging-relay", required=True, help="Dedicated staging workers.dev origin"
    )
    parser.add_argument("--home", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        result = compare(args.home or default_home(), args.staging_relay)
    except ValueError:
        result = {"result": "failed", "reason": "invalid_staging_relay"}
    print(json.dumps(result, indent=2))
    return 0 if result["result"] == "public_health_compared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
