"""Small, read-only build identifiers. Metadata is not a publisher signature."""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from ._version import VERSION

_SHA = re.compile(r"[a-f0-9]{40}\Z")


def _text(path, limit):
    for item in (path, *path.parents):
        if item.is_symlink() or (
            item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("Linked build metadata")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Oversized build metadata")
    return raw.decode("utf-8")


def checkout_head(root):
    """Read Git's HEAD without executing Git, hooks, config or project code."""
    try:
        directory = root / ".git"
        if directory.is_file():
            pointer = _text(directory, 4096).strip()
            if not pointer.startswith("gitdir: "):
                return None
            directory = (root / pointer[8:]).absolute()
        head = _text(directory / "HEAD", 256).strip()
        if _SHA.fullmatch(head):
            return head
        if not head.startswith("ref: refs/"):
            return None
        ref = head[5:]
        if not re.fullmatch(r"refs/[A-Za-z0-9_./-]{1,200}", ref) or ".." in ref:
            return None
        if (directory / "commondir").exists():
            directory = (
                directory / _text(directory / "commondir", 4096).strip()
            ).absolute()
        try:
            value = _text(directory / ref, 128).strip()
            return value if _SHA.fullmatch(value) else None
        except FileNotFoundError:
            for line in _text(directory / "packed-refs", 1048576).splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and _SHA.fullmatch(parts[0]):
                    return parts[0]
    except (OSError, ValueError):
        pass
    return None


def identify(package, *, frozen=False):
    revision, dirty = None, None
    layout, origin = ("unknown", "unavailable") if frozen else ("source", "checkout")
    if frozen:
        try:
            value = json.loads(_text(package / "build_info.json", 262144))
            if not isinstance(value, dict) or value.get("version") != VERSION:
                raise ValueError("Wrong build version")
            candidate = value.get("source_revision")
            candidate_layout = value.get("build_layout", "onefile")
            if candidate_layout not in ("onefile", "onedir"):
                raise ValueError("Invalid build layout")
            candidate_dirty = value.get("source_dirty")
            if candidate is None and candidate_dirty is None:
                # A GitHub source archive has no Git metadata. Report its
                # embedded layout, but never manufacture a verified revision.
                if (
                    value.get("kind") != "frozen"
                    or value.get("release_provenance") is not True
                    or value.get("python_embedded") is not True
                    or value.get("code_signed") is not False
                ):
                    raise ValueError("Untrusted layout-only build metadata")
                layout, origin = candidate_layout, "embedded-layout-only"
            else:
                if not isinstance(candidate, str) or not _SHA.fullmatch(candidate):
                    raise ValueError("Unknown build revision")
                if type(candidate_dirty) is not bool:
                    raise ValueError("Unknown build source state")
                revision, dirty = candidate, candidate_dirty
                layout, origin = candidate_layout, "embedded"
        except (OSError, ValueError):
            pass  # Unknown identity never becomes a claim of a verified build.
    else:
        revision = checkout_head(package.parent.parent)
    suffix = revision[:12] if revision else "unidentified"
    if not frozen:
        suffix += ".source"
    elif dirty:
        suffix += ".dirty"
    return {
        "version": VERSION,
        "build_id": VERSION + "+" + suffix,
        "source_revision": revision,
        "source_dirty": dirty,
        "build_layout": layout,
        "identity_source": origin,
        "publisher_verified": False,
    }


@lru_cache(maxsize=1)
def _identity():
    return identify(Path(__file__).parent, frozen=getattr(sys, "frozen", False))


def runtime_identity():
    return dict(_identity())


def display_identity():
    return runtime_identity()["build_id"]
