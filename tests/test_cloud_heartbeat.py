"""Fail-closed Cloudflare WebSocket heartbeat regression tests.

These simulate socket frames only; no live credentials or remote actions.
"""
from types import SimpleNamespace

import pytest
import websocket

from udb import cloud_agent


class FakeSocket:
    def __init__(self, events):
        self.events = list(events)
        self.timeouts = []
        self.pings = []
        self.reads = 0

    def settimeout(self, value):
        self.timeouts.append(value)

    def ping(self, payload):
        self.pings.append(payload)

    def recv_data_frame(self, control_frame=False):
        assert control_frame is True
        self.reads += 1
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def frame(opcode, data=b""):
    return opcode, SimpleNamespace(data=data)


def timed_out():
    return websocket.WebSocketTimeoutException("simulated idle timeout")


def test_text_frame_does_not_ping():
    socket = FakeSocket([frame(websocket.ABNF.OPCODE_TEXT, b'{"kind":"rpc"}')])
    assert cloud_agent.receive_relay_text(socket, websocket) == '{"kind":"rpc"}'
    assert socket.pings == []
    assert socket.timeouts == [cloud_agent._HEARTBEAT_IDLE_SECONDS]


def test_idle_ping_matching_pong_recovers_and_reads_rpc():
    socket = FakeSocket([
        timed_out(),
        frame(websocket.ABNF.OPCODE_PONG, cloud_agent._HEARTBEAT_PAYLOAD),
        frame(websocket.ABNF.OPCODE_TEXT, b'{"kind":"rpc"}'),
    ])
    assert cloud_agent.receive_relay_text(socket, websocket) == '{"kind":"rpc"}'
    assert socket.pings == [cloud_agent._HEARTBEAT_PAYLOAD]
    assert socket.timeouts == [
        cloud_agent._HEARTBEAT_IDLE_SECONDS,
        cloud_agent._HEARTBEAT_PONG_SECONDS,
        cloud_agent._HEARTBEAT_IDLE_SECONDS,
    ]


def test_absent_pong_raises_for_reconnect_and_never_replays():
    socket = FakeSocket([timed_out(), timed_out()])
    with pytest.raises(websocket.WebSocketTimeoutException):
        cloud_agent.receive_relay_text(socket, websocket)
    assert socket.pings == [cloud_agent._HEARTBEAT_PAYLOAD]
    assert socket.reads == 2


def test_unmatched_pong_is_not_liveness_confirmation():
    socket = FakeSocket([
        timed_out(),
        frame(websocket.ABNF.OPCODE_PONG, b"unrelated"),
        timed_out(),
    ])
    with pytest.raises(websocket.WebSocketTimeoutException):
        cloud_agent.receive_relay_text(socket, websocket)
    assert socket.pings == [cloud_agent._HEARTBEAT_PAYLOAD]


def test_unsolicited_pong_does_not_disable_heartbeat():
    socket = FakeSocket([
        frame(websocket.ABNF.OPCODE_PONG, cloud_agent._HEARTBEAT_PAYLOAD),
        timed_out(), timed_out(),
    ])
    with pytest.raises(websocket.WebSocketTimeoutException):
        cloud_agent.receive_relay_text(socket, websocket)
    assert socket.pings == [cloud_agent._HEARTBEAT_PAYLOAD]


def test_remote_close_is_not_dispatched_as_rpc():
    socket = FakeSocket([frame(websocket.ABNF.OPCODE_CLOSE)])
    assert cloud_agent.receive_relay_text(socket, websocket) is None
    assert socket.pings == []


@pytest.mark.parametrize("opcode", [
    websocket.ABNF.OPCODE_BINARY, websocket.ABNF.OPCODE_CONT
])
def test_binary_and_invalid_opcode_fail_closed(opcode):
    socket = FakeSocket([frame(opcode, b"private")])
    with pytest.raises(websocket.WebSocketProtocolException):
        cloud_agent.receive_relay_text(socket, websocket)


def test_invalid_utf8_fails_closed():
    socket = FakeSocket([frame(websocket.ABNF.OPCODE_TEXT, b"\xff")])
    with pytest.raises(websocket.WebSocketProtocolException):
        cloud_agent.receive_relay_text(socket, websocket)


def test_server_ping_is_ignored_then_text_is_processed():
    socket = FakeSocket([
        frame(websocket.ABNF.OPCODE_PING, b"health"),
        frame(websocket.ABNF.OPCODE_TEXT, b"{}"),
    ])
    assert cloud_agent.receive_relay_text(socket, websocket) == "{}"
