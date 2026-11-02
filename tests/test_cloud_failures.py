"""Offline fault injection for Cloudflare pairing, websocket and stdio failures."""

from __future__ import annotations

import io
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
    assert attempted[0]["header"] == ["Authorization: Bearer " + "x" * 48]


def test_agent_backs_off_immediately_closed_websockets(monkeypatch, tmp_path):
    configure_agent(monkeypatch, tmp_path)
    connections = []

    class ClosedSocket:
        def settimeout(self, timeout):
            assert timeout is None

        def recv(self):
            return ""

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
