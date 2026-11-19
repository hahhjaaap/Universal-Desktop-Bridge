"""Reply mailbox notification must be armed before publishing host commands."""

import json
import threading
from types import SimpleNamespace

import pytest

from udb import host_client
from udb.core import PolicyError


@pytest.fixture
def owned(tmp_path, monkeypatch):
    state = tmp_path / "state"
    inbox = state / "host" / "inbox"
    replies = state / "host" / "replies"
    inbox.mkdir(parents=True)
    replies.mkdir()
    monkeypatch.setattr(
        host_client,
        "status",
        lambda _agent: {"worker_ready": True, "enabled": True, "sessions": []},
    )
    return SimpleNamespace(state=state), inbox, replies


def test_reply_listener_armed_before_command_publish_and_closed(owned, monkeypatch):
    agent, inbox, replies = owned
    events = []

    class FakeWake:
        def __init__(self, directory):
            assert directory == replies
            assert not list(inbox.iterdir()), "arm before command publish to avoid lost reply"
            events.append("armed")

        def wait(self, timeout, stop_event):
            assert isinstance(stop_event, threading.Event)
            assert 0 < timeout <= 0.04
            events.append("woke")
            requests = list(inbox.glob("*.json"))
            assert len(requests) == 1
            rid = json.loads(requests[0].read_text())["id"]
            host_client.atomic_json(
                replies / (rid + ".json"), {"ok": True, "result": {"clicked": True}}
            )
            return True

        def close(self):
            events.append("closed")

    monkeypatch.setattr(host_client, "InboxWake", FakeWake)
    result = host_client.command(agent, "browser", action="read", session_id="fake")
    assert result == {"clicked": True}
    assert events == ["armed", "woke", "closed"]


def test_reply_wake_does_not_override_worker_failure_or_retry(owned, monkeypatch):
    agent, inbox, replies = owned
    events = []
    submitted = []

    class FakeWake:
        def __init__(self, directory):
            assert directory == replies

        def wait(self, timeout, stop_event):
            requests = list(inbox.glob("*.json"))
            assert len(requests) == 1
            rid = json.loads(requests[0].read_text())["id"]
            submitted.append(rid)
            host_client.atomic_json(
                replies / (rid + ".json"),
                {"ok": False, "error": "Host operation failed; inspect status"},
            )
            events.append("woke")

        def close(self):
            events.append("closed")

    monkeypatch.setattr(host_client, "InboxWake", FakeWake)
    with pytest.raises(PolicyError, match="Host operation failed"):
        host_client.command(agent, "browser", action="click")
    assert len(submitted) == 1 and events == ["woke", "closed"]


def test_reply_listener_closed_when_publish_fails(owned, monkeypatch):
    agent, _, replies = owned
    closed = []

    class FakeWake:
        def __init__(self, directory):
            assert directory == replies

        def wait(self, timeout, stop_event):
            pytest.fail("A rejected command must not wait")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(host_client, "InboxWake", FakeWake)
    monkeypatch.setattr(
        host_client,
        "atomic_json",
        lambda *_: (_ for _ in ()).throw(OSError("write refused")),
    )
    with pytest.raises(OSError, match="write refused"):
        host_client.command(agent, "browser", action="read")
    assert closed == [True]
