"""Safe multi-application desktop batch contracts using simulated Win32 windows.

No real user windows, screen capture, physical input, UAC or permissions are
modified. Window identities are exact and each use is independently checked.
"""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


class FakeGui:
    def __init__(self):
        self.rows = {
            111: {"pid": 101, "class_name": "App1Class", "title": "App One"},
            222: {"pid": 202, "class_name": "App2Class", "title": "App Two"},
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

    def GetClassName(self, hwnd):
        return self.rows[hwnd]["class_name"]

    def GetWindowText(self, hwnd):
        return self.rows[hwnd]["title"]

    def GetForegroundWindow(self):
        return self.foreground

    def IsIconic(self, hwnd):
        return False


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.delenv("UDB_UIA_PERSISTENT", raising=False)
    d = Desktop.__new__(Desktop)
    d.gui = FakeGui()
    d.windows = {}
    d.process = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (0, d.gui.rows[hwnd]["pid"])
    )
    d.interactive = lambda: None
    d.is_cloaked = lambda hwnd: False
    return d


def locator(pid, class_name, title):
    return {
        "action": "find_window",
        "pid": pid,
        "class_name": class_name,
        "title": title,
    }


def test_locate_two_app_windows_then_switch_and_observe_in_one_batch(desktop):
    called = []

    def action(action, window_id, **kwargs):
        hwnd = desktop.resolve(window_id, focus=False)
        called.append((action, hwnd))
        return {"foreground": True} if action == "focus" else {"ok": True}

    desktop._dispatch = action
    result = desktop.batch(
        "",
        [
            {**locator(101, "App1Class", "App One"), "return_result": False},
            {
                "action": "focus",
                "window_ref": 0,
                "verify": {"field": "foreground", "equals": True},
            },
            locator(202, "App2Class", "App Two"),
            {
                "action": "read_text",
                "window_ref": 2,
                "when": {"step_index": 2, "field": "found", "equals": True},
                "verify": {"field": "ok", "equals": True},
            },
        ],
    )
    assert result["ok"] is True
    assert result["completed_steps"] == 4
    assert called == [("focus", 111), ("read_text", 222)]
    assert result["results"][0].get("result") is None
    assert result["results"][2]["result"]["pid"] == 202
    assert result["results"][2]["result"]["window_id"] in desktop.windows
    assert desktop.gui.visits == 2


def test_no_match_skips_window_ref_and_never_sends_input(desktop):
    calls = []
    desktop._dispatch = lambda action, window_id="", x=0, y=0: calls.append(
        (action, window_id, x, y)
    )
    result = desktop.batch(
        "",
        [
            locator(101, "App1Class", "Window that has been renamed"),
            {"action": "click", "window_ref": 0, "x": 5, "y": 5},
        ],
    )
    assert result["ok"] is True
    assert result["completed_steps"] == 1
    assert result["results"][0]["result"] == {"found": False}
    assert result["results"][1]["skipped"] is True
    assert calls == []


def test_missing_window_verification_fails_before_mutation_and_is_safe(desktop):
    desktop._dispatch = lambda action, window_id="", x=0, y=0: pytest.fail(
        "must not dispatch"
    )
    result = desktop.batch(
        "",
        [
            {
                **locator(101, "App1Class", "wrong title"),
                "verify": {"field": "found", "equals": True},
            },
            {"action": "click", "window_ref": 0, "x": 5, "y": 5},
        ],
    )
    assert result["ok"] is False
    assert result["failed_index"] == 0
    assert result["outcome_unknown"] is False


def test_ambiguous_window_identity_fails_closed(desktop):
    desktop.gui.rows[333] = dict(desktop.gui.rows[111])
    desktop._dispatch = lambda action, window_id="": pytest.fail(
        "ambiguous must not dispatch"
    )
    result = desktop.batch(
        "",
        [
            locator(101, "App1Class", "App One"),
            {"action": "focus", "window_ref": 0},
        ],
    )
    assert result["ok"] is False
    assert result["completed_steps"] == 0
    assert result["failed_index"] == 0
    assert result["outcome_unknown"] is False
    assert desktop.windows == {}


def test_identity_change_after_observation_is_rejected_before_action(desktop):
    result = desktop.find_window(101, "App1Class", "App One")
    assert result["found"] is True
    desktop.gui.rows[111]["pid"] = 999
    with pytest.raises(PolicyError, match="expired or changed"):
        desktop.resolve(result["window_id"], focus=False)


def test_expired_identity_is_rejected_and_safe_refresh_works(desktop):
    first = desktop.find_window(101, "App1Class", "App One")
    hwnd, pid, cls, _ = desktop.windows[first["window_id"]]
    desktop.windows[first["window_id"]] = (hwnd, pid, cls, time.monotonic() - 1)
    with pytest.raises(PolicyError, match="expired or changed"):
        desktop.resolve(first["window_id"], focus=False)
    second = desktop.find_window(101, "App1Class", "App One")
    assert second["found"]
    assert second["window_id"] != first["window_id"]
    assert first["window_id"] not in desktop.windows


@pytest.mark.parametrize(
    "bad",
    [
        {"pid": True},
        {"pid": -1},
        {"pid": 1.0},
        {"pid": 4294967296},
        {"class_name": ""},
        {"class_name": "x" * 129},
        {"title": ""},
        {"title": "x" * 301},
        {"class_name": None},
        {"title": None},
        {"window_ref": 0},
        {"window_id": "forged"},
        {"text": "unexpected"},
    ],
)
def test_invalid_window_locator_plan_rejected_before_any_work(desktop, bad):
    called = []
    desktop.interactive = lambda: called.append(True)
    with pytest.raises(PolicyError):
        desktop.batch(
            "",
            [{**locator(101, "App1Class", "App One"), **bad}],
        )
    assert called == []


@pytest.mark.parametrize(
    "ref, extra",
    [
        (True, {}),
        (-1, {}),
        (0, {"window_id": "forged"}),
        (1, {}),
        ("0", {}),
    ],
)
def test_window_ref_rejects_ambiguous_or_invalid_reference(desktop, ref, extra):
    called = []
    desktop.interactive = lambda: called.append(True)
    with pytest.raises(PolicyError):
        desktop.batch(
            "",
            [
                locator(101, "App1Class", "App One"),
                {"action": "focus", "window_ref": ref, **extra},
            ],
        )
    assert called == []


def test_window_ref_must_point_to_locator_not_arbitrary_prior_result(desktop):
    called = []
    desktop._dispatch = lambda **kw: called.append(kw)
    with pytest.raises(PolicyError):
        desktop.batch(
            "",
            [
                {"action": "control_status"},
                {"action": "focus", "window_ref": 0},
            ],
        )
    assert called == []


def test_fresh_lookup_never_overrides_owner_pause_or_permissions(desktop):
    # A window locator may only observe a granted interactive desktop.
    desktop.interactive = lambda: (_ for _ in ()).throw(
        PolicyError("Interactive desktop is unavailable or locked")
    )
    result = desktop.batch("", [locator(101, "App1Class", "App One")])
    assert not result["ok"]
    assert not result["outcome_unknown"]
    assert desktop.gui.visits == 0


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Win32 UI")
def test_windows_test_owned_form_can_be_reobserved_by_real_native_identity():
    """Never accesses a user window or sends real mouse/keyboard input."""
    import win32gui
    import win32process

    from tools.compare_uia_snapshot_cache import _fixture

    with _fixture(50) as form:
        hwnd = form["hwnd"]
        title = win32gui.GetWindowText(hwnd)
        class_name = win32gui.GetClassName(hwnd)
        assert title and class_name
        d = Desktop.__new__(Desktop)
        d.gui = win32gui
        d.process = win32process
        d.windows = {}
        # The CI form is test-owned; this test checks identity only. Owner
        # desktop / secure-screen authorization is exercised separately.
        d.interactive = lambda: None
        d.is_cloaked = lambda _hwnd: False
        found = d.find_window(form["pid"], class_name, title)
        assert found["found"] is True
        assert found["pid"] == form["pid"]
        assert d.resolve(found["window_id"], focus=False) == hwnd
        assert d.find_window(form["pid"], class_name, title + " changed") == {
            "found": False
        }
