"""Cloud lifecycle tests: the desktop only starts an explicitly paired agent."""

import json
import threading
import uuid
from types import SimpleNamespace

import pytest

from udb import cloud_secrets
from udb.desktop import DesktopController


def controller_for_test(home):
    controller = DesktopController.__new__(DesktopController)
    controller.agent = SimpleNamespace(home=home)
    controller.lock = threading.RLock()
    controller.cloud_wanted = False
    controller.error = ""
    controller.spawned = []

    def start(name, argv):
        controller.spawned.append((name, argv))

    controller.start_process = start
    return controller


def test_cloud_agent_rejects_unpaired_device(tmp_path):
    controller = controller_for_test(tmp_path)
    with pytest.raises(ValueError, match="Cloud pairing"):
        controller.start_cloud()
    assert controller.spawned == []


def test_cloud_agent_uses_local_pairing_and_never_passes_secret_in_argv(tmp_path):
    token = "a" * 48
    device_id = uuid.uuid4().hex
    cloud_secrets.save_device_token(tmp_path, device_id, token)
    try:
        (tmp_path / "cloud-pairing.json").write_text(
            json.dumps(
                {"relay": "https://example.workers.dev", "device_id": device_id}
            ),
            encoding="utf-8",
        )
        controller = controller_for_test(tmp_path)
        controller.start_cloud()
        assert len(controller.spawned) == 1
        role, argv = controller.spawned[0]
        assert role == "cloud"
        assert "cloud-agent" in argv
        assert "--home" in argv
        assert token not in " ".join(argv)
        assert not any("Authorization:" in item for item in argv)
    finally:
        cloud_secrets.remove_device_token(tmp_path, device_id)


def test_cloud_agent_rejects_invalid_pairing_token(tmp_path, monkeypatch):
    device_id = uuid.uuid4().hex
    (tmp_path / "cloud-pairing.json").write_text(
        json.dumps({"relay": "https://example.workers.dev", "device_id": device_id}),
        encoding="utf-8",
    )

    def invalid_token(*_args):
        raise ValueError("Invalid device token")

    monkeypatch.setattr(cloud_secrets, "load_device_token", invalid_token)
    controller = controller_for_test(tmp_path)
    with pytest.raises(ValueError, match="Invalid device token"):
        controller.start_cloud()
    assert controller.spawned == []
