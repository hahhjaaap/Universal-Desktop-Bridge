"""Managed Windows logon scripts must target the installed launcher name."""

from pathlib import Path

import pytest

from udb import autostart
from udb.config import Settings
from udb.owner_command import CommandError


def test_managed_cloud_agent_autostart_uses_real_installer_launcher(
    tmp_path, monkeypatch
):
    root = tmp_path / "managed"
    helper = root / "bin" / "udb-launcher.ps1"
    helper.parent.mkdir(parents=True)
    helper.write_text("# synthetic managed launcher\n", encoding="utf-8")
    settings = Settings(tmp_path / "owner", tmp_path / "work")
    monkeypatch.setattr(
        autostart,
        "installation",
        lambda: (root, {"home": str(settings.home)}),
    )
    monkeypatch.setattr(
        autostart, "system_executable", lambda _: str(Path("C:/Windows/powershell.exe"))
    )
    script = autostart.script_text(settings, cloud_agent=True)
    assert "udb-launcher.ps1" in script
    assert "'cloud-agent'" in script
    assert "'--disable-terminal'" in script
    assert "'--access'" not in script
    assert "'udb.ps1'" not in script


def test_managed_cloud_agent_autostart_refuses_missing_launcher(tmp_path, monkeypatch):
    root = tmp_path / "managed"
    root.mkdir()
    settings = Settings(tmp_path / "owner", tmp_path / "work")
    monkeypatch.setattr(
        autostart, "installation", lambda: (root, {"home": str(settings.home)})
    )
    with pytest.raises(CommandError, match="launcher missing"):
        autostart.script_text(settings, cloud_agent=True)
