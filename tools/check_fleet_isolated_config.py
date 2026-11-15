"""Fail-closed check for the opt-in, physically isolated Fleet staging Worker.

Read-only: no Wrangler, Cloudflare API, credential, network or deployment actions.
The isolated Worker must never reuse the existing live script name, DO binding,
external script namespace, route, or runtime secrets from the source config.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.check_staging_worker_config import (
    ALLOWED_STAGING_KEYS,
    DEFAULT_PRIMARY,
    DEFAULT_STAGING,
    _load_config,
    check_config,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISOLATED = ROOT / "cloudflare" / "wrangler.fleet-isolated-staging.jsonc"
ISOLATED_NAME = "udb-fleet-isolated-staging"


def check_isolated_config(
    isolated: Path = DEFAULT_ISOLATED,
    staging: Path = DEFAULT_STAGING,
    primary: Path = DEFAULT_PRIMARY,
) -> dict:
    # First confirm the original/live staging contract has not been changed.
    check_config(staging, primary)
    config = _load_config(isolated)
    main = _load_config(staging)
    if (
        set(config) != ALLOWED_STAGING_KEYS
        or config["name"] != ISOLATED_NAME
        or config["name"] == main["name"]
        or config["main"] != main["main"]
        or config["compatibility_date"] != main["compatibility_date"]
        or config["workers_dev"] is not True
        or config["durable_objects"]
        != {"bindings": [{"name": "DEVICES", "class_name": "DeviceRelay"}]}
        or config["migrations"]
        != [{"tag": "v1", "new_sqlite_classes": ["DeviceRelay"]}]
    ):
        raise ValueError("Unsafe isolated Fleet configuration")
    # A new Worker script and an unshared new_sqlite_classes migration are
    # required. No script_name link to the live DO namespace is permitted.
    return {
        "result": "isolated_fleet_configuration_safe",
        "worker": ISOLATED_NAME,
        "runtime_flags_enabled": False,
        "deployed": False,
        "oauth_verified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated-config", type=Path, default=DEFAULT_ISOLATED)
    args = parser.parse_args(argv)
    try:
        report = check_isolated_config(args.isolated_config)
    except (OSError, TypeError, ValueError, KeyError):
        print(json.dumps({"result": "failed", "reason": "unsafe_fleet_isolation"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
