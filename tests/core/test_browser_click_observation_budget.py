"""Bounded, opt-in navigation observation for fast, inspected browser clicks.

All cases use fake CDP and a virtual clock; no personal Chrome, network,
Windows input or real website is accessed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from udb import browser_actions, host_browser, host_service
from udb.core import PolicyError


@pytest.mark.parametrize("value", [True, False, None, 99, 1001, 10.0, "100"])
def test_reject_invalid_click_budget_without_input(value):
    with pytest.raises(PolicyError, match="click_navigation_observe_ms"):
        browser_actions.validate_click_navigation_budget(
            {
                "action": "click",
                "observe_after": "snapshot",
                "click_navigation_observe_ms": value,
            }
        )


@pytest.mark.parametrize(
    "action,observation",
    [
        ("click", "none"),
        ("click", ""),
        ("read", "snapshot"),
        ("navigate", "read"),
        ("batch", "snapshot"),
    ],
)
def test_fast_click_requires_explicit_post_observation(action, observation):
    with pytest.raises(PolicyError, match="requires click with observe_after"):
        browser_actions.validate_click_navigation_budget(
            {
                "action": action,
                "observe_after": observation,
                "click_navigation_observe_ms": 100,
            }
        )


def test_default_budget_preserves_legacy_behavior():
    assert browser_actions.validate_click_navigation_budget({"action": "click"}) == 1000
    assert (
        browser_actions.validate_click_navigation_budget(
            {"action": "navigate", "click_navigation_observe_ms": 1000}
        )
        == 1000
    )


def test_service_rejects_invalid_budget_before_capacity_or_browser(monkeypatch):
    calls = []
    service = host_service.HostService.__new__(host_service.HostService)
    service.agent = object()
    monkeypatch.setattr(host_service, "enabled", lambda _agent: True)
    monkeypatch.setattr(
        host_service,
        "require_capacity",
        lambda *args: calls.append("capacity"),
    )
    for bad in (
        {
            "action": "click",
            "observe_after": "none",
            "click_navigation_observe_ms": 100,
        },
        {
            "action": "navigate",
            "observe_after": "read",
            "click_navigation_observe_ms": 100,
        },
        {
            "action": "click",
            "observe_after": "snapshot",
            "click_navigation_observe_ms": True,
        },
    ):
        with pytest.raises(PolicyError):
            service.dispatch("browser", bad)
    assert calls == []


class VirtualClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        self.current += max(0, seconds)


def simulate_non_navigating_click(monkeypatch, observe_ms):
    clock = VirtualClock()
    browser = host_browser.Browser.__new__(host_browser.Browser)
    browser._cdp = object()  # Compatibility CDP path, bounded fallback checks
    browser.tabs = {"owned-tab": "owned-session"}
    observed = []

    def call(method, params=None, session=None, timeout=10):
        observed.append(method)
        assert method == "Target.getTargets"
        return {
            "targetInfos": [
                {"type": "page", "targetId": "owned-tab", "url": "https://example.org/"}
            ]
        }

    browser.call = call
    with monkeypatch.context() as patch:
        patch.setattr(
            host_browser,
            "time",
            SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep),
        )
        result = browser._wait_for_click_navigation(
            "owned-tab", "https://example.org/", observe_ms=observe_ms
        )
    return result, clock.current, observed


def test_fast_non_navigating_click_exits_at_shortened_window(monkeypatch):
    fast, fast_seconds, fast_calls = simulate_non_navigating_click(monkeypatch, 100)
    regular, regular_seconds, regular_calls = simulate_non_navigating_click(
        monkeypatch, 1000
    )
    assert fast_seconds < 0.15
    assert 0.95 <= regular_seconds <= 1.05
    assert regular_seconds - fast_seconds >= 0.85
    assert len(fast_calls) < len(regular_calls)
    assert fast == {
        "navigation_completed": False,
        "navigation_observation_limited": True,
        "navigation_observed_ms": 100,
    }
    assert regular == {"navigation_completed": False}


def test_no_previous_url_marks_short_click_unverified(monkeypatch):
    clock = VirtualClock()
    browser = host_browser.Browser.__new__(host_browser.Browser)
    with monkeypatch.context() as patch:
        patch.setattr(
            host_browser,
            "time",
            SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep),
        )
        result = browser._wait_for_click_navigation("owned-tab", None, observe_ms=100)
    assert result == {
        "navigation_completed": False,
        "navigation_observation_limited": True,
        "navigation_observed_ms": 0,
    }
    assert clock.current == 0


def test_click_budget_passed_to_browser_only_when_explicitly_shortened():
    arguments = []

    class FakeOwnedBrowser:
        def element(self, *args, **kwargs):
            arguments.append((args, kwargs))
            return {"clicked": True, "replay_safe": False}

    obj = FakeOwnedBrowser()
    a = {
        "action": "click",
        "tab_id": "owned-tab",
        "selector": "#next",
        "observe_after": "snapshot",
    }
    browser_actions.dispatch_browser(obj, a)
    assert arguments[-1][1] == {}
    browser_actions.dispatch_browser(obj, dict(a, click_navigation_observe_ms=100))
    assert arguments[-1][1] == {"observe_navigation_ms": 100}


def test_browser_click_passes_fast_window_without_replaying_input():
    browser = host_browser.Browser.__new__(host_browser.Browser)
    calls = []
    browser.evaluate = lambda *args, **kwargs: "https://example.org/"
    browser._locator_expression = lambda *args, **kwargs: "fixed"
    browser._wait_for_element_action = lambda *args, **kwargs: {
        "ok": True,
        "x": 12,
        "y": 24,
    }
    browser.call = lambda *args, **kwargs: {
        "frameTree": {"frame": {"loaderId": "old", "id": "frame"}}
    }
    browser.tabs = {"owned-tab": "session"}
    browser._cdp = object()
    browser._mouse_click = lambda *args: calls.append("clicked")
    browser._wait_for_click_navigation = lambda *args, **kwargs: (
        calls.append(kwargs["observe_ms"])
        or {
            "navigation_completed": False,
            "navigation_observation_limited": True,
        }
    )
    result = browser.element(
        "owned-tab", "click", selector="#next", observe_navigation_ms=100
    )
    assert result == {
        "ok": True,
        "clicked": True,
        "replay_safe": False,
        "navigation_completed": False,
        "navigation_observation_limited": True,
    }
    assert calls == ["clicked", 100]
