"""Scoped source-file operations and path validation, independent of MCP."""

from __future__ import annotations

import fnmatch
import hashlib
import heapq
import os
import re
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from udb.path_policy import canonical_relative_parts, is_data_container

from .constants import (
    HIDDEN_DIRS_CASEFOLD,
    MAX_FILE_BYTES,
    MAX_READ_BYTES,
    MAX_SCAN_FILES,
    PROTECTED_NAMES,
    PROTECTED_PREFIXES,
    PROTECTED_SUFFIXES,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_sha256(path: Path) -> str:
    """Stream the commit-time verification hash without another 8-MiB allocation."""
    hasher = hashlib.sha256()
    consumed = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(256 * 1024), b""):
            consumed += len(block)
            if consumed > MAX_FILE_BYTES:
                raise ValueError("Existing file exceeds 8 MiB guarded-write limit")
            hasher.update(block)
    return hasher.hexdigest()


def is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


class ScopedFiles:
    def __init__(self, root: str):
        home = Path(root).expanduser().absolute()
        if not home.is_dir() or is_reparse(home):
            raise ValueError("Project root must exist and must not be a link")
        self.root = home.resolve(strict=True)

    def path(self, given: str, allow_missing: bool = False) -> Path:
        if not isinstance(given, str) or not given or "\x00" in given:
            raise ValueError("Missing or invalid file path")
        p = Path(given)
        if any(x.endswith((".", " ")) for x in p.parts):
            raise PermissionError("Trailing dot or space not allowed")
        raw = (p if p.is_absolute() else self.root / p).absolute()
        full = Path(os.path.normpath(str(raw)))
        if os.name == "nt" and (str(full).startswith("\\\\") or ":" in str(full)[2:]):
            raise PermissionError("UNC and alternate data streams are not allowed")
        try:
            rel = full.relative_to(self.root)
        except ValueError:
            raise PermissionError("Path is outside the authorized project") from None

        def deny_source_parts(names):
            if any(
                part.casefold() in PROTECTED_NAMES
                or is_data_container(part)
                or part.casefold().startswith(PROTECTED_PREFIXES)
                or part.lower().endswith(tuple(PROTECTED_SUFFIXES))
                for part in names
            ):
                raise PermissionError("Protected file is not accessible")
            if any(
                part.casefold().startswith(
                    (".udb-stage-", ".udb-upload-", ".udb-write-")
                )
                or part.casefold() in HIDDEN_DIRS_CASEFOLD
                for part in names
            ):
                raise PermissionError("Protected directory is not accessible")

        deny_source_parts(rel.parts)
        walk = self.root
        for item in rel.parts:
            walk = walk / item
            if is_reparse(walk):
                raise PermissionError("Links / reparse points are not allowed")
        if not full.resolve(strict=False).is_relative_to(self.root):
            raise PermissionError("Resolved path is outside the authorized project")
        deny_source_parts(canonical_relative_parts(self.root, full))
        if full.is_file() and full.stat().st_nlink > 1:
            raise PermissionError("Hardlinked data files are not allowed")
        if not allow_missing and not full.exists():
            raise FileNotFoundError("File or directory not found")
        return full

    def list(self, path: str = ".", limit: int = 100) -> dict[str, Any]:
        base = self.path(path)
        if not base.is_dir():
            raise NotADirectoryError("Target is not a directory")
        count = max(1, min(int(limit), 500))

        # Stream directory entries and keep only the first 'count' safe names.
        # Sorting all entries can allocate unbounded memory in a large folder.
        def allowed_entries():
            with os.scandir(base) as entries:
                for entry in entries:
                    try:
                        # Preserve full path authorization before metadata use.
                        yield self.path(entry.path), entry
                    except (PermissionError, ValueError, FileNotFoundError):
                        continue

        items = []
        for safe, entry in heapq.nsmallest(
            count,
            allowed_entries(),
            key=lambda pair: (pair[0].name.casefold(), pair[0].name),
        ):
            try:
                # DirEntry caches metadata for this scan only, avoiding
                # repeated Path.stat/is_file/is_dir calls or stale auth caches.
                directory = entry.is_dir(follow_symlinks=False)
                regular = entry.is_file(follow_symlinks=False)
                size = entry.stat(follow_symlinks=False).st_size if regular else None
            except OSError:
                continue
            items.append(
                {
                    "name": safe.name,
                    "kind": "dir" if directory else "file",
                    "size": size,
                }
            )
        return {
            "path": str(base.relative_to(self.root)),
            "items": items,
            "limit": count,
        }

    def read(self, path: str, offset: int = 0, limit: int = 8192) -> dict[str, Any]:
        p = self.path(path)
        if not p.is_file():
            raise ValueError("Target is not a file")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("File is too large; use a dedicated large-file processor")
        start = max(0, int(offset))
        count = max(1, min(MAX_READ_BYTES, int(limit)))
        hasher = hashlib.sha256()
        with p.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > MAX_FILE_BYTES:
                raise ValueError(
                    "File is too large; use a dedicated large-file processor"
                )
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
            stream.seek(start)
            view = stream.read(count)
            # Keep byte-based pagination but complete a final UTF-8 character
            # (at most three extra bytes). Never silently skip an invalid
            # start offset or a malformed sequence.
            extra = 0
            while True:
                try:
                    displayed = view.decode("utf-8")
                    break
                except UnicodeDecodeError as exc:
                    if (
                        exc.reason != "unexpected end of data"
                        or start + len(view) >= size
                        or extra >= 3
                    ):
                        raise ValueError(
                            "Read range must contain valid UTF-8; "
                            "offset must begin at a code-point boundary"
                        ) from exc
                    following = stream.read(1)
                    if not following:
                        raise ValueError("Incomplete UTF-8 file content") from exc
                    view += following
                    extra += 1
        return {
            "path": str(p.relative_to(self.root)),
            "content": displayed,
            "sha256": hasher.hexdigest(),
            "size": size,
            "next_offset": start + len(view),
            "remaining": max(0, size - start - len(view)),
        }

    def write(
        self, path: str, content: str, expected_sha256: str = "NEW"
    ) -> dict[str, Any]:
        p = self.path(path, allow_missing=True)
        if not isinstance(content, str):
            raise ValueError("content must be text")
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("8 MiB write limit exceeded")
        p.parent.mkdir(parents=True, exist_ok=True)
        is_existing = p.exists()
        if is_existing and not p.is_file():
            raise ValueError("Target is not a normal file")
        if expected_sha256 == "NEW":
            if is_existing:
                raise FileExistsError(
                    "File already exists. Supply its current SHA256 to replace."
                )
        elif not re.fullmatch(r"[0-9a-f]{64}", expected_sha256, re.I):
            raise ValueError("expected_sha256 must be NEW or a 64-char SHA256")
        if is_existing:
            if p.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("Existing file exceeds 8 MiB guarded-write limit")
            with p.open("rb") as source:
                previous = source.read(MAX_FILE_BYTES + 1)
            if len(previous) > MAX_FILE_BYTES:
                raise ValueError("Existing file exceeds 8 MiB guarded-write limit")
            if digest(previous).lower() != expected_sha256.lower():
                raise ValueError("File changed since reading; write cancelled")
        elif expected_sha256 != "NEW":
            raise FileNotFoundError("Cannot replace a file that no longer exists")
        handle, temp_name = tempfile.mkstemp(prefix=".udb-write-", dir=str(p.parent))
        try:
            with os.fdopen(handle, "wb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            if not is_existing:
                # Atomic create-only: hard links refuse an existing destination.
                # Both names are on the same filesystem.
                os.link(temp_name, p)
            else:
                # Best effort CAS; noncooperating external writers may still
                # race a replacement. Never suppress failed comparisons.
                if _bounded_sha256(p).lower() != expected_sha256.lower():
                    raise ValueError("File changed before commit; write cancelled")
                if not p.name.startswith(".udb-companion-test-"):
                    recovery = self.root / ".udb-recovery"
                    if is_reparse(recovery):
                        raise PermissionError("Recovery directory is redirected")
                    recovery.mkdir(exist_ok=True)
                    if is_reparse(recovery):
                        raise PermissionError("Recovery directory is redirected")
                    backup = recovery / (
                        digest(str(p).encode())[:12]
                        + "-"
                        + str(int(time.time() * 1000))
                        + ".bak"
                    )
                    with backup.open("xb") as b:
                        b.write(previous)
                        b.flush()
                        os.fsync(b.fileno())
                os.replace(temp_name, p)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return {
            "path": str(p.relative_to(self.root)),
            "bytes": len(data),
            "sha256": digest(data),
            "created": not is_existing,
        }

    def replace(
        self, path: str, old: str, new: str, expected_sha256: str, occurrences: int = 1
    ) -> dict[str, Any]:
        p = self.path(path)
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("Nonempty old text and string new text required")
        if type(occurrences) is not int or not 1 <= occurrences <= 100:
            raise ValueError("Occurrences must be 1..100")
        with p.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("File too large")
        if digest(data) != expected_sha256:
            raise ValueError("File changed since reading; edit cancelled")
        source = data.decode("utf-8")
        actual = source.count(old)
        if actual != occurrences:
            raise ValueError(
                f"Expected {occurrences} matches, found {actual}; edit cancelled"
            )
        return self.write(
            path, source.replace(old, new, occurrences), expected_sha256
        ) | {"replacements": actual}

    def search(
        self, path: str = ".", pattern: str = "*", text: str = "", limit: int = 30
    ) -> dict[str, Any]:
        root = self.path(path)
        if not root.is_dir():
            raise NotADirectoryError("Search path must be a folder")
        matches = []
        scanned = 0
        skipped = {"too_large": 0, "unreadable": 0}

        def report(truncated):
            partial = any(skipped.values())
            return {
                "matches": matches,
                "scanned": min(scanned, MAX_SCAN_FILES),
                "truncated": truncated or partial,
                **({"skipped": skipped} if partial else {}),
            }

        def onerror(_error):
            skipped["unreadable"] += 1

        cap = max(1, min(200, int(limit)))
        folded_text = text.casefold() if text else ""
        for base, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            # Do not descend into protected trees just to reject every file.
            # This also avoids scanning large datasets, model weights and secrets.
            allowed_dirs = []
            for name in dirs:
                if name.casefold() in HIDDEN_DIRS_CASEFOLD:
                    continue
                try:
                    self.path(str(Path(base) / name))
                except (PermissionError, ValueError, FileNotFoundError, OSError):
                    continue
                allowed_dirs.append(name)
            dirs[:] = allowed_dirs
            for name in files:
                scanned += 1
                if scanned > MAX_SCAN_FILES:
                    return report(True)
                if not fnmatch.fnmatch(name, pattern):
                    continue
                p = Path(base) / name
                try:
                    p = self.path(str(p))
                except (OSError, ValueError):
                    continue  # Do not expose or count paths denied by project policy.
                try:
                    if not p.is_file():
                        continue
                    if text:
                        if p.stat().st_size > 1024 * 1024:
                            skipped["too_large"] += 1
                            continue
                        if "\n" in text or "\r" in text:
                            # Multiline queries still need the original whole-text
                            # semantics (including matches across line breaks).
                            found = (
                                folded_text
                                in p.read_text(
                                    encoding="utf-8", errors="replace"
                                ).casefold()
                            )
                        else:
                            # For ordinary literal searches, stop at the first
                            # matching line instead of copying every file.
                            with p.open(
                                "r", encoding="utf-8", errors="replace"
                            ) as stream:
                                found = any(
                                    folded_text in line.casefold() for line in stream
                                )
                        if not found:
                            continue
                except OSError:
                    skipped["unreadable"] += 1
                    continue
                matches.append(str(p.relative_to(self.root)))
                if len(matches) >= cap:
                    return report(True)
        return report(False)
