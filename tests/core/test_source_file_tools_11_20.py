"""Regression acceptance for source-file tool improvements 11 through 20."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from udb.companion.extensions import _file_read_lines, _file_stat
from udb.companion.files import ScopedFiles
from udb.core import MAX_TEXT, Agent, PolicyError
from udb.fileops import read_files, search_files


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)
    return agent, root


def test_list_files_offset_and_cursor_are_deterministic(project):
    agent, root = project
    for name in ("Alpha.py", "beta.py", "delta.py", "gamma.py", "zeta.py"):
        (root / name).write_text("value = 1\n", encoding="utf-8")
    (root / "raw.bin").write_bytes(b"hidden binary")
    (root / ".env").write_text("secret", encoding="utf-8")
    first = agent.listing("demo", limit=2)
    assert [r["path"] for r in first["items"]] == ["Alpha.py", "beta.py"]
    assert first["next_offset"] == 2
    assert first["next_after"] == "beta.py"
    assert first["scan_truncated"] is False
    second = agent.listing("demo", offset=2, limit=2)
    assert [r["path"] for r in second["items"]] == ["delta.py", "gamma.py"]
    (root / "AA.py").write_text("new-before-cursor", encoding="utf-8")
    after = agent.listing("demo", limit=2, after=first["next_after"])
    assert after["items"] == second["items"]
    final = agent.listing("demo", limit=2, after=after["next_after"])
    assert [r["path"] for r in final["items"]] == ["zeta.py"]
    assert final["next_after"] is None
    assert final["next_offset"] is None
    assert agent.listing("demo", limit=2) == agent.listing("demo", limit=2)
    for bad in ("\0", "x" * 241, 12):
        with pytest.raises(PolicyError):
            agent.listing("demo", after=bad)
    with pytest.raises(PolicyError, match="either offset or after"):
        agent.listing("demo", offset=1, after="beta.py")


def test_single_source_read_decodes_once_and_never_executes(project, monkeypatch):
    agent, root = project
    source = root / "demo.py"
    source.write_text('raise RuntimeError("not executed")\n', encoding="utf-8")
    calls = []
    original = Path.open

    def observed_open(self, *args, **kwargs):
        if self == source:
            calls.append(args[0] if args else kwargs.get("mode", "r"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    read = agent.read("demo", "demo.py")
    assert read["text"] == 'raise RuntimeError("not executed")\n'
    assert read["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert calls == ["rb"]
    assert agent.syntax_check("demo", "demo.py") == {
        "valid": True,
        "executes_code": False,
    }
    assert calls == ["rb", "rb"]
    source.write_text("def invalid(:\n", encoding="utf-8")
    result = agent.syntax_check("demo", "demo.py")
    assert not result["valid"] and result["executes_code"] is False
    assert result["line"] == 1 and result["column"] is not None
    assert "end_line" in result and "end_column" in result
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    assert agent.read("demo", ".gitignore")["text"] == "*.log\n"


def test_batched_reads_bounded_parallel_order_and_fresh_permissions(project, monkeypatch):
    agent, root = project
    names = [f"file_{index:02d}.py" for index in range(12)]
    for index, name in enumerate(names):
        (root / name).write_text(f"x = {index}\n", encoding="utf-8")
    original = agent.read
    lock = threading.Lock()
    active = 0
    highest = 0

    def observed(project_id, relative):
        nonlocal active, highest
        with lock:
            active += 1
            highest = max(highest, active)
        try:
            time.sleep(0.008)
            return original(project_id, relative)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(agent, "read", observed)
    result = read_files(agent, "demo", names)
    assert [r["path"] for r in result["files"]] == names
    assert result["bytes"] == sum(
        len((root / name).read_bytes()) for name in names
    )
    assert 1 < highest <= 4

    (root / "oversize.py").write_bytes(b"x" * (MAX_TEXT + 1))
    with pytest.raises(PolicyError, match="Combined"):
        read_files(agent, "demo", ["oversize.py"])
    with pytest.raises(PolicyError):
        read_files(agent, "demo", ["file_00.py", "../outside.py"])


def test_search_skips_protected_and_reports_reason_and_limits(project):
    agent, root = project
    (root / "a.py").write_text("found = 1\n", encoding="utf-8")
    (root / "b.py").write_text("found = 2\n", encoding="utf-8")
    (root / "ignore.bin").write_text("found = 3\n", encoding="utf-8")
    (root / "checkpoints").mkdir()
    (root / "checkpoints" / "private.py").write_text(
        "found = 'SECRET'\n", encoding="utf-8"
    )
    partial = search_files(agent, "demo", pattern="*.py", text="found", limit=1)
    assert partial["truncated"] is True
    assert partial["truncation_reason"] == "result_limit"
    assert partial["matches_returned"] == 1
    full = search_files(agent, "demo", pattern="*.py", text="found", limit=20)
    assert {r["path"] for r in full["items"]} == {"a.py", "b.py"}
    assert full["truncated"] is False
    assert full["truncation_reason"] is None
    assert full["bytes_searched"] == sum(
        (root / name).stat().st_size for name in ("a.py", "b.py")
    )


def test_project_files_utf8_paging_is_byte_exact(tmp_path):
    source = tmp_path / "unicode.txt"
    source.write_text("A💡B", encoding="utf-8")
    files = ScopedFiles(str(tmp_path))
    first = files.read("unicode.txt", offset=0, limit=2)
    assert first["content"] == "A💡"
    assert first["next_offset"] == len("A💡".encode("utf-8"))
    assert first["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    last = files.read("unicode.txt", offset=first["next_offset"], limit=1)
    assert last["content"] == "B" and last["remaining"] == 0
    with pytest.raises(ValueError, match="UTF-8"):
        files.read("unicode.txt", offset=2, limit=3)
    (tmp_path / "corrupt.txt").write_bytes(b"bad\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        files.read("corrupt.txt", limit=20)


def test_project_files_stat_listing_and_unicode_line_offsets(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("α\r\nb\u2028c\n", encoding="utf-8")
    files = ScopedFiles(str(tmp_path))
    rt = SimpleNamespace(files=files)
    listing = files.list(limit=10)
    assert listing["items"] == [
        {"name": "notes.txt", "kind": "file", "size": source.stat().st_size}
    ]
    stat = _file_stat(rt, {"path": "notes.txt"})
    assert "SHA256: " + hashlib.sha256(source.read_bytes()).hexdigest() in stat
    page = _file_read_lines(rt, {"path": "notes.txt", "offset": 1, "length": 2})
    assert "Lines: 2-3 of 3" in page
    assert "2: b\n3: c" in page
    assert "Next offset: 3" in page
    assert "Output clipped: False" in page
    (tmp_path / ".env").write_text("credential", encoding="utf-8")
    assert [x["name"] for x in files.list()["items"]] == ["notes.txt"]


def test_large_line_reads_remain_bounded(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("A\n" * 200000, encoding="utf-8")
    files = ScopedFiles(str(tmp_path))
    rt = SimpleNamespace(files=files)
    import tracemalloc

    tracemalloc.start()
    try:
        row = _file_read_lines(rt, {"path": "large.txt", "offset": 199998})
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert "Lines: 199999-200000 of 200000" in row
    assert peak < 2 * 1024 * 1024
