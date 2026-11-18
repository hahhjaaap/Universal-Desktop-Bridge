"""Cloud Agent integration: the real 10-worker pool uses isolated task lanes.

Fake stdio proxies; no machine, network, WebSocket or permission operations.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from udb import cloud_agent
from udb.remote_task_scheduler import resource_for_rpc


def rpc(name, action, ident):
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "method": "tools/call",
        "params": {"name": name, "arguments": {"action": action}},
    }


def test_pool_serializes_two_gui_batches_without_blocking_owned_browser(monkeypatch):
    first_entered = threading.Event()
    unlock_first = threading.Event()
    second_entered = threading.Event()
    browser_entered = threading.Event()
    running = 0
    running_guard = threading.Lock()

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            self.settings = settings

        def call(self, request):
            nonlocal running
            tool = request["params"]["name"]
            if tool == "computer_desktop":
                with running_guard:
                    running += 1
                    assert running == 1, "Two desktop GUI batches overlapped"
                if request["id"] == 1:
                    first_entered.set()
                    assert unlock_first.wait(5)
                else:
                    second_entered.set()
                with running_guard:
                    running -= 1
            if tool == "host_browser":
                browser_entered.set()
            return {"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}}

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        requests = [
            rpc("computer_desktop", "batch", 1),
            rpc("computer_desktop", "batch", 2),
            rpc("host_browser", "fastpath", 3),
        ]
        futures = []
        for request in requests:
            kind = resource_for_rpc(request)
            assert pool.scheduler.admit(kind)
            future = pool.submit(request, kind)
            futures.append((future, kind))
            if request["id"] == 1:
                assert first_entered.wait(5)
        assert browser_entered.wait(5)
        assert not second_entered.is_set()
        unlock_first.set()
        for future, kind in futures:
            assert future.result(timeout=8)["result"]["ok"]
            pool.scheduler.release(kind)
        assert second_entered.is_set()
        assert pool.scheduler.inflight == 0
    finally:
        unlock_first.set()
        pool.close()


def test_inflight_opaque_launch_still_prevents_other_mutations():
    from udb.remote_task_scheduler import DeviceTaskScheduler

    scheduler = DeviceTaskScheduler()
    assert scheduler.admit("exclusive")
    assert not scheduler.admit("desktop")
    assert not scheduler.admit("owned_browser")
    scheduler.release("exclusive")
    assert scheduler.admit("desktop")
    assert scheduler.admit("owned_browser")
    assert not scheduler.admit("exclusive")
    scheduler.release("desktop")
    scheduler.release("owned_browser")
