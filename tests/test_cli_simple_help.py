"""CLI discoverability stays small while compatibility commands remain callable."""

import re

import pytest

from udb import cli


@pytest.mark.parametrize("argv", [["--help"], ["help"]])
def test_everyday_help_has_only_memorable_commands(argv, capsys, monkeypatch):
    # Help must not load owner state, start a process, or touch a device.
    monkeypatch.setattr(
        cli, "load", lambda **kwargs: pytest.fail("help must not load UDB state")
    )
    if argv == ["--help"]:
        with pytest.raises(SystemExit) as exited:
            cli.main(argv)
        assert exited.value.code == 0
    else:
        assert cli.main(argv) == 0

    output = capsys.readouterr().out
    displayed = set(re.findall(r"^    ([a-z][a-z-]*)\s+", output, re.MULTILINE))
    assert displayed == set(cli.SIMPLE_COMMAND_HELP)
    assert "udb help advanced" in output


def test_advanced_help_describes_old_commands_without_running_them(capsys, monkeypatch):
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
        "udb revoke-access",
        "udb runtime",
        "udb build",
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
    # --help proves the entry point is registered without executing it.
    with pytest.raises(SystemExit) as exited:
        cli.main([command, "--help"])
    assert exited.value.code == 0
    assert "usage: udb " + command in capsys.readouterr().out


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
