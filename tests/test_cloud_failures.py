"""Offline fault injection for Cloudflare pairing, websocket and stdio failures."""

from __future__ import annotations

import io
import json
import queue
from types import SimpleNamespace

import pytest
import websocket

from udb import cloud_agent
from udb.cloud_agent import LocalProxy
from udb.cloud_pair import claim_device


def configure_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda _home: ("https://relay.workers.dev", "a" * 32, tmp_path / "token"),
    )
    monkeypatch.setattr(
        cloud_agent, "load_device_token", lambda _home, _device: "x" * 48
    )
    monkeypatch.setattr(
        cloud_agent,
        "LocalProxy",
        lambda _settings: pytest.fail("idle or disconnected relay spawned local proxy"),
    )


def test_agent_disallows_bearer_redirects_on_handshake(monkeypatch, tmp_path):
    configure_agent(monkeypatch, tmp_path)
    attempted = []

    def refused(_url, **options):
        attempted.append(options)
        raise websocket.WebSocketException("network offline")

    monkeypatch.setattr(websocket, "create_connection", refused)
    monkeypatch.setattr(
        cloud_agent.time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    assert cloud_agent.run(SimpleNamespace(home=tmp_path)) == 0
    assert attempted[0]["redirect_limit"] == 0
    assert attempted[0]["header"] == [
        "Authorization: Bearer " + "x" * 48,
        f"User-Agent: {cloud_agent.CLOUD_USER_AGENT}",
    ]


def test_agent_backs_off_immediately_closed_websockets(monkeypatch, tmp_path):
    configure_agent(monkeypatch, tmp_path)
    connections = []

    class ClosedSocket:
        def settimeout(self, timeout):
            assert timeout == cloud_agent._HEARTBEAT_IDLE_SECONDS

        def recv_data_frame(self, control_frame=False):
            assert control_frame is True
            return websocket.ABNF.OPCODE_CLOSE, SimpleNamespace(data=b"")

        def close(self):
            pass

    def connect(*_args, **_kwargs):
        connections.append(True)
        return ClosedSocket()

    monkeypatch.setattr(websocket, "create_connection", connect)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(cloud_agent.time, "sleep", sleep)
    assert cloud_agent.run(SimpleNamespace(home=tmp_path)) == 0
    assert len(connections) == 3
    assert sleeps == [5, 10, 20]


def make_proxy(reply):
    proxy = LocalProxy.__new__(LocalProxy)
    proxy.unusable = False
    proxy.initialized = True
    proxy.process = SimpleNamespace(poll=lambda: None, stdin=io.BytesIO())
    proxy.replies = queue.Queue()
    proxy.replies.put_nowait(reply)
    return proxy


@pytest.mark.parametrize(
    "reply",
    [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": True, "result": {}},
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}},
        {"jsonrpc": "1.0", "id": 1, "result": {}},
    ],
)
def test_proxy_disallows_inconsistent_replies_without_retry(reply):
    proxy = make_proxy(reply)
    with pytest.raises(RuntimeError, match="invalid RPC reply"):
        proxy.call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert proxy.unusable is True
    assert proxy.process.stdin.getvalue().count(b"tools/list") == 1


def test_proxy_accepts_matching_reply():
    response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    proxy = make_proxy(response)
    assert proxy.call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) == response
    assert proxy.unusable is False


def test_dispatched_timeout_poisons_proxy_and_cannot_repeat_the_call(monkeypatch):
    monkeypatch.setattr(cloud_agent.time, "monotonic", lambda: 100.0)
    proxy = make_proxy(None)
    proxy.replies = queue.Queue()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "read_file", "arguments": {}},
    }
    with pytest.raises(TimeoutError, match="Outcome unknown"):
        proxy.call(request, timeout=0.01)
    sent = proxy.process.stdin.getvalue()
    with pytest.raises(RuntimeError, match="unavailable"):
        proxy.call(request)
    assert proxy.process.stdin.getvalue() == sent and sent.count(b"tools/call") == 1


def bootstrapping_proxy(initialization=None, clock=None):
    proxy = make_proxy(None)
    proxy.initialized = False
    proxy.replies = queue.Queue()

    class DeviceInput(io.BytesIO):
        def write(self, wire):
            result = super().write(wire)
            rpc = json.loads(wire)
            if "id" in rpc:
                payload = (
                    initialization
                    if rpc["method"] == "initialize"
                    else {"result": {"tools": []}}
                )
                proxy.replies.put_nowait(
                    dict(
                        jsonrpc="2.0",
                        id=rpc["id"],
                        **(payload or {"result": {"protocolVersion": "2025-11-25"}}),
                    )
                )
                if clock is not None and rpc["method"] == "initialize":
                    clock[0] += 5
            return result

    proxy.process.stdin = DeviceInput()
    return proxy


def test_fresh_proxy_bootstraps_before_resumed_call_and_notifies_once():
    proxy = bootstrapping_proxy()
    for ident in (1, 2):
        result = proxy.call({"jsonrpc": "2.0", "id": ident, "method": "tools/list"})
        assert result["id"] == ident
    sent = [json.loads(line) for line in proxy.process.stdin.getvalue().splitlines()]
    assert [rpc["method"] for rpc in sent] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/list",
    ]
    assert sent[0]["id"] not in (1, 2)


@pytest.mark.parametrize(
    "initialization",
    [
        {"error": {"code": -32000, "message": "private"}},
        {"result": {"protocolVersion": "unsupported"}},
        {"result": {}},
    ],
)
def test_bootstrap_failure_never_dispatches_the_call(initialization):
    proxy = bootstrapping_proxy(initialization)
    with pytest.raises(RuntimeError, match="initialization rejected"):
        proxy.call(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "read_file", "arguments": {}},
            }
        )
    assert b"tools/call" not in proxy.process.stdin.getvalue() and proxy.unusable


def test_bootstrap_and_rpc_share_one_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(cloud_agent.time, "monotonic", lambda: clock[0])
    proxy = bootstrapping_proxy(clock=clock)
    with pytest.raises(TimeoutError, match="before dispatch"):
        proxy.call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=1)
    assert b"tools/list" not in proxy.process.stdin.getvalue()


def test_pairing_network_timeout_never_writes_local_credentials(tmp_path):
    class Offline:
        def open(self, _request, timeout):
            assert timeout == 20
            raise TimeoutError("connection reset after claim")

    with pytest.raises(RuntimeError, match="outcome unknown"):
        claim_device(
            tmp_path,
            "https://example.workers.dev",
            "a" * 32,
            "b" * 64,
            opener=Offline(),
        )
    assert not (tmp_path / "cloud-pairing.json").exists()
    assert not (tmp_path / "cloud-device-token").exists()
