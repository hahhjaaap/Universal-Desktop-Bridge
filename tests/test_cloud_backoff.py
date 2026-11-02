"""Cloud reconnects back off and never spawn a local MCP worker while offline."""

from types import SimpleNamespace

import pytest
import websocket

from udb import cloud_agent


def test_offline_agent_has_bounded_backoff_and_no_idle_proxy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda home: ("https://example.workers.dev", "a" * 32, tmp_path / "token"),
    )
    monkeypatch.setattr(
        cloud_agent, "load_device_token", lambda home, device_id: "x" * 48
    )

    def unreachable(*_args, **_kwargs):
        raise websocket.WebSocketException("offline")

    monkeypatch.setattr(websocket, "create_connection", unreachable)
    monkeypatch.setattr(
        cloud_agent, "LocalProxy", lambda _settings: pytest.fail("proxy spawned idle")
    )
    sleeps = []

    def stop_after_three(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(cloud_agent.time, "sleep", stop_after_three)
    assert cloud_agent.run(SimpleNamespace(home=tmp_path)) == 0
    assert sleeps == [5, 10, 20]
