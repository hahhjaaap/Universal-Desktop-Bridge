"""Host Desktop FastPath contracts using only simulated Win32 application windows.

No real user browser, Office app, OS input, permission or local file is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


class FakeGui:
    def __init__(self):
        self.rows = {
            111: dict(pid=101, class_name="Chrome_WidgetWin_1", title="Chat - Google Chrome"),
            222: dict(pid=202, class_name="XLMAIN", title="Book1 - Excel"),
        }
        self.foreground = 111
        self.visits = 0

    def EnumWindows(self, callback, context):
        self.visits += 1
        for hwnd in tuple(self.rows):
            callback(hwnd, context)

    def IsWindowVisible(self, hwnd):
        return hwnd in self.rows

    def IsWindow(self, hwnd):
        return hwnd in self.rows

    def IsIconic(self, hwnd):
        return False

    def GetClassName(self, hwnd):
        return self.rows[hwnd]["class_name"]

    def GetWindowText(self, hwnd):
        return self.rows[hwnd]["title"]

    def GetForegroundWindow(self):
        return self.foreground


@pytest.fixture
def desktop():
    d = Desktop.__new__(Desktop)
    d.gui = FakeGui()
    d.windows = {}
    d.process = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (0, d.gui.rows[hwnd]["pid"])
    )
    d.interactive = lambda: None
    d.is_cloaked = lambda hwnd: False
    return d


def test_prefix_reobservation_binds_the_actual_full_title(desktop):
    d = desktop
    d.gui.rows[111]["title"] = "YouTube - Google Chrome"
    found = d.find_window(101, "Chrome_WidgetWin_1", title_prefix="YouTube -")
    assert found["found"] and found["title"] == "YouTube - Google Chrome"
    assert d.windows[found["window_id"]].expected_title == found["title"]
    d.gui.rows[111]["title"] = "nhạc hay - YouTube - Google Chrome"
    with pytest.raises(PolicyError, match="expired or changed"):
        d.resolve(found["window_id"], focus=False)


def test_fastpath_open_tab_wait_and_switch_apps_in_one_owner_batch(desktop):
    d = desktop
    calls = []

    def dispatch(action, window_id="", text=""):
        calls.append(action)
        if action == "open_chrome_tab":
            assert text == "https://www.youtube.com/"
            d.gui.rows[111]["title"] = "YouTube - Google Chrome"
            return {"requested": True}
        if action == "focus":
            hwnd = d.resolve(window_id, focus=False)
            return {"foreground": hwnd == 111}
        if action == "read_text":
            hwnd = d.resolve(window_id, focus=False)
            return {"ok": hwnd == 222}
        raise AssertionError("unexpected action")

    d._dispatch = dispatch
    result = d.batch(
        "",
        [
            {
                "action": "open_chrome_tab",
                "text": "https://www.youtube.com/",
                "verify": {"field": "requested", "equals": True},
            },
            {
                "action": "wait_window",
                "pid": 101,
                "class_name": "Chrome_WidgetWin_1",
                "title_prefix": "YouTube -",
                "wait_ms": 500,
                "verify": {"field": "found", "equals": True},
            },
            {
                "action": "focus",
                "window_ref": 1,
                "verify": {"field": "foreground", "equals": True},
            },
            {
                "action": "find_window",
                "pid": 202,
                "class_name": "XLMAIN",
                "title": "Book1 - Excel",
            },
            {
                "action": "read_text",
                "window_ref": 3,
                "verify": {"field": "ok", "equals": True},
            },
        ],
        fastpath=True,
    )
    assert result["ok"] and result["completed_steps"] == 5
    assert result["replay_safe"] is False
    assert calls == ["open_chrome_tab", "focus", "read_text"]
    assert result["results"][1]["result"]["title"] == "YouTube - Google Chrome"


def test_old_batch_keeps_navigation_outside_plan(desktop):
    with pytest.raises(PolicyError, match="Invalid/nested"):
        desktop.batch(
            "",
            [{"action": "open_chrome_tab", "text": "https://www.youtube.com/"}],
        )


@pytest.mark.parametrize(
    "locator",
    [
        {"title_prefix": "x"},
        {"title_prefix": ""},
        {"title_prefix": None},
        {"title": "Exact", "title_prefix": "LongPrefix"},
        {"title": ""},
        {"title": 1},
        {},
        {"title_prefix": "x" * 301},
        {"title_prefix": "ValidPrefix", "pid": True},
    ],
)
def test_invalid_locator_rejected_before_desktop_observation(desktop, locator):
    observed = []
    desktop.interactive = lambda: observed.append(True)
    row = {
        "action": "wait_window",
        "pid": 101,
        "class_name": "Chrome_WidgetWin_1",
        **locator,
    }
    with pytest.raises(PolicyError):
        desktop.batch("", [row], fastpath=True)
    assert not observed


def test_wait_window_requires_bounded_integer_timeout(desktop):
    for invalid in (-1, 10001, True, 1.0, "1000"):
        with pytest.raises(PolicyError):
            desktop.batch(
                "",
                [
                    {
                        "action": "wait_window",
                        "pid": 101,
                        "class_name": "Chrome_WidgetWin_1",
                        "title_prefix": "YouTube -",
                        "wait_ms": invalid,
                    }
                ],
                fastpath=True,
            )


def test_window_wait_times_out_without_sending_input(desktop):
    calls = []
    desktop._dispatch = lambda action, window_id="": calls.append(action)
    result = desktop.batch(
        "",
        [
            {
                "action": "wait_window",
                "pid": 101,
                "class_name": "Chrome_WidgetWin_1",
                "title_prefix": "YouTube -",
                "wait_ms": 0,
                "verify": {"field": "found", "equals": True},
            },
            {"action": "focus", "window_ref": 0},
        ],
        fastpath=True,
    )
    assert result["failed_index"] == 0
    assert result["outcome_unknown"] is False
    assert not calls


def test_prefix_ambiguity_is_refused_without_input(desktop):
    desktop.gui.rows[333] = dict(desktop.gui.rows[111])
    desktop.gui.rows[111]["title"] = "YouTube - Tab A"
    desktop.gui.rows[333]["title"] = "YouTube - Tab B"
    desktop._dispatch = lambda **_: pytest.fail("must not send input")
    result = desktop.batch(
        "",
        [
            {
                "action": "find_window",
                "pid": 101,
                "class_name": "Chrome_WidgetWin_1",
                "title_prefix": "YouTube -",
            },
            {"action": "click", "window_ref": 0, "x": 25, "y": 25},
        ],
        fastpath=True,
    )
    assert not result["ok"]
    assert result["failed_index"] == 0
    assert result["outcome_unknown"] is False
    assert desktop.windows == {}


def test_grant_or_locked_desktop_denies_window_wait(desktop):
    desktop.interactive = lambda: (_ for _ in ()).throw(
        PolicyError("Computer access was revoked")
    )
    result = desktop.batch(
        "",
        [
            {
                "action": "wait_window",
                "pid": 101,
                "class_name": "Chrome_WidgetWin_1",
                "title_prefix": "YouTube -",
                "wait_ms": 50,
            },
            {"action": "focus", "window_ref": 0},
        ],
        fastpath=True,
    )
    assert not result["ok"] and result["failed_index"] == 0
    assert result["outcome_unknown"] is False
