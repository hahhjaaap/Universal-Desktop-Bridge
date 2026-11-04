"""Disposable Windows host fixture waits for an actual ready heartbeat."""

import pytest

from tools import check_runtime_scenarios as scenarios


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


def test_waits_for_matching_session_and_enabled_host(monkeypatch):
    session_id = "a" * 32
    replies = iter(
        [
            {"worker_ready": False, "enabled": True, "sessions": []},
            {
                "worker_ready": True,
                "enabled": True,
                "sessions": [{"session_id": "b" * 32, "kind": "browser"}],
            },
            {
                "worker_ready": True,
                "enabled": False,
                "sessions": [{"session_id": session_id, "kind": "browser"}],
            },
            {
                "worker_ready": True,
                "enabled": True,
                "sessions": [{"session_id": session_id, "kind": "browser"}],
            },
        ]
    )
    seen = []
    monkeypatch.setattr(
        scenarios, "host_status", lambda agent: (seen.append(agent), next(replies))[1]
    )
    monkeypatch.setattr(scenarios.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        scenarios, "host_command", lambda *_a, **_kw: pytest.fail("Unexpected RPC")
    )
    agent = object()
    scenarios._wait_for_fixture_host(agent, FakeProcess(), session_id, timeout=5)
    assert seen == [agent] * 4


def test_fixture_worker_exit_does_not_attempt_a_browser_mutation(monkeypatch):
    monkeypatch.setattr(
        scenarios, "host_status", lambda *_: pytest.fail("Should not check exited worker")
    )
    with pytest.raises(RuntimeError, match="exited before host readiness"):
        scenarios._wait_for_fixture_host(object(), FakeProcess(7), "a" * 32)


def test_fixture_timeout_is_bounded_without_rpc_replay(monkeypatch):
    monkeypatch.setattr(
        scenarios, "host_command", lambda *_a, **_kw: pytest.fail("Unexpected RPC")
    )
    with pytest.raises(RuntimeError, match="heartbeat did not become ready"):
        scenarios._wait_for_fixture_host(object(), FakeProcess(), "a" * 32, timeout=0)
