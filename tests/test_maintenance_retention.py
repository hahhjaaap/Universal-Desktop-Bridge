import io
import json
import os
import sys
import time
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from udb import cli, onboarding
from udb.config import Settings
from udb.core import Agent


@pytest.fixture
def history(tmp_path):
    agent = Agent(tmp_path / "home")
    workspace = agent.home / "projects" / "workspace"
    project = tmp_path / "registered-project"
    project.mkdir()
    agent.register_local("registered", str(project), writable=True)
    now = int(time.time())
    with agent.connect() as db:
        db.execute("DELETE FROM events")
        db.executemany(
            "INSERT INTO events(at,event,details) VALUES (?, 'test', 'private text')",
            [(now - 100 * 86400,)] * 1002 + [(now,)],
        )
    return agent, Settings(agent.home, workspace), project, now


def _old_backups(folder, now):
    folder.mkdir(parents=True)
    files = [folder / f"{i:032x}.bak" for i in range(22)]
    for i, path in enumerate(files):
        path.write_text("private backup data")
        age = now - 100 * 86400 + i
        os.utime(path, (age, age))
    return files


def _events(agent):
    with agent.connect() as db:
        return db.execute("SELECT event, details FROM events ORDER BY seq").fetchall()


def test_retention_cli_preview_has_no_side_effect_or_private_data(history, capsys):
    agent, settings, project, now = history
    backups = _old_backups(project / ".udb-recovery", now)
    args = ["--home", str(settings.home), "--json", "retention"]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["eligible"] == {"backups": 2, "events": 3}
    assert "private" not in output and str(project) not in output
    assert all(path.is_file() for path in backups)
    assert len(_events(agent)) == 1003


def test_retention_apply_requires_console_and_explicit_confirmation(
    history, capsys, monkeypatch
):
    agent, settings, _, now = history
    backups = _old_backups(agent.state / "backups", now)
    args = ["--home", str(settings.home), "retention", "--apply"]
    monkeypatch.setattr(onboarding, "attended_console", lambda: False)
    monkeypatch.setattr("sys.stdin", io.StringIO("PRUNE UDB HISTORY\n"))
    assert cli.main(args) == 2
    assert "attended Windows terminal" in capsys.readouterr().err
    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("prune udb history\n"))
    assert cli.main(args) == 2
    assert "cancelled" in capsys.readouterr().err.lower()
    assert all(path.is_file() for path in backups)
    assert len(_events(agent)) == 1003


def test_retention_prunes_only_reviewed_old_history(history, monkeypatch, capsys):
    from udb import retention

    agent, settings, project, now = history
    state_backups = _old_backups(agent.state / "backups", now)
    document_backups = _old_backups(project / ".udb-recovery", now)
    file_backups = _old_backups(settings.project_root / ".udb-recovery", now)
    file_backup = file_backups[0].parent / "abcdef012345-1700000000000.bak"
    file_backups[0].rename(file_backup)
    unrelated = file_backup.with_name("owner.bak")
    unrelated.write_text("owner data")
    os.utime(unrelated, (0, 0))
    changed = state_backups[0]

    class Confirmation(io.StringIO):
        def readline(self):
            changed.write_text("changed since preview")
            return "PRUNE UDB HISTORY\n"

    def remove(path: Path, expected):
        if (
            retention._snapshot(path, retention._backup_fingerprint(path.lstat()))
            != expected
        ):
            return False
        path.unlink()
        return True

    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr("sys.stdin", Confirmation())
    monkeypatch.setattr(retention, "_remove_windows_backup", remove)
    assert (
        cli.main(
            [
                "--home",
                str(settings.home),
                "--root",
                str(settings.project_root),
                "retention",
                "--apply",
            ]
        )
        == 0
    )
    report = capsys.readouterr().out
    assert "Removed 5 backups and 3 audit events." in report
    assert "Skipped 1 backups and 0 audit events." in report
    assert changed.is_file() and unrelated.is_file()
    assert not state_backups[1].exists()
    assert not document_backups[0].exists() and not document_backups[1].exists()
    assert not file_backup.exists() and not file_backups[1].exists()
    assert all(
        path.exists()
        for path in state_backups[2:] + document_backups[2:] + file_backups[2:]
    )
    events = _events(agent)
    assert len(events) == 1001
    assert list(events[-1]) == ["retention_prune", '{"backups":5,"events":3}']


def test_retention_excludes_protected_folders_and_exact_expiry_boundary(history):
    from udb.retention import _candidates, _events

    agent, settings, project, now = history
    _old_backups(project / ".udb-recovery", now)
    agent.protect_local(str(project))
    backups = _old_backups(agent.state / "backups", now)
    cutoff = now - 100 * 86400 + 1
    with agent.connect() as db:
        db.execute("UPDATE events SET at=? WHERE event='test'", (cutoff,))
        assert _events(db, cutoff) == []
        assert [path for path, _ in _candidates(db, settings, cutoff)] == [backups[0]]


def test_windows_backup_handle_policy_without_windows(monkeypatch):
    from udb import retention

    path = PureWindowsPath(r"C:\history\reviewed.bak")
    handle = SimpleNamespace(close=lambda: None)
    removed = []
    info = [0, 10, 11, 12, 4, 0, 42, 1, 0, 7]
    native = SimpleNamespace(
        FILE_FLAG_OPEN_REPARSE_POINT=0x00200000,
        FileDispositionInfo=4,
        CreateFile=lambda *args: handle,
        GetFinalPathNameByHandle=lambda *_: "\\\\?\\" + str(path),
        GetFileInformationByHandle=lambda _: tuple(info),
        SetFileInformationByHandle=lambda *args: removed.append(args),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(DELETE=0x10000, FILE_SHARE_READ=1, OPEN_EXISTING=3),
    )
    monkeypatch.setitem(sys.modules, "win32file", native)
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=OSError))
    monkeypatch.setattr(retention, "regular", lambda path: path)

    approved = retention._windows_backup(path)
    assert approved is not None
    info[0] = 0x400
    assert retention._windows_backup(path, expected=approved) is None
    info[0] = 0
    info[7] = 2
    assert retention._windows_backup(path, expected=approved) is None
    info[7] = 1
    info[9] = 8
    assert retention._windows_backup(path, expected=approved) is None
    info[9] = 7
    assert retention._windows_backup(path, expected=approved) == approved
    assert removed == [(handle, native.FileDispositionInfo, True)]


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows handle semantics")
def test_windows_backup_removal_rechecks_the_reviewed_object(tmp_path):
    from udb.retention import _windows_backup

    path = tmp_path / "reviewed.bak"
    path.write_text("old backup")
    approved = _windows_backup(path)
    assert approved is not None

    path.write_text("replacement with different content and size")
    assert _windows_backup(path, expected=approved) is None
    assert path.is_file()

    approved = _windows_backup(path)
    assert approved is not None
    assert _windows_backup(path, expected=approved) == approved
    assert not path.exists()
