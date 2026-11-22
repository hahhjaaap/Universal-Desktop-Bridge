"""Opt-in cloud prewarm is read-only and reuses one local proxy."""

from types import SimpleNamespace

import pytest

from udb import cloud_agent


def test_prewarm_pings_once_and_reuses_one_proxy(monkeypatch):
    created = []
    calls = []
    closed = []

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            assert settings is not None
            created.append(self)

        def call(self, rpc):
            calls.append(rpc)
            return {"jsonrpc": "2.0", "id": rpc["id"], "result": {}}

        def close(self):
            closed.append(self)

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.prewarm_one(timeout=10) is True
        assert len(created) == 1
        assert calls[0]["method"] == "ping"
        assert cloud_agent.valid_remote_rpc(calls[0])
        result = pool.submit(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        ).result(timeout=5)
        assert result == {"jsonrpc": "2.0", "id": 2, "result": {}}
        assert len(created) == 1
    finally:
        pool.close()
    assert closed == created


def test_opted_in_prewarm_warms_the_actual_shared_status_worker(monkeypatch):
    """A read-only warm ping must avoid a second onefile status startup."""
    monkeypatch.setenv("UDB_SHARED_STATUS_PROXY", "1")
    created = []
    calls = []

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            created.append(self)

        def call(self, rpc):
            calls.append((self, rpc["method"], rpc.get("params", {}).get("name")))
            return {"jsonrpc": "2.0", "id": rpc["id"], "result": {}}

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.prewarm_one(timeout=10) is True
        assert len(created) == 1
        assert pool.status_proxy is created[0]
        assert calls == [(created[0], "ping", None)]

        result = pool.submit({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "bridge_status", "arguments": {}},
        }).result(timeout=5)
        assert result["id"] == 7
        assert len(created) == 1, "First status must reuse the prewarmed worker"
        assert calls[-1] == (created[0], "tools/call", "bridge_status")

        # Unmarked pings still use independent workers. The status lane is
        # selected by the local prewarm flag, not by an untrusted RPC ID.
        pool.submit({
            "jsonrpc": "2.0", "id": "udb-prewarm-test",
            "method": "ping",
        }).result(timeout=5)
        assert len(created) == 2
        assert calls[-1][0] is not pool.status_proxy
    finally:
        pool.close()


def test_prewarm_rejects_bad_timeout_without_starting_child(monkeypatch):
    monkeypatch.setattr(
        cloud_agent,
        "LocalProxy",
        lambda settings: pytest.fail("No subprocess should start"),
    )
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        for timeout in (0, -1, 31, "15", True):
            with pytest.raises(ValueError):
                pool.prewarm_one(timeout=timeout)
    finally:
        pool.close()


def test_failed_read_only_ping_poison_pool_without_calling_tools(monkeypatch):
    calls = []

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            pass

        def call(self, rpc):
            calls.append(rpc["method"])
            return {
                "jsonrpc": "2.0",
                "id": rpc["id"],
                "error": {"code": -32000, "message": "rejected"},
            }

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        with pytest.raises(RuntimeError, match="prewarm ping rejected"):
            pool.prewarm_one()
        assert calls == ["ping"]
        with pytest.raises(RuntimeError, match="unavailable"):
            pool.submit({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    finally:
        pool.close()
