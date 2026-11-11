"""The single start command reuses choices without prompting automation."""

import io
import json
from types import SimpleNamespace

import pytest

from udb import cli, config, onboarding, owner_command
from udb.config import Settings


class Console(io.StringIO):
    def isatty(self):
        return True


def route(monkeypatch, *, interactive=True):
    monkeypatch.setattr(onboarding, "attended_console", lambda: interactive)
    monkeypatch.setattr(onboarding, "os", SimpleNamespace(name="nt"))
    stream = Console if interactive else io.StringIO
    monkeypatch.setattr(onboarding.sys, "stdin", stream())
    monkeypatch.setattr(onboarding.sys, "stdout", stream())
    calls, setups = [], []
    monkeypatch.setattr(owner_command, "main", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(
        onboarding,
        "setup_cloud",
        lambda settings: setups.append(settings) or 0,
    )
    return calls, setups


def test_first_interactive_start_opens_setup_without_creating_home(
    tmp_path, monkeypatch
):
    calls, setups = route(monkeypatch)
    home = tmp_path / "first run"
    previous = config._active
    assert cli.main(["start", "--home", str(home)]) == 0
    assert len(calls) == 1 and "--offline" in calls[0]
    assert len(setups) == 1 and setups[0].home == home
    assert config._active is previous and not home.exists()


@pytest.mark.parametrize("flags", [["--json"], ["--detach"], ["--access", "computer"]])
def test_explicit_machine_or_owner_commands_never_enter_automatic_setup(
    tmp_path, monkeypatch, flags
):
    calls, setups = route(monkeypatch)
    home = tmp_path / "no prompts"
    assert cli.main(["start", "--home", str(home), *flags]) == 0
    assert len(calls) == 1 and not setups and not home.exists()


def test_redirected_start_never_enters_setup(tmp_path, monkeypatch):
    calls, setups = route(monkeypatch, interactive=False)
    home = tmp_path / "redirected"
    assert cli.main(["start", "--home", str(home)]) == 0
    assert len(calls) == 1 and not setups and not home.exists()


def test_old_tunnel_metadata_never_selects_a_connection(tmp_path, monkeypatch):
    calls, setups = route(monkeypatch)
    home = tmp_path / "existing"
    (home / "state").mkdir(parents=True)
    data = json.dumps({"tunnel_id": "tunnel_" + "a" * 32})
    connection = home / "state/connection.json"
    connection.write_text(data)
    assert cli.main(["start", "--home", str(home)]) == 0
    assert len(calls) == 1 and setups and "--offline" in calls[0]
    assert connection.read_text() == data


def test_offline_choice_is_reused_even_by_machine_readable_start(tmp_path, monkeypatch):
    calls, setups = route(monkeypatch, interactive=False)
    home = tmp_path / "local"
    settings = Settings(home, home / "workspace")
    onboarding.save_mode(settings, "offline")
    assert cli.main(["start", "--home", str(home), "--json"]) == 0
    assert len(calls) == 1 and "--offline" in calls[0] and not setups
    assert onboarding.saved_mode(settings) == "offline"
    assert not (home / "state/connection.json").exists()
    assert not (home / "state/computer-access.dpapi").exists()


def test_explicit_offline_start_can_bypass_a_damaged_preference(tmp_path, monkeypatch):
    calls, setups = route(monkeypatch)
    home = tmp_path / "local"
    (home / "state").mkdir(parents=True)
    preference = home / "state/startup-preferences.json"
    preference.write_text("damaged")
    assert cli.main(["start", "--home", str(home), "--offline"]) == 0
    assert "--offline" in calls[0] and not setups
    assert preference.read_text() == "damaged"


def test_invalid_saved_mode_does_not_start_online_or_echo_its_content(
    tmp_path, monkeypatch, capsys
):
    calls, setups = route(monkeypatch)
    home = tmp_path / "invalid"
    (home / "state").mkdir(parents=True)
    data = '{"schema":1,"mode":"SYNTHETIC_PRIVATE_VALUE"}'
    preference = home / "state/startup-preferences.json"
    preference.write_text(data)
    assert cli.main(["start", "--home", str(home), "--json"]) == 0
    assert not setups and "--offline" in calls[0]
    assert preference.read_text() == data
    assert "SYNTHETIC_PRIVATE_VALUE" not in capsys.readouterr().err


def test_setup_routes_only_to_cloudflare_pairing(tmp_path, monkeypatch):
    calls, setups = route(monkeypatch)
    assert cli.main(["setup", "--home", str(tmp_path), "--edit"]) == 0
    assert not calls and setups[0].home == tmp_path
    with pytest.raises(SystemExit) as exc:
        cli.main(["setup", "--home", str(tmp_path), "--local"])
    assert exc.value.code == 2


def test_canceling_first_run_restores_settings_and_creates_nothing(
    tmp_path, monkeypatch, capsys
):
    calls, setups = route(monkeypatch)

    def cancel(settings):
        raise KeyboardInterrupt()

    monkeypatch.setattr(onboarding, "setup_cloud", cancel)
    home = tmp_path / "cancelled"
    previous = config._active
    assert cli.main(["start", "--home", str(home)]) == 130
    assert not home.exists() and not calls and config._active is previous
    assert "Setup canceled" in capsys.readouterr().err


def test_paired_device_uses_cloudflare_despite_old_offline_preference(
    tmp_path, monkeypatch
):
    calls, setups = route(monkeypatch)
    home = tmp_path / "active"
    settings = Settings(home, home / "workspace")
    onboarding.save_mode(settings, "offline")
    (home / "cloud-pairing.json").write_text(
        json.dumps(
            {
                "relay": "https://example.workers.dev",
                "device_id": "a" * 32,
            }
        )
    )
    assert cli.main(["start", "--home", str(home)]) == 0
    assert not setups and "--offline" not in calls[-1]
    assert onboarding.saved_mode(settings) == "offline"


def test_live_and_mcp_config_use_one_paired_endpoint(tmp_path, monkeypatch, capsys):
    (tmp_path / "cloud-pairing.json").write_text(
        json.dumps(
            {
                "relay": "https://example.workers.dev/",
                "device_id": "a" * 32,
            }
        )
    )
    endpoint = "https://example.workers.dev/v1/devices/" + "a" * 32 + "/mcp"
    assert cli.main(["mcp-config", "--home", str(tmp_path)]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["mcpServers"]["universal-desktop-bridge"] == {
        "type": "streamable-http",
        "url": endpoint,
    }
    calls = []
    monkeypatch.setattr(
        "webbrowser.open", lambda url, **options: calls.append(url) or True
    )
    assert cli.main(["live", "--home", str(tmp_path)]) == 0
    assert calls == [endpoint + "?view=live"]
    assert not (tmp_path / "state").exists()


def test_offline_agent_from_an_older_release_needs_no_new_setup(tmp_path, monkeypatch):
    calls, setups = route(monkeypatch)
    monkeypatch.setattr(
        owner_command, "headless_state", lambda _: {"connection_mode": "offline"}
    )
    home = tmp_path / "older"
    assert cli.main(["start", "--home", str(home)]) == 0
    assert not setups and "--offline" in calls[-1]
    assert not home.exists()
