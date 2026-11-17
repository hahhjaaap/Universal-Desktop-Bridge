"""WS3: unexpected backend faults yield one bounded, generic RPC error."""

from __future__ import annotations

import io
import json
import threading
from types import SimpleNamespace

import pytest

from udb import proxy


@pytest.mark.parametrize(
    "exception",
    (AttributeError("secret value"), IndexError("private argument")),
)
def test_unexpected_backend_exception_reports_once_and_releases_slot(exception, capsys):
    instance = proxy.UnifiedProxy.__new__(proxy.UnifiedProxy)
    instance.startup_ok = True
    instance.activity = None
    instance.active_limit = threading.BoundedSemaphore(1)
    assert instance.active_limit.acquire(blocking=False)
    seen = []
    instance.send = seen.append

    def broken(_params):
        raise exception

    instance.call_tool = broken
    instance.handle(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "file_read", "arguments": {}},
        }
    )
    assert len(seen) == 1
    assert seen[0]["error"]["code"] == -32603
    assert "secret" not in str(seen)
    assert "private" not in str(seen)
    assert "secret" not in capsys.readouterr().err
    assert instance.active_limit.acquire(blocking=False)


def test_output_failure_not_retried_after_possible_partial_write(capsys):
    instance = proxy.UnifiedProxy.__new__(proxy.UnifiedProxy)
    instance.startup_ok = True
    instance.activity = None
    instance.active_limit = threading.BoundedSemaphore(1)
    assert instance.active_limit.acquire(blocking=False)
    count = 0

    def failing_send(_):
        nonlocal count
        count += 1
        raise OSError("sensitive output")

    instance.send = failing_send
    instance.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert count == 1
    assert instance.active_limit.acquire(blocking=False)
    assert "sensitive" not in capsys.readouterr().err


def test_oversized_request_id_emits_one_bounded_json_error(monkeypatch):
    instance = proxy.UnifiedProxy.__new__(proxy.UnifiedProxy)
    instance.send_lock = threading.Lock()
    output = io.BytesIO()
    monkeypatch.setattr(proxy.sys, "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(proxy, "MAX_LINE", 350)
    instance.send({"jsonrpc": "2.0", "id": "a" * 1000, "result": {}})
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    reply = json.loads(lines[0])
    assert reply["id"] is None
    assert reply["error"]["code"] == -32005
    assert b"aaaa" not in output.getvalue()


def test_failing_telemetry_never_leaks_concurrency_slot(monkeypatch):
    instance = proxy.UnifiedProxy.__new__(proxy.UnifiedProxy)
    instance.startup_ok = True
    instance.activity = None
    instance.active_limit = threading.BoundedSemaphore(1)
    assert instance.active_limit.acquire(blocking=False)
    responses = []
    instance.send = responses.append

    def telemetry_failure(*_args, **_kwargs):
        raise AttributeError("untrusted telemetry content")

    monkeypatch.setattr(proxy.perf, "interval", telemetry_failure)
    instance.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})
    assert len(responses) == 1
    assert instance.active_limit.acquire(blocking=False)
