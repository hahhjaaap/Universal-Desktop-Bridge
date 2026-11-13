"""The short CLI help is side-effect free; legacy names remain compatible."""

import re

import pytest

from udb import cli


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["-h"],
        ["help"],
        ["--home", "do-not-create", "--help"],
    ],
)
def test_everyday_help_is_small_and_never_loads_state(argv, capsys, monkeypatch):
    monkeypatch.setattr(
        cli, "load", lambda **kwargs: pytest.fail("help must not load UDB state")
    )
    if "--help" in argv or "-h" in argv:
        with pytest.raises(SystemExit) as exited:
            cli.main(argv)
        assert exited.value.code == 0
    else:
        assert cli.main(argv) == 0

    output = capsys.readouterr().out
    assert output == cli._everyday_help() + "\n"
    displayed = set(re.findall(r"^  udb ([a-z][a-z-]*)\s+", output, re.MULTILINE))
    assert displayed == set(cli.SIMPLE_COMMAND_HELP)
    assert "udb help advanced" in output
    for advanced_option in ("--root", "--core-exe", "--enable-terminal", "--access"):
        assert advanced_option not in output
    for old_name in ("cloud-pair", "rollback", "logs", "manifest"):
        assert old_name not in displayed


def test_advanced_help_describes_all_recovery_routes(capsys, monkeypatch):
    monkeypatch.setattr(
        cli, "load", lambda **kwargs: pytest.fail("help must not load UDB state")
    )
    assert cli.main(["help", "advanced"]) == 0
    output = capsys.readouterr().out
    for command in (
        "udb logs",
        "udb mcp-config",
        "udb rollback",
        "udb cloud-pair",
        "udb --access computer",
        "udb revoke-access",
        "udb allow-source",
        "udb revoke-source",
        "udb runtime",
        "udb version --json",
        "udb build",
        "udb setup --edit",
    ):
        assert command in output


@pytest.mark.parametrize(
    "command",
    [
        "logs",
        "cloud-pair",
        "cloud-agent",
        "runtime",
        "init",
        "build",
        "build-info",
        "manifest",
        "mcp-config",
        "rollback",
        "autostart",
        "reconnect",
        "test",
        "tools",
        "allow-source",
        "revoke-source",
        "revoke-access",
        "quickstart",
        "version",
    ],
)
def test_advanced_commands_remain_accepted(command, capsys):
    # --help proves the old entry point is registered but does not execute it.
    with pytest.raises(SystemExit) as exited:
        cli.main([command, "--help"])
    assert exited.value.code == 0
    assert "usage: udb " + command in capsys.readouterr().out


def test_help_for_specific_command_is_read_only(capsys, monkeypatch):
    monkeypatch.setattr(
        cli, "load", lambda **kwargs: pytest.fail("help must not load UDB state")
    )
    assert cli.main(["help", "status"]) == 0
    assert "usage: udb status" in capsys.readouterr().out
    assert cli.main(["help", "rollback"]) == 0
    assert "usage: udb rollback" in capsys.readouterr().out


def test_old_setup_edit_warns_but_preserves_cloudflare_flow(
    monkeypatch, tmp_path, capsys
):
    from udb import onboarding

    received = []
    monkeypatch.setattr(onboarding, "setup_cloud", lambda settings: received.append(settings) or 0)
    assert cli.main(["setup", "--edit", "--home", str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert "--edit is obsolete" in out.err
    assert received and received[0].home == tmp_path
    assert not tmp_path.joinpath("cloud-pairing.json").exists()


def test_old_logs_and_new_live_viewers_share_a_backend(monkeypatch, tmp_path):
    from udb import activity

    calls = []

    def fake_watch(home, **kwargs):
        calls.append((home, kwargs))
        return 0

    monkeypatch.setattr(activity, "watch", fake_watch)
    for command in ("logs", "live"):
        assert cli.main([command, "--home", str(tmp_path), "--once"]) == 0
    assert len(calls) == 2
    assert calls[0] == calls[1]
