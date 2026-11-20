"""Local cloud-proxy stdio teardown uses EOF before terminating children.

All tests use a disposable Python child or a fake Popen object. They never
launch the installed owner's UDB bridge, access pairing, or touch Cloudflare.
"""

from __future__ import annotations

import subprocess
import sys

from udb.cloud_agent import LocalProxy


def test_local_proxy_closes_disposable_stdio_child_by_eof():
    # Same input contract as UnifiedProxy.serve(): EOF ends the serving loop.
    program = "import sys; sys.stdin.buffer.read(); sys.exit(0)"
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    proxy = object.__new__(LocalProxy)
    proxy.process = process
    proxy.reader = None
    try:
        proxy.close()
        assert process.poll() == 0, "Normal EOF exit must not be terminated"
        assert process.stdin.closed
        assert process.stdout.closed
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


def test_unresponsive_stdio_falls_back_to_terminate():
    events = []

    class Pipe:
        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(f"{self.name}.close")

    class Process:
        stdin = Pipe("stdin")
        stdout = Pipe("stdout")
        running = True

        def poll(self):
            return None if self.running else 0

        def wait(self, timeout):
            events.append(f"wait:{timeout}")
            if self.running:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

        def terminate(self):
            events.append("terminate")
            self.running = False

        def kill(self):
            raise AssertionError("Graceful terminate path must not kill")

    proxy = object.__new__(LocalProxy)
    proxy.process = Process()
    proxy.reader = None
    proxy.close()
    assert events == [
        "stdin.close",
        "wait:2",
        "terminate",
        "wait:3",
        "stdout.close",
    ]


def test_stuck_terminated_stdio_uses_previous_bounded_kill():
    events = []

    class Pipe:
        def close(self):
            pass

    class Process:
        stdin = Pipe()
        stdout = Pipe()
        killed = False

        def poll(self):
            return None if not self.killed else 1

        def wait(self, timeout):
            events.append(timeout)
            if not self.killed:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 1

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")
            self.killed = True

    proxy = object.__new__(LocalProxy)
    proxy.process = Process()
    proxy.reader = None
    proxy.close()
    assert events == [2, "terminate", 3, "kill", 3]


def test_already_exited_worker_does_not_relaunch_or_terminate():
    events = []

    class Pipe:
        def close(self):
            events.append("close")

    class Process:
        stdin = Pipe()
        stdout = Pipe()

        def poll(self):
            return 0

        def terminate(self):
            raise AssertionError("Already exited worker must not be terminated")

    proxy = object.__new__(LocalProxy)
    proxy.process = Process()
    proxy.reader = None
    proxy.close()
    assert events == ["close", "close"]
