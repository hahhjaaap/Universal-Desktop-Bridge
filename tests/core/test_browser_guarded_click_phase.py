"""Guarded-click failures carry bounded, non-sensitive phase evidence.

These tests are synthetic and never send an OS/browser mouse event.
"""

from __future__ import annotations

import pytest

from udb.browser_click_postcondition import (
    GuardedClickPhaseError,
    click_with_postcondition,
)
from udb.core import PolicyError


class FakeChannel:
    def discard_committed_navigation(self, session, frame_id, loader_id):
        return None

    def has_pending_navigation(self, session, frame_id):
        return False


class FakeBrowser:
    def __init__(self, fail_stage):
        self.fail_stage = fail_stage
        self._cdp = FakeChannel()
        self.input_calls = 0

    def sid(self, tab):
        return "owned-session"

    def call(self, method, params=None, session=None, timeout=10):
        if method == "Page.getFrameTree":
            if self.fail_stage == "document_identity":
                raise PolicyError("private frame URL and secret")
            return {"frameTree": {"frame": {"id": "frame", "loaderId": "loader"}}}
        if method == "Page.createIsolatedWorld":
            if self.fail_stage == "observer_context":
                raise PolicyError("private isolated context detail")
            return {"executionContextId": 12}
        if method == "Runtime.evaluate":
            if (
                self.fail_stage == "watch_arm"
                and "const button = one(buttonSelector)" in params["expression"]
            ):
                raise PolicyError("private page content and secret")
            return {"result": {"value": True}}
        raise AssertionError(f"Unexpected protocol method: {method}")

    def _click_point(self, tab, selector):
        if self.fail_stage == "target_resolution":
            raise PolicyError("private element label and secret")
        return {
            "ok": True,
            "x": 50,
            "y": 50,
            "previous_url": "https://example.test/fixture",
        }

    def _mouse_click(self, tab, x, y, before_press=None):
        self.input_calls += 1
        raise PolicyError("private CDP response and secret")


@pytest.mark.parametrize(
    "phase",
    ["document_identity", "target_resolution", "observer_context", "watch_arm", "input_dispatch"],
)
def test_guarded_click_error_contains_only_safe_phase(phase):
    browser = FakeBrowser(phase)
    with pytest.raises(GuardedClickPhaseError) as raised:
        click_with_postcondition(
            browser,
            "tab",
            "#next",
            {"selector": "#page", "text": "Page 2", "timeout_ms": 1500},
            None,
        )
    err = raised.value
    assert err.phase == phase
    assert isinstance(err, PolicyError)
    assert "secret" not in str(err)
    assert "private" not in str(err)
    assert browser.input_calls == (1 if phase == "input_dispatch" else 0)
