"""Regressions for per-tool optimization group 71–80.

The fixtures never spawn a shell, access an owner desktop, or replay a job.
"""

from __future__ import annotations

import collections
import queue
import threading
from types import SimpleNamespace

import pytest

from udb.companion.background import Background
from udb.companion.extensions import _file_search_context, _terminal_list
from udb.companion.files import ScopedFiles
from udb.companion.jobs import Task
from udb.companion.journal import WorkRecovery
from udb.companion.runtime import Runtime
from udb.companion.search import SearchMixin
from udb.companion.terminal import TerminalSession


def test_71_terminal_invalid_envelope_fails_before_scoped_path_lookup():
    runtime = Runtime.__new__(Runtime)
    runtime.enable_terminal = True
    runtime.sessions = {}
    runtime.files = SimpleNamespace(
        path=lambda *_a: pytest.fail("invalid request must not touch filesystem")
    )
    for kwargs in (
        {"timeout_seconds": True},
        {"memory_mib": False},
        {"arguments": ["a\x00b"]},
        {"mode": "unknown"},
    ):
        params = dict(
            program="python",
            arguments=[],
            cwd=".",
            timeout_seconds=60,
            memory_mib=128,
            mode="pipe",
            columns=100,
            rows=30,
        )
        params.update(kwargs)
        with pytest.raises(ValueError):
            runtime._start(**params)


def test_72_terminal_list_keeps_order_and_live_process_status():
    readings = []

    def process(name, exit_code):
        return SimpleNamespace(poll=lambda: readings.append(name) or exit_code)

    runtime = SimpleNamespace(
        sessions={
            "first": SimpleNamespace(process=process("first", None)),
            "second": SimpleNamespace(process=process("second", 0)),
            "third": SimpleNamespace(process=process("third", 8)),
        }
    )
    assert _terminal_list(runtime, {}) == (
        "first | RUNNING | exit=None\nsecond | PASS | exit=0\nthird | ERROR | exit=8"
    )
    assert readings == ["first", "second", "third"]
    runtime.sessions.clear()
    assert _terminal_list(runtime, {}) == "No companion-owned terminal sessions."


def _terminal_with_fake_process(data=b"", code=None):
    terminal = TerminalSession.__new__(TerminalSession)
    terminal.id = "a" * 12
    terminal.chunks = collections.deque([(0, data)] if data else [])
    terminal.position = len(data)
    terminal.read_cursor = 0
    terminal.lock = threading.Lock()
    terminal.arrival = threading.Event()
    terminal.done = False
    terminal.reason = ""
    terminal.mode = "pipe"
    terminal.process = SimpleNamespace(poll=lambda: code)
    return terminal


def test_73_idle_terminal_read_does_not_create_utf8_decoder(monkeypatch):
    terminal = _terminal_with_fake_process()
    monkeypatch.setattr(
        "udb.companion.terminal.codecs.getincrementaldecoder",
        lambda *_args: pytest.fail("idle read should not allocate decoder"),
    )
    row = terminal.read(0, 0)
    assert row["output"] == ""
    assert row["output_base64"] == ""
    assert row["next_offset"] == 0
    assert row["state"] == "RUNNING"


def test_73_terminal_partial_utf8_cursor_preserved():
    terminal = _terminal_with_fake_process(b"\xe2\x82")
    pending = terminal.read(0, 0)
    assert pending["output"] == ""
    assert pending["next_offset"] == 0
    terminal.chunks.append((2, b"\xac"))
    terminal.position = 3
    full = terminal.read(0, 0)
    assert full["output"] == "€"
    assert full["next_offset"] == 3


def test_74_terminal_send_encodes_once_and_still_enforces_byte_limit():
    class Counted(str):
        calls = 0

        def encode(self, *args, **kwargs):
            self.calls += 1
            return super().encode(*args, **kwargs)

    terminal = _terminal_with_fake_process()
    terminal.input_queue = queue.Queue(maxsize=4)
    terminal.input_done = threading.Event()
    msg = Counted("é" * 4000)
    assert terminal.send(msg)["input_queued"] is True
    assert msg.calls == 1
    assert terminal.input_queue.get_nowait() == msg.encode("utf-8")
    with pytest.raises(ValueError, match="Input limit"):
        terminal.send("é" * 5001)
    assert terminal.input_queue.empty()


def test_75_terminal_capacity_slot_closed_once_on_repeated_stop():
    terminal = _terminal_with_fake_process()
    counts = []

    class Slot:
        def close(self):
            counts.append("slot")

    class Process:
        stdin = SimpleNamespace(close=lambda: None)
        stdout = SimpleNamespace(close=lambda: None)

        def __init__(self):
            self.exit = None

        def poll(self):
            return self.exit

        def close(self):
            self.exit = 0

    terminal.process = Process()
    terminal.capacity = Slot()
    terminal.input_done = threading.Event()
    terminal.thread = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    assert terminal.stop()["state"] == "STOPPED"
    assert terminal.stop()["state"] == "STOPPED"
    assert counts == ["slot"]
    assert terminal.capacity is None


def test_76_search_invalid_envelope_skips_path_resolution():
    search = SearchMixin()
    search.files = SimpleNamespace(
        path=lambda *_a: pytest.fail("preflight must run before scoped path")
    )
    for kwargs in (
        {"text": "x" * 501},
        {"pattern": "*" * 201},
        {"timeout_seconds": 121},
        {"search_type": "unsupported"},
    ):
        with pytest.raises(ValueError):
            search.search(**kwargs)


def test_77_live_search_read_and_cancel_skip_journal_load():
    bg = Background.__new__(Background)
    calls = []
    bg.tasks = {
        "owned": SimpleNamespace(
            read=lambda offset, limit: (
                calls.append(("read", offset, limit)) or {"ok": True}
            ),
            stop=lambda: calls.append(("stop",)) or {"cancel": True},
        )
    }
    bg.journal = SimpleNamespace(
        load=lambda *_a: pytest.fail("live owned job should not decrypt journal")
    )
    assert bg.task("owned", "read", offset=2, limit=5) == {"ok": True}
    assert bg.task("owned", "cancel") == {"cancel": True}
    assert calls == [("read", 2, 5), ("stop",)]


def test_78_search_cancel_is_idempotent_without_skipping_worker_terminate():
    task = Task("search")
    terminated = []
    task.worker = SimpleNamespace(terminate=lambda: terminated.append("kill"))
    assert task._checkpoint_version == 0
    first = task.stop()
    second = task.stop()
    assert first["cancellation_requested"] is True
    assert second["cancellation_requested"] is True
    assert task._checkpoint_version == 1
    assert terminated == ["kill", "kill"]


def test_79_context_search_keeps_line_numbers_and_protected_roots(tmp_path):
    (tmp_path / "alpha.txt").write_text("north\nNeedLe\nsouth\n", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("another needle\n", encoding="utf-8")
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("needle secret\n", encoding="utf-8")
    rt = SimpleNamespace(files=ScopedFiles(str(tmp_path)))
    row = _file_search_context(
        rt,
        {"path": ".", "pattern": "*.txt", "text": "NEEDLE", "context": 1, "limit": 10},
    )
    assert "alpha.txt:2" in row
    assert "2: NeedLe" in row
    assert "beta.txt:1" in row
    assert "secret.txt" not in row


def test_80_recovery_inspects_live_owned_state_without_journal_io():
    class Journal:
        def load(self, key):
            pytest.fail("Live task inspect must not decode disk journal")

    task = SimpleNamespace(read=lambda: {"state": "running", "job_id": "owned"})
    terminal = SimpleNamespace(
        read=lambda offset, wait_ms: {
            "state": "RUNNING",
            "session_id": "console",
            "next_offset": 0,
        }
    )
    bg = SimpleNamespace(journal=Journal(), tasks={"owned": task})
    rt = SimpleNamespace(
        features=SimpleNamespace(background=bg), sessions={"console": terminal}
    )
    work = WorkRecovery(rt)
    assert work.call("inspect", "job", "owned") == {
        "state": "running",
        "job_id": "owned",
    }
    assert work.call("inspect", "terminal", "console")["state"] == "RUNNING"
    with pytest.raises(ValueError, match="action"):
        work.call("unknown", "job", "owned")
