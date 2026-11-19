"""Bound request-scoped policy reads and surface incomplete search coverage."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from udb.companion.files import ScopedFiles
from udb.companion.search import search_worker
from udb.core import Agent


def test_listing_reuses_policy_queries_without_reusing_them_between_requests(
    tmp_path, monkeypatch
):
    agent = Agent(tmp_path / "bridge")
    project = tmp_path / "workspace"
    project.mkdir()
    for i in range(20):
        (project / f"sample{i}.txt").write_text("text")
    agent.register_local("p", str(project))
    connect = agent.connect
    count = 0

    def traced():
        nonlocal count
        count += 1
        return connect()

    monkeypatch.setattr(agent, "connect", traced)
    assert len(agent.listing("p")["items"]) == 20
    assert count <= 2
    with connect() as conn:
        conn.execute("INSERT INTO protected (root) VALUES (?)", (str(project),))
    with pytest.raises(ValueError, match="Protected root"):
        agent.listing("p")


@pytest.fixture
def partial_project(tmp_path, monkeypatch):
    (tmp_path / "found.txt").write_text("needle", encoding="utf-8")
    stalled = tmp_path / "unreadable.txt"
    stalled.write_text("needle", encoding="utf-8")
    with (tmp_path / "large.txt").open("wb") as out:
        out.truncate(64 * 1024 * 1024 + 1)
    real = Path.open

    def opened(path, *args, **kwargs):
        if path == stalled:
            raise PermissionError("fixture")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    return tmp_path


def test_inline_search_reports_oversized_and_unreadable_files(partial_project):
    out = ScopedFiles(str(partial_project)).search(text="needle")
    assert out["matches"] == ["found.txt"]
    assert out["truncated"] is True
    assert out["skipped"] == {"too_large": 1, "unreadable": 1}


def test_background_search_reports_oversized_and_unreadable_files(
    partial_project, monkeypatch, capsys
):
    config = dict(
        root=str(partial_project),
        path=str(partial_project),
        text="needle",
        pattern="*.txt",
        case_sensitive=True,
        regex=False,
        search_type="content",
    )
    monkeypatch.setattr(
        "sys.stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(config).encode()))
    )
    search_worker()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["value"]["path"] for row in rows if row["type"] == "match"] == [
        "found.txt"
    ]
    assert rows[-1]["value"]["truncated"] is True
    assert rows[-1]["value"]["skipped"] == {
        "too_large": 1,
        "unreadable": 1,
        "lines_too_large": 0,
    }
