"""Regression gates for UDB per-tool optimization steps 41–50.

All fixtures are disposable. No Windows host input or real Sandbox is started.
Performance numbers are informational; policy/response invariants are asserted.
"""

from __future__ import annotations

import json
import struct
import time
import tracemalloc
import zlib

import pytest

from udb import desktop_vm as vm
from udb import sandbox
from udb.core import Agent, PolicyError
from udb.sandbox import reserve_vm
from udb.server_project_tools import register_project_tools


@pytest.fixture
def project(tmp_path):
    agent = Agent(tmp_path / "bridge")
    root = tmp_path / "project"
    root.mkdir()
    agent.register_local("demo", str(root), True)
    (root / "hello.py").write_text("x = 1\n", encoding="utf-8")
    return agent, root


@pytest.fixture
def guest_desktop_fixture(tmp_path):
    agent = Agent(tmp_path / "bridge")
    root = tmp_path / "source"
    root.mkdir()
    (root / "hello.py").write_text("x=1\n", encoding="utf-8")
    agent.register_local("demo", str(root), True)
    sid = "c" * 32
    source = agent.state / "desktops" / sid / "input"
    output = source.parent / "output"
    (source / "commands").mkdir(parents=True)
    (output / "replies").mkdir(parents=True)
    info = {
        "kind": "desktop",
        "expires": time.time() + 60,
        "task": "Guest fixture",
        "permissions": {},
        "project": "demo",
    }
    reserve_vm(agent, sid, info)
    (output / "ready.json").write_text(
        json.dumps({"session_id": sid, "state": {"width": 800, "height": 600}})
    )
    return agent, sid, source, output


@pytest.mark.parametrize(
    "language,script,timeout",
    [
        ("python", object(), 120),
        ("python", "x" * 64001, 120),
        ("python", "💡" * 20000, 120),
        ("python", "a\x00b", 120),
        ("python", "print(1)", True),
        ("python", "print(1)", 120.5),
        ("cmd", "print(1)", 120),
    ],
)
def test_41_sandbox_script_preflight_blocks_before_io(
    project, monkeypatch, language, script, timeout
):
    agent, _ = project

    def forbidden():
        pytest.fail("Availability must not be probed on invalid input")

    monkeypatch.setattr(sandbox, "available", forbidden)
    monkeypatch.setattr(
        agent,
        "snapshot",
        lambda *_: pytest.fail("No source traversal on invalid input"),
    )
    with pytest.raises(PolicyError):
        agent.propose_job("demo", language, script, timeout)
    with agent.connect() as c:
        assert c.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


def test_41_valid_job_keeps_approval_and_source_manifest(project, monkeypatch):
    agent, _ = project
    monkeypatch.setattr(sandbox, "available", lambda: True)
    response = agent.propose_job("demo", "python", "print(1)", 30)
    assert response["status"] == "pending_local_approval"
    with agent.connect() as c:
        proposal = json.loads(
            c.execute(
                "SELECT payload FROM requests WHERE id=?", (response["request_id"],)
            ).fetchone()[0]
        )
    assert proposal["manifest"] == agent.snapshot("demo")
    assert proposal["timeout"] == 30
    assert proposal["language"] == "python"


def test_42_snapshot_preserves_2000_source_file_cap(project, monkeypatch):
    agent, root = project
    (root / "hello.py").unlink()
    for index in range(2001):
        (root / f"file_{index:04}.py").write_bytes(b"x\n")
    reads = []

    def fake_read(project_name, relative):
        reads.append(relative)
        return b"x\n"

    monkeypatch.setattr(agent, "read_bytes", fake_read)
    with pytest.raises(PolicyError, match="2000 files"):
        agent.snapshot("demo")
    assert len(reads) == 2001


def test_42_snapshot_filters_binary_before_scoped_read(project, monkeypatch):
    agent, root = project
    (root / "image.bin").write_bytes(b"private-binary")
    nested = root / "nested"
    nested.mkdir()
    (nested / "child.py").write_text("y=1\\n", encoding="utf-8")
    (nested / "track.csv").write_bytes(b"private-data")
    reads = []
    original = agent.read_bytes

    def observed(project_name, relative):
        reads.append(relative)
        return original(project_name, relative)

    monkeypatch.setattr(agent, "read_bytes", observed)
    manifest = agent.snapshot("demo")
    assert set(manifest) == {"hello.py", "nested/child.py"}
    assert set(reads) == set(manifest)


def test_43_request_status_handles_empty_and_nonempty_result(project):
    agent, root = project
    requested = agent.propose("write", {"project": "demo", "root": str(root)})
    rid = requested["request_id"]
    initial = agent.request_status(rid)
    assert initial["result"] == {}
    assert initial["status"] == "pending"
    with agent.connect() as c:
        c.execute(
            "UPDATE requests SET status='rejected', result=? WHERE id=?",
            (json.dumps({"reason": "local owner denied"}), rid),
        )
    final = agent.request_status(rid)
    assert final["status"] == "rejected"
    assert final["result"] == {"reason": "local owner denied"}


def test_44_job_status_accepts_missing_log_then_exact_byte_page(project):
    agent, _ = project
    jid = "a" * 32
    with agent.connect() as c:
        c.execute(
            "INSERT INTO jobs VALUES (?,?,?)",
            (jid, "running", json.dumps({"language": "python"})),
        )
    waiting = agent.job_status(jid)
    assert waiting["info"]["language"] == "python"
    assert "output" not in waiting and "next_offset" not in waiting
    out = agent.state / "jobs" / jid / "output"
    out.mkdir(parents=True)
    (out / "output.log").write_bytes(b"abcdef")
    page = agent.job_status(jid, offset=2, limit=2)
    assert page["output"] == "cd" and page["next_offset"] == 4
    latest = agent.job_status(jid, limit=3, tail=True)
    assert latest["output"] == "def" and latest["next_offset"] == 6


class FakeMcp:
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn

        return register


def test_45_list_jobs_still_returns_only_last_30_in_order(project):
    agent, _ = project
    with agent.connect() as c:
        for n in range(35):
            c.execute(
                "INSERT INTO jobs VALUES (?,?,?)",
                (f"{n:032x}", "done", json.dumps({"order": n})),
            )
    mcp = FakeMcp()
    register_project_tools(mcp, agent, None, None)
    rows = mcp.tools["list_jobs"]()
    assert len(rows) == 30
    assert [json.loads(row["info"])["order"] for row in rows] == list(range(34, 4, -1))
    # A shorter read now avoids materializing/transporting 28 extra job rows.
    brief = mcp.tools["list_jobs"](limit=2)
    assert [json.loads(row["info"])["order"] for row in brief] == [34, 33]
    for invalid in (0, 31, True, 1.5):
        with pytest.raises(ValueError, match="1..30"):
            mcp.tools["list_jobs"](limit=invalid)


@pytest.mark.parametrize(
    "task,duration", [("", 600), ("good", True), ("good", 60.5), ("a" * 2001, 600)]
)
def test_46_invalid_desktop_task_fails_before_sandbox_probe(
    project, monkeypatch, task, duration
):
    agent, _ = project
    monkeypatch.setattr(
        vm, "available", lambda: pytest.fail("VM probe must not run for invalid task")
    )
    with pytest.raises(PolicyError):
        agent.propose_desktop("demo", task, duration)
    with agent.connect() as c:
        assert c.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


def test_47_49_dispatch_reuses_session_row_and_skips_progress_read(
    guest_desktop_fixture, monkeypatch
):
    agent, sid, source, output = guest_desktop_fixture
    (output / "progress.json").write_text(
        json.dumps({"session_id": sid, "completed": 1})
    )
    session_calls = []
    real_session = vm.session
    real_read_json = vm.read_json
    read_names = []

    def counted_session(owner, key):
        session_calls.append(key)
        return real_session(owner, key)

    def tracked_read_json(path, *args, **kwargs):
        read_names.append(path.name)
        return real_read_json(path, *args, **kwargs)

    def reply(_):
        for file in (source / "commands").glob("*.json"):
            (output / "replies" / file.name).write_text('{"ok":true}')

    monkeypatch.setattr(vm, "session", counted_session)
    monkeypatch.setattr(vm, "read_json", tracked_read_json)
    monkeypatch.setattr(vm.time, "sleep", reply)
    assert vm.command(agent, sid, "state")["ok"] is True
    # Once for initial validation, once for the mandated live revocation poll.
    assert session_calls == [sid, sid]
    assert "ready.json" in read_names and "progress.json" not in read_names
    # Public status must still report live progress and fresh session metadata.
    current = vm.status(agent, sid)
    assert current["progress_untrusted"]["completed"] == 1


def _png_chunk(kind, body):
    return (
        struct.pack("!I", len(body))
        + kind
        + body
        + struct.pack("!I", zlib.crc32(body, zlib.crc32(kind)) & 0xFFFFFFFF)
    )


def test_48_guest_png_crc_verification_uses_bounded_extra_memory():
    header = _png_chunk(b"IHDR", struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    image = (
        b"\x89PNG\r\n\x1a\n"
        + header
        + _png_chunk(b"IDAT", b"X" * (2 * 1024 * 1024))
        + _png_chunk(b"IEND", b"")
    )
    tracemalloc.start()
    try:
        vm.validate_png(image)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 512 * 1024
    with pytest.raises(PolicyError, match="checksum"):
        vm.validate_png(image[:-5] + b"x" + image[-4:])


def test_50_desktop_lock_schema_is_created_once_not_per_command(
    guest_desktop_fixture, monkeypatch
):
    agent, sid, source, output = guest_desktop_fixture
    with agent.connect() as c:
        exists = c.execute(
            "SELECT name FROM sqlite_master WHERE name='desktop_control'"
        ).fetchone()
    assert exists is not None
    statements = []
    original_connect = agent.connect

    def traced_connect():
        c = original_connect()
        c.set_trace_callback(statements.append)
        return c

    def reply(_):
        for file in (source / "commands").glob("*.json"):
            (output / "replies" / file.name).write_text('{"ok":true}')

    monkeypatch.setattr(agent, "connect", traced_connect)
    monkeypatch.setattr(vm.time, "sleep", reply)
    assert vm.command(agent, sid, "state")["ok"] is True
    assert any("desktop_control" in sql for sql in statements)
    assert not any("CREATE TABLE" in sql.upper() for sql in statements)
    with agent.connect() as c:
        assert c.execute("SELECT count(*) FROM desktop_control").fetchone()[0] == 0
