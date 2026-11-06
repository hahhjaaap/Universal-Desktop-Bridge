"""Real overlay visibility on one Job-owned synthetic tab strip."""

import json
import os
import queue
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("UDB_RUN_INTERACTIVE_WINDOWS_TESTS") != "1",
    reason="Native Windows overlay requires an isolated, explicitly opted-in desktop",
)


def test_native_overlay_follows_registered_tab_without_input(tmp_path, monkeypatch):
    import win32gui
    import win32process

    from udb import chrome_tab_identity as tabs
    from udb.companion.virtual_pointer import VirtualPointer
    from udb.computer_desktop import Desktop
    from udb.owned_process import OwnedProcess
    from udb.windows_paths import system_executable

    # The real owner's marker file and applications are never touched.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ready = tmp_path / "ready.json"
    process = OwnedProcess(
        [
            system_executable("powershell.exe"),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",  # The checked-in fixture only; no persistent policy change.
            "-Sta",
            "-File",
            str(Path(__file__).parent / "fixtures/native_tab_identity.ps1"),
            "-ReadyPath",
            str(ready),
        ],
        tmp_path,
    )
    pointer = None
    try:
        # Hosted Windows runners may be busy initializing a WPF compositor;
        # allow a bounded longer startup before declaring an actual failure.
        wait_seconds = 45 if os.environ.get("CI") == "true" else 20
        deadline = time.monotonic() + wait_seconds
        while not ready.exists() and time.monotonic() < deadline:
            error = ready.with_name(ready.name + ".error")
            assert process.alive(), (
                error.read_text() if error.exists() else "Fixture exited"
            )
            time.sleep(0.05)
        if not ready.exists():
            error = ready.with_name(ready.name + ".error")
            pytest.fail(
                error.read_text()
                if error.exists()
                else "Synthetic WPF fixture did not publish a window within "
                f"{wait_seconds}s; verify the runner's interactive desktop"
            )
        hwnd = json.loads(ready.read_text())["hwnd"]
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        assert process.owns_pid(pid)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pytest.skip(
                "Windows foreground policy refused the synthetic fixture window"
            )
        if win32gui.GetForegroundWindow() != hwnd:
            pytest.skip("Windows did not activate the synthetic fixture window")
        before = tabs.observe_tabs(hwnd)
        assert before and len(before) == 2
        selected = [row for row in before if row["selected"]]
        assert len(selected) == 1
        previous = [row for row in before if not row["selected"]]
        assert tabs.register_new_tab(hwnd, pid, previous)
        cursor = win32gui.GetCursorPos()
        pointer = VirtualPointer()
        pointer.show_idle()
        replies = queue.Queue()

        def read():
            for line in pointer.overlay.stdout:
                replies.put(line.strip())

        threading.Thread(target=read, daemon=True).start()

        def visible(expected):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                pointer.overlay.stdin.write(b"probe\n")
                if replies.get(timeout=8) == expected:
                    return
                time.sleep(0.1)
            pytest.fail("Native overlay did not reach " + repr(expected))

        visible(b"painted")
        assert win32gui.GetForegroundWindow() == hwnd
        assert win32gui.GetCursorPos() == cursor
        desktop = Desktop(guard=lambda: process.alive())
        assert desktop.uia(hwnd, "select", automation_id="Ordinary")["selected"]
        visible(b"hidden")
        assert desktop.uia(hwnd, "select", automation_id="AI")["selected"]
        visible(b"painted")
        tabs.marker_path().unlink()
        visible(b"hidden")
        assert win32gui.GetForegroundWindow() == hwnd
        assert win32gui.GetCursorPos() == cursor
    finally:
        if pointer is not None:
            pointer.close()
        process.close()
