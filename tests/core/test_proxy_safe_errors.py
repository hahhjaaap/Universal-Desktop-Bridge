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


@pytest.mark.parametrize("route", ["direct", "fleet", "non-tool"])
@pytest.mark.parametrize(
    ("code", "reason", "public_code", "public_reason"),
    [
        (-32602, "synthetic-secret", -32602, None),
        (
            -32002,
            "outcome_unknown_do_not_retry_mutations",
            -32002,
            "outcome_unknown_do_not_retry_mutations",
        ),
        (-32099, ["synthetic-secret"], -32099, None),
        (True, None, -32603, None),
    ],
)
def test_backend_rpc_error_is_sanitized(
    route, code, reason, public_code, public_reason, capsys
):
    def request(_method, _params):
        return {
            "error": {
                "code": code,
                "message": r"C:\Users\fixture\private-file.txt synthetic-secret",
                "data": {"reason": reason, "trace": "synthetic-stack-trace"},
            },
            "synthetic-extra": "synthetic-secret",
        }

    backend = SimpleNamespace(request=request)
    p = proxy.UnifiedProxy(backend, object(), fleet=SimpleNamespace(local_id="pc-home"))
    p.tool_routes = {"bridge_status": backend}
    p.startup_ok = True
    frames = []
    p.send = frames.append
    params = {"name": "bridge_status", "arguments": {}}
    if route == "fleet":
        params = {
            "name": "fleet_call",
            "arguments": {
                "computer_id": "pc-home",
                "tool": "bridge_status",
                "arguments": {},
            },
        }
    assert p.active_limit.acquire(blocking=False)
    p.handle(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "fixture" if route == "non-tool" else "tools/call",
            "params": params,
        }
    )
    assert len(frames) == 1 and frames[0]["id"] == 31
    error = frames[0]["error"]
    assert error["code"] == public_code
    assert error.get("data", {}).get("reason") == public_reason
    if public_reason:
        assert "inspect state before retrying" in error["message"]
    report = json.dumps(frames) + capsys.readouterr().err
    for secret in ("private-file", "synthetic-secret", "synthetic-stack-trace"):
        assert secret not in report
