"""Owner diagnostics must not confuse Cloudflare pairing with legacy Tunnel."""

import json

import pytest

from udb import autostart, components, maintenance, owner_command


@pytest.fixture(autouse=True)
def isolated_doctor(monkeypatch):
    monkeypatch.setattr(
        components,
        "runtime_report",
        lambda: {"components": [], "office_modules": {"office": True}},
    )
    monkeypatch.setattr(
        autostart, "status", lambda *_: {"enabled": False, "matches_current": True}
    )
    monkeypatch.setattr(maintenance, "installation", lambda: None)
    monkeypatch.setattr(owner_command, "headless_state", lambda *_: None)


def report():
    return {
        "manager_running": False,
        "connection_mode": "unknown",
        "local_tunnel_ready": False,
        "next_action": "Run udb",
    }


def checks(home):
    return {x["check"]: x for x in owner_command.doctor(home, report())}


def test_valid_cloud_pairing_does_not_require_legacy_tunnel(tmp_path):
    (tmp_path / "cloud-pairing.json").write_text(
        json.dumps({"relay": "https://example.workers.dev", "device_id": "a" * 32}),
        encoding="utf-8",
    )
    result = checks(tmp_path)
    assert result["connection_configuration"]["ok"] is True
    assert "Cloudflare pairing" in result["connection_configuration"]["action"]
    assert "local_tunnel" not in result
    assert "tunnel_component" not in result
    assert "udb start" in result["chatgpt_session"]["action"]
    assert result["chatgpt_session"]["ok"] is None


def test_malformed_cloud_pairing_fails_closed_without_tunnel_fallback(tmp_path):
    (tmp_path / "cloud-pairing.json").write_text(
        '{"relay":"invalid","device_id":"invalid"}',
        encoding="utf-8",
    )
    result = checks(tmp_path)
    assert result["connection_configuration"]["ok"] is False
    assert "Cloudflare pairing invalid" in result["connection_configuration"]["action"]
    assert "udb setup" in result["chatgpt_session"]["action"]


def test_legacy_tunnel_metadata_does_not_substitute_for_cloud_pairing(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "connection.json").write_text(
        json.dumps({"tunnel_id": "tunnel_" + "a" * 32}), encoding="utf-8"
    )
    result = checks(tmp_path)
    assert result["connection_configuration"]["ok"] is None
    assert "udb setup" in result["connection_configuration"]["action"]
    assert "udb setup" in result["chatgpt_session"]["action"]
