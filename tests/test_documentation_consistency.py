"""Keep user-facing documentation synchronized with the UDB source tree.

This is a read-only check: it neither rewrites docs nor accesses user state.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

from udb._version import VERSION

ROOT = Path(__file__).resolve().parents[1]
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]*)\)")


def _markdown_documents() -> list[Path]:
    # Avoid third-party notices, build output, local virtualenvs and private
    # owner workspaces; only public documentation locations are inspected.
    return sorted(
        [
            *ROOT.glob("*.md"),
            *(ROOT / "docs").glob("*.md"),
            *(ROOT / "cloudflare").glob("*.md"),
            *(ROOT / "examples").rglob("*.md"),
            *(ROOT / "integrations").rglob("*.md"),
        ]
    )


def test_readme_qt_pin_is_the_actual_pyproject_pin():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    matches = [
        dep.split(";")[0].strip()
        for dep in project["project"]["dependencies"]
        if dep.startswith("PySide6-Essentials==")
    ]
    assert len(matches) == 1
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"`{matches[0]}`" in readme


def test_source_version_identifies_the_current_docs():
    for relative in ("README.md", "docs/README.md", "docs/current-version.md"):
        body = (ROOT / relative).read_text(encoding="utf-8")
        assert VERSION in body, relative
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in project["project"]["dynamic"]
    assert "version" not in project["project"]


def test_local_document_links_resolve_to_checked_in_files():
    broken: list[str] = []
    documents = _markdown_documents()
    assert len(documents) >= 40
    for source in documents:
        text = source.read_text(encoding="utf-8")
        for found in LOCAL_LINK.finditer(text):
            raw = found.group(1).strip().split(maxsplit=1)[0].strip("<>")
            if not raw or raw.startswith(("#", "//", "mailto:", "data:")):
                continue
            if re.match(r"^[a-z][a-z0-9+.-]*:", raw, flags=re.IGNORECASE):
                continue
            path = unquote(raw.split("#", 1)[0].split("?", 1)[0])
            if not path:
                continue
            dest = (source.parent / path).resolve()
            if not dest.is_relative_to(ROOT) or not dest.is_file():
                broken.append(f"{source.relative_to(ROOT)} -> {raw}")
    assert not broken, "\n".join(broken)


def test_staging_docs_do_not_confuse_local_catalog_with_cloud_grants():
    staging = (ROOT / "cloudflare/STAGING-OPERATIONS.md").read_text(
        encoding="utf-8"
    )
    assert "only the explicitly granted" in staging
    assert "not\nauthorization" in staging
