"""No network or user permissions are needed for these cloud-agent tests."""
import json

import pytest

from udb.cloud_agent import device_url, load_pairing, read_device_token, valid_remote_rpc


def test_device_url_tls_only():
    target = "a" * 32
    assert device_url("https://relay.example", target) == (
        "wss://relay.example/v1/devices/" + target + "/connect"
    )
    for url in ["http://relay.example", "https://user:pass@relay.example",
                "https://relay.example/?key=x", "https://relay.example/hidden"]:
        with pytest.raises(ValueError):
            device_url(url, target)
    with pytest.raises(ValueError):
        device_url("https://relay.example", "../other")


def test_remote_rpc_allowlist():
    assert valid_remote_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert valid_remote_rpc({"jsonrpc": "2.0", "id": "one", "method": "tools/call",
        "params": {"name": "bridge_status", "arguments": {}}})
    assert not valid_remote_rpc({"jsonrpc": "2.0", "id": 1, "method": "shutdown"})
    assert not valid_remote_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "bridge_status", "arguments": None}})


def test_token_file_and_pairing(tmp_path):
    token = tmp_path / "cloud-device-token"
    token.write_text("x" * 48, encoding="ascii")
    assert read_device_token(token) == "x" * 48
    (tmp_path / "cloud-pairing.json").write_text(json.dumps({
        "relay": "https://relay.example", "device_id": "a" * 32}))
    assert load_pairing(tmp_path) == ("https://relay.example", "a" * 32, token)
    token.write_text("weak", encoding="ascii")
    with pytest.raises(ValueError):
        read_device_token(token)
