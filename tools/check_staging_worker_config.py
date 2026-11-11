"""Offline, fail-closed verification that both Wrangler configs target one UDB gateway.

Never calls Wrangler, Cloudflare APIs, a local UDB agent, or the network.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIMARY = ROOT / "cloudflare" / "wrangler.jsonc"
DEFAULT_STAGING = ROOT / "cloudflare" / "wrangler.staging.jsonc"
EXPECTED_STAGING_NAME = "udb-private-relay-staging"
ALLOWED_STAGING_KEYS = {
    "$schema",
    "name",
    "main",
    "compatibility_date",
    "workers_dev",
    "durable_objects",
    "migrations",
}


def _load_config(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError("Invalid Worker configuration")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid Worker configuration")
    return value


def check_config(staging_path: Path, primary_path: Path) -> dict:
    staging = _load_config(staging_path)
    primary = _load_config(primary_path)
    if (
        set(staging) != ALLOWED_STAGING_KEYS
        or set(primary) != ALLOWED_STAGING_KEYS
        or staging.get("name") != EXPECTED_STAGING_NAME
        or primary.get("name") != EXPECTED_STAGING_NAME
        or staging.get("workers_dev") is not True
        or staging.get("main") != "src/index.js"
        or primary != staging
    ):
        raise ValueError("Unsafe staging deployment configuration")
    if staging["durable_objects"] != {
        "bindings": [{"name": "DEVICES", "class_name": "DeviceRelay"}]
    } or staging["migrations"] != [
        {"tag": "v1", "new_sqlite_classes": ["DeviceRelay"]}
    ]:
        raise ValueError("Unexpected staging Durable Object binding")
    return {
        "result": "staging_configuration_safe",
        "worker": EXPECTED_STAGING_NAME,
        "deployed": False,
        "oauth_verified": False,
        "authenticated_project_read_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-config", type=Path, default=DEFAULT_STAGING)
    parser.add_argument(
        "--primary-config", "--production-config",
        dest="primary_config", type=Path, default=DEFAULT_PRIMARY,
    )
    args = parser.parse_args()
    try:
        result = check_config(args.staging_config, args.primary_config)
    except (OSError, ValueError, TypeError):
        print(json.dumps({"result": "failed", "reason": "unsafe_staging_config"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
