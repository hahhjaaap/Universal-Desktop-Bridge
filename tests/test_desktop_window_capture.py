"""Window screenshots must not silently capture a different application's pixels."""

import os
import time
import uuid
from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop, DesktopFrameRejected, WindowObservation
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
    desktop.windows["observed"] = WindowObservation(
        10, 123, "fixture", time.monotonic() + 60
    )
    with pytest.raises(PolicyError, match="expired or changed"):
        desktop.resolve("observed", focus=False)


@pytest.fixture
def observed_frame():
    desktop = fixture_desktop()
    wid = "1" * 32
    desktop.windows[wid] = WindowObservation(10, 123, "fixture", time.monotonic() + 60)
    desktop.capture = lambda box: {"png_base64": "first-frame", "bounds": box}
    frame = desktop._dispatch(action="screenshot", window_id=wid)
    return desktop, wid, frame["frame_id"]


def test_matching_frame_allows_pointer_input_and_rejects_changed_pixels(observed_frame):
    desktop, wid, frame_id = observed_frame
    desktop.u = SimpleNamespace(GetAsyncKeyState=lambda key: 0)
    calls = []
    desktop.mouse_action = lambda *args: calls.append(args) or {"injected": True}
    args = dict(action="mouse_move", window_id=wid, x=10, y=10, expected_frame=frame_id)
    assert desktop._dispatch(**args)["injected"] is True
    assert len(calls) == 1

    desktop.capture = lambda box: {"png_base64": "changed", "bounds": box}
    result = desktop.batch(wid, [{k: v for k, v in args.items() if k != "window_id"}])
    assert result["failed_index"] == 0
    assert result["outcome_unknown"] is False
    assert result.get("replay_safe") is not False
    assert len(calls) == 1


def test_guarded_drag_rejects_point_outside_captured_area(observed_frame):
    desktop, wid, frame_id = observed_frame
    with pytest.raises(DesktopFrameRejected, match="outside"):
        desktop._dispatch(
            action="drag",
            window_id=wid,
            from_x=-4,
            from_y=-4,
            x=20,
            y=20,
            expected_frame=frame_id,
        )


def test_guarded_pointer_never_focuses_an_old_window(observed_frame):
    desktop, wid, frame_id = observed_frame
    desktop.gui.GetForegroundWindow = lambda: 20
    with pytest.raises(DesktopFrameRejected, match="foreground"):
        desktop._dispatch(action="click", window_id=wid, expected_frame=frame_id)


def test_frame_state_does_not_send_pixels_or_compare_other_windows(observed_frame):
    desktop, wid, frame_id = observed_frame
    state = desktop._dispatch(
        action="frame_state", window_id=wid, expected_frame=frame_id
    )
    assert state["frame_id"] == frame_id
    assert state["changed"] is False
    assert "png_base64" not in state

    with pytest.raises(DesktopFrameRejected, match="Observe this window"):
        desktop._dispatch(
            action="frame_state", window_id=wid, expected_frame="2" + frame_id[1:]
        )


def test_post_action_verification_failure_marks_batch_unsafe_to_repeat(observed_frame):
    desktop, wid, frame_id = observed_frame
    desktop.u = SimpleNamespace(GetAsyncKeyState=lambda key: 0)
    calls = []
    desktop.mouse_action = lambda *args: calls.append(args) or {"injected": True}
    result = desktop.batch(
        wid,
        [
            {"action": "mouse_move", "x": 10, "y": 10, "expected_frame": frame_id},
            {
                "action": "frame_state",
                "expected_frame": frame_id,
                "verify": {"field": "changed", "equals": True},
            },
        ],
    )
    assert result["ok"] is False
    assert result["failed_index"] == 1
    assert result["outcome_unknown"] is False
    assert result["replay_safe"] is False
    assert len(calls) == 1


def test_invalid_frame_is_rejected_before_earlier_batch_mutation(observed_frame):
    desktop, wid, _ = observed_frame
    desktop.interactive = lambda: pytest.fail("No Windows action during preflight")
    with pytest.raises(PolicyError, match="expected_frame"):
        desktop.batch(
            wid,
            [
                {"action": "click", "x": 10, "y": 10},
                {"action": "click", "x": 10, "y": 10, "expected_frame": "invalid"},
            ],
        )


@pytest.mark.skipif(
    os.name != "nt" or os.getenv("UDB_RUN_INTERACTIVE_WINDOWS_TESTS") != "1",
    reason="requires an interactive Windows test desktop",
)
def test_native_form_move_invalidates_visual_coordinates(monkeypatch):
    import pywintypes
    import win32con
    import win32gui
    import win32process

    from tools.compare_uia_snapshot_cache import _fixture

    with _fixture(50) as fixture:
        hwnd = fixture["hwnd"]
        pid = fixture["pid"]
        assert win32process.GetWindowThreadProcessId(hwnd)[1] == pid
        if win32gui.GetForegroundWindow() != hwnd:
            try:
                win32gui.SetForegroundWindow(hwnd)
            except pywintypes.error:
                pass
        if win32gui.GetForegroundWindow() != hwnd:
            pytest.skip("Windows did not activate the isolated fixture")

        desktop = Desktop()
        wid = uuid.uuid4().hex
        desktop.windows[wid] = WindowObservation(
            hwnd, pid, win32gui.GetClassName(hwnd), time.monotonic() + 60
        )
        monkeypatch.setattr(
            desktop, "mouse_action", lambda *args: pytest.fail("Input reached Win32")
        )
        frame = desktop.dispatch("screenshot", window_id=wid)
        assert frame["png_base64"].startswith("iVBOR")
        assert frame["frame_id"].startswith(f"{wid}.")
        left, top, _, _ = frame["bounds"]
        win32gui.SetWindowPos(
            hwnd,
            0,
            left + 24,
            top + 24,
            0,
            0,
            win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER | win32con.SWP_NOSIZE,
        )
        assert desktop.dispatch(
            "frame_state", window_id=wid, expected_frame=frame["frame_id"]
        )["changed"]
        with pytest.raises(DesktopFrameRejected, match="frame changed"):
            desktop.dispatch(
                "mouse_move",
                window_id=wid,
                x=left + 40,
                y=top + 40,
                expected_frame=frame["frame_id"],
            )


def test_detailed_screenshot_fits_relay_and_preserves_screen_mapping():
    desktop = Desktop.__new__(Desktop)
    sizes = []

    def gdi(box, max_width, max_height):
        sizes.append((max_width, max_height))
        if len(sizes) == 1:
            return b"0" * (700 * 1024), 1920, 1440
        return b"0" * (512 * 384 * 3 + 500), 512, 384

    desktop._capture_png = gdi
    image = desktop.capture([100, 50, 2020, 1490])
    assert sizes == [(1920, 1440), (512, 384)]
    assert image["bounds"] == [100, 50, 2020, 1490]
    assert image["scale_x"] == image["scale_y"] == 3.75
    assert len(image["png_base64"]) < 900 * 1024
