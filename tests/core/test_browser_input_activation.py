"""CDP input must target an activated tab in UDB's private browser."""

import pytest

from udb.browser_input import BrowserInputMixin
from udb.core import PolicyError


class FakeBrowser(BrowserInputMixin):
    def __init__(self, *, fail_activation=False):
        self.calls = []
        self.fail_activation = fail_activation

    def sid(self, tab):
        return "owned-session"

    def call(self, method, params=None, session=None, timeout=10):
        self.calls.append((method, params, session, timeout))
        if method == "Target.activateTarget" and self.fail_activation:
            raise PolicyError("Target activation failed")
        if method == "Page.getLayoutMetrics":
            return {"cssVisualViewport": {"clientWidth": 800, "clientHeight": 600}}
        return {}

    def _show_identity(self, tab, x, y):
        self.calls.append(("show_identity", tab, x, y))

    def _locator_expression(self, selector, role, name, exact, body):
        return "bounded-test-locator"

    def evaluate(self, tab, expression, timeout=10):
        self.calls.append(("evaluate", expression, timeout))
        return {"ok": True}


def _methods(browser):
    return [call[0] for call in browser.calls]


def test_mouse_click_activates_exact_owned_target_before_input():
    browser = FakeBrowser()

    assert browser._mouse_click("owned-tab", 40, 50) is True

    activation = next(
        call for call in browser.calls if call[0] == "Target.activateTarget"
    )
    assert activation[1] == {"targetId": "owned-tab"}
    assert activation[2] is None
    assert activation[3] == 2
    assert _methods(browser).index("Target.activateTarget") < _methods(browser).index(
        "Input.dispatchMouseEvent"
    )


def test_press_activates_target_before_key_input():
    browser = FakeBrowser()

    result = browser.press("owned-tab", "Enter", selector="#submit")

    assert result["ok"] is True
    methods = _methods(browser)
    assert methods.index("Target.activateTarget") < methods.index(
        "Input.dispatchKeyEvent"
    )


def test_scroll_activates_target_before_wheel_input():
    browser = FakeBrowser()

    result = browser.scroll("owned-tab", 0, 120)

    assert result["scrolled"] is True
    methods = _methods(browser)
    assert methods.index("Target.activateTarget") < methods.index(
        "Input.dispatchMouseEvent"
    )


@pytest.mark.parametrize("action", ["click", "press", "scroll"])
def test_input_fails_closed_when_target_activation_fails(action):
    browser = FakeBrowser(fail_activation=True)

    with pytest.raises(PolicyError, match="Target activation failed"):
        if action == "click":
            browser._mouse_click("owned-tab", 40, 50)
        elif action == "press":
            browser.press("owned-tab", "Enter", selector="#submit")
        else:
            browser.scroll("owned-tab", 0, 120)

    assert not any(
        method in {"Input.dispatchMouseEvent", "Input.dispatchKeyEvent"}
        for method in _methods(browser)
    )
