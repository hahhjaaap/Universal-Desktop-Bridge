"""Project-independent names for data/backup containers in scoped source APIs."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Callable

DATA_CONTAINER_SUFFIXES = (
    "_datasets",
    "-datasets",
    "_backups",
    "-backups",
    "_quarantine",
    "-quarantine",
)


def is_data_container(name: str) -> bool:
    return name.casefold().endswith(DATA_CONTAINER_SUFFIXES)


def _on_windows() -> bool:
    return os.name == "nt"


def _windows_long_path(path: Path) -> Path:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api = kernel.GetLongPathNameW
    api.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    api.restype = ctypes.c_uint
    length = api(str(path), None, 0)
    if length <= 0 or length > 32767:
        raise OSError(ctypes.get_last_error(), "Cannot canonicalize Windows path")
    buf = ctypes.create_unicode_buffer(length + 1)
    written = api(str(path), buf, len(buf))
    if written <= 0 or written >= len(buf):
        raise OSError(ctypes.get_last_error(), "Cannot canonicalize Windows path")
    return Path(buf.value)


def canonical_relative_parts(
    root: Path,
    target: Path,
    *,
    long_path: Callable[[Path], Path] | None = None,
) -> tuple[str, ...]:
    root, target = Path(root), Path(target)
    try:
        original = target.relative_to(root)
    except ValueError:
        raise PermissionError("Path outside authorized project") from None
    if any(p.endswith((".", " ")) for p in original.parts):
        raise PermissionError("Unsafe trailing dot or space")
    if long_path is None and not _on_windows():
        return original.parts
    resolver = long_path or _windows_long_path
    try:
        canonical_root = Path(resolver(root))
    except (OSError, ValueError, TypeError):
        raise PermissionError("Cannot canonicalize project root") from None
    cursor = root
    canonical = canonical_root
    missing = False
    for segment in original.parts:
        cursor = cursor / segment
        if missing:
            canonical = canonical / segment
            continue
        try:
            cursor.stat()
        except FileNotFoundError:
            missing = True
            canonical = canonical / segment
            continue
        except OSError:
            raise PermissionError("Cannot inspect existing path") from None
        try:
            candidate = Path(resolver(cursor))
            candidate.relative_to(canonical_root)
        except (OSError, TypeError, ValueError):
            raise PermissionError("Cannot canonicalize existing path") from None
        canonical = candidate
    try:
        result = canonical.relative_to(canonical_root).parts
    except ValueError:
        raise PermissionError("Canonical path escaped project") from None
    if any(p.endswith((".", " ")) for p in result):
        raise PermissionError("Unsafe canonical path")
    return result
