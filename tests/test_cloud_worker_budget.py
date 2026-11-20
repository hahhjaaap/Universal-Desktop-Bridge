"""Conservative opt-in Cloud RPC concurrency budget.

This tests the in-process scheduler, executor and fake LocalProxy only.
No remote connectivity, owner grants, input control or production state.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from udb import cloud_agent
from udb.remote_task_scheduler import MAX_TASKS, DeviceTaskScheduler


def _read(ident):
    return {"jsonrpc": "2.0", "id": ident, "method": "tools/list"}


def test_default_cloud_worker_budget_is_unchanged(monkeypatch):
    monkeypatch.delenv("UDB_CLOUD_MAX_RPC_WORKERS", raising=False)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.max_rpc_workers == 10
        assert pool.scheduler.max_tasks == MAX_TASKS == 10
        assert pool.executor._max_workers == 10
    finally:
        pool.close()


@pytest.mark.parametrize("limit", ["1", "2", "4", "10"])
def test_bounded_worker_budget_matches_admission(monkeypatch, limit):
    monkeypatch.setenv("UDB_CLOUD_MAX_RPC_WORKERS", limit)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        count = int(limit)
        assert pool.max_rpc_workers == count
        assert pool.executor._max_workers == count
        for _ in range(count):
            assert pool.scheduler.admit("read")
        assert not pool.scheduler.admit("read"), "No RPC may queue beyond worker count"
        assert not pool.scheduler.admit("exclusive")
        for _ in range(count):
            pool.scheduler.release("read")
        assert pool.scheduler.admit("exclusive")
        assert not pool.scheduler.admit("read")
        pool.scheduler.release("exclusive")
    finally:
        pool.close()


@pytest.mark.parametrize(
    "invalid",
    ["", "0", "11", "100", "-1", "1.0", " 2", "2 ", "yes", "２", "１", "999999"],
)
def test_invalid_budget_fails_before_subprocess_or_executor(monkeypatch, invalid):
    monkeypatch.setenv("UDB_CLOUD_MAX_RPC_WORKERS", invalid)
    with pytest.raises(ValueError, match="must be 1..10"):
        cloud_agent.ParallelLocalProxies(SimpleNamespace())


@pytest.mark.parametrize("invalid", [True, False, 0, 11, 3.2, "2", None])
def test_scheduler_direct_configuration_is_capped(invalid):
    with pytest.raises(ValueError, match="1..10"):
        DeviceTaskScheduler(max_tasks=invalid)


def test_bounded_admission_never_schedules_third_call(monkeypatch):
    monkeypatch.setenv("UDB_CLOUD_MAX_RPC_WORKERS", "2")
    monkeypatch.delenv("UDB_SHARED_STATUS_PROXY", raising=False)
    entered_two = threading.Event()
    release = threading.Event()
    guarded = threading.Lock()
    created = []
    calls = []

    class FakeProxy:
        unusable = False

        def __init__(self, settings):
            with guarded:
                created.append(self)

        def call(self, rpc):
            with guarded:
                calls.append(rpc["id"])
                if len(calls) == 2:
                    entered_two.set()
            assert release.wait(timeout=8)
            return {"jsonrpc": "2.0", "id": rpc["id"], "result": {"ok": True}}

        def close(self):
            pass

    monkeypatch.setattr(cloud_agent, "LocalProxy", FakeProxy)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    submitted = []
    try:
        for ident in (1, 2):
            assert pool.scheduler.admit("read")
            submitted.append((pool.submit(_read(ident), "read"), "read"))
        assert entered_two.wait(timeout=5)
        assert not pool.scheduler.admit("read")
        assert not pool.scheduler.admit("exclusive")
        # Exactly the two accepted RPCs have reached the fake local stdio.
        assert sorted(calls) == [1, 2]
        assert len(created) == 2
        release.set()
        for future, kind in submitted:
            assert future.result(timeout=5)["result"]["ok"] is True
            pool.scheduler.release(kind)
        assert pool.scheduler.inflight == 0
    finally:
        release.set()
        pool.close()


def test_custom_budget_does_not_change_lane_authorization(monkeypatch):
    monkeypatch.setenv("UDB_CLOUD_MAX_RPC_WORKERS", "2")
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.scheduler.admit("desktop")
        assert pool.scheduler.admit("owned_browser")
        assert not pool.scheduler.admit("exclusive")
        assert not pool.scheduler.admit("read")
        pool.scheduler.release("desktop")
        pool.scheduler.release("owned_browser")
        assert pool.scheduler.admit("exclusive")
        assert not pool.scheduler.admit("desktop")
        pool.scheduler.release("exclusive")
    finally:
        pool.close()
