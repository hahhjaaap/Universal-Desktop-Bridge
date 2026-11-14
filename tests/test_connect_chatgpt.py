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
    assert "Use --setup --autostart" in capsys.readouterr().err
    assert connect_chatgpt.run(settings(tmp_path), setup=True, as_json=True) == 2
    assert "cannot run in JSON" in capsys.readouterr().err


def test_private_setup_cannot_enable_terminal_at_logon(tmp_path, monkeypatch, capsys):
    from udb import autostart, onboarding

    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(onboarding, "setup_cloud", lambda config: 0)
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
