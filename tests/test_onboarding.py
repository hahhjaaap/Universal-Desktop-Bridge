"""Cloudflare-only setup requires owner-attended pairing and no Tunnel key."""

import io
import json
import os
from types import SimpleNamespace

import pytest

from udb import cli, cloud_pair, onboarding, owner_command
from udb.config import Settings


class Console(io.StringIO):
    def isatty(self):
        return True


def attended(monkeypatch, answers):
    monkeypatch.setattr(onboarding, "console_input", lambda: True)
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    monkeypatch.setattr(owner_command, "headless_state", lambda _: None)
    calls = []
    monkeypatch.setattr(owner_command, "main", lambda args: calls.append(args) or 0)
    return calls


def make_paired(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "cloud-pairing.json").write_text(
        json.dumps({
            "relay": "https://udb-example.workers.dev",
            "device_id": "a" * 32,
        }),
        encoding="utf-8",
    )


def test_redirected_setup_cannot_prompt_or_create_state(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "console_input", lambda: False)
    home = tmp_path / "unused"
    with pytest.raises(ValueError, match="attended"):
        onboarding.run(Settings(home, home / "work"))
    assert not home.exists()


def test_cli_rejects_unattended_setup_json_before_writing(tmp_path):
    home = tmp_path / "unused"
    assert cli.main(["--json", "setup", "--home", str(home)]) == 2
    assert not home.exists()


def test_missing_pairing_can_cancel_without_credentials(tmp_path, monkeypatch):
    calls = attended(monkeypatch, ["n"])
    home = tmp_path / "owner"
    assert onboarding.run(Settings(home, home / "work")) == 0
    assert calls == []
    assert not (home / "cloud-pairing.json").exists()


def test_owner_pairing_uses_cloud_invitation_not_runtime_key(tmp_path, monkeypatch, capsys):
    calls = attended(monkeypatch, ["y", "n"])
    home = tmp_path / "owner"
    pairing = []

    def pair(settings):
        pairing.append(settings.home)
        make_paired(settings.home)
        return 0

    monkeypatch.setattr(cloud_pair, "run", pair)
    assert onboarding.run(Settings(home, home / "work")) == 0
    assert pairing == [home]
    assert [call[0] for call in calls] == ["start"]
    assert "--offline" not in calls[-1]
    assert "OpenAI Tunnel ID" in capsys.readouterr().out
    assert not (home / "state/connection.json").exists()


def test_existing_paired_device_is_reused_without_new_invitation(tmp_path, monkeypatch):
    calls = attended(monkeypatch, ["n"])
    home = tmp_path / "owner"
    make_paired(home)
    monkeypatch.setattr(
        cloud_pair, "run", lambda _: pytest.fail("must not claim another device")
    )
    assert onboarding.run(Settings(home, home / "work")) == 0
    assert calls and calls[-1][0] == "start"
    assert onboarding.saved_connection(Settings(home, home / "work")) == "a" * 32


def test_edit_does_not_overwrite_an_existing_cloud_device(tmp_path, monkeypatch):
    calls = attended(monkeypatch, [])
    home = tmp_path / "owner"
    make_paired(home)
    original = (home / "cloud-pairing.json").read_bytes()
    assert onboarding.run(Settings(home, home / "work"), edit=True) == 0
    assert (home / "cloud-pairing.json").read_bytes() == original
    assert not calls


def test_invalid_pairing_is_not_treated_as_connected(tmp_path):
    home = tmp_path / "owner"
    make_paired(home)
    (home / "cloud-pairing.json").write_text('{"relay":"http://evil.invalid"}')
    assert onboarding.saved_connection(Settings(home, home / "work")) is None


def test_offline_diagnostics_never_pair_or_start_cloud(tmp_path, monkeypatch):
    calls = attended(monkeypatch, [])
    home = tmp_path / "owner"
    settings = Settings(home, home / "work")
    assert onboarding.run(settings, local=True) == 0
    assert [call[0] for call in calls] == ["start"]
    assert "--offline" in calls[-1]
    assert onboarding.saved_mode(settings) == "offline"
    assert not (home / "cloud-pairing.json").exists()


def test_switching_from_cloud_to_offline_stops_old_manager(tmp_path, monkeypatch):
    calls = attended(monkeypatch, [])
    home = tmp_path / "owner"
    make_paired(home)
    monkeypatch.setattr(
        owner_command, "headless_state",
        lambda _: {"connection_mode": "online"},
    )
    assert onboarding.run(Settings(home, home / "work"), local=True) == 0
    assert [args[0] for args in calls] == ["stop", "start"]


def test_failed_stop_preserves_owner_startup_mode(tmp_path, monkeypatch):
    calls = attended(monkeypatch, [])
    home = tmp_path / "owner"
    settings = Settings(home, home / "work")
    onboarding.save_mode(settings, "online")
    monkeypatch.setattr(
        owner_command, "headless_state",
        lambda _: {"connection_mode": "online"},
    )
    monkeypatch.setattr(owner_command, "main", lambda args: calls.append(args) or 1)
    with pytest.raises(ValueError, match="did not stop"):
        onboarding.run(settings, local=True)
    assert [call[0] for call in calls] == ["stop"]
    assert onboarding.saved_mode(settings) == "online"


@pytest.mark.parametrize("options", [{"edit": True}, {"local": True}])
def test_alternate_setup_modes_refuse_redirected_input(tmp_path, monkeypatch, options):
    monkeypatch.setattr(onboarding, "console_input", lambda: False)
    home = tmp_path / "unused"
    with pytest.raises(ValueError, match="attended"):
        onboarding.run(Settings(home, home / "work"), **options)
    assert not home.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows console API")
def test_windows_nul_is_not_an_attended_console():
    with open(os.devnull) as stream:
        assert onboarding._console_stream(stream) is False


def test_setup_links_to_plugins_not_legacy_tunnels():
    assert onboarding.CHATGPT_URL == "https://chatgpt.com/plugins"
    assert not hasattr(onboarding, "TUNNELS_URL")
    assert not hasattr(onboarding, "KEYS_URL")
