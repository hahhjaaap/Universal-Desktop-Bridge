"""Dependency-injected window identity contract from the WS14 audit."""

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
