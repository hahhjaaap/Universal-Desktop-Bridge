"""Wake the owned Windows host worker when a new mailbox file appears.

Windows file-name notifications remove the 250 ms idle polling delay without
spinning. Unavailable/failed watchers fall back to the existing bounded poll.
This signal does not authorize, read, claim or execute any command.
"""

from __future__ import annotations

import os


class InboxWake:
    """One owned inbox watcher; wake hints are never treated as trusted commands."""

    def __init__(self, inbox):
        self._api = None
        self._handle = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            api = ctypes.WinDLL("kernel32", use_last_error=True)
            first = api.FindFirstChangeNotificationW
            first.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
            first.restype = wintypes.HANDLE
            next_change = api.FindNextChangeNotification
            next_change.argtypes = [wintypes.HANDLE]
            next_change.restype = wintypes.BOOL
            wait = api.WaitForSingleObject
            wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait.restype = wintypes.DWORD
            close = api.FindCloseChangeNotification
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL

            # FILE_NOTIFY_CHANGE_FILE_NAME: atomic_json's temp->.json rename
            # fires this even when the contents are not yet read by the worker.
            handle = first(str(inbox), False, 0x00000001)
            invalid = ctypes.c_void_p(-1).value
            if not handle or handle == invalid:
                return
            self._api = api
            self._handle = handle
        except (OSError, AttributeError, TypeError, ValueError):
            # This is a latency optimization, never a correctness dependency.
            self._api = None
            self._handle = None

    def wait(self, timeout_seconds, stop_event):
        """Wait for an inbox filename event, retaining periodic fallback scans.

        The caller scans the full inbox *before* waiting; the watcher is armed
        beforehand and re-armed immediately on a signal. A file deposited
        between scan and wait therefore cannot be lost.
        """
        if self._handle is None:
            stop_event.wait(timeout_seconds)
            return False
        try:
            result = self._api.WaitForSingleObject(
                self._handle, max(0, int(timeout_seconds * 1000))
            )
            if result == 0:  # WAIT_OBJECT_0
                if not self._api.FindNextChangeNotification(self._handle):
                    self.close()
                return True
            if result == 258:  # WAIT_TIMEOUT
                return False
        except (OSError, AttributeError, TypeError, ValueError):
            pass
        # Invalid/failed notification handle: fail over to normal polling.
        self.close()
        return False

    def close(self):
        handle = self._handle
        self._handle = None
        api = self._api
        self._api = None
        if handle is not None and api is not None:
            try:
                api.FindCloseChangeNotification(handle)
            except (OSError, AttributeError, TypeError, ValueError):
                pass
