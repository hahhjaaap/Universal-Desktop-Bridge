"""Atomic owner GUI state and Cloudflare pairing paths remain protected."""

import json
from types import SimpleNamespace

import pytest

from udb import desktop
from udb.cloud_agent import load_pairing
from udb.core import PolicyError


def controller_for(tmp_path):
    return SimpleNamespace(agent=SimpleNamespace(state=tmp_path))


def test_malformed_gui_settings_fail_closed(tmp_path):
    (tmp_path / "gui.json").write_text("not-json", encoding="utf-8")
    assert desktop.DesktopController.settings(controller_for(tmp_path)) == {}


def test_gui_save_is_atomic_and_booleans_only(tmp_path):
    controller = controller_for(tmp_path)
    desktop.DesktopController.save_settings(
        controller, {"motion": 1, "autoconnect": False, "access_token": "PRIVATE"}
    )
    assert desktop.DesktopController.settings(controller) == {
        "motion": True,
        "autoconnect": False,
    }


def test_cloud_pairing_rejects_symlinks_and_oversized_records(tmp_path):
    external = tmp_path / "outside.json"
    external.write_text('{"relay":"https://example.workers.dev","device_id":"' +
                        "a" * 32 + '"}')
    path = tmp_path / "cloud-pairing.json"
    try:
        path.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host")
    with pytest.raises((OSError, ValueError, PolicyError)):
        load_pairing(tmp_path)
    path.unlink()
    path.write_bytes(b"x" * 2049)
    with pytest.raises((OSError, ValueError, PolicyError)):
        load_pairing(tmp_path)


def test_cloud_pairing_metadata_does_not_include_plaintext_token(tmp_path):
    record = {
        "relay": "https://bridge.workers.dev",
        "device_id": "a" * 32,
    }
    (tmp_path / "cloud-pairing.json").write_text(json.dumps(record))
    relay, device_id, _ = load_pairing(tmp_path)
    assert relay == record["relay"] and device_id == record["device_id"]
    assert "token" not in (tmp_path / "cloud-pairing.json").read_text().lower()
