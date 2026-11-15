"""Windows tool hot-path regressions for roadmap steps 51–60.

Uses synthetic owner homes, handles and image buffers only. Never starts real
host applications, changes the clipboard or sends desktop input.
"""

from __future__ import annotations

import json
import struct
import sys
import tracemalloc
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from udb import computer_desktop as desktop_mod
from udb import windows_utilities as utilities_mod
from udb.computer_capture import encode_bgrx_png
from udb.computer_desktop import Desktop
from udb.computer_jobs import MAX_OUTPUT, Jobs
from udb.core import Agent, PolicyError
from udb.windows_utilities import Utilities


class FakeProcess:
    def __init__(self, argv, cwd, output):
        self.argv = argv
        self.output = output
        self.closed = 0
        output.write_bytes(b"test-output")

    def poll(self):
        return None

    def close(self):
        self.closed += 1


@pytest.fixture
def manager(tmp_path):
    owner = Agent(tmp_path / "owner")
    folder = tmp_path / "work"
    folder.mkdir()
    jobs = Jobs(owner, lambda: "owner-grant", factory=FakeProcess)
    try:
        yield jobs, folder
    finally:
        jobs.close()


def test_51_start_rejects_boolean_timeout_before_executable_lookup(
    manager, monkeypatch
):
    jobs, work = manager
    monkeypatch.setattr(
        "udb.computer_jobs.executable_path",
        lambda *_: pytest.fail("invalid duration must not reach filesystem"),
    )
    with pytest.raises(PolicyError, match="timeout"):
        jobs.start(sys.executable, [], str(work), True, "owner-grant")
    assert not jobs.rows


def test_51_start_resolves_absolute_target_without_path_lookup(manager, monkeypatch):
    jobs, work = manager
    monkeypatch.setattr(
        "udb.computer_jobs.shutil.which",
        lambda *_: pytest.fail("absolute executable must not run PATH lookup"),
    )
    jid = jobs.start(
        str(Path(sys.executable).resolve()), [], str(work), 10, "owner-grant"
    )["job_id"]
    assert jobs.rows[jid]["process"].argv[0] == str(Path(sys.executable).resolve())


def test_52_end_of_output_quota_never_opens_a_log(manager):
    jobs, _ = manager

    class ClosedLog:
        def open(self, *_args, **_kwargs):
            pytest.fail("quota-complete cursor must not reopen log")

    jid = "test-job"
    jobs.rows[jid] = dict(
        status="exited",
        output=ClosedLog(),
        exit_code=0,
    )
    result = jobs.process("read", jid, offset=MAX_OUTPUT)
    assert result["output"] == ""
    assert result["next_offset"] == MAX_OUTPUT
    assert result["exit_code"] == 0
    for bad in (True, -1, MAX_OUTPUT + 1, 1.5):
        with pytest.raises(PolicyError, match="offset"):
            jobs.process("read", jid, offset=bad)


def test_53_list_only_materializes_requested_owned_rows(manager):
    jobs, _ = manager
    for index in range(30):
        jobs.rows[f"owned-{index}"] = dict(status="exited", exit_code=index)
    assert len(jobs.process("list")["jobs"]) == 30
    subset = jobs.process("list", limit=2)["jobs"]
    assert [row["job_id"] for row in subset] == ["owned-28", "owned-29"]
    for bad in (0, 31, True, 1.5):
        with pytest.raises(PolicyError, match="1..30"):
            jobs.process("list", limit=bad)


def test_54_released_slot_is_not_closed_twice_during_cleanup_retry(manager):
    jobs, _ = manager
    calls = []

    class Slot:
        def close(self):
            calls.append("slot")

    proc = SimpleNamespace(close=lambda: calls.append("process"))
    row = dict(process=proc, capacity=Slot(), status="running", exit_code=None)
    jobs._finish(row, "stopped")
    jobs._finish(row, "stopped")
    assert row["capacity"] is None
    assert calls.count("slot") == 1


def test_55_window_listing_uses_one_fresh_metadata_sample_per_window():
    counts = dict(text=0, kind=0, foreground=0)
    gui = SimpleNamespace(
        IsWindowVisible=lambda hwnd: True,
        GetWindowText=lambda hwnd: (
            counts.__setitem__("text", counts["text"] + 1) or "Example"
        ),
        GetClassName=lambda hwnd: (
            counts.__setitem__("kind", counts["kind"] + 1) or "FixtureWindow"
        ),
        GetForegroundWindow=lambda: (
            counts.__setitem__("foreground", counts["foreground"] + 1) or 42
        ),
        GetWindowRect=lambda hwnd: (0, 0, 500, 400),
        IsIconic=lambda hwnd: False,
        EnumWindows=lambda callback, param: callback(42, param),
        IsWindow=lambda hwnd: True,
    )
    desk = Desktop.__new__(Desktop)
    desk.gui = gui
    desk.process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (0, 123))
    desk.is_cloaked = lambda hwnd: False
    desk.interactive = lambda: None
    listed = desk.listing()
    assert listed["windows"][0]["foreground"] is True
    assert counts == {"text": 1, "kind": 1, "foreground": 1}
    assert desk.resolve(listed["windows"][0]["window_id"], focus=False) == 42
    assert counts["kind"] == 2  # identity rechecked when the window is used


def _unpack_png(data):
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    chunks = {}
    while pos < len(data):
        count = struct.unpack("!I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        value = data[pos + 8 : pos + 8 + count]
        checksum = struct.unpack("!I", data[pos + 8 + count : pos + 12 + count])[0]
        assert checksum == zlib.crc32(value, zlib.crc32(kind)) & 0xFFFFFFFF
        chunks.setdefault(kind, []).append(value)
        pos += 12 + count
    return chunks


def test_56_capture_encodes_exact_bgrx_pixels_and_crc():
    source = bytes([0, 0, 255, 255, 255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 0, 255])
    chunks = _unpack_png(encode_bgrx_png(source, 2, 2))
    assert struct.unpack("!II", chunks[b"IHDR"][0][:8]) == (2, 2)
    pixels = zlib.decompress(chunks[b"IDAT"][0])
    assert pixels == bytes([0, 255, 0, 0, 0, 0, 255, 0, 0, 255, 0, 0, 0, 0])
    with pytest.raises(ValueError, match="buffer"):
        encode_bgrx_png(b"short", 2, 2)


def test_56_png_intermediate_memory_is_bounded():
    source = b"\x01\x02\x03\x04" * (800 * 600)
    tracemalloc.start()
    try:
        encoded = encode_bgrx_png(source, 800, 600)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert encoded.startswith(b"\x89PNG")
    assert peak < 3 * 1024 * 1024


def test_57_58_uia_uses_compact_json_and_rejects_nonzero_without_parsing(
    monkeypatch,
):
    desk = Desktop.__new__(Desktop)
    desk.interactive = lambda: None
    desk.process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (0, 123))
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=' {"ok":true,"text":"safe"}\n', returncode=0)

    monkeypatch.setattr(desktop_mod.subprocess, "run", run)
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    result = desk.uia(42, "read_text", name="Editor", limit=42)
    assert result["text"] == "safe"
    argv, opts = calls[-1]
    assert opts["shell"] is False
    assert opts["input"].startswith('{"hwnd":42,"pid":123')
    assert json.loads(opts["input"])["limit"] == 42
    assert str(desktop_mod._UIA_HELPER) in argv

    monkeypatch.setattr(
        desktop_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="sensitive-helper-output", returncode=1
        ),
    )
    with pytest.raises(PolicyError, match="outcome may be unknown") as error:
        desk.uia(42, "invoke", name="Button")
    assert "sensitive-helper-output" not in str(error.value)


def test_59_invalid_clipboard_version_rejected_before_input_observation(
    tmp_path, monkeypatch
):
    tool = Utilities(Agent(tmp_path), backend=SimpleNamespace())
    monkeypatch.setattr(
        utilities_mod,
        "InputControl",
        lambda _agent: pytest.fail("invalid CAS must not initialize input observer"),
    )
    with pytest.raises(PolicyError, match="expected_version"):
        tool.dispatch("clipboard_set", text="will not write", expected_version="oops")
    assert tool.control is None


def test_60_app_selection_short_circuits_ambiguity_without_launch(tmp_path):
    class Backend:
        def __init__(self):
            self.launched = []

        def apps(self):
            return [
                {"name": "Editor", "app_id": "app-one"},
                {"name": "EDITOR", "app_id": "app-two"},
                {"name": None, "app_id": None},  # must not be visited
            ]

        def launch(self, app_id):
            self.launched.append(app_id)
            return dict(requested=True)

    backend = Backend()
    tool = Utilities(
        Agent(tmp_path), backend=backend, control=SimpleNamespace(check=lambda: None)
    )
    with pytest.raises(PolicyError, match="ambiguous"):
        tool.dispatch("launch_app", name="Editor")
    assert backend.launched == []


def test_60_app_selection_accepts_unique_exact_id(tmp_path):
    backend = SimpleNamespace(
        apps=lambda: [
            {"name": "Editor", "app_id": "app-one"},
            {"name": "Browser", "app_id": "app-two"},
        ],
        launch=lambda app_id: {"app_id": app_id, "requested": True},
    )
    tool = Utilities(
        Agent(tmp_path), backend=backend, control=SimpleNamespace(check=lambda: None)
    )
    assert tool.dispatch("launch_app", name="app-two")["app_id"] == "app-two"
    with pytest.raises(PolicyError, match="unknown or ambiguous"):
        tool.dispatch("launch_app", name="app")
