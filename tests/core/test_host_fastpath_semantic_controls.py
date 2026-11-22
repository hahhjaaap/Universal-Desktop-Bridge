"""Bounded semantic UIA observations and explicit same-window element references.

All tests use synthetic data; no user desktop, browser or physical input.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


class FakeGui:
    def __init__(self):
        self.rows = {
            101: {
                "pid": 100,
                "class_name": "Chrome_WidgetWin_1",
                "title": "YouTube - Chrome",
            },
            202: {"pid": 200, "class_name": "XLMAIN", "title": "Book1 - Excel"},
        }

    def EnumWindows(self, callback, context):
        for hwnd in self.rows:
            callback(hwnd, context)

    def IsWindowVisible(self, hwnd):
        return hwnd in self.rows

    def IsWindow(self, hwnd):
        return hwnd in self.rows

    def GetClassName(self, hwnd):
        return self.rows[hwnd]["class_name"]

    def GetWindowText(self, hwnd):
        return self.rows[hwnd]["title"]

    def IsIconic(self, hwnd):
        return False

    def GetForegroundWindow(self):
        return 101


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


def locator(pid, title, kind):
    return {"action": "find_window", "pid": pid, "class_name": kind, "title": title}


def semantic(window_ref):
    return {
        "action": "find_control",
        "window_ref": window_ref,
        "name": "YouTube results",
        "text": "Nhạc",
        "control_type": "Hyperlink",
        "verify": {"field": "found", "equals": True},
    }


def test_discovers_first_matching_control_and_invokes_once_in_one_batch(desktop):
    calls = []

    def dispatch(
        action, window_id="", name="", text="", automation_id="", control_type=""
    ):
        hwnd = desktop.resolve(window_id, focus=False)
        calls.append((action, hwnd, name, text, control_type))
        if action == "find_control":
            return {
                "ok": True,
                "found": True,
                "name": "Nhạc Trẻ Ballad",
                "automation_id": "video-title",
                "control_type": "ControlType.Hyperlink",
                "matched": 3,
            }
        if action == "invoke":
            assert name == "Nhạc Trẻ Ballad"
            assert automation_id == "video-title"
            assert control_type == "ControlType.Hyperlink"
            return {"ok": True, "invoked": True}
        raise AssertionError("unexpected")

    desktop._dispatch = dispatch
    rows = [
        locator(100, "YouTube - Chrome", "Chrome_WidgetWin_1"),
        semantic(0),
        {"action": "invoke", "window_ref": 0, "element_ref": 1},
    ]
    result = desktop.batch("", rows, fastpath=True)
    assert result["ok"] and result["completed_steps"] == 3
    assert [call[0] for call in calls] == ["find_control", "invoke"]
    assert result["replay_safe"] is False


def test_missing_semantic_match_skips_invoke_and_never_sends_input(desktop):
    def dispatch(action, window_id="", name="", text="", control_type=""):
        if action == "find_control":
            return {"ok": True, "found": False, "matched": 0}
        pytest.fail("must not invoke a missing semantic target")

    desktop._dispatch = dispatch
    result = desktop.batch(
        "",
        [
            locator(100, "YouTube - Chrome", "Chrome_WidgetWin_1"),
            {
                "action": "find_control",
                "window_ref": 0,
                "name": "YouTube results",
                "text": "Nhạc",
                "control_type": "Hyperlink",
            },
            {"action": "invoke", "window_ref": 0, "element_ref": 1},
        ],
        fastpath=True,
    )
    assert result["ok"] and result["completed_steps"] == 2
    assert result["results"][2]["skipped"] is True


@pytest.mark.parametrize(
    "find_step",
    [
        {
            "action": "find_control",
            "text": "a",
            "name": "Results",
            "control_type": "Hyperlink",
        },
        {"action": "find_control", "text": "Music", "control_type": "Hyperlink"},
        {
            "action": "find_control",
            "text": "Music",
            "name": "Results",
            "control_type": "Edit",
        },
        {
            "action": "find_control",
            "text": "Music",
            "name": "Results",
            "control_type": "Hyperlink",
            "run_shell": "whoami",
        },
    ],
)
def test_bad_semantic_selector_is_rejected_before_any_action(desktop, find_step):
    desktop._dispatch = lambda **_: pytest.fail("must validate before I/O")
    with pytest.raises(PolicyError):
        desktop.batch("", [find_step], fastpath=True)


def test_legacy_batch_does_not_gain_semantic_control_selection(desktop):
    desktop._dispatch = lambda **_: pytest.fail("must validate before I/O")
    with pytest.raises(PolicyError):
        desktop.batch(
            "",
            [
                {
                    "action": "find_control",
                    "name": "Results",
                    "text": "Music",
                    "control_type": "Hyperlink",
                }
            ],
        )


@pytest.mark.parametrize(
    "invoke_args",
    [
        {"window_ref": 0, "element_ref": 1, "name": "forged"},
        {"window_ref": 0, "element_ref": 1, "automation_id": "forged"},
        {"window_ref": 2, "element_ref": 1},
        {"window_ref": 0, "element_ref": "1"},
        {"window_ref": 0, "element_ref": 0},
    ],
)
def test_element_ref_rejects_forged_selector_or_other_window(desktop, invoke_args):
    desktop._dispatch = lambda **_: pytest.fail("must validate before I/O")
    with pytest.raises(PolicyError):
        desktop.batch(
            "",
            [
                locator(100, "YouTube - Chrome", "Chrome_WidgetWin_1"),
                {
                    "action": "find_control",
                    "window_ref": 0,
                    "name": "Results",
                    "text": "Music",
                    "control_type": "Hyperlink",
                },
                locator(200, "Book1 - Excel", "XLMAIN"),
                {"action": "invoke", **invoke_args},
            ],
            fastpath=True,
        )
