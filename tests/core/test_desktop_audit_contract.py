"""Dependency-injected window identity contract from the WS14 audit."""

import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from udb.computer_desktop import Desktop, WindowObservation
from udb.core import PolicyError


def test_physical_input_refuses_changed_window_identity_before_send():
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = lambda: None
    desktop.is_cloaked = lambda _hwnd: False
    desktop.guard = lambda: True
    desktop.control = None
    desktop.gui = SimpleNamespace(
        IsWindow=lambda _hwnd: True,
        IsWindowVisible=lambda _hwnd: True,
        GetClassName=lambda _hwnd: "fixture",
        GetForegroundWindow=lambda: 10,
    )
    desktop.process = SimpleNamespace(
        GetWindowThreadProcessId=Mock(side_effect=[(1, 100), (1, 101)])
    )
    desktop.u = SimpleNamespace(
        GetAsyncKeyState=Mock(return_value=0),
        SendInput=Mock(side_effect=lambda count, *_args: count),
    )
    desktop.windows = {
        "fixture": WindowObservation(10, 100, "fixture", time.monotonic() + 30)
    }
    with pytest.raises(PolicyError, match="Window identity changed before input"):
        desktop._dispatch("type", window_id="fixture", text="fixture")
    desktop.u.SendInput.assert_not_called()

    # Same fixture remains usable when both lookups agree. No real Win32 input.
    desktop.process.GetWindowThreadProcessId.side_effect = [
        (1, 100),
        (1, 100),
    ]
    desktop._dispatch("type", window_id="fixture", text="fixture")
    desktop.u.SendInput.assert_called_once()


def _mock_pointer_target(monkeypatch, *, current_pid, send_input):
    """Isolated pointer fixture; no real cursor or input API is invoked."""
    desktop = Desktop.__new__(Desktop)
    desktop.interactive = lambda: None
    desktop.guard = lambda: True
    desktop.control = None
    desktop.resolve = lambda *_args, **_kwargs: 10
    desktop.is_cloaked = lambda _hwnd: False
    desktop.windows = {
        "fixture": WindowObservation(10, 100, "fixture", time.monotonic() + 30)
    }
    desktop.process = SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (1, current_pid)
    )
    desktop.gui = SimpleNamespace(
        IsWindow=lambda _hwnd: True,
        IsWindowVisible=lambda _hwnd: True,
        GetClassName=lambda _hwnd: "fixture",
        GetForegroundWindow=lambda: 10,
        GetWindowRect=lambda _hwnd: (0, 0, 100, 100),
        WindowFromPoint=lambda _point: 10,
    )
    desktop.u = SimpleNamespace(
        GetAncestor=Mock(return_value=10),
        GetAsyncKeyState=Mock(return_value=0),
        SendInput=send_input,
    )
    moves = []
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(
            SetCursorPos=lambda point: moves.append(point),
            GetCursorPos=lambda: (10, 10),
        ),
    )
    return desktop, moves


def test_stale_window_never_moves_pointer_or_sends_mouse_release(monkeypatch):
    sent = Mock(return_value=1)
    desktop, moves = _mock_pointer_target(
        monkeypatch, current_pid=101, send_input=sent
    )
    with pytest.raises(PolicyError, match="Window identity changed before input"):
        desktop._dispatch("click", window_id="fixture", x=20, y=20)
    assert moves == []
    sent.assert_not_called()


def test_rejected_mouse_input_does_not_emit_unowned_release(monkeypatch):
    sent = Mock(return_value=0)
    desktop, moves = _mock_pointer_target(
        monkeypatch, current_pid=100, send_input=sent
    )
    with pytest.raises(PolicyError, match="Windows blocked or partially accepted"):
        desktop._dispatch("click", window_id="fixture", x=20, y=20)
    assert moves == [(20, 20)]
    sent.assert_called_once()
    assert sent.call_args.args[0] == 2


def test_partial_mouse_input_releases_owned_button_once(monkeypatch):
    sent = Mock(side_effect=[1, 1])
    desktop, _ = _mock_pointer_target(
        monkeypatch, current_pid=100, send_input=sent
    )
    with pytest.raises(PolicyError, match="partially accepted"):
        desktop._dispatch("click", window_id="fixture", x=20, y=20)
    assert [call.args[0] for call in sent.call_args_list] == [2, 1]


def test_stale_window_never_moves_pointer_via_mouse_move(monkeypatch):
    sent = Mock(return_value=1)
    desktop, moves = _mock_pointer_target(
        monkeypatch, current_pid=101, send_input=sent
    )
    with pytest.raises(PolicyError, match="Window identity changed before input"):
        desktop._dispatch("mouse_move", window_id="fixture", x=20, y=20)
    assert moves == []
    sent.assert_not_called()
