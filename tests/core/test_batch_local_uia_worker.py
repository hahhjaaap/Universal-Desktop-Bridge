"""Batch-local UIA worker reuse without touching a real Windows desktop."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


@pytest.fixture
def fake_batch_desktop(monkeypatch):
    monkeypatch.delenv("UDB_UIA_PERSISTENT", raising=False)
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    created = []
    calls = []
    closed = []

    class FakeWorker:
        def __init__(self, executable, helper):
            created.append((str(executable), str(helper)))

        def call(self, request, deadline):
            calls.append((request, deadline))
            return {"ok": True, "text": "fixture-safe"}

        def close(self):
            closed.append(True)

    monkeypatch.setattr("udb.uia_worker.PersistentUIA", FakeWorker)
    monkeypatch.setattr(
        "udb.computer_desktop.subprocess.run",
        lambda *_a, **_k: pytest.fail("Batch must not start one-shot UIA subprocess"),
    )
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = lambda: None
    desktop.process = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, 321)
    )
    desktop._uia_worker = None

    def dispatch(action, window_id="", **_other):
        assert window_id == "observed-window"
        return desktop.uia(1001, action)

    desktop._dispatch = dispatch
    return desktop, created, calls, closed


def test_two_uia_steps_start_one_private_helper_and_close_at_batch_end(
    fake_batch_desktop,
):
    desktop, created, calls, closed = fake_batch_desktop
    result = desktop.batch(
        "observed-window",
        [
            {"action": "snapshot", "verify": {"field": "ok", "equals": True}},
            {"action": "read_text", "return_result": False},
        ],
    )
    assert result["ok"] is True
    assert result["completed_steps"] == 2
    assert len(created) == 1
    assert [request["mode"] for request, _ in calls] == ["snapshot", "read_text"]
    assert all(request["hwnd"] == 1001 and request["pid"] == 321 for request, _ in calls)
    assert closed == [True]
    assert desktop._uia_worker is None
    assert desktop._batch_uia is False
    assert "result" not in result["results"][1]


def test_failed_mutating_step_cleans_helper_without_retry(fake_batch_desktop):
    desktop, created, calls, closed = fake_batch_desktop

    def fail_mutation(_request, _deadline):
        calls.append(("invoke", "one attempt"))
        raise PolicyError("UIA worker stopped; outcome may be unknown")

    class FailedWorker:
        def __init__(self, executable, helper):
            created.append((str(executable), str(helper)))

        def call(self, request, timeout):
            return fail_mutation(request, timeout)

        def close(self):
            closed.append(True)

    import udb.uia_worker as uia_worker

    original = uia_worker.PersistentUIA
    uia_worker.PersistentUIA = FailedWorker
    try:
        result = desktop.batch(
            "observed-window",
            [{"action": "invoke"}, {"action": "read_text"}],
        )
    finally:
        uia_worker.PersistentUIA = original
    assert result["ok"] is False
    assert result["completed_steps"] == 0
    assert result["failed_index"] == 0
    assert len(calls) == 1
    assert len(created) == 1 and closed == [True]
    assert desktop._uia_worker is None


def test_guarded_skip_does_not_start_power_shell(fake_batch_desktop):
    desktop, created, calls, closed = fake_batch_desktop

    def dispatch(action, window_id="", **_kwargs):
        if action == "control_status":
            return {"paused": True}
        pytest.fail("Skipped UIA step must not execute")

    desktop._dispatch = dispatch
    result = desktop.batch(
        "observed-window",
        [
            {"action": "control_status"},
            {
                "action": "snapshot",
                "when": {"step_index": 0, "field": "paused", "equals": False},
            },
        ],
    )
    assert result["ok"] and result["completed_steps"] == 1
    assert result["results"][1]["skipped"]
    assert created == calls == closed == []
    assert desktop._uia_worker is None


def test_invalid_batch_does_not_enable_worker(fake_batch_desktop):
    desktop, created, calls, closed = fake_batch_desktop
    with pytest.raises(PolicyError):
        desktop.batch(
            "observed-window",
            [{"action": "snapshot"}, {"action": "batch"}],
        )
    assert created == calls == closed == []
    assert not getattr(desktop, "_batch_uia", False)


def test_global_persistent_opt_in_keeps_existing_lifetime(fake_batch_desktop, monkeypatch):
    desktop, created, calls, closed = fake_batch_desktop
    monkeypatch.setenv("UDB_UIA_PERSISTENT", "1")
    result = desktop.batch(
        "observed-window",
        [{"action": "snapshot"}, {"action": "read_text"}],
    )
    assert result["ok"] is True
    assert len(created) == 1 and len(calls) == 2
    assert closed == [] and desktop._uia_worker is not None
    desktop.close()
    assert closed == [True]
