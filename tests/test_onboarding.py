"""Cloudflare-only attended setup and read-only legacy state regressions."""

import json
import os
from types import SimpleNamespace

import pytest

from udb import cli, cloud_agent, cloud_pair, connection, onboarding, owner_command
from udb.config import Settings


def settings(tmp_path):
    home = tmp_path / "owner"
    return Settings(home, home / "work")


def test_setup_json_is_refused_before_any_state_write(tmp_path):
    home = tmp_path / "unused"
    assert cli.main(["--json", "setup", "--home", str(home)]) == 2
    assert not home.exists()


def test_public_setup_dispatches_only_cloudflare_without_state_write(
    tmp_path, monkeypatch
):
    selected = settings(tmp_path)
    calls = []
    monkeypatch.setattr(
        onboarding, "setup_cloud", lambda candidate: calls.append(candidate) or 0
    )
    args = SimpleNamespace(json=False, access=None, offline=False, online=False)
    assert cli._run_setup(args, selected) == 0
    assert calls == [selected]
    assert not selected.home.exists()


def test_redirected_cloud_setup_refuses_before_pairing_or_state_write(
    tmp_path, monkeypatch
):
    selected = settings(tmp_path)
    monkeypatch.setattr(onboarding, "console_input", lambda: False)
    monkeypatch.setattr(
        cloud_pair,
        "run",
        lambda *_: pytest.fail("Non-attended setup may not pair"),
    )
    with pytest.raises(ValueError, match="attended"):
        onboarding.setup_cloud(selected)
    assert not selected.home.exists()


def test_cloud_pair_cancellation_does_not_fall_back_to_tunnel(tmp_path, monkeypatch):
    selected = settings(tmp_path)
    monkeypatch.setattr(onboarding, "console_input", lambda: True)
    monkeypatch.setattr(onboarding, "paired_cloud", lambda _: None)
    monkeypatch.setattr(cloud_pair, "run", lambda _: 130)
    assert onboarding.setup_cloud(selected) == 130
    assert not selected.home.exists()


def test_existing_cloud_pairing_preserves_legacy_state_without_key_prompt(
    tmp_path, monkeypatch, capsys
):
    selected = settings(tmp_path)
    selected.home.mkdir()
    (selected.home / "state").mkdir()
    legacy = selected.home / "state/connection.json"
    legacy_bytes = b'{"tunnel_id":"tunnel_' + b"b" * 32 + b'"}'
    legacy.write_bytes(legacy_bytes)
    pairing = selected.home / "cloud-pairing.json"
    pairing_bytes = (
        b'{"relay":"https://example.workers.dev","device_id":"' + b"a" * 32 + b'"}'
    )
    pairing.write_bytes(pairing_bytes)
    monkeypatch.setattr(onboarding, "console_input", lambda: True)
    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda _: ("https://example.workers.dev", "a" * 32, None),
    )
    monkeypatch.setattr(
        connection,
        "cloud_mcp_url",
        lambda _: "https://example.workers.dev/v1/devices/" + "a" * 32 + "/mcp",
    )
    monkeypatch.setattr(
        cloud_pair,
        "run",
        lambda *_: pytest.fail("Existing paired device may not be re-enrolled"),
    )
    assert onboarding.setup_cloud(selected) == 0
    assert "Cloudflare MCP:" in capsys.readouterr().out
    assert legacy.read_bytes() == legacy_bytes
    assert pairing.read_bytes() == pairing_bytes
    assert not (selected.home / "state/computer-access.dpapi").exists()


def test_malformed_cloud_pairing_never_falls_back_to_legacy_enrollment(
    tmp_path, monkeypatch
):
    selected = settings(tmp_path)
    selected.home.mkdir()
    pairing = selected.home / "cloud-pairing.json"
    pairing.write_text('{"relay":"invalid"}', encoding="utf-8")
    before = pairing.read_bytes()
    monkeypatch.setattr(onboarding, "console_input", lambda: True)
    monkeypatch.setattr(
        cloud_pair,
        "run",
        lambda *_: pytest.fail("Malformed pairing may not prompt for Tunnel"),
    )
    with pytest.raises((ValueError, KeyError, OSError)):
        onboarding.setup_cloud(selected)
    assert pairing.read_bytes() == before


def test_new_cloud_pairing_prints_only_the_scoped_https_endpoint(
    tmp_path, monkeypatch, capsys
):
    selected = settings(tmp_path)
    state = {"paired": False}
    monkeypatch.setattr(onboarding, "console_input", lambda: True)
    monkeypatch.setattr(
        onboarding,
        "paired_cloud",
        lambda _: (
            ("https://example.workers.dev", "a" * 32) if state["paired"] else None
        ),
    )

    def simulate_pair(_):
        state["paired"] = True
        return 0

    monkeypatch.setattr(cloud_pair, "run", simulate_pair)
    monkeypatch.setattr(
        connection,
        "cloud_mcp_url",
        lambda _: "https://example.workers.dev/v1/devices/" + "a" * 32 + "/mcp",
    )
    assert onboarding.setup_cloud(selected) == 0
    output = capsys.readouterr().out
    assert "https://example.workers.dev/v1/devices/" in output
    assert "Tunnel ID" not in output and "Runtime key" not in output
    assert not selected.home.exists()


def test_legacy_connection_reader_is_read_only_and_fails_closed(tmp_path):
    selected = settings(tmp_path)
    state = selected.home / "state"
    state.mkdir(parents=True)
    path = state / "connection.json"
    original = b'{"tunnel_id":"tunnel_' + b"a" * 32 + b'"}'
    path.write_bytes(original)
    assert onboarding.saved_connection(selected) == "tunnel_" + "a" * 32
    assert path.read_bytes() == original

    bad_id = b'{"tunnel_id":"not-a-tunnel"}'
    path.write_bytes(bad_id)
    assert onboarding.saved_connection(selected) is None
    assert path.read_bytes() == bad_id

    broken = b"{bad-json"
    path.write_bytes(broken)
    with pytest.raises(ValueError, match="Saved connection"):
        onboarding.saved_connection(selected)
    assert onboarding.saved_connection(selected, repair=True) is None
    assert path.read_bytes() == broken


def test_startup_preferences_are_preserved_during_legacy_state_reads(tmp_path):
    selected = settings(tmp_path)
    (selected.home / "state").mkdir(parents=True)
    legacy = selected.home / "state/connection.json"
    legacy.write_text('{"tunnel_id":"tunnel_' + "c" * 32 + '"}')
    onboarding.save_mode(selected, "offline")
    assert onboarding.saved_mode(selected) == "offline"
    before = legacy.read_bytes()
    with pytest.raises(ValueError, match="Invalid startup mode"):
        onboarding.save_mode(selected, "invalid")
    assert onboarding.saved_mode(selected) == "offline"
    assert legacy.read_bytes() == before
    saved = json.loads((selected.home / "state/startup-preferences.json").read_text())
    assert saved == {"schema": 1, "mode": "offline"}


def test_explicit_online_without_pairing_is_rejected_not_tunneled(
    tmp_path, monkeypatch
):
    selected = settings(tmp_path)
    monkeypatch.setattr(onboarding, "paired_cloud", lambda _: None)
    args = SimpleNamespace(
        offline=False, online=True, detach=False, json=False, access=None
    )
    with pytest.raises(ValueError, match="Cloudflare"):
        cli._prepare_startup(args, selected)
    assert not selected.home.exists()


def test_unpaired_noninteractive_start_is_local_only(tmp_path, monkeypatch):
    selected = settings(tmp_path)
    monkeypatch.setattr(onboarding, "paired_cloud", lambda _: None)
    monkeypatch.setattr(owner_command, "headless_state", lambda _: None)
    args = SimpleNamespace(
        offline=False, online=False, detach=False, json=True, access=None
    )
    assert cli._prepare_startup(args, selected) is None
    assert args.offline is True
    assert not selected.home.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows console API")
def test_windows_nul_is_not_an_attended_console():
    with open(os.devnull) as stream:
        assert onboarding._console_stream(stream) is False


def test_owner_setup_links_to_chatgpt_plugins():
    assert onboarding.CHATGPT_URL == "https://chatgpt.com/plugins"


def test_paired_cloudflare_default_start_uses_cloud_agent(tmp_path, monkeypatch):
    selected = settings(tmp_path)
    monkeypatch.setattr(
        onboarding,
        "paired_cloud",
        lambda _: ("https://example.workers.dev", "a" * 32),
    )
    monkeypatch.setattr(
        owner_command, "headless_state", lambda _: {"connection_mode": "online"}
    )
    args = SimpleNamespace(
        offline=False, online=False, detach=False, json=False, access=None
    )
    assert cli._prepare_startup(args, selected) is None
    assert args.offline is False


def test_explicit_online_uses_paired_cloudflare_device(tmp_path, monkeypatch):
    selected = settings(tmp_path)
    monkeypatch.setattr(
        onboarding,
        "paired_cloud",
        lambda _: ("https://example.workers.dev", "a" * 32),
    )
    args = SimpleNamespace(
        offline=False, online=True, detach=False, json=False, access=None
    )
    assert cli._prepare_startup(args, selected) is None
    assert args.online is True and args.offline is False
