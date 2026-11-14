#!/usr/bin/env python3
"""Export the authoritative Windows MCP tool schemas for the Cloudflare fleet gateway.

The generated JSON is checked into cloudflare/src so Worker discovery never
needs a live Windows device or a second hand-maintained schema inventory.
Run with --write after changing a native/Companion tool schema; CI uses --check.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from udb.registry import catalog  # noqa: E402

OUTPUT = ROOT / "cloudflare" / "src" / "fleet-tool-catalog.json"


def render() -> str:
    tools = catalog()["tools"]
    names = [tool.get("name") for tool in tools]
    if not tools or len(names) != len(set(names)):
        raise SystemExit(
            "Authoritative UDB catalog is empty or contains duplicate names"
        )
    return json.dumps(tools, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the checked-in JSON")
    mode.add_argument(
        "--check", action="store_true", help="fail if generated JSON is stale"
    )
    args = parser.parse_args()
    generated = render()
    if args.write:
        OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
        print(f"Wrote {OUTPUT.relative_to(ROOT)}")
        return 0
    if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != generated:
        print(
            "Fleet catalog is stale. Run: python tools/export_fleet_catalog.py --write",
            file=sys.stderr,
        )
        return 1
    print(
        f"Fleet catalog matches {len(json.loads(generated))} authoritative public tools"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
