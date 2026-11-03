"""Cloud pairing never exposes an administrator key to the Windows user."""

import hashlib
import io
import json
import uuid

import pytest

from udb.cloud_agent import CLOUD_USER_AGENT
from udb.cloud_pair import claim_device, validate_origin
from udb.cloud_secrets import load_device_token, on_windows, remove_device_token


class FakeResponse(io.BytesIO):
    status = 201

    def __init__(self):
        super().__init__(b'{"registered":true}')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self):
        self.called = False
        self.request = None

    def open(self, request, timeout):
        self.called = True
        self.request = request
        assert timeout == 20
        return FakeResponse()


def test_pair_without_admin_secret_or_command_line_token(tmp_path):
    opener = FakeOpener()
    ident = uuid.uuid4().hex
    code = "b" * 64
    claim_device(
        tmp_path,
        "https://example.workers.dev",
        ident,
        code,
        opener=opener,
    )
    assert opener.called
    assert opener.request.get_header("Authorization") == "Bearer " + code
    assert opener.request.get_header("User-agent") == CLOUD_USER_AGENT
    pairing = json.loads((tmp_path / "cloud-pairing.json").read_text())
    assert pairing == {
        "relay": "https://example.workers.dev",
        "device_id": ident,
    }
    try:
        token = load_device_token(tmp_path, ident)
        assert len(token) >= 32
        if on_windows():
            assert not (tmp_path / "cloud-device-token").exists()
        body = json.loads(opener.request.data)
        assert body["device_token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
        assert "admin" not in str(pairing)
        with pytest.raises(ValueError, match="already paired"):
            claim_device(tmp_path, pairing["relay"], ident, code, opener=opener)
    finally:
        remove_device_token(tmp_path, ident)


def test_pairing_rejects_external_hosts_and_bad_codes(tmp_path):
    ident = "0" * 32
    for url in [
        "http://example.workers.dev",
        "https://evil.example.org",
        "https://example.workers.dev.evil.com",
        "https://user:pass@example.workers.dev",
        "https://example.workers.dev/path",
    ]:
        with pytest.raises(ValueError):
            validate_origin(url, ident)
    opener = FakeOpener()
    with pytest.raises(ValueError, match="Invalid pairing invitation"):
        claim_device(
            tmp_path,
            "https://example.workers.dev",
            ident,
            "not-a-valid-code",
            opener=opener,
        )
    assert not opener.called
    assert not (tmp_path / "cloud-device-token").exists()
