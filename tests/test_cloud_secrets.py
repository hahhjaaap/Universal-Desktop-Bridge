"""Cloud device secrets use Credential Manager on Windows, not plaintext files."""

from __future__ import annotations

import uuid

import pytest

from udb import cloud_secrets


def test_credential_name_is_device_scoped():
    value = uuid.uuid4().hex
    assert cloud_secrets.credential_target(value) == (
        "UniversalDesktopBridge/Cloud/" + value
    )
    for bad in ["../wrong", "0" * 31, "A" * 32]:
        with pytest.raises(ValueError, match="Invalid device ID"):
            cloud_secrets.credential_target(bad)


def test_windows_credential_manager_path_does_not_create_plaintext(
    tmp_path, monkeypatch
):
    memory = {}
    monkeypatch.setattr(cloud_secrets, "on_windows", lambda: True)

    def save(value, target):
        memory[target] = value

    def load(target):
        return memory[target]

    monkeypatch.setattr(cloud_secrets, "save_key", save)
    monkeypatch.setattr(cloud_secrets, "load_key", load)
    device_id = uuid.uuid4().hex
    token = "x" * 48
    cloud_secrets.save_device_token(tmp_path, device_id, token)
    assert cloud_secrets.load_device_token(tmp_path, device_id) == token
    assert not (tmp_path / "cloud-device-token").exists()
    assert list(memory) == [cloud_secrets.credential_target(device_id)]


def test_invalid_cloud_token_rejected_before_windows_store(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_secrets, "on_windows", lambda: True)
    monkeypatch.setattr(
        cloud_secrets,
        "save_key",
        lambda *_args, **_kwargs: pytest.fail("must not store invalid token"),
    )
    with pytest.raises(ValueError, match="Invalid device token"):
        cloud_secrets.save_device_token(tmp_path, uuid.uuid4().hex, "short")
