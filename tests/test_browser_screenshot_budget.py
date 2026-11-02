"""Regression checks for bounded, single-attempt browser screenshot capture."""

import pytest

from udb.core import PolicyError
from udb.host_browser import Browser


def _browser_without_process():
    browser = Browser.__new__(Browser)
    browser._show_identity = lambda tab: None
    browser.sid = lambda tab: "owned-session"
    return browser


def test_screenshot_uses_bounded_render_budget():
    browser = _browser_without_process()
    calls = []

    def call(method, params=None, session=None, timeout=10):
        calls.append((method, params, session, timeout))
        return {"data": "a" * 128}

    browser.call = call
    assert browser.screenshot("owned-tab") == "a" * 128
    assert calls == [
        (
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": False},
            "owned-session",
            20,
        )
    ]


def test_uncertain_screenshot_timeout_is_not_replayed():
    browser = _browser_without_process()
    calls = []

    def call(method, params=None, session=None, timeout=10):
        calls.append(method)
        raise PolicyError("Browser operation timed out; outcome may be unknown")

    browser.call = call
    with pytest.raises(PolicyError, match="outcome may be unknown"):
        browser.screenshot("owned-tab")
    assert calls == ["Page.captureScreenshot"]
