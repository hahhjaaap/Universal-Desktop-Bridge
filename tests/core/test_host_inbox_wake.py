"""Windows host inbox wake hint: low latency without changing mailbox policy."""

from __future__ import annotations

import os
import threading
import time

import pytest

from udb.host_inbox_wake import InboxWake


class FakeStop:
    def __init__(self):
        self.delays = []

    def wait(self, delay):
        self.delays.append(delay)


class FakeWindows:
    def __init__(self, *outcomes, rearm=True):
        self.outcomes = list(outcomes)
        self.rearm = rearm
        self.calls = []
        self.closed = []

    def WaitForSingleObject(self, handle, timeout):
        self.calls.append((handle, timeout))
        return self.outcomes.pop(0)

    def FindNextChangeNotification(self, handle):
        self.calls.append(("rearm", handle))
        return self.rearm

    def FindCloseChangeNotification(self, handle):
        self.closed.append(handle)
        return True


def fake_watcher(api=None):
    watcher = InboxWake.__new__(InboxWake)
    watcher._handle = 1234 if api is not None else None
    watcher._api = api
    return watcher


def test_native_wakeup_rearms_without_waiting_for_idle_poll():
    api = FakeWindows(0, 258)
    watcher = fake_watcher(api)
    stop = FakeStop()
    assert watcher.wait(0.25, stop) is True
    assert api.calls == [(1234, 250), ("rearm", 1234)]
    assert stop.delays == []
    assert watcher.wait(0.25, stop) is False
    assert api.calls[-1] == (1234, 250)
    watcher.close()
    watcher.close()
    assert api.closed == [1234]


def test_missing_watcher_preserves_legacy_bounded_poll():
    watcher = fake_watcher()
    stop = FakeStop()
    assert watcher.wait(0.25, stop) is False
    assert stop.delays == [0.25]


def test_notification_failure_disables_watcher_and_falls_back():
    api = FakeWindows(0xFFFFFFFF)
    watcher = fake_watcher(api)
    stop = FakeStop()
    assert watcher.wait(0.25, stop) is False
    assert api.closed == [1234]
    assert watcher.wait(0.06, stop) is False
    assert stop.delays == [0.06]


def test_rearm_failure_is_not_treated_as_successful_future_notification():
    api = FakeWindows(0, rearm=False)
    watcher = fake_watcher(api)
    stop = FakeStop()
    assert watcher.wait(0.25, stop) is True
    assert api.closed == [1234]
    assert watcher.wait(0.25, stop) is False
    assert stop.delays == [0.25]


def test_native_watcher_does_not_exist_outside_windows(tmp_path):
    if os.name == "nt":
        pytest.skip("Only the non-Windows fallback is checked here")
    watcher = InboxWake(tmp_path)
    assert watcher._handle is None
    watcher.close()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows directory notification")
def test_native_directory_signal_wakes_when_atomic_mailbox_file_appears(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    watcher = InboxWake(inbox)
    if watcher._handle is None:
        pytest.skip("Native notifications unavailable; fallback remains supported")

    start = threading.Event()
    finished = threading.Event()

    def write_command():
        start.wait(timeout=2)
        time.sleep(0.07)
        temp = inbox / "pending.tmp"
        temp.write_text("{}", encoding="utf-8")
        temp.replace(inbox / "pending.json")
        finished.set()

    thread = threading.Thread(target=write_command, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        start.set()
        # The worker watches filename changes, not the JSON payload.
        assert watcher.wait(1.5, threading.Event()) is True
        assert time.monotonic() - started < 1.4
        assert finished.wait(2)
        assert (inbox / "pending.json").exists()
    finally:
        watcher.close()
        thread.join(timeout=2)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows directory notification")
def test_notification_deposited_before_wait_is_not_lost(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    watcher = InboxWake(inbox)
    if watcher._handle is None:
        pytest.skip("Native notifications unavailable; fallback remains supported")
    try:
        (inbox / "queued.tmp").write_text("{}", encoding="utf-8")
        (inbox / "queued.tmp").replace(inbox / "queued.json")
        assert watcher.wait(0.25, threading.Event()) is True
    finally:
        watcher.close()
