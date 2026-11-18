"""Desktop Fast Mode contracts without touching the actual Windows desktop.

All conditions use exact local evidence and do not replay mutating actions.
"""

from __future__ import annotations

from udb.computer_desktop import Desktop
from udb.core import PolicyError


def fake_desktop(callback):
    desktop = Desktop.__new__(Desktop)
    desktop._dispatch = callback
    return desktop


def test_legacy_batch_is_backward_compatible():
    calls = []

    def dispatch(action, window_id=""):
        calls.append((action, window_id))
        return {"state": "ready"}

    outcome = fake_desktop(dispatch).batch("window", [{"action": "control_status"}])
    assert outcome == {
        "ok": True,
        "completed_steps": 1,
        "results": [{"index": 0, "result": {"state": "ready"}}],
        "rollback": False,
    }
    assert calls == [("control_status", "window")]


def test_one_call_condition_and_dependencies_skip_mutation():
    calls = []

    def dispatch(action, window_id=""):
        calls.append(action)
        return {"state": "user_active"}

    outcome = fake_desktop(dispatch).batch(
        "window",
        [
            {"action": "control_status", "return_result": False},
            {
                "action": "invoke",
                "name": "Confirm",
                "when": {"step_index": 0, "field": "state", "equals": "idle"},
            },
            {"action": "click", "depends_on": [1]},
        ],
    )
    assert outcome["ok"]
    assert outcome["completed_steps"] == 1
    assert [row.get("skipped") for row in outcome["results"]] == [
        None,
        True,
        True,
    ]
    assert "result" not in outcome["results"][0]
    assert calls == ["control_status"]


def test_guard_match_executes_locally_and_verifies_once():
    calls = []

    def dispatch(action, window_id=""):
        calls.append(action)
        return {"paused": False} if action == "control_status" else {"requested": True}

    result = fake_desktop(dispatch).batch(
        "window",
        [
            {
                "action": "control_status",
                "verify": {"field": "paused", "equals": False},
            },
            {
                "action": "focus",
                "when": {"step_index": 0, "field": "paused", "equals": False},
                "verify": {"field": "requested", "equals": True},
                "return_result": False,
            },
        ],
    )
    assert result["ok"] and result["completed_steps"] == 2
    assert result["results"][1]["verified"] is True
    assert "result" not in result["results"][1]
    assert calls == ["control_status", "focus"]


def test_all_invalid_guards_reject_before_any_action():
    calls = []

    def dispatch(action, window_id=""):
        calls.append(action)
        return {"ok": True}

    malformed = [
        {"when": {"step_index": 0, "field": "ok", "equals": True}},
        {"verify": {"field": "private_data", "equals": True}},
        {"verify": {"field": "ok", "equals": {"nested": "untrusted"}}},
        {"verify": {"field": "ok", "equals": "x" * 161}},
        {"return_result": 1},
        {"depends_on": [0]},
        {"depends_on": [False]},
        {"depends_on": [0, 0]},
    ]
    import pytest

    for item in malformed:
        with pytest.raises(PolicyError):
            fake_desktop(dispatch).batch(
                "window", [{"action": "control_status", **item}]
            )
    assert not calls


def test_mutation_verification_mismatch_is_unknown_and_never_retried():
    calls = []

    def dispatch(action, window_id=""):
        calls.append(action)
        return {"requested": False}

    result = fake_desktop(dispatch).batch(
        "window",
        [
            {"action": "invoke", "verify": {"field": "requested", "equals": True}},
            {"action": "click"},
        ],
    )
    assert not result["ok"]
    assert result["failed_index"] == 0 and result["completed_steps"] == 0
    assert result["outcome_unknown"] is True
    assert calls == ["invoke"]


def test_missing_mutation_evidence_does_not_run_next_step():
    calls = []

    def dispatch(action, window_id=""):
        calls.append(action)
        return {"some_unrelated_field": True}

    result = fake_desktop(dispatch).batch(
        "window",
        [
            {"action": "invoke", "verify": {"field": "requested", "equals": True}},
            {"action": "click"},
        ],
    )
    assert not result["ok"]
    assert result["failed_index"] == 0 and result["outcome_unknown"] is True
    assert calls == ["invoke"]


def test_bool_evidence_never_equals_integer_one():
    calls = []

    def dispatch(action, window_id=""):
        calls.append(action)
        return {"ok": True}

    result = fake_desktop(dispatch).batch(
        "window",
        [
            {"action": "control_status"},
            {
                "action": "invoke",
                "when": {"step_index": 0, "field": "ok", "equals": 1},
            },
        ],
    )
    assert result["ok"] and result["completed_steps"] == 1
    assert result["results"][1]["skipped"]
    assert calls == ["control_status"]
