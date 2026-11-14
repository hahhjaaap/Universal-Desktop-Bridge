"""Ensure the remote gateway's public names match the local unified catalog."""

from __future__ import annotations

import re
from pathlib import Path

from udb.catalog import HIDDEN_ALIASES
from udb.registry import catalog
from udb.tool_families import FAMILY_MEMBERS, FAMILY_NAMES, LEGACY_ALIASES


def _js_names(path: Path, constant: str) -> list[str]:
    source = path.read_text(encoding="utf-8")
    pattern = rf"export const {constant} = Object\.freeze\(\[([\s\S]*?)\]\);"
    match = re.search(pattern, source)
    assert match is not None, f"Missing {constant}"
    return re.findall(r'"([a-z][a-z0-9_]*)"', match.group(1))


def test_cloudflare_legacy_grants_cover_the_compact_public_catalog() -> None:
    base = Path(__file__).resolve().parents[1] / "cloudflare" / "src"
    listing = catalog()
    public = [item["name"] for item in listing["tools"]]
    read = _js_names(base / "read-tools.js", "READ_TOOLS")
    owner = _js_names(base / "owner-tools.js", "OWNER_TOOLS")
    companion = _js_names(base / "companion-tools.js", "COMPANION_TOOLS")
    allowed = read + [x for x in owner if x not in LEGACY_ALIASES] + companion
    compact = (set(allowed) - FAMILY_MEMBERS) | FAMILY_NAMES

    assert listing["tool_count"] == 40
    assert listing["core_count"] == 36
    assert listing["companion_count"] == 31
    assert len(public) == len(set(public)) == 40
    assert len(allowed) == len(set(allowed)) == 59
    assert set(public) == compact
    assert set(companion).isdisjoint(owner + read)
    assert not set(public).intersection(HIDDEN_ALIASES)
