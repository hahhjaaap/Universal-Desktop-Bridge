"""Owner-attended pruning of generated backups and the core audit journal."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path, PureWindowsPath

from . import onboarding
from .config import Settings
from .core import ScopedConnection
from .owner_command import CommandError, regular

RETENTION_DAYS = 90
KEEP_BACKUPS = 20
KEEP_EVENTS = 1000
BACKUP_LIMIT = 200
EVENT_LIMIT = 2000
_UUID_BACKUP = re.compile(r"[0-9a-f]{32}\.bak")
_RECOVERY_BACKUP = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{12}-[0-9]{13})\.bak")
_REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
_FILE_READ_ATTRIBUTES = 0x0080  # Win32 file access right in winnt.h


def _database(
    path: Path, *, expected: os.stat_result | None = None
) -> tuple[ScopedConnection, os.stat_result]:
    regular(path)
    try:
        database_info = path.lstat()
    except FileNotFoundError:
        raise CommandError("An existing UDB state database is required.") from None
    if expected is not None and not os.path.samestat(database_info, expected):
        raise CommandError(
            "The UDB state database changed since preview. Run retention again."
        )
    if not stat.S_ISREG(database_info.st_mode) or database_info.st_nlink != 1:
        raise CommandError("UDB state database is not a private file.")
    for suffix in ("-wal", "-shm", "-journal"):
        item = path.with_name(path.name + suffix)
        regular(item)
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CommandError("UDB database sidecar is not a private file.")
    connection = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if expected is not None else "?mode=ro"),
        uri=True,
        timeout=5,
        factory=ScopedConnection,
    )
    return connection, database_info


def _events(db: ScopedConnection, cutoff: float) -> list[tuple[int, float]]:
    return db.execute(
        """
        SELECT seq, at FROM events
        WHERE at < ? AND typeof(at) IN ('integer', 'real')
          AND seq < COALESCE(
            (SELECT seq FROM events ORDER BY seq DESC LIMIT 1 OFFSET ?), 0
          )
        ORDER BY seq LIMIT ?
        """,
        (cutoff, KEEP_EVENTS - 1, EVENT_LIMIT),
    ).fetchall()


def _folders(
    db: ScopedConnection, settings: Settings
) -> Iterator[tuple[Path, re.Pattern[str]]]:
    yield settings.home / "state" / "backups", _UUID_BACKUP
    projects = {Path(row[0]) for row in db.execute("SELECT root FROM projects")}
    projects.add(settings.project_root)
    protected = tuple(Path(row[0]) for row in db.execute("SELECT root FROM protected"))
    for root in sorted(projects):
        folder = root / ".udb-recovery"
        if (
            not root.is_absolute()
            or root == root.parent
            or settings.home.is_relative_to(root)
            or Path.home().is_relative_to(root)
            or (
                root.is_relative_to(settings.home)
                and not root.is_relative_to(settings.home / "projects")
            )
            or any(
                folder.is_relative_to(p) or p.is_relative_to(folder) for p in protected
            )
        ):
            continue
        try:
            if regular(folder).resolve() == folder:
                yield folder, _RECOVERY_BACKUP
        except (OSError, CommandError):
            continue


def _backup_fingerprint(info: os.stat_result) -> tuple | None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or getattr(info, "st_file_attributes", 0) & _REPARSE
    ):
        return None
    return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size


def _candidates(
    db: ScopedConnection, settings: Settings, cutoff: float
) -> Iterator[tuple[Path, tuple]]:
    count = 0
    for folder, pattern in _folders(db, settings):
        files = []
        try:
            for path in regular(folder).iterdir():
                if not pattern.fullmatch(path.name):
                    continue
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                fingerprint = _backup_fingerprint(info)
                if fingerprint is not None:
                    files.append((info.st_mtime, path, fingerprint))
        except (FileNotFoundError, CommandError):
            continue
        files.sort()
        for stamp, path, fingerprint in files[: max(0, len(files) - KEEP_BACKUPS)]:
            if stamp >= cutoff:
                break
            yield path, fingerprint
            count += 1
            if count >= BACKUP_LIMIT:
                return


def _windows_backup(path: Path, *, expected: tuple | None = None) -> tuple | None:
    import pywintypes
    import win32con
    import win32file

    # Reject redirected handles and delete the previewed object by handle.
    # Excluding write/delete sharing prevents concurrent updates while held.
    if not re.fullmatch(r"[A-Za-z]:", path.drive):
        return None
    try:
        with closing(
            win32file.CreateFile(
                str(regular(path)),
                _FILE_READ_ATTRIBUTES | (win32con.DELETE if expected else 0),
                win32con.FILE_SHARE_READ,
                None,
                win32con.OPEN_EXISTING,
                win32file.FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
        ) as handle:
            final = win32file.GetFinalPathNameByHandle(handle, 0)
            info = win32file.GetFileInformationByHandle(handle)
            if (
                not final.startswith("\\\\?\\")
                or PureWindowsPath(final[4:]) != path
                or info[0] & (_REPARSE | stat.FILE_ATTRIBUTE_DIRECTORY)
                or info[7] != 1
                or not (info[8] or info[9])
            ):
                return None
            fingerprint = (info[1], info[3], *info[4:])
            if expected is not None:
                if fingerprint != expected:
                    return None
                win32file.SetFileInformationByHandle(
                    handle, win32file.FileDispositionInfo, True
                )
            return fingerprint
    except (OSError, pywintypes.error, CommandError):
        return None


def _snapshot(path: Path, fingerprint: tuple) -> tuple | None:
    if os.name != "nt":
        return fingerprint
    native = _windows_backup(path)
    try:
        if native is not None and _backup_fingerprint(path.lstat()) == fingerprint:
            return native
    except FileNotFoundError:
        pass
    return None


def _remove_windows_backup(path: Path, expected: tuple) -> bool:
    return _windows_backup(path, expected=expected) is not None


def run(settings: Settings, *, apply: bool, as_json: bool) -> int:
    if apply and not onboarding.attended_console():
        raise CommandError("Retention requires an attended Windows terminal.")
    cutoff = time.time() - RETENTION_DAYS * 86400
    path = settings.home / "state" / "agent.sqlite3"
    try:
        connection, database_info = _database(path)
        with connection as db:
            events = _events(db, cutoff)
            backups = {}
            for item, fingerprint in _candidates(db, settings, cutoff):
                snapshot = _snapshot(item, fingerprint)
                if snapshot is not None:
                    backups[item] = fingerprint, snapshot
        report = {"eligible": {"backups": len(backups), "events": len(events)}}
        if as_json:
            print(json.dumps(report))
        else:
            print(f"Eligible to prune this run ({RETENTION_DAYS}+ days old).")
            print(f"{len(backups)} backups, {len(events)} audit events.")
        if not apply or not (backups or events):
            return 0
        print(
            "Type PRUNE UDB HISTORY to permanently remove these items.",
            file=sys.stderr,
            flush=True,
        )
        try:
            confirmed = sys.stdin.readline().rstrip("\r\n") == "PRUNE UDB HISTORY"
        except (KeyboardInterrupt, OSError):
            confirmed = False
        if not confirmed:
            raise CommandError("Retention cancelled.")

        connection, _ = _database(path, expected=database_info)
        with connection as db:
            db.execute("BEGIN IMMEDIATE")
            eligible = dict(_candidates(db, settings, cutoff))
            deleted_backups = sum(
                _remove_windows_backup(item, native)
                for item, (fingerprint, native) in backups.items()
                if eligible.get(item) == fingerprint
            )
            approved_events = set(events).intersection(_events(db, cutoff))
            removed = db.executemany(
                "DELETE FROM events WHERE seq=? AND at=?", sorted(approved_events)
            ).rowcount
            result = {"backups": deleted_backups, "events": removed}
            if any(result.values()):
                db.execute(
                    "INSERT INTO events(at,event,details) VALUES (?, 'retention_prune', ?)",
                    (time.time(), json.dumps(result, separators=(",", ":"))),
                )
        skipped = {name: report["eligible"][name] - result[name] for name in result}
        if as_json:
            print(json.dumps({"removed": result, "skipped": skipped}))
        else:
            print(
                f"Removed {result['backups']} backups and {result['events']} audit events. "
                f"Skipped {skipped['backups']} backups and {skipped['events']} audit events."
            )
        return 0
    except (OSError, sqlite3.Error):
        raise CommandError(
            "Could not complete retention. Some reviewed backups may already have been removed."
        ) from None
