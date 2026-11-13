"""Window screenshots must not silently capture a different application's pixels."""

import time
from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


def fixture_desktop(*, foreground=10, minimized=(), cloaked=(), order=(10,)):
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = lambda: None
    boxes = {10: (-8, -8, 300, 200), 20: (30, 30, 100, 100)}
    desktop.gui = SimpleNamespace(
        IsWindow=lambda hwnd: hwnd in boxes,
        IsWindowVisible=lambda hwnd: True,
        IsIconic=lambda hwnd: hwnd in minimized,
        GetForegroundWindow=lambda: foreground,
        GetWindowRect=lambda hwnd: boxes[hwnd],
        GetClassName=lambda hwnd: "fixture",
        GetWindowText=lambda hwnd: "fixture" if hwnd == 10 else "",
        EnumWindows=lambda visitor, arg: [visitor(hwnd, arg) for hwnd in order],
    )
    desktop.process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 123))
    desktop.is_cloaked = lambda hwnd: hwnd in cloaked
    desktop.display_inventory = lambda: {"displays": [{"bounds": [0, 0, 800, 600]}]}
    desktop.windows = {}
    return desktop


@pytest.mark.parametrize(
    "options",
    [
        {"foreground": 20},
        {"minimized": (10,)},
        {"cloaked": (10,)},
        {"order": (20, 10)},  # Untitled topmost overlay is also an occluder.
    ],
)
def test_wrong_hidden_or_covered_window_is_refused_before_capture(options):
    desktop = fixture_desktop(**options)
    desktop.capture = lambda box: pytest.fail("Must not capture another app")
    with pytest.raises(PolicyError):
        desktop.screenshot(10)


def test_visible_window_capture_clips_invisible_resize_border_and_labels_scope():
    desktop = fixture_desktop()
    boxes = []
    desktop.capture = lambda box: boxes.append(box) or {"png_base64": "fixture"}
    result = desktop.screenshot(10)
    assert boxes == [(0, 0, 300, 200)]
    assert result["source"] == "visible_window_region"
    assert result["window_content_isolated"] is False
    assert result["occlusion_checked"] is True


def test_foreground_change_during_capture_discards_result_without_replay():
    desktop = fixture_desktop()
    captures = []

    def capture(box):
        captures.append(box)
        desktop.gui.GetForegroundWindow = lambda: 20
        return {"png_base64": "must-not-return"}

    desktop.capture = capture
    with pytest.raises(PolicyError):
        desktop.screenshot(10)
    assert len(captures) == 1


def test_cloaked_shell_is_not_listed_but_real_minimized_frame_is_identified():
    desktop = fixture_desktop(cloaked=(10,), order=(10,))
    assert desktop.listing()["windows"] == []
    assert not desktop.windows
    desktop = fixture_desktop(minimized=(10,))
    result = desktop.listing()
    assert result["cloaked_windows_hidden"] is True
    assert result["windows"][0]["minimized"] is True
    assert result["windows"][0]["class_name"] == "fixture"


def test_window_becoming_cloaked_invalidates_an_existing_observation():
    desktop = fixture_desktop(cloaked=(10,))
    desktop.windows["observed"] = (10, 123, "fixture", time.monotonic() + 60)
    with pytest.raises(PolicyError, match="expired or changed"):
        desktop.resolve("observed", focus=False)
