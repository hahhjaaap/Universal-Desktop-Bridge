"""Native batch/capture boundaries, including uncertain mutation recovery."""

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from udb import browser_batch as batches
from udb import browser_capture as capture
from udb import host_client
from udb.core import Agent, PolicyError
from udb.host_service import HostService
from udb.resources import Governor

SID = "a" * 32


@pytest.fixture
def engine(tmp_path):
    h = HostService.__new__(HostService)
    h.agent = Agent(tmp_path / "home")
    host_client.atomic_json(h.agent.state / "host-settings.json", {"enabled": True})
    h.folder = h.agent.state / "host"
    h.folder.mkdir()
    h.stop_event = threading.Event()
    h.resource = Governor().update(
        dict(
            at=time.time(),
            cpu_percent=10,
            ram_percent=30,
            available_mib=6000,
            commit_percent=30,
        )
    )
    browser = SimpleNamespace(
        visible=False,
        frozen=False,
        deadline=time.monotonic() + 20,
        sid=Mock(return_value="owned"),
        screenshot=Mock(return_value="cG5n"),
    )
    h.sessions = {SID: dict(kind="browser", object=browser, expires=time.time() + 900)}
    return h


def args(steps=None, rid="test-1"):
    return dict(
        session_id=SID,
        tab_id="tab",
        request_id=rid,
        steps=steps or [{"action": "click", "selector": "#submit"}, {"action": "read"}],
    )


def test_batch_uses_one_dispatch_and_never_replays_after_result_eviction(
    engine, monkeypatch
):
    dispatch = Mock(return_value={"ok": True})
    monkeypatch.setattr(batches, "dispatch_browser", dispatch)
    payload = args()
    first = engine.dispatch("browser", dict(payload, action="batch"))
    assert first["state"] == "completed" and first["completed_steps"] == 2
    assert dispatch.call_count == 2
    assert engine.dispatch("browser", dict(payload, action="batch"))["cached_result"]
    engine.batches = batches.BatchRunner()  # Simulates lost in-memory output.
    receipt = engine.dispatch("browser", dict(payload, action="batch"))
    assert receipt["result_available"] is False and not receipt["outcome_unknown"]
    assert dispatch.call_count == 2
    with pytest.raises(PolicyError, match="different actions"):
        engine.dispatch("browser", dict(args([{"action": "reload"}]), action="batch"))
    assert (
        "submit"
        not in next((engine.folder / "batches" / SID).glob("*.json")).read_text()
    )


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"action": "batch"}],
        [{"action": "click", "session_id": "other"}],
        [{"action": "upload"}],
        [{"action": "read"}] * 13,
    ],
)
def test_batch_rejects_entire_structure_before_page_input(engine, monkeypatch, steps):
    dispatch = Mock()
    monkeypatch.setattr(batches, "dispatch_browser", dispatch)
    with pytest.raises(PolicyError):
        batches.BatchRunner().run(
            engine, engine.sessions[SID]["object"], dict(args(), steps=steps)
        )
    dispatch.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("private page detail"),
        {"ok": False},
        {"navigation_timed_out": True},
    ],
)
def test_batch_stops_on_failure_and_retry_does_not_resubmit(
    engine, monkeypatch, failure
):
    dispatch = (
        Mock(side_effect=failure)
        if isinstance(failure, Exception)
        else Mock(return_value=failure)
    )
    monkeypatch.setattr(batches, "dispatch_browser", dispatch)
    runner = batches.BatchRunner()
    result = runner.run(engine, engine.sessions[SID]["object"], args())
    assert result["ok"] is False and result["completed_steps"] == 0
    assert result["failed_index"] == 0 and dispatch.call_count == 1
    runner.run(engine, engine.sessions[SID]["object"], args())
    assert dispatch.call_count == 1 and "private page detail" not in json.dumps(result)


@pytest.mark.parametrize(
    "boundary", ["cancel", "revoke", "handoff", "expired", "stop", "malformed_cancel"]
)
def test_batch_rechecks_owner_state_between_steps(engine, monkeypatch, boundary):
    def first(*_):
        if boundary == "cancel":
            assert batches.cancel(engine.folder, SID, "test-1")[
                "cancellation_requested"
            ]
        elif boundary == "revoke":
            host_client.atomic_json(
                engine.agent.state / "host-settings.json", {"enabled": False}
            )
        elif boundary == "handoff":
            engine.sessions[SID]["object"].visible = True
        elif boundary == "expired":
            engine.sessions[SID]["expires"] = time.time() - 1
        elif boundary == "stop":
            engine.stop_event.set()
        else:
            host_client.atomic_json(
                batches.receipt_path(engine.folder, SID, "test-1").with_suffix(
                    ".cancel"
                ),
                {"expires": "bad"},
            )
        return {"ok": True}

    dispatch = Mock(side_effect=first)
    monkeypatch.setattr(batches, "dispatch_browser", dispatch)
    # Expiry calls native owned cleanup; no actual process exists in this fixture.
    engine._close = Mock()
    result = batches.BatchRunner().run(engine, engine.sessions[SID]["object"], args())
    assert (
        dispatch.call_count == 1 and not result["ok"] and result["completed_steps"] == 1
    )


def test_persisted_running_receipt_reports_uncertainty_without_replay(
    engine, monkeypatch
):
    path = batches.receipt_path(engine.folder, SID, "test-1")
    path.parent.mkdir(parents=True)
    _, digest = batches.prepare(args())
    host_client.atomic_json(
        path, dict(request_id="test-1", digest=digest, state="running")
    )
    dispatch = Mock()
    monkeypatch.setattr(batches, "dispatch_browser", dispatch)
    result = batches.BatchRunner().run(engine, engine.sessions[SID]["object"], args())
    assert result["outcome_unknown"] and not result["result_available"]
    dispatch.assert_not_called()


def test_batch_status_and_cancel_bypass_worker_queue_but_check_live_inventory(
    engine, monkeypatch
):
    path = batches.receipt_path(engine.folder, SID, "test-1")
    path.parent.mkdir(parents=True)
    host_client.atomic_json(
        path, dict(request_id="test-1", state="running", digest="hidden")
    )
    inventory = dict(
        enabled=True,
        worker_ready=True,
        sessions=[dict(session_id=SID, kind="browser", expires=time.time() + 30)],
    )
    monkeypatch.setattr(host_client, "status", lambda _: inventory)
    result = host_client.command(
        engine.agent, "browser", action="batch_status", **args()
    )
    assert result["state"] == "running" and "digest" not in result
    assert host_client.command(
        engine.agent, "browser", action="batch_cancel", **args()
    )["cancellation_requested"]
    inventory["sessions"] = []
    with pytest.raises(PolicyError):
        host_client.command(engine.agent, "browser", action="batch_cancel", **args())


def test_capture_cadence_and_cached_reads_do_not_take_new_screenshots(
    engine, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    cache = capture.CaptureCache()
    cache.start(engine, SID, "tab")
    browser = engine.sessions[SID]["object"]
    original_deadline = browser.deadline
    for _ in range(10):
        cache.tick(engine)
        assert cache.get(SID, "tab")["cached"]
    assert browser.screenshot.call_count == 1
    clock[0] += 1
    cache.tick(engine)
    assert browser.screenshot.call_count == 2 and browser.deadline == original_deadline
    cache.streams[(SID, "tab")]["frame"]["captured_at"] -= 10
    with pytest.raises(PolicyError, match="stale"):
        cache.get(SID, "tab")


@pytest.mark.parametrize(
    "boundary", ["visible", "frozen", "paused", "revoked", "oversized"]
)
def test_capture_stops_serving_frames_when_control_or_capacity_changes(
    engine, boundary
):
    cache = capture.CaptureCache()
    cache.start(engine, SID, "tab")
    row = cache.streams[(SID, "tab")]
    row["next"] = 0
    browser = engine.sessions[SID]["object"]
    if boundary in ("visible", "frozen"):
        setattr(browser, boundary, True)
    elif boundary == "paused":
        engine.resource["admission_ready"] = False
    elif boundary == "revoked":
        host_client.atomic_json(
            engine.agent.state / "host-settings.json", {"enabled": False}
        )
    else:
        browser.screenshot.return_value = "x" * (4 * 1048576 + 1)
    cache.tick(engine)
    with pytest.raises(PolicyError):
        cache.get(SID, "tab")
    if boundary != "oversized":
        assert browser.screenshot.call_count == 1


def test_capture_stream_limit_and_explicit_cleanup(engine):
    cache = capture.CaptureCache()
    for n in range(4):
        cache.start(engine, SID, str(n))
    with pytest.raises(PolicyError, match="four"):
        cache.start(engine, SID, "extra")
    assert cache.stop(SID)["stopped"] and not cache.streams
