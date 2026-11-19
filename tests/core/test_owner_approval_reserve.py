"""Synthetic backup and approvals tests; no production state touched."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from udb import desktop_vm
from udb.companion.files import ScopedFiles
from udb.core import Agent, PolicyError


def test_fixture_like_filename_has_same_guarded_recovery_backup(tmp_path):
    files = ScopedFiles(str(tmp_path))
    existing = files.write(".udb-companion-test-real.txt", "original", "NEW")
    files.write(".udb-companion-test-real.txt", "replacement", existing["sha256"])
    backups = list((tmp_path / ".udb-recovery").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == "original"


def test_remote_requests_cannot_consume_attended_desktop_slots(tmp_path, monkeypatch):
    agent = Agent(tmp_path / "bridge")
    project = tmp_path / "workspace"
    project.mkdir()
    agent.register_local("p", str(project))
    monkeypatch.setattr(desktop_vm, "available", lambda: True)

    def request(index):
        try:
            return agent.propose("media", {"index": index})["request_id"]
        except PolicyError as exc:
            assert "Too many pending approvals" in str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        remote = [value for value in pool.map(request, range(40)) if value]
    assert len(remote) == 25
    assert len(remote) == len(set(remote))
    for _ in range(5):
        result = agent.propose_desktop("p", "owner fixture", 120, owner_initiated=True)
        assert result["status"] == "pending_local_approval"
        assert "owner_initiated" not in json.dumps(result)
    with pytest.raises(PolicyError, match="Too many pending approvals"):
        agent.propose_desktop("p", "last fixture", 120, owner_initiated=True)
