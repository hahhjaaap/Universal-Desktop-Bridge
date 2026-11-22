"""Synthetic UI Automation persistent-worker regression and no-replay contracts.

On Windows only, a deliberate zero-HWND fixture checks that the static
PowerShell helper stays alive for two *rejected* inputs, never a live window.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from udb import hyperspeed_perf as perf
from udb.computer_desktop import Desktop
from udb.core import PolicyError
from udb.uia_worker import PersistentUIA, enabled


class FakeInput:
    def __init__(self, replies, results):
        self.replies = replies
        self.results = results
        self.writes = []
        self.fail = False
        self.block = False
        self.written = threading.Event()

    def write(self, data):
        self.writes.append(data)
        self.written.set()
        if self.fail:
            raise BrokenPipeError("fixture broken pipe")
        if self.replies:
            self.results.put(self.replies.pop(0))
        elif not self.block:
            self.results.put(None)

    def flush(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self, replies, results):
        self.stdin = FakeInput(replies, results)
        self.stdout = SimpleNamespace(close=lambda: None)
        self.killed = False

    def poll(self):
        return None if not self.killed else 1

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 1


@pytest.fixture
def fake_worker(monkeypatch):
    worker = PersistentUIA(Path("fixed.exe"), Path("fixed.ps1"))
    responses = queue.Queue(maxsize=2)
    fixture = FakeProcess(
        ['{"sequence":1,"result":{"ok":true,"verified_control_value":true}}\n'],
        responses,
    )

    def begin():
        worker._process = fixture
        worker._replies = responses

    monkeypatch.setattr(worker, "_begin", begin)
    yield worker, fixture, responses
    worker.close()


def test_21_22_24_worker_reuses_one_private_process_for_two_requests(fake_worker):
    worker, fake, _ = fake_worker
    fake.stdin.replies.append('{"sequence":2,"result":{"ok":true,"matched":true}}\n')
    assert worker.call({"hwnd": 19, "pid": 33, "mode": "read_text"}, 1)["ok"]
    assert worker.call({"hwnd": 19, "pid": 33, "mode": "wait_for"}, 1)["ok"]
    assert len(fake.stdin.writes) == 2
    assert fake.stdin.writes[0].endswith("\n")
    assert json.loads(fake.stdin.writes[0])["pid"] == 33


def test_22_worker_never_launches_a_network_server(fake_worker):
    worker, _, _ = fake_worker
    assert not hasattr(worker, "listen")
    assert not hasattr(worker, "bind")


def test_23_worker_kills_process_after_bad_framing_without_replay(fake_worker):
    worker, fake, _ = fake_worker
    fake.stdin.replies[:] = ['{"sequence":1,"result":{"ok":true}}']
    with pytest.raises(PolicyError, match="may be unknown"):
        worker.call({"mode": "invoke", "hwnd": 19}, 1)
    assert fake.killed
    assert len(fake.stdin.writes) == 1


def test_23_worker_kills_process_on_timeout(fake_worker):
    worker, fake, _ = fake_worker
    fake.stdin.replies[:] = []
    # Queue returns None, which is an EOF error; no further action sent.
    with pytest.raises(PolicyError, match="may be unknown"):
        worker.call({"mode": "set_value", "hwnd": 19}, 1)
    assert fake.killed
    assert len(fake.stdin.writes) == 1


def test_23_stale_duplicate_sequence_cannot_be_reported_as_next_result(
    fake_worker,
):
    worker, fake, _ = fake_worker
    fake.stdin.replies[:] = [
        '{"sequence":1,"result":{"ok":true}}\n',
        '{"sequence":1,"result":{"ok":true}}\n',
    ]
    assert worker.call({"mode": "read_text"}, 1)["ok"]
    with pytest.raises(PolicyError, match="may be unknown"):
        worker.call({"mode": "invoke"}, 1)
    assert fake.killed
    assert len(fake.stdin.writes) == 2


def test_24_worker_rejects_oversized_request_before_any_write(fake_worker):
    worker, fake, _ = fake_worker
    with pytest.raises(PolicyError, match="too large"):
        worker.call({"text": "x" * 100001}, 1)
    assert fake.stdin.writes == []


def test_25_worker_rejects_nonfinite_or_unserializable_data(fake_worker):
    worker, fake, _ = fake_worker
    with pytest.raises(PolicyError, match="Invalid UIA request"):
        worker.call({"hwnd": float("nan")}, 1)
    with pytest.raises(PolicyError, match="Invalid UIA request"):
        worker.call({"hwnd": object()}, 1)
    assert not fake.stdin.writes


def test_26_worker_reports_app_refusal_without_replay(fake_worker):
    worker, fake, _ = fake_worker
    fake.stdin.replies[:] = [
        '{"sequence":1,"result":{"ok":false,"error":"control changed"}}\n'
    ]
    assert worker.call({"mode": "invoke", "hwnd": 19}, 1)["ok"] is False
    assert len(fake.stdin.writes) == 1
    assert not fake.killed


def test_27_opt_in_is_explicit_and_fails_closed(monkeypatch):
    monkeypatch.delenv("UDB_UIA_PERSISTENT", raising=False)
    assert not enabled()
    monkeypatch.setenv("UDB_UIA_PERSISTENT", "yes")
    assert not enabled()
    monkeypatch.setenv("UDB_UIA_PERSISTENT", "1")
    assert enabled()


def test_28_interactive_preflight_blocks_before_worker_request(monkeypatch):
    monkeypatch.setenv("UDB_UIA_PERSISTENT", "1")
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = Mock(side_effect=PolicyError("Computer grant revoked"))
    desktop.process = Mock()
    desktop._uia_worker = Mock()
    with pytest.raises(PolicyError, match="revoked"):
        desktop.uia(190, "set_value", text="fixture")
    desktop.process.GetWindowThreadProcessId.assert_not_called()
    desktop._uia_worker.call.assert_not_called()


def test_29_no_one_shot_fallback_on_uncertain_worker_outcome(monkeypatch):
    monkeypatch.setenv("UDB_UIA_PERSISTENT", "1")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = Mock()
    desktop.process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 123))
    desktop._uia_worker = Mock()
    desktop._uia_worker.call.side_effect = PolicyError("may be unknown")
    monkeypatch.setattr(
        "udb.computer_desktop.subprocess.run",
        lambda *_a, **_k: pytest.fail("Uncertain mutation must not be replayed"),
    )
    with pytest.raises(PolicyError, match="may be unknown"):
        desktop.uia(190, "invoke", name="Submit")
    desktop._uia_worker.call.assert_called_once()


def test_30_close_is_idempotent_and_closes_private_process(fake_worker):
    worker, fake, _ = fake_worker
    worker.call({"mode": "snapshot", "hwnd": 19}, 1)
    worker.close()
    worker.close()
    assert fake.killed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
def test_windows_powershell_two_rejected_requests_keep_worker_alive():
    helper = Path(__file__).parents[2] / "src" / "udb" / "computer_uia.ps1"
    exe = Path(os.environ["SystemRoot"]) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    fixture = {
        "hwnd": 0,
        "pid": -1,  # Cannot match any live Windows process, even the desktop root.
        "mode": "snapshot",
        "text": "",
    }
    process = subprocess.Popen(
        [
            str(exe),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Sta",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-Persistent",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        data, stderr = process.communicate(
            ((json.dumps(fixture) + "\n") * 2).encode("utf-8"), timeout=18
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    assert process.returncode == 0, stderr[:300]
    lines = data.decode("utf-8-sig").splitlines()
    assert len(lines) == 2, (lines, stderr[:300])
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]
    assert all(json.loads(line)["result"]["ok"] is False for line in lines)


def test_helper_keeps_per_request_pid_checks_and_refuses_password_reads():
    script = (Path(__file__).parents[2] / "src" / "udb" / "computer_uia.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "$root.Current.ProcessId -ne [int]$r.pid" in script
    assert "if($target.Current.IsPassword)" in script
    assert "Unsupported UIA mode" in script
    assert "[Console]::In.ReadLine()" in script
    assert "$script:UdbProvidersRegistered" in script


def test_24_warm_worker_avoids_redundant_root_lookup_with_live_pid_guard():
    script = (Path(__file__).parents[2] / "src" / "udb" / "computer_uia.ps1").read_text(
        encoding="utf-8-sig"
    )
    start = script.index("    $root=[Windows.Automation.AutomationElement]::FromHandle")
    end = script.index("    if($r.mode -in @('chatgpt_prepare'", start)
    preflight = script[start:end]
    provider_start = preflight.index("    if (-not $script:UdbProvidersRegistered)")
    provider_end = preflight.index("\n    }", provider_start)
    # Always resolve a fresh HWND/PID on each request. Only the first
    # provider registration is allowed to reacquire the same root.
    assert preflight.count("::FromHandle") == 2
    assert preflight.count("$root.Current.ProcessId -ne [int]$r.pid") == 2
    assert preflight.rfind("::FromHandle") < provider_end


def test_30_opt_in_worker_trace_redacts_payload(fake_worker, monkeypatch, tmp_path):
    worker, _, _ = fake_worker
    perf.disable()
    monkeypatch.setenv("UDB_HYPERSPEED_TRACE", "1")
    assert perf.configure(tmp_path)
    try:
        request = {"hwnd": 19, "pid": 33, "mode": "read_text", "text": "private"}
        assert worker.call(request, 1)["ok"]
        path = tmp_path / "hyperspeed" / "traces.jsonl"
        events = perf.read_trace(path)
        phases = [event["phase"] for event in events]
        assert phases == ["startup", "dispatch", "observation"]
        assert all(event["operation"] == "desktop.uia" for event in events)
        assert all(event["duration_ns"] >= 0 for event in events)
        assert "private" not in path.read_text(encoding="utf-8")
    finally:
        perf.disable()


def test_31_worker_stops_inflight_wait_when_computer_access_is_revoked(fake_worker):
    worker, fake, _ = fake_worker
    fake.stdin.block = True
    checked = threading.Event()

    def revoked():
        checked.set()
        raise PolicyError("Computer access was revoked")

    with pytest.raises(PolicyError, match="revoked"):
        worker.call({"mode": "wait_for"}, 2, cancel_check=revoked)
    assert checked.wait(1)
    assert fake.killed
    assert len(fake.stdin.writes) == 1


def test_31_close_cancels_inflight_wait_without_replay(fake_worker):
    worker, fake, _ = fake_worker
    fake.stdin.block = True
    errors = []

    def invoke():
        try:
            worker.call({"mode": "wait_for"}, 5)
        except PolicyError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    assert fake.stdin.written.wait(1)
    worker.close()
    thread.join(2)
    assert not thread.is_alive()
    assert fake.killed
    assert len(fake.stdin.writes) == 1
    assert errors and "closed" in errors[0]


def test_32_event_observer_is_opt_in_and_requires_persistent_worker(monkeypatch):
    monkeypatch.setenv("UDB_UIA_PERSISTENT", "1")
    monkeypatch.delenv("UDB_UIA_EVENT_OBSERVER", raising=False)
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = Mock()
    desktop.process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 123))
    desktop._uia_worker = Mock()
    desktop._uia_worker.call.return_value = {"ok": True}

    desktop.uia(190, "wait_for", automation_id="fixture", wait_ms=100)
    request = desktop._uia_worker.call.call_args.args[0]
    assert request["event_observer"] is False
    assert desktop._uia_worker.call.call_args.kwargs["cancel_check"] == desktop.interactive

    monkeypatch.setenv("UDB_UIA_EVENT_OBSERVER", "1")
    desktop._uia_worker.call.reset_mock()
    desktop.uia(190, "wait_for", automation_id="fixture", wait_ms=100)
    request = desktop._uia_worker.call.call_args.args[0]
    assert request["event_observer"] is True
    assert desktop._uia_worker.call.call_args.kwargs["cancel_check"] == desktop.interactive


def test_32_one_shot_wait_never_enables_event_observer(monkeypatch):
    monkeypatch.delenv("UDB_UIA_PERSISTENT", raising=False)
    monkeypatch.setenv("UDB_UIA_EVENT_OBSERVER", "1")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = Mock()
    desktop.process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 123))
    captured = {}

    def run(*args, **kwargs):
        captured.update(json.loads(kwargs["input"]))
        return SimpleNamespace(stdout='{"ok":true}', returncode=0)

    monkeypatch.setattr("udb.computer_desktop.subprocess.run", run)
    assert desktop.uia(190, "wait_for", automation_id="fixture", wait_ms=100)["ok"]
    assert captured["event_observer"] is False


def test_33_wait_for_event_handlers_are_bounded_and_removed_in_finally():
    script = (
        Path(__file__).parents[2] / "src" / "udb" / "computer_uia.ps1"
    ).read_text(encoding="utf-8-sig")
    start = script.index("        if($r.mode -eq 'wait_for')")
    end = script.index("        $matches=$root.FindAll", start)
    wait_block = script[start:end]
    assert "AddStructureChangedEventHandler" in wait_block
    assert "RemoveStructureChangedEventHandler" in wait_block
    assert "AddAutomationPropertyChangedEventHandler" in wait_block
    assert "RemoveAutomationPropertyChangedEventHandler" in wait_block
    assert "WaitOne($remaining)" in wait_block
    assert "Start-Sleep -Milliseconds $remaining" in wait_block
    assert "observer_cleanup=$observerCleanup" in wait_block
    assert "finally{" in wait_block


def test_33_wait_for_revalidates_hwnd_pid_and_runtime_identity():
    script = (
        Path(__file__).parents[2] / "src" / "udb" / "computer_uia.ps1"
    ).read_text(encoding="utf-8-sig")
    start = script.index("        if($r.mode -eq 'wait_for')")
    end = script.index("        $matches=$root.FindAll", start)
    wait_block = script[start:end]
    assert "FromHandle([IntPtr]$r.hwnd)" in wait_block
    assert "$liveRoot.Current.ProcessId -ne [int]$r.pid" in wait_block
    assert "$liveRuntimeId -ne $rootRuntimeId" in wait_block
