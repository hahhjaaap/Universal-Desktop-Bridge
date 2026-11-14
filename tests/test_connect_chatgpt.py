"""A browser handoff must not masquerade as verified ChatGPT device access."""

import json
from types import SimpleNamespace

import pytest

from udb import cli, connect_chatgpt


def settings(tmp_path):
    return SimpleNamespace(home=tmp_path / "owner", enable_terminal=False)


@pytest.fixture
def paired(monkeypatch):
    monkeypatch.setattr(
        connect_chatgpt,
        "paired_cloud",
        lambda home: ("https://unit.workers.dev", "a" * 32),
    )
    monkeypatch.setattr(
        connect_chatgpt,
        "cloud_mcp_url",
        lambda home: "https://unit.workers.dev/v1/devices/" + "a" * 32 + "/mcp",
    )


def test_fresh_download_stays_unpaired(tmp_path, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(connect_chatgpt, "paired_cloud", lambda home: None)
    result = connect_chatgpt.run(settings(tmp_path), opener=opened.append)
    assert result == 2
    assert not opened
    assert not (tmp_path / "owner").exists()
    assert "not yet enrolled" in capsys.readouterr().out


def test_invalid_pairing_does_not_open_or_leak(tmp_path, monkeypatch, capsys):
    opened = []

    def broken(home):
        raise ValueError("private token leakage attempt")

    monkeypatch.setattr(connect_chatgpt, "paired_cloud", broken)
    result = connect_chatgpt.run(settings(tmp_path), opener=opened.append)
    assert result == 2
    output = capsys.readouterr().out
    assert not opened
    assert "private token leakage attempt" not in output
    assert "invalid" in output


def test_paired_device_opens_only_chatgpt(tmp_path, paired, capsys):
    opened = []

    def opener(url):
        opened.append(url)
        return True

    result = connect_chatgpt.run(settings(tmp_path), opener=opener)
    assert result == 0
    assert opened == ["https://chatgpt.com/plugins"]
    output = capsys.readouterr().out
    assert "NOT verified" in output
    assert "/mcp" in output
    assert not (tmp_path / "owner").exists()


def test_json_never_opens_browser(tmp_path, paired, capsys):
    def deny(url):
        pytest.fail("JSON must not open a browser")

    result = connect_chatgpt.run(settings(tmp_path), as_json=True, opener=deny)
    assert result == 0
    status = json.loads(capsys.readouterr().out)
    assert status["paired"] is True
    assert status["chatgpt_verified"] is False
    assert status["state"] == "ready_to_authorize_in_chatgpt"
    assert not status["browser_opened"]


def test_no_browser_opt_out(tmp_path, paired, capsys):
    def deny(url):
        pytest.fail("Browser was not requested")

    result = connect_chatgpt.run(settings(tmp_path), open_browser=False, opener=deny)
    assert result == 0
    assert "Browser was not opened" in capsys.readouterr().out


def test_cli_connect_json_before_enrollment(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(connect_chatgpt, "paired_cloud", lambda home: None)
    assert cli.main(["connect", "--home", str(tmp_path), "--json"]) == 2
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "needs_enrollment"
    assert status["paired"] is False
    assert status["chatgpt_verified"] is False


def test_cli_connect_cannot_grant_computer_access(tmp_path, capsys):
    args = ["--access", "computer", "connect", "--home", str(tmp_path)]
    assert cli.main(args) == 2
    assert "does not change Windows access" in capsys.readouterr().err
    assert not (tmp_path / "state" / "computer-access.dpapi").exists()


def test_private_setup_requires_attended_local_console(tmp_path, monkeypatch, capsys):
    from udb import onboarding

    monkeypatch.setattr(onboarding, "attended_console", lambda: False)
    monkeypatch.setattr(
        onboarding, "setup_cloud", lambda home: pytest.fail("setup must not run")
    )
    assert connect_chatgpt.run(settings(tmp_path), setup=True) == 2
    assert "attended Windows terminal" in capsys.readouterr().err
    assert not (tmp_path / "owner").exists()


def test_private_setup_preserves_one_time_existing_pairing_logic(
    tmp_path, monkeypatch, capsys
):
    from udb import onboarding

    calls = []
    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(
        onboarding, "setup_cloud", lambda config: calls.append(config) or 0
    )
    monkeypatch.setattr(
        connect_chatgpt,
        "paired_cloud",
        lambda home: ("https://unit.workers.dev", "a" * 32),
    )
    monkeypatch.setattr(
        connect_chatgpt, "cloud_mcp_url", lambda home: "https://unit.workers.dev/mcp"
    )
    assert connect_chatgpt.run(settings(tmp_path), setup=True, open_browser=False) == 0
    assert len(calls) == 1
    assert "Add custom MCP server (private)" in capsys.readouterr().out
    assert not (tmp_path / "owner").exists()


def test_autostart_is_explicit_and_reuses_owner_guard(tmp_path, monkeypatch, capsys):
    from udb import autostart, onboarding

    calls = []
    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(onboarding, "setup_cloud", lambda config: 0)
    monkeypatch.setattr(
        connect_chatgpt,
        "paired_cloud",
        lambda home: ("https://unit.workers.dev", "a" * 32),
    )
    monkeypatch.setattr(
        connect_chatgpt, "cloud_mcp_url", lambda home: "https://unit.workers.dev/mcp"
    )
    monkeypatch.setattr(
        autostart,
        "run",
        lambda config, action, *, cloud_agent: (
            calls.append((config, action, cloud_agent)) or 0
        ),
    )
    assert (
        connect_chatgpt.run(
            settings(tmp_path), setup=True, autostart=True, open_browser=False
        )
        == 0
    )
    assert calls[0][1:] == ("enable", True)
    assert "NOT verified" in capsys.readouterr().out


def test_autostart_without_setup_or_in_json_mode_denied(tmp_path, capsys):
    assert connect_chatgpt.run(settings(tmp_path), autostart=True) == 2
    assert "not yet enrolled" in capsys.readouterr().out
    assert connect_chatgpt.run(settings(tmp_path), setup=True, as_json=True) == 2
    assert "cannot run in JSON" in capsys.readouterr().err


def test_private_setup_cannot_enable_terminal_at_logon(tmp_path, monkeypatch, capsys):
    from udb import autostart, onboarding

    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(onboarding, "setup_cloud", lambda config: 0)
    monkeypatch.setattr(
        connect_chatgpt,
        "paired_cloud",
        lambda home: ("https://unit.workers.dev", "a" * 32),
    )
    monkeypatch.setattr(
        connect_chatgpt,
        "cloud_mcp_url",
        lambda home: "https://unit.workers.dev/mcp",
    )
    monkeypatch.setattr(
        autostart,
        "run",
        lambda *args, **kwargs: pytest.fail("must not enable autostart"),
    )
    setting = settings(tmp_path)
    setting.enable_terminal = True
    assert (
        connect_chatgpt.run(setting, setup=True, autostart=True, open_browser=False)
        == 2
    )
    assert "not enabled" in capsys.readouterr().err


def test_existing_paired_device_enables_autostart_without_reenrollment(
    tmp_path, monkeypatch, paired, capsys
):
    from udb import autostart, onboarding

    calls = []
    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(
        autostart,
        "run",
        lambda config, operation, *, cloud_agent: (
            calls.append((config, operation, cloud_agent)) or 0
        ),
    )
    assert (
        connect_chatgpt.run(settings(tmp_path), autostart=True, open_browser=False)
        == 0
    )
    assert len(calls) == 1
    assert calls[0][1:] == ("enable", True)
    assert "NOT verified" in capsys.readouterr().out
    assert not (tmp_path / "owner").exists()


def test_existing_pairing_autostart_requires_attended_console(
    tmp_path, paired, monkeypatch, capsys
):
    from udb import autostart, onboarding

    monkeypatch.setattr(onboarding, "attended_console", lambda: False)
    monkeypatch.setattr(
        autostart,
        "run",
        lambda *a, **k: pytest.fail("Unattended invocation enabled autostart"),
    )
    assert connect_chatgpt.run(settings(tmp_path), autostart=True) == 2
    assert "attended local Windows terminal" in capsys.readouterr().err


def test_invalid_or_unpaired_device_never_enables_autostart(
    tmp_path, monkeypatch, capsys
):
    from udb import autostart

    monkeypatch.setattr(
        autostart, "run", lambda *a, **k: pytest.fail("Invalid device enabled autostart")
    )
    monkeypatch.setattr(connect_chatgpt, "paired_cloud", lambda home: None)
    assert connect_chatgpt.run(settings(tmp_path), autostart=True) == 2
    assert "not yet enrolled" in capsys.readouterr().out
    monkeypatch.setattr(
        connect_chatgpt,
        "paired_cloud",
        lambda home: ("https://unit.workers.dev", "a" * 32),
    )
    monkeypatch.setattr(
        connect_chatgpt,
        "cloud_mcp_url",
        lambda home: (_ for _ in ()).throw(ValueError("invalid endpoint")),
    )
    assert connect_chatgpt.run(settings(tmp_path), autostart=True) == 2
    assert "invalid pairing" in capsys.readouterr().out.lower()


def test_existing_pairing_autostart_cannot_enable_terminal(
    tmp_path, monkeypatch, paired, capsys
):
    from udb import autostart, onboarding

    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(
        autostart, "run", lambda *a, **k: pytest.fail("Terminal access enabled")
    )
    config = settings(tmp_path)
    config.enable_terminal = True
    assert connect_chatgpt.run(config, autostart=True) == 2
    assert "not enabled" in capsys.readouterr().err


def test_existing_pairing_autostart_error_is_redacted(
    tmp_path, monkeypatch, paired, capsys
):
    from udb import autostart, onboarding
    from udb.owner_command import CommandError

    monkeypatch.setattr(onboarding, "attended_console", lambda: True)

    def blocked(*a, **k):
        raise CommandError("secret-not-for-output")

    monkeypatch.setattr(autostart, "run", blocked)
    assert connect_chatgpt.run(settings(tmp_path), autostart=True) == 2
    output = capsys.readouterr()
    assert "not enabled" in output.err
    assert "secret-not-for-output" not in str(output)
    assert "NOT verified" not in output.out


def test_existing_pairing_autostart_cannot_run_in_json_mode(
    tmp_path, monkeypatch, paired, capsys
):
    from udb import autostart

    monkeypatch.setattr(
        autostart, "run", lambda *a, **k: pytest.fail("JSON mode wrote startup")
    )
    assert connect_chatgpt.run(settings(tmp_path), autostart=True, as_json=True) == 2
    assert "cannot run in JSON mode" in capsys.readouterr().err


def test_cli_connect_existing_autostart_flag_dispatches_without_setup(
    tmp_path, monkeypatch
):
    recorded = []
    monkeypatch.setattr(
        connect_chatgpt,
        "run",
        lambda config, **kwargs: recorded.append(kwargs) or 0,
    )
    assert (
        cli.main(["connect", "--home", str(tmp_path), "--autostart", "--no-browser"])
        == 0
    )
    assert len(recorded) == 1
    assert recorded[0]["autostart"] is True
    assert recorded[0]["setup"] is False
    assert recorded[0]["enroll"] is False
    assert recorded[0]["open_browser"] is False
