"""Bounded, scoped source operations using the existing Agent path policy."""

from __future__ import annotations

import fnmatch
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .core import BLOCK_DIRS, MAX_TEXT, SOURCE_EXT, PolicyError


def read_files(agent, project, paths):
    if (
        not isinstance(paths, list)
        or not 1 <= len(paths) <= 20
        or any(not isinstance(p, str) for p in paths)
    ):
        raise PolicyError("Provide 1..20 source paths")
    # Preflight every individual path using the SAME owner/project policy.
    # Refuse an oversized aggregate before reading any file in a worker.
    total_bytes = 0
    for relative in paths:
        file_path = agent.path(project, relative)
        if not file_path.is_file() or (
            file_path.suffix.lower() not in SOURCE_EXT
            and file_path.name.lower() not in SOURCE_EXT
        ):
            raise PolicyError("Only small source/text files may be read")
        total_bytes += file_path.stat().st_size
        if total_bytes > MAX_TEXT:
            raise PolicyError("Combined source response exceeds 512 KiB")
    # Concurrent disk reads are bounded to four; map preserves user order.
    # Every read independently re-checks current policy and emits its audit.
    if len(paths) == 1:
        rows = [agent.read(project, paths[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(paths))) as pool:
            rows = list(pool.map(lambda p: agent.read(project, p), paths))
    size = sum(len(row["text"].encode("utf-8")) for row in rows)
    if size > MAX_TEXT:
        raise PolicyError("Combined source response exceeds 512 KiB")
    return {"files": rows, "bytes": size}


def search_files(agent, project, path=".", pattern="*", text="", limit=100):
    if (
        not isinstance(pattern, str)
        or not 1 <= len(pattern) <= 120
        or not isinstance(text, str)
        or len(text) > 200
    ):
        raise PolicyError("Invalid filename pattern or literal search text")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise PolicyError("Result limit must be 1..200")
    folded_pattern = pattern.casefold()
    folded_text = text.casefold()
    start = agent.path(project, path)
    _, root = agent.project(project)
    if not start.is_dir():
        raise PolicyError("Search root must be a project directory")
    pending = [start]
    matches = []
    scanned = 0
    byte_count = 0
    truncated = False
    truncation_reason = None
    deadline = time.monotonic() + 3
    while pending and scanned < 10000 and time.monotonic() < deadline:
        folder = pending.pop()
        try:
            agent.path(project, folder.relative_to(root).as_posix())
            with os.scandir(folder) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > 10000 or time.monotonic() >= deadline:
                        truncated = True
                        truncation_reason = (
                            "scan_cap" if scanned > 10000 else "time_budget"
                        )
                        break
                    try:
                        # Reject known excluded folders and glob misses before
                        # the expensive policy lookup. ALL candidates and
                        # traversed directories still pass agent.path().
                        name = entry.name.casefold()
                        directory = entry.is_dir(follow_symlinks=False)
                        if directory and name in BLOCK_DIRS:
                            continue
                        if not directory and (
                            (
                                Path(name).suffix not in SOURCE_EXT
                                and name not in SOURCE_EXT
                            )
                            or not fnmatch.fnmatch(name, folded_pattern)
                        ):
                            continue
                        rel = Path(entry.path).relative_to(root).as_posix()
                        target = agent.path(project, rel)
                        if directory:
                            pending.append(target)
                            continue
                        if not target.is_file():
                            continue
                        row = {"path": rel}
                        if text:
                            data = agent.read_bytes(project, rel)
                            byte_count += len(data)
                            if byte_count > 4 * 1024 * 1024:
                                truncated = True
                                truncation_reason = "byte_budget"
                                pending.clear()
                                break
                            lines = data.decode("utf-8-sig").splitlines()
                            hits = []
                            for i, line in enumerate(lines, 1):
                                if folded_text in line.casefold():
                                    hits.append({"line": i, "text": line[:300]})
                                    if len(hits) == 10:
                                        break
                            if not hits:
                                continue
                            row["matches"] = hits
                        matches.append(row)
                        if len(matches) >= limit:
                            truncated = True
                            truncation_reason = "result_limit"
                            pending.clear()
                            break
                    except (PolicyError, OSError, UnicodeError):
                        continue
        except (PolicyError, OSError):
            continue
    if pending and not truncated:
        truncated = True
        truncation_reason = "scan_cap" if scanned >= 10000 else "time_budget"
    return {
        "items": matches,
        "scanned": min(scanned, 10000),
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "matches_returned": len(matches),
        "bytes_searched": byte_count,
        "protected_items_hidden": True,
        "literal_search": True,
    }


def propose_text_edit(
    agent, project, path, old_text, new_text, expected_sha256, occurrences=1
):
    if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
        raise PolicyError("Nonempty old_text and string new_text required")
    if type(occurrences) is not int or not 1 <= occurrences <= 100:
        raise PolicyError("Occurrences must be 1..100")
    row = agent.read(project, path)
    if row["sha256"] != expected_sha256:
        raise PolicyError("File changed since it was read")
    if row["text"].count(old_text) != occurrences:
        raise PolicyError("Exact occurrence count mismatch")
    # Exact occurrence count was checked above, so bounded replacement is
    # equivalent to replacing all occurrences without a second unbounded pass.
    updated = row["text"].replace(old_text, new_text, occurrences)
    return agent.propose_write(project, path, updated, expected_sha256)
