"""Prepare a deterministic, disposable local project for Cloudflare read acceptance.

This script is offline. It does not register projects, set grants, start an
agent, connect ChatGPT or deploy a Worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_NAME = "udb-staging-fixture"
README = b"# UDB synthetic staging fixture\nmarker: scoped-read-v1\n"
PROBE = b"def answer():\n    return 'udb-synthetic-ok'\n"
PROTECTED = b"SYNTHETIC_ONLY=not-a-credential\n"
OUTSIDE = b"synthetic out-of-project boundary check\n"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def create_fixture(root: Path) -> dict:
    """Create an isolated fixture once; fail rather than overwrite any path."""
    if not root.is_absolute() or not root.parent.is_dir():
        raise ValueError("Fixture requires a new absolute directory with an existing parent")
    # mkdir is exclusive. A repeat run or a pre-existing symlink must fail.
    root.mkdir(mode=0o700, exist_ok=False)
    project = root / "project"
    project.mkdir(mode=0o700)
    (project / "README.md").write_bytes(README)
    (project / "probe.py").write_bytes(PROBE)
    (project / ".env").write_bytes(PROTECTED)
    (root / "outside.txt").write_bytes(OUTSIDE)

    manifest = {
        "schema_version": 1,
        "project_name": PROJECT_NAME,
        "project_directory": "project",
        "expected_reads": {
            "README.md": _sha256(README),
            "probe.py": _sha256(PROBE),
        },
        "expected_denials": [".env", "../outside.txt"],
        "note": "Synthetic local fixture only; no remote access or grant implied.",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="New absolute disposable fixture directory; parent must exist",
    )
    args = parser.parse_args()
    try:
        manifest = create_fixture(args.root)
    except (OSError, ValueError):
        # Never print unreviewed local paths or arbitrary filesystem errors.
        print(json.dumps({"result": "failed", "reason": "fixture_directory_unavailable"}))
        return 1
    print(
        json.dumps(
            {
                "result": "created",
                "project_name": manifest["project_name"],
                "manifest": "manifest.json",
                "expected_reads": manifest["expected_reads"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
