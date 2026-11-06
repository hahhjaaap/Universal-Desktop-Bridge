"""Offline, fail-closed summary of owner-attended P0-B staging acceptance.

This checks a *redacted evidence checklist*, not the truth of a live OAuth
session. It never connects to Cloudflare or prints submitted identifiers.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MAX_BYTES = 16384
NETWORKS = ("network_a", "network_b", "network_c")
DENIALS = (
    "wrong_identity",
    "wrong_device",
    "protected_path",
    "revoked_grant",
    "write_or_desktop",
)
FLAGS = (
    "owner_attended",
    "verified_oauth_chatgpt_read",
    "fixture_content_sha256_match",
    "only_granted_read_tools_listed",
    "two_owners_verified",
    "two_devices_verified",
    "reconnect_without_replay",
    "ten_concurrent_reads_matched",
    "eleventh_concurrent_read_rejected",
    "mutations_exclusive",
)
TOP_KEYS = {
    "schema_version",
    "environment",
    "source_commit",
    "worker_revision",
    "checks",
    "denials",
    "networks",
}


def _valid_revision(value: object, *, length: int) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]+", value) is not None
        and length <= len(value) <= (40 if length == 40 else 64)
        and any(ch != "0" for ch in value)
    )


def evaluate(report: object) -> dict:
    """Return only constant, audited labels; never echo submitted values."""
    if not isinstance(report, dict) or set(report) != TOP_KEYS:
        return {"result": "invalid", "reason": "schema_mismatch"}
    if (
        type(report["schema_version"]) is not int
        or report["schema_version"] != 1
        or report["environment"] != "isolated-staging"
        or not _valid_revision(report["source_commit"], length=40)
        or not _valid_revision(report["worker_revision"], length=8)
    ):
        return {"result": "invalid", "reason": "invalid_identity_or_environment"}
    checks = report["checks"]
    denials = report["denials"]
    networks = report["networks"]
    if (
        not isinstance(checks, dict)
        or set(checks) != set(FLAGS)
        or not all(type(value) is bool for value in checks.values())
        or not isinstance(denials, dict)
        or set(denials) != set(DENIALS)
        or not all(type(value) is bool for value in denials.values())
        or not isinstance(networks, dict)
        or set(networks) != set(NETWORKS)
    ):
        return {"result": "invalid", "reason": "invalid_checklist"}
    for value in networks.values():
        if (
            not isinstance(value, dict)
            or set(value) != {"attempted", "matched"}
            or type(value["attempted"]) is not int
            or type(value["matched"]) is not int
            or not 0 <= value["matched"] <= value["attempted"] <= 10000
        ):
            return {"result": "invalid", "reason": "invalid_network_counts"}

    missing = [name for name in FLAGS if not checks[name]]
    missing.extend(name for name in DENIALS if not denials[name])
    missing.extend(
        name
        for name in NETWORKS
        if networks[name]["attempted"] < 30
        or networks[name]["matched"] != networks[name]["attempted"]
    )
    return {
        "result": "checklist_complete" if not missing else "blocked",
        "missing_checks": missing,
        "note": "Self-reported staging checklist only; independent review and live evidence still required.",
    }


def run(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return {"result": "invalid", "reason": "invalid_file"}
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            return {"result": "invalid", "reason": "invalid_file"}
        return evaluate(json.loads(raw))
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        return {"result": "invalid", "reason": "unreadable_file"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report", type=Path, help="Owner-reviewed redacted JSON checklist"
    )
    args = parser.parse_args(argv)
    result = run(args.report)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "checklist_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
