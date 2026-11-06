"""Offline concurrency tests: one local stdio process per active Cloud RPC."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
import websocket

from udb import cloud_agent


def test_pool_lazily_runs_ten_read_rpcs_at_the_same_time(monkeypatch):
    barrier = threading.Barrier(10)
    lock = threading.Lock()
    created = []
    active = 0
    peak = 0

    class FakeProxy:
        unusable = False

        def __init__(self, _settings):
            self.closed = False
            with lock:
                created.append(self)

        def call(self, rpc):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(timeout=10)
                return {"jsonrpc": "2.0", "id": rpc["id"], "result": {}}
            finally:
                with lock:
                    active -= 1

        def close(self):
            self.closed = True

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert created == [], "Idle cloud connection must not launch processes"
        futures = [
            pool.submit({"jsonrpc": "2.0", "id": i, "method": "tools/list"})
            for i in range(10)
        ]
        assert [f.result(timeout=15)["id"] for f in futures] == list(range(10))
        assert peak == 10
        assert len(created) == 10
    finally:
        pool.close()
    assert all(proxy.closed for proxy in created)
    assert pool.closed
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit({"jsonrpc": "2.0", "id": 20, "method": "tools/list"})


def test_pool_marks_uncertain_result_failed_without_replaying(monkeypatch):
    calls = []

    class Poisoned:
        unusable = False

        def __init__(self, _settings):
            pass

        def call(self, rpc):
            calls.append(rpc["id"])
            self.unusable = True
            raise TimeoutError("Outcome unknown")

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", Poisoned)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        future = pool.submit({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        with pytest.raises(TimeoutError, match="unknown"):
            future.result(timeout=5)
        assert pool.failed.is_set()
        assert calls == [3]
    finally:
        pool.close()


def test_cloud_agent_sends_ten_parallel_results_with_distinct_ids(
    monkeypatch, tmp_path
):
    barrier = threading.Barrier(10)
    lock = threading.Lock()
    active = 0
    peak = 0
    received = []
    replies_ready = threading.Event()

    class FakeProxy:
        unusable = False

        def __init__(self, _settings):
            pass

        def call(self, rpc):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(timeout=10)
                return {
                    "jsonrpc": "2.0",
                    "id": rpc["id"],
                    "result": {"parallel": rpc["id"]},
                }
            finally:
                with lock:
                    active -= 1

        def close(self):
            pass

    class FakeSocket:
        index = 0

        def settimeout(self, value):
            assert value is None

        def recv(self):
            if self.index < 10:
                self.index += 1
                ident = self.index
                return json.dumps(
                    {
                        "kind": "rpc",
                        "id": f"relay-{ident}",
                        "rpc": {"jsonrpc": "2.0", "id": ident, "method": "tools/list"},
                    }
                )
            assert replies_ready.wait(timeout=15)
            return ""

        def send(self, frame):
            with lock:
                received.append(json.loads(frame))
                if len(received) == 10:
                    replies_ready.set()

        def close(self):
            pass

    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda _home: ("https://staging.workers.dev", "a" * 32, tmp_path / "token"),
    )
    monkeypatch.setattr(cloud_agent, "load_device_token", lambda *_args: "x" * 48)
    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    monkeypatch.setattr(
        websocket, "create_connection", lambda *_args, **_kwargs: FakeSocket()
    )
    monkeypatch.setattr(
        cloud_agent.time,
        "sleep",
        lambda _delay: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert cloud_agent.run(SimpleNamespace(home=tmp_path)) == 0
    assert peak == 10
    assert {item["id"] for item in received} == {f"relay-{i}" for i in range(1, 11)}
    assert {item["rpc"]["id"] for item in received} == set(range(1, 11))
    assert all(
        item["rpc"]["result"]["parallel"] == item["rpc"]["id"] for item in received
    )
