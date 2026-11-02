"""Cloud lifecycle tests: the desktop only starts an explicitly paired agent."""

import json
from types import SimpleNamespace

import pytest

from udb.desktop import DesktopController


def controller_for_test(home):
    controller = DesktopController.__new__(DesktopController)
    controller.agent = SimpleNamespace(home=home)
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
    (tmp_path / "cloud-device-token").write_text(token, encoding="ascii")
    (tmp_path / "cloud-pairing.json").write_text(
        json.dumps(
            {"relay": "https://example.workers.dev", "device_id": "b" * 32}
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


def test_cloud_agent_rejects_invalid_pairing_token(tmp_path):
    (tmp_path / "cloud-device-token").write_text("weak", encoding="ascii")
    (tmp_path / "cloud-pairing.json").write_text(
        json.dumps(
            {"relay": "https://example.workers.dev", "device_id": "c" * 32}
        ),
        encoding="utf-8",
    )
    controller = controller_for_test(tmp_path)
    with pytest.raises(ValueError, match="Invalid device token"):
        controller.start_cloud()
    assert controller.spawned == []
