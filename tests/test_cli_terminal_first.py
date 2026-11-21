"""Human-friendly terminal operations without breaking scripts or safety checks."""

import argparse
import io
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from udb import cli, connection, host_client, onboarding, owner_command


def test_installer_probe_observes_only_the_selected_cloud_agent(tmp_path, capsys):
    home = tmp_path.resolve()
    args = ["status", "--home", str(home), "--cloud-agent-lease", "--json"]
    with owner_command.launch_gate(home / "other-profile" / "cloud-agent"):
        assert cli.main(args) == 0
    assert capsys.readouterr().out == '{"cloud_agent_lease_held": false}\n'

    with owner_command.launch_gate(home / "cloud-agent"):
        assert cli.main(args) == 0
    assert capsys.readouterr().out == '{"cloud_agent_lease_held": true}\n'
    assert not (home / "state").exists()


def test_old_installer_cannot_switch_a_paired_profile_with_a_separate_agent(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "program"
    active = root / "releases" / ("a" * 24) / "udb.exe"
    candidate = root / "releases" / ("b" * 24) / "udb.exe"
    for image in (active, candidate):
        image.parent.mkdir(parents=True)
        image.touch()
    home = tmp_path.resolve() / "data"
    (root / "install.json").write_text(
        json.dumps(
            {
                "product": "UniversalDesktopBridge",
                "schema": 1,
                "version": "0.13.0",
                "archive_sha256": "a" * 64,
                "home": str(home),
                "exe": str(active),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(candidate))
    monkeypatch.setattr(onboarding, "paired_cloud", lambda _: True)
    monkeypatch.setattr(
        connection, "cloud_mcp_url", lambda _: "https://relay.example/mcp"
    )
    args = ["--home", str(home), "mcp-config"]
    with owner_command.launch_gate(home / "cloud-agent"):
        assert cli.main(args) == 2
        assert "A separate Cloud Agent" in capsys.readouterr().err
        monkeypatch.setattr(sys, "executable", str(active))
        assert cli.main(args) == 0
        capsys.readouterr()
    monkeypatch.setattr(sys, "executable", str(candidate))
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["mcpServers"]


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_background_cli_enables_and_revokes_the_live_worker_setting(
    tmp_path, monkeypatch, capsys
):
    args = ["background", "--home", str(tmp_path)]
    agent = SimpleNamespace(state=tmp_path / "state")
    monkeypatch.setattr(onboarding, "attended_console", lambda: True)

    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert cli.main([*args, "enable"]) == 2
    assert not agent.state.exists()

    def confirm(prompt):
        assert "ALLOW BACKGROUND" in prompt
        return "ALLOW BACKGROUND"

    monkeypatch.setattr("builtins.input", confirm)
    assert cli.main([*args, "enable"]) == 0
    assert host_client.enabled(agent)
    capsys.readouterr()
    assert cli.main([*args, "status", "--json"]) == 0
    assert capsys.readouterr().out == '{"background": "unavailable"}\n'

    assert cli.main([*args, "disable"]) == 0
    assert not host_client.enabled(agent)
    capsys.readouterr()
    assert cli.main([*args, "status", "--json"]) == 0
    assert capsys.readouterr().out == '{"background": "disabled"}\n'


@pytest.mark.parametrize("operation", ["enable", "disable"])
def test_background_cli_refuses_unattended_grant_changes(
    operation, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(onboarding, "attended_console", lambda: False)
    assert cli.main(["background", operation, "--home", str(tmp_path)]) == 2
    assert "your own local Windows terminal" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_background_cli_rejects_redirected_confirmation(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "udb",
            "background",
            "enable",
            "--home",
            str(tmp_path),
        ],
        input="ALLOW BACKGROUND\n",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2, result.stderr
    assert "your own local Windows terminal" in result.stderr
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    ("preferences", "resources", "expected"),
    [
        ({"enabled": True, "padding": " " * 4096}, {}, "invalid_settings"),
        ({"enabled": True, "other": float("nan")}, {}, "invalid_settings"),
        ({"enabled": True}, {"cpu_percent": None}, "unavailable"),
        ({"enabled": True}, {"at": 10**500}, "unavailable"),
    ],
)
def test_background_cli_does_not_report_false_readiness(
    tmp_path, capsys, preferences, resources, expected
):
    state = tmp_path / "state"
    (state / "host").mkdir(parents=True)
    host_client.atomic_json(state / "host-settings.json", preferences)
    resource_status = {
        "at": time.time(),
        "paused": False,
        "admission_ready": resources.get("cpu_percent", 20) is not None,
        **resources,
    }
    host_client.atomic_json(
        state / "host" / "status.json",
        {"worker_ready": True, "resources": resource_status},
    )
    assert cli.main(["background", "status", "--home", str(tmp_path), "--json"]) == 0
    assert capsys.readouterr().out == f'{{"background": "{expected}"}}\n'


@pytest.mark.parametrize(
    ("action", "token"),
    [("update", "UPDATE"), ("rollback", "ROLLBACK")],
)
def test_attended_maintenance_requires_exact_confirmation(action, token):
    args = argparse.Namespace(json=False, yes=False, check=False)
    output = TTY()
    assert not cli._confirm_attended_maintenance(
        action, args, incoming=TTY("y\n"), outgoing=output
    )
    assert f"Type {token}" in output.getvalue()
    assert cli._confirm_attended_maintenance(
        action, args, incoming=TTY(token + "\n"), outgoing=TTY()
    )


@pytest.mark.parametrize("action", ["update", "rollback"])
def test_old_machine_automation_is_not_forced_into_new_prompt(action):
    # Preserve the existing noninteractive/json command contracts.
    args = argparse.Namespace(json=False, yes=False, check=False)
    output = TTY()
    assert cli._confirm_attended_maintenance(
        action, args, incoming=io.StringIO(""), outgoing=output
    )
    assert output.getvalue() == ""
    args.json = True
    assert cli._confirm_attended_maintenance(
        action, args, incoming=TTY(), outgoing=output
    )
    args.json = False
    args.yes = True
    assert cli._confirm_attended_maintenance(
        action, args, incoming=TTY(), outgoing=output
    )
    assert output.getvalue() == ""


def test_checking_for_updates_never_demands_confirmation():
    args = argparse.Namespace(check=True, json=False, yes=False)
    output = TTY()
    assert cli._confirm_attended_maintenance(
        "update", args, incoming=TTY(), outgoing=output
    )
    assert output.getvalue() == ""


@pytest.mark.parametrize("action", ["update", "rollback"])
def test_cancelled_attended_change_never_calls_updater(action, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        cli, "_confirm_attended_maintenance", lambda command, args: False
    )
    monkeypatch.setattr(
        cli,
        "_run_maintenance",
        lambda *args, **kwargs: pytest.fail("cancelled action ran the updater"),
    )
    assert cli.main([action]) == 2
    assert "Cancelled" in capsys.readouterr().err


def test_vietnamese_help_does_not_load_state(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "load", lambda **kwargs: pytest.fail("help must not load settings")
    )
    assert cli.main(["help", "vi"]) == 0
    output = capsys.readouterr().out
    for phrase in ("udb start", "udb stop", "udb doctor", "udb help advanced"):
        assert phrase in output
    assert "Ghép nối" in output


@pytest.mark.parametrize(
    ("typo", "suggestion"),
    [("statu", "status"), ("doctro", "doctor"), ("rolback", "rollback")],
)
def test_command_typo_suggests_closest_entry_without_loading_state(
    typo, suggestion, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "load", lambda **kwargs: pytest.fail("typo must not load settings")
    )
    with pytest.raises(SystemExit) as exited:
        cli.main([typo])
    assert exited.value.code == 2
    error = capsys.readouterr().err
    assert f"udb {suggestion}" in error
    assert "udb help" in error
    assert "choose from" not in error


def test_old_command_help_includes_explicit_opt_in_for_maintenance(capsys):
    for action in ("update", "rollback"):
        with pytest.raises(SystemExit) as exited:
            cli.main([action, "--help"])
        assert exited.value.code == 0
        assert "--yes" in capsys.readouterr().out
