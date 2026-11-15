"""Regression tests for opt-in fast status and fresh owner project inventory."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from udb import computer, host_client
from udb.computer_jobs import Jobs
from udb.core import Agent, PolicyError
from udb.readiness import report as readiness_report
from udb.server import make_server


def fixture_agent(tmp_path):
    agent = Agent(tmp_path / "agent")
    with agent.connect() as connection:
        connection.execute(
            "INSERT INTO projects (id,root,writable) VALUES (?,?,?)",
            ("bravo", str(tmp_path / "bravo"), 0),
        )
        connection.execute(
            "INSERT INTO projects (id,root,writable) VALUES (?,?,?)",
            ("alpha", str(tmp_path / "alpha"), 1),
        )
    return agent


def test_project_paging_is_index_ordered_and_permissions_are_always_fresh(tmp_path):
    agent = fixture_agent(tmp_path)
    rows = agent.projects()
    assert [row["id"] for row in rows] == ["alpha", "bravo"]
    assert agent.projects(offset=1, limit=1) == [rows[1]]
    assert agent.projects(offset=1) == [rows[1]]
    assert agent.projects(limit=1) == [rows[0]]
    assert agent.project_counts() == (2, 1)

    with agent.connect() as connection:
        connection.execute("UPDATE projects SET writable=0 WHERE id='alpha'")
    assert agent.projects()[0]["writable"] == 0
    assert agent.project_counts() == (2, 0)
    for offset, limit in ((-1, 0), (0, -1), (0, 1001), (True, 0), (0, False)):
        with pytest.raises(PolicyError):
            agent.projects(offset=offset, limit=limit)


def test_compact_bridge_status_preserves_current_readiness_without_heavy_scans(
    tmp_path, monkeypatch
):
    agent = fixture_agent(tmp_path)
    health = {
        "enabled": False,
        "worker_ready": True,
        "sessions": [],
        "resources": {"paused": False, "at": 1, "cpu_percent": 12},
    }
    monkeypatch.setattr(host_client, "status", lambda _: health)
    monkeypatch.setattr(
        "udb.computer_access.summary", lambda _: {"enabled": False, "capabilities": []}
    )
    monkeypatch.setattr("udb.headless.manager_status", lambda _: {"mode": "headless"})

    def unexpected(*args, **kwargs):
        raise AssertionError("brief status must not load expensive ancillary grants")

    monkeypatch.setattr(agent, "source_autonomy_projects", unexpected)
    monkeypatch.setattr(agent, "sandbox_autonomy_projects", unexpected)
    monkeypatch.setattr(agent, "media_autonomy", unexpected)
    monkeypatch.setattr("udb.sandbox.available", unexpected)

    brief = agent.diagnostics(brief=True)
    assert brief["projects"] == 2
    assert brief["readiness"]["readable_projects"] == 2
    assert brief["readiness"]["writable_projects"] == 1
    assert brief["readiness"]["state"] == "project_only"
    assert "sandbox_autonomy_projects" not in brief
    assert "auto_write_projects" not in brief
    with agent.connect() as connection:
        connection.execute("UPDATE projects SET writable=0 WHERE id='alpha'")
    assert agent.diagnostics(brief=True)["readiness"]["state"] == "read_only"


def test_readiness_aggregate_agrees_with_full_project_rows():
    manager = {"mode": "headless"}
    host = {"enabled": False, "worker_ready": True, "resources": {"paused": False}}
    computer_access = {"enabled": False}
    rows = [{"writable": 1}, {"writable": 0}, {"writable": 1}]
    assert readiness_report(manager, host, computer_access, rows) == readiness_report(
        manager, host, computer_access, [], project_totals=(3, 2)
    )


def test_computer_job_usage_is_read_without_enumerating_identifiers(monkeypatch):
    monkeypatch.setattr(computer.access, "summary", lambda _: {"enabled": False})
    monkeypatch.setattr("udb.desktop_control.paused", lambda _: False)
    monkeypatch.setattr("udb.desktop_control.browser_handoff", lambda _: False)

    def must_not_list(*_):
        raise AssertionError("brief status unexpectedly enumerated job IDs")

    selected = computer.Computer.__new__(computer.Computer)
    selected.agent = object()
    selected.jobs = SimpleNamespace(
        usage=lambda: {"known_computer_jobs": 3, "active_computer_jobs": 2},
        process=must_not_list,
    )
    brief = selected.dispatch("status", {"brief": True}, {})
    assert brief["processes"] == {"available": True, "jobs_omitted": True}
    assert brief["job_usage"]["active_computer_jobs"] == 2
    assert brief["job_usage"]["remaining_shared_slots_upper_bound"] == 8
    assert brief["job_usage"]["other_background_jobs_not_included"] is True

    rows = {
        "jobs": [
            {"job_id": "one", "status": "running"},
            {"job_id": "two", "status": "cleanup_failed"},
            {"job_id": "three", "status": "exited"},
        ]
    }
    full = computer.status_report(selected.agent, rows)
    assert full["processes"] == rows
    assert full["job_usage"]["known_computer_jobs"] == 3
    assert full["job_usage"]["active_computer_jobs"] == 2


def test_jobs_usage_does_not_copy_job_identifiers_or_outputs():
    jobs = Jobs.__new__(Jobs)
    jobs.lock = threading.RLock()
    jobs.rows = {
        "secret-first": {"status": "running", "output": "private"},
        "secret-second": {"status": "cleanup_failed"},
        "secret-third": {"status": "exited"},
    }
    assert jobs.usage() == {"known_computer_jobs": 3, "active_computer_jobs": 2}


def test_worker_down_computer_status_does_not_claim_available_jobs(monkeypatch):
    monkeypatch.setattr(host_client, "status", lambda _: {"worker_ready": False})
    monkeypatch.setattr(computer.access, "summary", lambda _: {"enabled": False})
    monkeypatch.setattr("udb.desktop_control.paused", lambda _: False)
    monkeypatch.setattr("udb.desktop_control.browser_handoff", lambda _: False)
    result = host_client.command(
        object(), "computer", mode="status", arguments={"brief": True}
    )
    assert result["worker_ready"] is False
    assert result["processes"]["available"] is False
    assert result["job_usage"]["available"] is False
    assert result["job_usage"]["remaining_shared_slots_upper_bound"] is None


def test_mcp_optional_brief_tools_do_not_change_legacy_calls(tmp_path, monkeypatch):
    agent = fixture_agent(tmp_path)
    calls = []
    health = {
        "enabled": False,
        "worker_ready": True,
        "sessions": [
            {
                "session_id": "a" * 32,
                "kind": "browser",
                "task": "PRIVATE_SESSION_TASK",
                "tabs": 1,
                "expires": 100,
            }
        ],
        "resources": {
            "at": 100,
            "cpu_percent": 20,
            "ram_percent": 30,
            "paused": False,
            "admission_ready": True,
            "limits": {"private": "not-needed"},
        },
    }
    monkeypatch.setattr(
        host_client, "status", lambda _: calls.append("health") or health
    )
    monkeypatch.setattr(
        host_client,
        "command",
        lambda agent, operation, **kw: (
            calls.append((operation, kw))
            or {"enabled": False, "job_usage": {"available": True}}
        ),
    )
    server = make_server(agent)

    async def check():
        names = {t.name: t for t in await server.list_tools()}
        for name in (
            "bridge_status",
            "list_projects",
            "host_status",
            "computer_status",
        ):
            assert name in names
        assert "brief" in names["bridge_status"].input_schema["properties"]
        assert "limit" in names["list_projects"].input_schema["properties"]
        assert "brief" in names["host_status"].input_schema["properties"]
        assert "brief" in names["computer_status"].input_schema["properties"]
        await server.call_tool("host_status", {"brief": True})
        await server.call_tool("host_status", {})
        await server.call_tool("list_projects", {"offset": 1, "limit": 1})
        await server.call_tool("computer_status", {"brief": True})
        await server.call_tool("computer_status", {})

    asyncio.run(check())
    assert calls.count("health") == 2
    assert ("computer", {"mode": "status", "arguments": {"brief": True}}) in calls
    assert ("computer", {"mode": "status", "arguments": {}}) in calls
