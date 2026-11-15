"""Isolated host mailbox performance and cleanup regressions.

All fixtures are disposable. No real host sessions, owner grants or desktop IO.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from udb import host_service
from udb.host_service import HostService, pending_inbox_commands


def test_pending_filters_before_sort_but_preserves_os_suffix_rules(
    tmp_path, monkeypatch
):
    folder = tmp_path / "inbox"
    folder.mkdir()
    for name in (
        "Z.json",
        "a.json",
        "B.json",
        "skip.txt",
        "skip.py",
        "other.JSON",
    ):
        (folder / name).write_text("{}", encoding="utf-8")
    observed = []
    original = host_service.os.listdir

    def counted(path):
        observed.append(path)
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(host_service.os, "listdir", counted)
        found = [p.name for p in pending_inbox_commands(folder)]
    assert observed == [folder]
    if os.name == "nt":
        expected = ["a.json", "B.json", "other.JSON", "Z.json"]
    else:
        expected = ["B.json", "Z.json", "a.json"]
    assert found == expected


def test_pending_does_not_open_or_claim_commands(tmp_path, monkeypatch):
    folder = tmp_path / "inbox"
    folder.mkdir()
    pending = folder / ("a" * 32 + ".json")
    pending.write_text("not a command yet", encoding="utf-8")

    def forbidden_open(*args, **kwargs):
        raise AssertionError("Listing must not open command files")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", forbidden_open)
        assert pending_inbox_commands(folder) == [pending]
    assert pending.read_text(encoding="utf-8") == "not a command yet"


def _service(tmp_path):
    host = HostService.__new__(HostService)
    host.folder = tmp_path / "host"
    (host.folder / "replies").mkdir(parents=True)
    return host


def test_prune_uses_120_second_cutoff_and_preserves_other_entries(tmp_path):
    host = _service(tmp_path)
    replies = host.folder / "replies"
    old = replies / "old.json"
    new = replies / "new.json"
    ignored = replies / "old.txt"
    folder = replies / "dir.json"
    folder.mkdir()
    for p in (old, new, ignored):
        p.write_text("{}", encoding="utf-8")
    now = time.time()
    for p in (old, ignored):
        os.utime(p, (now - 200, now - 200))
    os.utime(new, (now - 5, now - 5))
    host._prune_replies()
    assert not old.exists()
    assert new.exists()
    assert ignored.exists()
    assert folder.is_dir()


def test_prune_does_not_follow_symlink_or_remove_external_target(tmp_path):
    host = _service(tmp_path)
    replies = host.folder / "replies"
    external = tmp_path / "external.json"
    external.write_text("do not delete", encoding="utf-8")
    link = replies / "redirect.json"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("Symlink privilege unavailable on this platform")
    host._prune_replies()
    assert link.is_symlink()
    assert external.read_text(encoding="utf-8") == "do not delete"


def test_prune_missing_directory_is_nonfatal(tmp_path):
    host = _service(tmp_path)
    (host.folder / "replies").rmdir()
    host._prune_replies()


def test_pending_empty_mailbox_remains_empty(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    assert pending_inbox_commands(inbox) == []


def test_prune_refuses_replaced_reply_folder_symlink(tmp_path):
    host = _service(tmp_path)
    replies = host.folder / "replies"
    replies.rmdir()
    external = tmp_path / "external-replies"
    external.mkdir()
    protected = external / "protected.json"
    protected.write_text("never delete", encoding="utf-8")
    past = time.time() - 200
    os.utime(protected, (past, past))
    try:
        replies.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink privilege unavailable")
    host._prune_replies()
    assert protected.read_text(encoding="utf-8") == "never delete"
