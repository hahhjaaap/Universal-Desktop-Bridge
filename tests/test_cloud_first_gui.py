"""One Cloudflare-first connection path for an already-paired UDB owner."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from udb.manager import MainWindow
from udb.manager_dialogs import ConnectionDialog


def test_paired_cloud_routes_main_connect_action_to_cloud_agent(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "cloud-pairing.json").write_text("{}", encoding="utf-8")
    called = []
    view = SimpleNamespace(
        agent=SimpleNamespace(home=home),
        toggle_cloud=lambda: called.append("cloud"),
        toggle_tunnel=lambda: called.append("tunnel"),
    )
    MainWindow.toggle_connection(view)
    assert called == ["cloud"]


def test_unpaired_owner_retains_legacy_tunnel_compatibility(tmp_path):
    called = []
    view = SimpleNamespace(
        agent=SimpleNamespace(home=tmp_path),
        toggle_cloud=lambda: called.append("cloud"),
        toggle_tunnel=lambda: called.append("tunnel"),
    )
    MainWindow.toggle_connection(view)
    assert called == ["tunnel"]


def test_paired_cloud_dialog_never_requests_or_overwrites_tunnel_key(tmp_path):
    _app = QApplication.instance() or QApplication([])
    home = tmp_path / "home"
    home.mkdir()
    (home / "cloud-pairing.json").write_text("{}", encoding="utf-8")
    saved = []

    class Controller:
        agent = SimpleNamespace(home=home)

        def config(self):
            return {"tunnel_id": "tunnel_" + "a" * 32}

        def settings(self):
            return {"motion": True, "autoconnect": False, "theme": "system"}

        def configure(self, *args):
            pytest.fail("Cloudflare must not alter the legacy Tunnel credential")

        def save_settings(self, settings):
            saved.append(settings)

    dialog = ConnectionDialog(Controller())
    try:
        dialog.show()
        _app.processEvents()
        assert dialog.cloud_selected
        assert "Cloudflare" in dialog.windowTitle()
        assert not dialog.auto.isVisible()
        dialog.save()
        assert saved and dialog.result() == dialog.DialogCode.Accepted
    finally:
        dialog.close()
