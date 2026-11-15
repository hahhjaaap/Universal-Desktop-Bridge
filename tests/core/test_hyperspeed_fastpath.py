"""HyperSpeed steps 11–20: declarative owned-browser FastPath contracts.

No real website or Windows input is exercised. The existing session grant,
one-shot receipt and cancel/stop checks stay in the same BatchRunner path.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from udb import browser_batch, host_client
from udb.core import Agent, PolicyError
from udb.fastpath import compile_plan, gate, matches
from udb.host_service import HostService
from udb.resources import Governor

SID = "d" * 32


@pytest.fixture
def owned(tmp_path):
    service = HostService.__new__(HostService)
    service.agent = Agent(tmp_path / "agent")
    host_client.atomic_json(
        service.agent.state / "host-settings.json", {"enabled": True}
    )
    service.folder = service.agent.state / "host"
    service.folder.mkdir()
    service.stop_event = threading.Event()
    service.resource = Governor().update(
        {
            "at": time.time(),
            "cpu_percent": 7,
            "ram_percent": 25,
            "available_mib": 6000,
            "commit_percent": 30,
        }
    )
    browser = SimpleNamespace(
        visible=False,
        frozen=False,
        deadline=time.monotonic() + 20,
    )
    service.sessions = {
        SID: {
            "kind": "browser",
            "object": browser,
            "expires": time.time() + 900,
        }
    }
    service._close = Mock()
    service.batches = browser_batch.BatchRunner()
    return service, browser


def payload(steps, request_id="fastpath-test"):
    return {
        "session_id": SID,
        "tab_id": "tab-a",
        "request_id": request_id,
        "action": "fastpath",
        "steps": steps,
    }


def test_11_14_fastpath_dispatches_three_steps_in_one_owned_batch(owned, monkeypatch):
    service, browser = owned
    dispatch = Mock(
        side_effect=[
            {"ok": True, "state": "visible"},
            {"ok": True, "changed": True},
            {"ok": True, "state": "text"},
        ]
    )
    monkeypatch.setattr(browser_batch, "dispatch_browser", dispatch)
    steps = [
        {
            "action": "wait_for",
            "selector": "#form",
            "step_id": "ready",
            "state": "visible",
            "verify": {"field": "ok", "equals": True},
        },
        {
            "action": "fill",
            "selector": "#input",
            "value": "fixture-value",
            "step_id": "fill",
            "depends_on": ["ready"],
            "when": {"step_id": "ready", "field": "state", "equals": "visible"},
            "verify": {"field": "changed", "equals": True},
        },
        {
            "action": "wait_for",
            "selector": "#saved",
            "step_id": "verify",
            "depends_on": ["fill"],
            "verify": {"field": "state", "equals": "text"},
        },
    ]
    result = service.dispatch("browser", payload(steps))
    assert result["mode"] == "fastpath"
    assert result["state"] == "completed" and result["completed_steps"] == 3
    assert result["considered_steps"] == 3
    assert dispatch.call_count == 3
    assert all("result" not in entry for entry in result["results"])
    # Plan-only metadata is not sent to the native browser action dispatcher.
    assert all("verify" not in call.args[1] for call in dispatch.call_args_list)
    assert all("when" not in call.args[1] for call in dispatch.call_args_list)
    assert "fixture-value" not in json.dumps(result)
    assert "fixture-value" not in next(
        (service.folder / "batches" / SID).glob("*.json")
    ).read_text()
    assert service.dispatch("browser", payload(steps))["cached_result"]
    assert dispatch.call_count == 3


def test_12_16_unmet_guard_skips_dependent_mutations(owned, monkeypatch):
    service, _ = owned
    dispatch = Mock(return_value={"ok": True, "state": "hidden"})
    monkeypatch.setattr(browser_batch, "dispatch_browser", dispatch)
    steps = [
        {"action": "read", "step_id": "inspect"},
        {
            "action": "click",
            "selector": "#button",
            "step_id": "click",
            "when": {"step_id": "inspect", "field": "state", "equals": "visible"},
        },
        {
            "action": "fill",
            "selector": "#secret",
            "value": "never",
            "depends_on": ["click"],
        },
    ]
    result = service.dispatch("browser", payload(steps))
    assert result["ok"] and result["completed_steps"] == 1
    assert result["considered_steps"] == 3
    assert [r.get("skipped") for r in result["results"]] == [None, True, True]
    assert dispatch.call_count == 1


def test_13_invalid_dag_or_unknown_fields_rejected_before_any_browser_io(
    owned, monkeypatch
):
    service, _ = owned
    dispatch = Mock()
    monkeypatch.setattr(browser_batch, "dispatch_browser", dispatch)
    forbidden = [
        [{"action": "click", "selector": "#a", "depends_on": ["next"]}],
        [{"action": "click", "selector": "#a", "step_id": "A"},
         {"action": "fill", "selector": "#b", "step_id": "A"}],
        [{"action": "click", "selector": "#a", "run_shell": "powershell"}],
        [{"action": "batch"}],
        [{"action": "read", "verify": {"field": "arbitrary_html", "equals": "x"}}],
        [{"action": "read", "when": {"step_id": "future", "field": "ok", "equals": True}}],
        [{"action": "read", "depends_on": [False]}],
        [{"action": "read", "return_result": 1}],
        [{"action": "read", "verify": {"field": "ok", "equals": {"evil": 1}}}],
    ]
    for n, steps in enumerate(forbidden):
        with pytest.raises(PolicyError):
            service.dispatch("browser", payload(steps, request_id=f"invalid-{n}"))
    dispatch.assert_not_called()
    assert not (service.folder / "batches" / SID).exists()


def test_15_17_readonly_wait_stops_workflow_on_timeout_without_next_click(
    owned, monkeypatch
):
    service, _ = owned
    dispatch = Mock(return_value={"ok": False, "timed_out": True})
    monkeypatch.setattr(browser_batch, "dispatch_browser", dispatch)
    steps = [
        {"action": "wait_for", "selector": "#ready"},
        {"action": "click", "selector": "#submit"},
    ]
    result = service.dispatch("browser", payload(steps))
    assert result["state"] == "outcome_unknown"
    assert result["failed_index"] == 0
    assert dispatch.call_count == 1


def test_18_19_mutation_verify_mismatch_is_unknown_and_never_replayed(
    owned, monkeypatch
):
    service, _ = owned
    dispatch = Mock(return_value={"ok": True, "changed": False})
    monkeypatch.setattr(browser_batch, "dispatch_browser", dispatch)
    steps = [
        {
            "action": "fill", "selector": "#input", "value": "once",
            "verify": {"field": "changed", "equals": True},
        },
        {"action": "press", "key": "ENTER"},
    ]
    args = payload(steps)
    first = service.dispatch("browser", args)
    assert first["state"] == "outcome_unknown"
    assert first["failed_index"] == 0
    assert first["results"][0]["verified"] is False
    assert first["completed_steps"] == 0
    service.dispatch("browser", args)
    service.batches = browser_batch.BatchRunner()
    again = service.dispatch("browser", args)
    assert again["result_available"] is False
    assert dispatch.call_count == 1


def test_19_receipt_rejects_changed_actions_and_legacy_digest_remains_stable(
    owned, monkeypatch
):
    service, _ = owned
    dispatch = Mock(return_value={"ok": True})
    monkeypatch.setattr(browser_batch, "dispatch_browser", dispatch)
    steps = [{"action": "read"}]
    service.dispatch("browser", payload(steps))
    with pytest.raises(PolicyError, match="different actions"):
        service.dispatch(
            "browser",
            payload([{"action": "click", "selector": "#submit"}]),
        )
    legacy = {**payload(steps, "legacy"), "action": "batch"}
    result = service.dispatch("browser", legacy)
    assert result["ok"] and "mode" not in result
    assert "result" in result["results"][0]
    assert dispatch.call_count == 2


def test_20_cancellation_blocks_later_step(owned, monkeypatch):
    service, _ = owned

    def dispatch(_browser, _args):
        assert browser_batch.cancel(service.folder, SID, "fastpath-test")[
            "cancellation_requested"
        ]
        return {"ok": True}

    wrapped = Mock(side_effect=dispatch)
    monkeypatch.setattr(browser_batch, "dispatch_browser", wrapped)
    result = service.dispatch(
        "browser",
        payload([{"action": "read"}, {"action": "click", "selector": "#submit"}]),
    )
    assert result["state"] == "cancelled"
    assert result["completed_steps"] == 1
    assert wrapped.call_count == 1


def test_20_owner_handoff_and_revoke_stop_at_next_boundary(owned, monkeypatch):
    service, browser = owned

    def dispatch(_browser, _args):
        browser.visible = True
        return {"ok": True}

    monkeypatch.setattr(browser_batch, "dispatch_browser", Mock(side_effect=dispatch))
    result = service.dispatch(
        "browser",
        payload([{"action": "read"}, {"action": "click", "selector": "#submit"}]),
    )
    assert not result["ok"] and result["completed_steps"] == 1


def test_strict_result_evidence_never_treats_true_as_one():
    assert not matches(
        {"ok": True}, {"field": "ok", "equals": 1}
    )
    assert matches(
        {"ok": True}, {"field": "ok", "equals": True}
    )
    with pytest.raises(PolicyError):
        matches({"ok": True}, {"field": "visible", "equals": True})


def test_compile_plan_requires_prior_dependencies_and_no_unlisted_action():
    allowed = {"read": set(), "click": {"selector"}}
    compiled = compile_plan(
        [
            {"action": "read", "step_id": "first"},
            {
                "action": "click", "selector": "#go", "step_id": "second",
                "depends_on": ["first"],
                "when": {"step_id": "first", "field": "ok", "equals": True},
            },
        ],
        allowed,
    )
    assert len(compiled) == 2
    assert compiled[1].depends_on == ("first",)
    assert gate(
        compiled[1],
        {"first": {"ok": True, "skipped": False, "value": {"ok": True}}},
    )
