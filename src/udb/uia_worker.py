"""Owner-local, opt-in persistent PowerShell UI Automation client.

The IPC is an inherited pair of anonymous pipes, never a network listener or
named pipe open to other users. Every invocation checks HWND/PID in the helper
and the Python caller must recheck owner grant and interactive desktop. A lost,
malformed or late response is *never* replayed against a new worker.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from . import hyperspeed_perf as perf
from .core import PolicyError

MAX_REQUEST_BYTES = 100000
MAX_RESPONSE_CHARS = 262144
IDLE_SECONDS = 90


class PersistentUIA:
    """Serialize per-desktop UIA on a private PowerShell STA host."""

    def __init__(self, executable: Path, helper: Path):
        self.executable = Path(executable)
        self.helper = Path(helper)
        self._lock = threading.RLock()
        self._process = None
        self._replies = None
        self._reader = None
        self._sequence = 0
        self._idle = None
        self._idle_token = None
        self._cancel_event = threading.Event()

    @staticmethod
    def _receive(process, replies):
        try:
            while True:
                line = process.stdout.readline(MAX_RESPONSE_CHARS + 2)
                if not line:
                    break
                try:
                    replies.put_nowait(line)
                except queue.Full:
                    # A second reply without a new request is a protocol error.
                    # Never discard the first or return a stale response.
                    break
        finally:
            try:
                replies.put_nowait(None)
            except queue.Full:
                pass

    def _stop_locked(self):
        timer = self._idle
        self._idle = None
        self._idle_token = None
        if timer is not None:
            timer.cancel()
        process = self._process
        self._process = None
        self._replies = None
        self._reader = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            # No further command is ever dispatched to this process.
            pass
        try:
            if process.stdout is not None:
                process.stdout.close()
        except (OSError, ValueError):
            pass

    def close(self):
        # Wake an in-flight bounded wait before acquiring its serialization lock.
        self._cancel_event.set()
        with self._lock:
            self._stop_locked()
            self._cancel_event.clear()

    def _expire(self, token):
        with self._lock:
            if self._idle_token is token and self._idle is not None:
                self._stop_locked()

    def _begin(self):
        if self._process is not None and self._process.poll() is None:
            return
        self._stop_locked()
        process = subprocess.Popen(
            [
                str(self.executable),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Sta",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.helper),
                "-Persistent",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=False,
        )
        if process.stdin is None or process.stdout is None:
            process.kill()
            raise OSError("PowerShell IPC pipes unavailable")
        self._process = process
        self._replies = queue.Queue(maxsize=2)
        self._sequence = 0
        self._reader = threading.Thread(
            target=self._receive,
            args=(process, self._replies),
            name="udb-uia-reader",
            daemon=True,
        )
        self._reader.start()

    def call(self, request: dict, timeout: float, *, cancel_check=None) -> dict:
        """Never resend after a write attempt, even on revoke, close or timeout."""
        if type(timeout) not in (int, float) or not 0 < timeout <= 22:
            raise PolicyError("Invalid UIA execution deadline")
        try:
            wire = json.dumps(
                request, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise PolicyError("Invalid UIA request") from exc
        if len(wire.encode("utf-8")) > MAX_REQUEST_BYTES or "\n" in wire:
            raise PolicyError("UIA request too large or malformed")
        with self._lock:
            if self._cancel_event.is_set():
                raise PolicyError("UI Automation worker is closing; request was not dispatched")
            if self._idle is not None:
                self._idle.cancel()
                self._idle = None
                self._idle_token = None
            try:
                with perf.span("desktop.uia", "startup"):
                    self._begin()
                process = self._process
                expected_sequence = self._sequence + 1
                with perf.span("desktop.uia", "dispatch"):
                    process.stdin.write(wire + "\n")
                    process.stdin.flush()
                with perf.span("desktop.uia", "observation"):
                    deadline = time.monotonic() + timeout
                    while True:
                        if self._cancel_event.is_set():
                            self._stop_locked()
                            raise PolicyError(
                                "UI Automation worker closed while a request was in flight; "
                                "the result may be unknown and no replay was attempted."
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise queue.Empty
                        try:
                            line = self._replies.get(timeout=min(0.1, remaining))
                            break
                        except queue.Empty:
                            if cancel_check is not None:
                                try:
                                    cancel_check()
                                except Exception:
                                    self._cancel_event.set()
                                    self._stop_locked()
                                    self._cancel_event.clear()
                                    raise PolicyError(
                                        "Computer access was revoked or the interactive "
                                        "desktop became unavailable during UIA wait; the "
                                        "observer worker was stopped and no replay occurred."
                                    ) from None
                if (
                    type(line) is not str
                    or not line.endswith("\n")
                    or len(line) > MAX_RESPONSE_CHARS
                ):
                    raise ValueError("Invalid UIA worker reply framing")
                envelope = json.loads(line)
                if (
                    not isinstance(envelope, dict)
                    or type(envelope.get("sequence")) is not int
                    or envelope["sequence"] != expected_sequence
                ):
                    raise ValueError("Stale or unexpected UIA worker response")
                reply = envelope.get("result")
                if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
                    raise ValueError("Invalid UIA worker reply schema")
                self._sequence = expected_sequence
                # A response of ok=false is a rejected action, NOT a retry signal.
                return reply
            except (
                OSError,
                ValueError,
                EOFError,
                queue.Empty,
                subprocess.SubprocessError,
            ):
                self._stop_locked()
                raise PolicyError(
                    "UI Automation worker stopped or timed out; result may be unknown. "
                    "Inspect target before any new mutation; no replay was attempted."
                ) from None
            finally:
                if self._process is not None:
                    token = object()
                    timer = threading.Timer(IDLE_SECONDS, self._expire, args=(token,))
                    timer.daemon = True
                    self._idle_token = token
                    self._idle = timer
                    timer.start()


def enabled():
    """Default off until an owner-authorized Windows canary validates behavior."""
    return os.environ.get("UDB_UIA_PERSISTENT", "0") == "1"
