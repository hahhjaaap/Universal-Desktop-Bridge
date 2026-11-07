"""Standalone UDB one-command startup never grants remote/host access."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from udb import cli, onboarding, owner_command, quickstart
from udb.config import Settings
from udb.owner_command import CommandError


def ready(**changes):
    return {
        "manager_running": True,
        "manager_mode": "headless",
        "connection_mode": "offline",
        **changes,
    }


def test_quickstart_returns_fixed_local_only_status_without_writing_grants(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "home"
    root = tmp_path / "project"
    called = []

    monkeypatch.setattr(owner_command, "executable", lambda _: tmp_path / "fake.exe")

    def start(home_path, exe, wait, connect):
        called.append((home_path, exe, wait, connect))
        return ready()

    monkeypatch.setattr(owner_command, "start", start)
    assert (
        cli.main(["quickstart", "--home", str(home), "--root", str(root), "--json"])
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "autostart": "unchanged",
        "chatgpt_remote_verified": False,
        "connection_mode": "offline",
        "local_manager": "running",
        "next_step": "udb mcp-config",
        "result": "local_ready",
    }
    assert called == [(home.resolve(), tmp_path / "fake.exe", 30, False)]
    assert not home.exists(), "Quickstart must not invent grants or pairing"
    assert "token" not in json.dumps(result).lower()
    assert "tunnel" not in json.dumps(result).lower()


def test_quickstart_is_idempotent_and_does_not_stop_an_existing_manager(
    tmp_path, monkeypatch, capsys
):
    settings = Settings(tmp_path / "home", tmp_path / "project")
    starts = []
    monkeypatch.setattr(owner_command, "executable", lambda _: tmp_path / "fake.exe")
    monkeypatch.setattr(
        owner_command,
        "start",
        lambda *a, **kw: starts.append(kw) or ready(),
    )
    for _ in range(2):
        assert quickstart.run(settings, as_json=True) == 0
    assert len(starts) == 2 and all(kw["connect"] is False for kw in starts)
    assert not (settings.home / "cloud-pairing.json").exists()
    assert not (settings.home / "state/startup-preferences.json").exists()
    assert len(capsys.readouterr().out.strip().splitlines()) == 2


@pytest.mark.parametrize(
    "report",
    [
        {
            "manager_running": False,
            "manager_mode": "stopped",
            "connection_mode": "unknown",
        },
        ready(connection_mode="online"),
        ready(manager_mode="legacy_or_unknown"),
    ],
)
def test_quickstart_never_reports_false_local_readiness(
    tmp_path, monkeypatch, capsys, report
):
    monkeypatch.setattr(owner_command, "executable", lambda _: tmp_path / "fake.exe")
    monkeypatch.setattr(owner_command, "start", lambda *a, **kw: report)
    assert quickstart.run(Settings(tmp_path, tmp_path), as_json=True) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "local_manager_not_ready"


def test_quickstart_rejects_existing_online_manager_without_stopping(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(owner_command, "executable", lambda _: tmp_path / "fake.exe")
    monkeypatch.setattr(
        owner_command,
        "start",
        lambda *a, **kw: (_ for _ in ()).throw(
            CommandError("SYNTHETIC_SECRET from active online manager")
        ),
    )
    assert cli.main(["quickstart", "--home", str(tmp_path), "--json"]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["reason"] == "local_configuration_or_mode_error"
    assert "SYNTHETIC_SECRET" not in output


@pytest.mark.parametrize(
    "invalid",
    [
        ["--access", "computer", "quickstart"],
        ["--online", "quickstart"],
        ["--offline", "quickstart"],
    ],
)
def test_quickstart_cannot_activate_owner_or_remote_mode(
    tmp_path, monkeypatch, capsys, invalid
):
    monkeypatch.setattr(
        owner_command,
        "start",
        lambda *a, **kw: pytest.fail("must reject before starting manager"),
    )
    assert cli.main([*invalid, "--home", str(tmp_path)]) == 2
    assert not (tmp_path / "state").exists()
    assert "local-only" in capsys.readouterr().err


def test_autostart_is_explicit_windows_only_and_local_profile_only(
    tmp_path, monkeypatch, capsys
):
    settings = Settings(tmp_path / "home", tmp_path / "project")
    monkeypatch.setattr(quickstart, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(onboarding, "paired_cloud", lambda home: ("relay", "device"))
    monkeypatch.setattr(
        owner_command,
        "start",
        lambda *a, **kw: pytest.fail("must not touch paired manager"),
    )
    assert quickstart.run(settings, enable_autostart=True, as_json=True) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == (
        "remote_profile_requires_setup"
    )
    assert not settings.home.exists()


def test_quickstart_autostart_opt_in_is_explicit_and_does_not_enable_remote(
    tmp_path, monkeypatch, capsys
):
    from udb import autostart

    home = tmp_path / "home"
    settings = Settings(home, tmp_path / "work")
    called = []
    monkeypatch.setattr(quickstart, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(onboarding, "paired_cloud", lambda _: None)
    monkeypatch.setattr(owner_command, "executable", lambda _: tmp_path / "fake.exe")
    monkeypatch.setattr(owner_command, "start", lambda *a, **kw: ready())

    def enable(settings, operation, **kwargs):
        called.append(operation)
        assert operation == "enable" and settings.home == home
        print("SYNTHETIC AUTOSTART DEBUG NEVER PRINT")
        return 0

    monkeypatch.setattr(autostart, "run", enable)
    assert quickstart.run(settings, as_json=True, enable_autostart=True) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["autostart"] == "enabled"
    assert result["chatgpt_remote_verified"] is False
    assert called == ["enable"]
    assert onboarding.saved_mode(settings) == "offline"
    assert not (home / "state/connection.json").exists()
    assert not (home / "cloud-pairing.json").exists()
    assert not (home / "state/computer-access.dpapi").exists()


def test_quickstart_invalid_wait_fails_without_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        owner_command,
        "start",
        lambda *a, **kw: pytest.fail("invalid wait must not launch"),
    )
    for value in (0, -1, 61, 1.5, True):
        with pytest.raises(ValueError, match="wait"):
            quickstart.run(Settings(tmp_path, tmp_path), wait=value)
