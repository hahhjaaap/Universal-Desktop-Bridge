"""Proxy errors remain useful without exposing exception arguments."""

import io
import json
from types import SimpleNamespace

import pytest

from udb import proxy


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        (TimeoutError, -32002),
        (OSError, -32000),
        (ValueError, -32000),
        (RuntimeError, -32000),
        (KeyError, -32000),
        (TypeError, -32000),
        (Exception, -32603),
    ],
)
def test_proxy_error_reply_and_local_log_do_not_echo_arguments(kind, code, capsys):
    def reject(method, params):
        raise kind(r"C:\Users\Test\private-file.txt synthetic-secret")

    stub = SimpleNamespace(request=reject)
    p = proxy.UnifiedProxy(stub, stub)
    frames = []
    p.send = frames.append
    assert p.active_limit.acquire(blocking=False)
    p.handle({"jsonrpc": "2.0", "id": 19, "method": "fixture"})
    assert len(frames) == 1
    assert frames[0]["error"]["code"] == code
    assert frames[0]["id"] == 19
    ledger = capsys.readouterr().err
    report = json.dumps(frames) + ledger
    assert "private-file" not in report
    assert "synthetic-secret" not in report
    assert kind.__name__ in ledger


def test_thread_start_failure_releases_slot_and_replies(monkeypatch, capsys):
    class UnavailableThread:
        def __init__(self, **_options):
            pass

        def start(self):
            raise RuntimeError(r"C:\private-runner\synthetic-secret")

    p = proxy.UnifiedProxy(object(), object())
    frames = []
    p.send = frames.append
    raw = b'{"jsonrpc":"2.0","id":23,"method":"ping"}\n'
    monkeypatch.setattr(proxy.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(proxy.threading, "Thread", UnavailableThread)
    p.serve()
    assert len(frames) == 1 and frames[0]["id"] == 23
    assert frames[0]["error"]["code"] == -32603
    assert "synthetic-secret" not in json.dumps(frames) + capsys.readouterr().err
    for _ in range(proxy.MAX_CONCURRENT):
        assert p.active_limit.acquire(blocking=False)
    assert not p.active_limit.acquire(blocking=False)


def test_explicit_initialization_policy_message_remains_visible():
    p = proxy.UnifiedProxy(object(), object())
    frames = []
    p.send = frames.append
    assert p.active_limit.acquire(blocking=False)
    p.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert frames[0]["error"]["code"] == -32000
    assert frames[0]["error"]["message"] == "MCP not initialized"
