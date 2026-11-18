"""Browser operation+observation fusion must not replay or weaken permissions."""

from __future__ import annotations

import pytest

from udb.browser_actions import attach_post_observation, validate_post_observation
from udb.core import PolicyError
from udb.host_service import HostService


class FakeBrowser:
    def __init__(self):
        self.calls = []
        self.visible = False

    def snapshot(self, tab):
        self.calls.append(("snapshot", tab))
        return {
            "title": "Local fixture",
            "url": "https://example.org/fixture",
            "elements": [{"role": "button", "name": "Continue"}],
        }

    def read(self, tab):
        self.calls.append(("read", tab))
        return {"title": "Local fixture", "text": "Ready"}

    def new(self, url):
        self.calls.append(("new", url))
        return {"tab_id": "owned-tab", "navigation_completed": True}


@pytest.mark.parametrize("mode", ["invalid", "", "SNAPSHOT", 123, None, True])
def test_invalid_observation_modes_fail_before_browser_action(mode):
    with pytest.raises(PolicyError, match="observe_after"):
        validate_post_observation({"action": "click", "observe_after": mode})


@pytest.mark.parametrize("action", ["batch", "fastpath", "upload", "download", "list", "close_tab"])
def test_no_observation_on_unrelated_or_special_actions(action):
    with pytest.raises(PolicyError, match="unsupported"):
        validate_post_observation({"action": action, "observe_after": "read"})


def test_snapshot_fuses_into_successful_click_without_extra_host_call():
    browser = FakeBrowser()
    args = {"action": "click", "tab_id": "owned-tab", "observe_after": "snapshot"}
    result = attach_post_observation(
        browser, args, {"ok": True, "clicked": True, "replay_safe": False}
    )
    assert result["clicked"] is True
    assert result["replay_safe"] is False
    assert result["observe_after"] == "snapshot"
    assert result["observation"]["elements"][0]["name"] == "Continue"
    assert browser.calls == [("snapshot", "owned-tab")]


def test_read_on_navigation_uses_action_result_tab_not_guessed_tab():
    browser = FakeBrowser()
    args = {"action": "new", "tab_id": "untrusted", "observe_after": "read"}
    result = attach_post_observation(
        browser, args, {"tab_id": "owned-tab", "navigation_completed": True}
    )
    assert result["observation"]["text"] == "Ready"
    assert browser.calls == [("read", "owned-tab")]


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False, "error": "disabled"},
        {"clicked": True, "navigation_timed_out": True},
        {"timed_out": True},
    ],
)
def test_failed_or_uncertain_mutation_is_never_observed_or_retried(result):
    browser = FakeBrowser()
    actual = attach_post_observation(
        browser,
        {"action": "click", "tab_id": "owned-tab", "observe_after": "snapshot"},
        result,
    )
    assert actual["observation_skipped"] == "action_failed_or_uncertain"
    assert browser.calls == []


def test_post_read_error_keeps_original_mutation_result():
    browser = FakeBrowser()

    def fail(_tab):
        browser.calls.append(("snapshot", _tab))
        raise PolicyError("Page context disappeared")

    browser.snapshot = fail
    actual = attach_post_observation(
        browser,
        {"action": "click", "tab_id": "owned-tab", "observe_after": "snapshot"},
        {"ok": True, "clicked": True, "replay_safe": False},
    )
    assert actual["clicked"] is True
    assert actual["replay_safe"] is False
    assert actual["observation_unavailable"] is True
    assert "observation" not in actual
    assert browser.calls == [("snapshot", "owned-tab")]


def test_unexpected_observation_payload_never_claims_success():
    browser = FakeBrowser()
    browser.snapshot = lambda _tab: {"error": "observation_failed"}
    actual = attach_post_observation(
        browser,
        {"action": "fill", "tab_id": "owned-tab", "observe_after": "snapshot"},
        {"ok": True, "changed": True},
    )
    assert actual == {"ok": True, "changed": True, "observation_unavailable": True}


def test_legacy_default_does_not_issue_any_browser_reads():
    browser = FakeBrowser()
    original = {"clicked": True, "replay_safe": False}
    actual = attach_post_observation(
        browser, {"action": "click", "tab_id": "owned-tab"}, original
    )
    assert actual is original
    assert browser.calls == []


def test_open_fuses_initial_snapshot_without_second_session():
    browser = FakeBrowser()
    sid = "c" * 32
    service = HostService.__new__(HostService)
    service.sessions = {sid: {"kind": "browser", "object": browser}}
    service._session = lambda session_id, kind=None: service.sessions[session_id]
    # Resource limits and owner consent are enforced before dispatch;
    # this test only checks fusion after an existing owned session.
    args = {
        "action": "open",
        "session_id": sid,
        "url": "https://example.org/fixture",
        "observe_after": "snapshot",
    }
    result = service._open_browser(args)
    assert result["session_id"] == sid
    assert result["tab_id"] == "owned-tab"
    assert result["observation"]["title"] == "Local fixture"
    assert browser.calls == [
        ("new", "https://example.org/fixture"),
        ("snapshot", "owned-tab"),
    ]


def test_invalid_open_option_fails_before_creating_tab():
    browser = FakeBrowser()
    sid = "d" * 32
    service = HostService.__new__(HostService)
    service.sessions = {sid: {"kind": "browser", "object": browser}}
    service._session = lambda session_id, kind=None: service.sessions[session_id]
    with pytest.raises(PolicyError):
        validate_post_observation(
            {"action": "open", "observe_after": "screenshot"}
        )
    assert browser.calls == []
