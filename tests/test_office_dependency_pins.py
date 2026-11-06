"""Keep optional document parser pins synchronized and above audited security floors."""

from __future__ import annotations

import tomllib
from pathlib import Path

from udb.companion.documents import VERSIONS


def test_document_worker_versions_match_project_office_pins():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    office = set(project["project"]["optional-dependencies"]["office"])
    for package, version in VERSIONS.items():
        assert f"{package}=={version}" in office


def test_pypdf_security_baseline():
    # The 6.21.4 release addresses publicly disclosed 2026 PDF parser
    # denial-of-service advisories. Future upgrades must not regress this.
    assert tuple(map(int, VERSIONS["pypdf"].split("."))) >= (6, 21, 4)
