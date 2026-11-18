"""Isolated 10-task scheduler tests; no network, Windows input or owner grants."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from udb.remote_task_scheduler import (
    MAX_TASKS,
    DeviceTaskScheduler,
    resource_for_rpc,
)


def call(name, **arguments):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def test_known_resource_lanes_and_fail_closed_unknowns():
    assert resource_for_rpc({"method": "ping"}) == "read"
    assert resource_for_rpc(call("bridge_status")) == "read"
    assert resource_for_rpc(call("computer_files", action="read")) == "read"
    assert resource_for_rpc(call("computer_process", action="list")) == "read"
    assert resource_for_rpc(call("computer_desktop", action="batch")) == "desktop"
    assert resource_for_rpc(call("open_chatgpt")) == "desktop"
    assert (
        resource_for_rpc(call("computer_utilities", action="launch_app")) == "desktop"
    )
    assert resource_for_rpc(call("host_browser", action="fastpath")) == "owned_browser"
    assert resource_for_rpc(call("computer_execute")) == "exclusive"
    assert resource_for_rpc(call("computer_files", action="write")) == "exclusive"
    assert resource_for_rpc(call("unknown_mutation")) == "exclusive"
    assert resource_for_rpc(None) == "exclusive"


def test_ten_shared_inflight_slots_and_capacity_release():
    scheduler = DeviceTaskScheduler()
    assert MAX_TASKS == 10
    for _ in range(MAX_TASKS):
        assert scheduler.admit("read")
    assert not scheduler.admit("read")
    scheduler.release("read")
    assert scheduler.admit("desktop")
    scheduler.release("desktop")
    for _ in range(MAX_TASKS - 1):
        scheduler.release("read")
    assert scheduler.inflight == 0


def test_unknown_mutation_is_exclusive_and_cannot_bypass_busy_slots():
    scheduler = DeviceTaskScheduler()
    assert scheduler.admit("desktop")
    assert not scheduler.admit("exclusive")
    scheduler.release("desktop")
    assert scheduler.admit("exclusive")
    assert not scheduler.admit("desktop")
    assert not scheduler.admit("read")
    assert not scheduler.admit("exclusive")
    scheduler.release("exclusive")
    assert scheduler.admit("owned_browser")
    scheduler.release("owned_browser")


def test_distinct_resources_can_run_together_but_desktop_batch_is_fifo():
    scheduler = DeviceTaskScheduler()
    entered = threading.Event()
    release = threading.Event()
    events = []

    def first():
        with scheduler.execution("desktop"):
            events.append("desktop-first")
            entered.set()
            assert release.wait(3)

    def second():
        with scheduler.execution("desktop"):
            events.append("desktop-second")

    def browser():
        with scheduler.execution("owned_browser"):
            events.append("browser")

    with ThreadPoolExecutor(max_workers=3) as pool:
        a = pool.submit(first)
        assert entered.wait(3)
        b = pool.submit(second)
        c = pool.submit(browser)
        c.result(timeout=3)
        assert "desktop-second" not in events
        release.set()
        a.result(timeout=3)
        b.result(timeout=3)
    assert events.index("desktop-first") < events.index("desktop-second")
    assert "browser" in events


def test_waiting_gui_batch_times_out_before_dispatch(monkeypatch):
    from udb import remote_task_scheduler as module

    monkeypatch.setattr(module, "RESOURCE_WAIT_SECONDS", 0.02)
    scheduler = DeviceTaskScheduler()
    called = []
    with scheduler.execution("desktop"):
        with pytest.raises(RuntimeError, match="ResourceBusy"):
            with scheduler.execution("desktop"):
                called.append("must-never-run")
    assert called == []
    assert scheduler.active == set()
    assert scheduler.waiting["desktop"] == []


def test_revoke_or_shutdown_wakes_waiting_gui_batches():
    scheduler = DeviceTaskScheduler()
    entered = threading.Event()
    outcome = []

    def second():
        entered.set()
        with pytest.raises(RuntimeError, match="ResourceBusy"):
            with scheduler.execution("desktop"):
                outcome.append("unsafe")

    with scheduler.execution("desktop"):
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(second)
            assert entered.wait(3)
            # Wait for queued state; no long wall-time dependency.
            for _ in range(100):
                with scheduler.condition:
                    if scheduler.waiting["desktop"]:
                        break
                time.sleep(0.001)
            scheduler.close()
            fut.result(timeout=3)
    assert outcome == []
    assert not scheduler.admit("read")
