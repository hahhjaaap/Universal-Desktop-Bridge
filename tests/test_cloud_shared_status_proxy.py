"""Opt-in status-proxy pooling; fake stdio workers, no OS/network actions."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from udb import cloud_agent


def _rpc(ident, name="bridge_status"):
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }


def test_opt_in_status_calls_reuse_exactly_one_serial_proxy(monkeypatch):
    monkeypatch.setenv("UDB_SHARED_STATUS_PROXY", "1")
    created = []
    results = []
    guard = threading.Lock()
    active = 0
    peak = 0

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            self.closed = False
            with guard:
                created.append(self)

        def call(self, rpc):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.005)
                with guard:
                    results.append(rpc["id"])
                return {"jsonrpc": "2.0", "id": rpc["id"], "result": {"ok": True}}
            finally:
                with guard:
                    active -= 1

        def close(self):
            self.closed = True

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        futures = [pool.submit(_rpc(i)) for i in range(8)]
        assert [item.result(timeout=10)["id"] for item in futures] == list(range(8))
        assert len(created) == 1, "Read-only status must not start eight workers"
        assert peak == 1, "A stdio proxy accepts only one outstanding JSON-RPC"
        assert sorted(results) == list(range(8))
        other = pool.submit(_rpc(99, "host_status")).result(timeout=10)
        assert other["id"] == 99
        assert len(created) == 2, "Only bridge_status belongs to shared lane"
    finally:
        pool.close()
    assert all(proxy.closed for proxy in created)


def test_opt_in_status_failure_poisoned_once_without_replay(monkeypatch):
    monkeypatch.setenv("UDB_SHARED_STATUS_PROXY", "1")
    calls = []
    instances = []

    class FakeProxy:
        def __init__(self, settings):
            self.unusable = False
            instances.append(self)

        def call(self, rpc):
            calls.append(rpc["id"])
            self.unusable = True
            raise TimeoutError("Outcome unknown")

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        with pytest.raises(TimeoutError, match="unknown"):
            pool.submit(_rpc(1)).result(timeout=5)
        assert pool.failed.is_set()
        with pytest.raises(RuntimeError, match="unavailable"):
            pool.submit(_rpc(2))
        assert calls == [1]
        assert len(instances) == 1
    finally:
        pool.close()


def test_shared_status_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("UDB_SHARED_STATUS_PROXY", raising=False)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert not pool.shared_status_enabled
    finally:
        pool.close()


def test_status_backpressure_never_dispatches_queued_second_rpc(monkeypatch):
    monkeypatch.setenv("UDB_SHARED_STATUS_PROXY", "1")
    monkeypatch.setattr(cloud_agent, "_STATUS_LOCK_WAIT_SECONDS", 0.05, raising=False)
    started = threading.Event()
    release = threading.Event()
    calls = []
    created = []

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            created.append(self)

        def call(self, rpc):
            calls.append(rpc["id"])
            started.set()
            assert release.wait(timeout=5)
            return {"jsonrpc": "2.0", "id": rpc["id"], "result": {}}

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        first = pool.submit(_rpc(1))
        assert started.wait(timeout=3)
        second = pool.submit(_rpc(2))
        with pytest.raises(cloud_agent.ResourceBusyError, match="ResourceBusy"):
            second.result(timeout=3)
        assert calls == [1], "Blocked status must not be dispatched or replayed"
        release.set()
        assert first.result(timeout=5)["id"] == 1
        assert len(created) == 1
    finally:
        release.set()
        pool.close()
