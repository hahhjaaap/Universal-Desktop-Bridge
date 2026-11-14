"""Human-friendly terminal operations without breaking scripts or safety checks."""

import argparse
import io
from types import SimpleNamespace

import pytest

from udb import cli


class TTY(io.StringIO):
    def isatty(self):
        return True


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
