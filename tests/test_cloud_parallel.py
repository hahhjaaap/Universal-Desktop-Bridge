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
        # Once an outcome is uncertain, subsequent RPCs must not be sent on
        # that device connection, even if free thread slots remain.
        with pytest.raises(RuntimeError, match="unavailable"):
            pool.submit({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
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


def test_dead_stdio_process_poisoned_even_when_flag_is_false(monkeypatch):
    calls = []

    class DeadProxy:
        unusable = False

        def __init__(self, _settings):
            self.process = SimpleNamespace(poll=lambda: 7)

        def call(self, rpc):
            calls.append(rpc["id"])
            raise RuntimeError("Local UDB proxy is unavailable")

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", DeadProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        future = pool.submit({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
        with pytest.raises(RuntimeError, match="unavailable"):
            future.result(timeout=5)
        assert pool.failed.is_set()
        with pytest.raises(RuntimeError, match="unavailable"):
            pool.submit({"jsonrpc": "2.0", "id": 11, "method": "tools/list"})
        assert calls == [10]
    finally:
        pool.close()


def test_unexpected_worker_exception_fails_closed_without_leaking(
    monkeypatch, tmp_path
):
    responses = []
    response_ready = threading.Event()
    closed = threading.Event()

    class FailingProxy:
        unusable = False

        def __init__(self, _settings):
            pass

        def call(self, _rpc):
            raise LookupError("private path or secret must not be exposed")

        def close(self):
            pass

    class FakeSocket:
        index = 0

        def settimeout(self, value):
            assert value is None

        def recv(self):
            if self.index == 0:
                self.index += 1
                return json.dumps(
                    {
                        "kind": "rpc",
                        "id": "relay-1",
                        "rpc": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    }
                )
            assert response_ready.wait(timeout=10)
            return ""

        def send(self, frame):
            responses.append(json.loads(frame))
            response_ready.set()

        def close(self):
            closed.set()

    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda _home: ("https://staging.workers.dev", "a" * 32, tmp_path / "token"),
    )
    monkeypatch.setattr(cloud_agent, "load_device_token", lambda *_args: "x" * 48)
    monkeypatch.setattr(cloud_agent, "LocalProxy", FailingProxy)
    monkeypatch.setattr(
        websocket, "create_connection", lambda *_args, **_kwargs: FakeSocket()
    )
    monkeypatch.setattr(
        cloud_agent.time,
        "sleep",
        lambda _delay: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert cloud_agent.run(SimpleNamespace(home=tmp_path)) == 0
    assert response_ready.is_set()
    assert closed.is_set()
    assert len(responses) == 1
    assert responses[0]["id"] == "relay-1"
    assert responses[0]["rpc"]["id"] == 1
    assert responses[0]["rpc"]["error"]["message"] == "InternalError"
    assert "private" not in json.dumps(responses)


def test_agent_releases_pool_even_when_websocket_close_raises(monkeypatch, tmp_path):
    created = []

    class TrackingPool:
        def __init__(self, _settings):
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

    class BrokenSocket:
        def settimeout(self, value):
            assert value is None

        def recv(self):
            return ""

        def close(self):
            raise OSError("connection already failed")

    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda _home: ("https://staging.workers.dev", "a" * 32, tmp_path / "token"),
    )
    monkeypatch.setattr(cloud_agent, "load_device_token", lambda *_args: "x" * 48)
    monkeypatch.setattr(cloud_agent, "ParallelLocalProxies", TrackingPool)
    monkeypatch.setattr(
        websocket, "create_connection", lambda *_args, **_kwargs: BrokenSocket()
    )
    monkeypatch.setattr(
        cloud_agent.time,
        "sleep",
        lambda _delay: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert cloud_agent.run(SimpleNamespace(home=tmp_path)) == 0
    assert len(created) == 1
    assert created[0].closed


def test_pool_cleanup_continues_after_one_worker_close_fails():
    cleaned = []

    class Broken:
        def close(self):
            cleaned.append("broken")
            raise OSError("broken pipe")

    class Healthy:
        def close(self):
            cleaned.append("healthy")

    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    pool.proxies.extend([Broken(), Healthy()])
    pool.close()
    assert cleaned == ["broken", "healthy"]
    assert pool.closed
    assert pool.failed.is_set()
