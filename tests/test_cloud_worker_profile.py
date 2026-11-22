"""Resource-aware Cloud RPC opt-in profile; no real process or network work."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from udb import cloud_agent, cloud_worker_profile

GIB = 1024**3


@pytest.mark.parametrize(
    ("total_gib", "free_gib", "logical_cpus", "expected"),
    [
        (8, 5, 4, 2),  # Target Intel i5-6500 / 8 GiB.
        (8, 3, 4, 2),
        (8, 1, 4, 1),  # Low available RAM: serialize until next connection.
        (6, 4, 4, 2),
        (12, 7, 4, 3),
        (16, 9, 12, 4),
        (16, 5, 12, 3),
        (32, 18, 12, 6),
        (32, 18, 2, 1),  # Keep CPU capacity for desktop/browser work.
    ],
)
def test_deterministic_resource_budget(total_gib, free_gib, logical_cpus, expected):
    assert (
        cloud_worker_profile.suggested_worker_budget(
            total_gib * GIB, free_gib * GIB, logical_cpus
        )
        == expected
    )


@pytest.mark.parametrize(
    "resources",
    [
        (None, None, None),
        (0, 0, 4),
        (-1, 1, 4),
        (8 * GIB, 9 * GIB, 4),
        (True, True, True),
        ("8", "4", "4"),
    ],
)
def test_unavailable_or_invalid_measurements_fail_small(resources):
    count = cloud_worker_profile.suggested_worker_budget(*resources)
    assert 1 <= count <= 2


def test_opt_in_auto_profile_bounds_both_scheduler_and_executor(monkeypatch):
    monkeypatch.setenv("UDB_CLOUD_WORKER_PROFILE", "auto")
    monkeypatch.delenv("UDB_CLOUD_MAX_RPC_WORKERS", raising=False)
    monkeypatch.setattr(cloud_agent, "local_worker_budget", lambda: 2)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.max_rpc_workers == 2
        assert pool.executor._max_workers == 2
        assert pool.scheduler.max_tasks == 2
        assert pool.scheduler.admit("read")
        assert pool.scheduler.admit("read")
        assert not pool.scheduler.admit("read")
        pool.scheduler.release("read")
        pool.scheduler.release("read")
    finally:
        pool.close()


def test_manual_worker_limit_takes_precedence_over_auto(monkeypatch):
    monkeypatch.setenv("UDB_CLOUD_WORKER_PROFILE", "auto")
    monkeypatch.setenv("UDB_CLOUD_MAX_RPC_WORKERS", "3")
    monkeypatch.setattr(
        cloud_agent,
        "local_worker_budget",
        lambda: pytest.fail("Manual override must not inspect hardware"),
    )
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.max_rpc_workers == 3
        assert pool.scheduler.max_tasks == 3
    finally:
        pool.close()


def test_auto_detect_uses_local_ram_and_cpu_snapshot_only(monkeypatch):
    monkeypatch.setattr(
        cloud_worker_profile, "windows_memory_bytes", lambda: (8 * GIB, 5 * GIB)
    )
    monkeypatch.setattr(cloud_worker_profile.os, "cpu_count", lambda: 4)
    assert cloud_worker_profile.local_worker_budget() == 2


def test_invalid_profile_fails_closed_before_startup(monkeypatch):
    monkeypatch.setenv("UDB_CLOUD_WORKER_PROFILE", "full")
    monkeypatch.delenv("UDB_CLOUD_MAX_RPC_WORKERS", raising=False)
    with pytest.raises(ValueError, match="must be auto or unset"):
        cloud_agent.ParallelLocalProxies(SimpleNamespace())


def test_existing_default_is_unchanged_when_profile_not_selected(monkeypatch):
    monkeypatch.delenv("UDB_CLOUD_WORKER_PROFILE", raising=False)
    monkeypatch.delenv("UDB_CLOUD_MAX_RPC_WORKERS", raising=False)
    pool = cloud_agent.ParallelLocalProxies(SimpleNamespace())
    try:
        assert pool.max_rpc_workers == 10
    finally:
        pool.close()


def test_windows_physical_memory_probe_smoke():
    """Validate the OS API shape on CI Windows; no private data is logged."""
    snapshot = cloud_worker_profile.windows_memory_bytes()
    if cloud_worker_profile.os.name != "nt":
        assert snapshot is None
        return
    assert snapshot is not None
    total, available = snapshot
    assert type(total) is int and type(available) is int
    assert 0 <= available <= total
    assert total >= GIB
