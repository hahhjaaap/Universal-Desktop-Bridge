"""Regression checks for bounded, atomic UDB connection and GUI state."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from udb import desktop
from udb.core import PolicyError
from udb.owner_command import CommandError


def controller_for(tmp_path):
    return SimpleNamespace(agent=SimpleNamespace(state=tmp_path))


def test_connection_rejects_oversized_file(tmp_path):
    controller = controller_for(tmp_path)
    (tmp_path / "connection.json").write_text(
        json.dumps({"tunnel_id": "x" * 5000}), encoding="utf-8"
    )
    with pytest.raises(CommandError, match="size limit"):
        desktop.DesktopController.config(controller)


def test_connection_rejects_symlink_without_reading_target(tmp_path):
    external = tmp_path / "external.json"
    external.write_text('{"tunnel_id":"PRIVATE_VALUE"}', encoding="utf-8")
    link = tmp_path / "connection.json"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host")
    with pytest.raises(CommandError):
        desktop.DesktopController.config(controller_for(tmp_path))


def test_malformed_gui_settings_fail_closed(tmp_path):
    (tmp_path / "gui.json").write_text("not-json", encoding="utf-8")
    assert desktop.DesktopController.settings(controller_for(tmp_path)) == {}


def test_connection_write_is_atomic_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "connection.json"
    old = {"tunnel_id": "tunnel_" + "a" * 32}
    path.write_text(json.dumps(old), encoding="utf-8")
    controller = controller_for(tmp_path)
    monkeypatch.setattr(desktop, "save_key", lambda key: None)
    original_replace = Path.replace

    def failure_on_connection(self, target):
        if Path(target) == path:
            raise OSError("Synthetic atomic replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failure_on_connection)
    with pytest.raises(OSError, match="Synthetic"):
        desktop.DesktopController.configure(
            controller, "tunnel_" + "b" * 32, "SYNTHETIC_ONLY"
        )
    assert json.loads(path.read_text(encoding="utf-8")) == old
    assert list(tmp_path.glob("connection.json.*.tmp")) == []


def test_gui_save_is_atomic_and_booleans_only(tmp_path):
    controller = controller_for(tmp_path)
    desktop.DesktopController.save_settings(
        controller, {"motion": 1, "autoconnect": False, "access_token": "PRIVATE"}
    )
    assert desktop.DesktopController.settings(controller) == {
        "motion": True,
        "autoconnect": False,
    }


def test_new_connection_defaults_to_empty_mapping(tmp_path):
    assert desktop.DesktopController.config(controller_for(tmp_path)) == {}


def test_symlinked_connection_never_changes_credentials(tmp_path, monkeypatch):
    real = tmp_path / "target.json"
    real.write_text('{"tunnel_id":"tunnel_' + "a" * 32 + '"}')
    link = tmp_path / "connection.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    monkeypatch.setattr(
        desktop,
        "save_key",
        lambda *_args: pytest.fail("Credentials changed before state validation"),
    )
    with pytest.raises(PolicyError):
        desktop.DesktopController.configure(
            controller_for(tmp_path), "tunnel_" + "b" * 32, "SYNTHETIC_ONLY"
        )


def test_legacy_manager_uses_same_bounded_tunnel_parser(tmp_path):
    pytest.importorskip("tkinter")
    from udb.manager_legacy import read_tunnel_config

    assert read_tunnel_config(tmp_path) == {}
    path = tmp_path / "connection.json"
    path.write_text(json.dumps({"tunnel_id": "a" * 5000}), encoding="utf-8")
    with pytest.raises(CommandError, match="size limit"):
        read_tunnel_config(tmp_path)
