"""Multi-PC regression tests: targeting, config validation, and authorization."""
import json
from pathlib import Path

import pytest

from udb.fleet import FleetRouter, load_secret, validate_url
from udb.fleet_agent import FleetHandler, FleetHTTPServer


def make_home(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "fleet-secrets").mkdir()
    (state / "fleet-secrets" / "pc-office.token").write_text("a" * 64, encoding="ascii")
    (state / "fleet.json").write_text(
        json.dumps({
            "schema": 1,
            "local_id": "pc-home",
            "remotes": [{"id": "pc-office", "url": "https://pc-office.example.ts.net"}],
        }), encoding="utf-8",
    )
    return tmp_path


def test_default_disabled(tmp_path):
    assert FleetRouter.from_home(tmp_path) is None


def test_fleet_configuration_and_explicit_target(tmp_path):
    home = make_home(tmp_path)
    fleet = FleetRouter.from_home(home)
    assert fleet.local_id == "pc-home"
    assert fleet.list_computers()["computers"][1]["id"] == "pc-office"
    assert load_secret(home, "pc-office") == "a" * 64
    with pytest.raises(ValueError, match="no fallback"):
        fleet.invoke("wrong-pc", "bridge_status", {})
    with pytest.raises(ValueError, match="Invalid remote tool"):
        fleet.invoke("pc-office", "fleet_call", {})


@pytest.mark.parametrize("url", [
    "http://pc-office.example.ts.net",
    "https://pc-office.example.ts.net.evil.com",
    "https://user:pass@pc-office.example.ts.net",
    "https://pc-office.example.ts.net:8443",
    "https://pc-office.example.ts.net/other",
    "https://127.0.0.1",
    "https://pc-office.example.ts.net?redirect=http://evil",
])
def test_reject_unsafe_origins(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_reject_duplicate_device_ids(tmp_path):
    home = make_home(tmp_path)
    (home / "state" / "fleet.json").write_text(json.dumps({
        "schema": 1, "local_id": "pc-home",
        "remotes": [
            {"id": "pc-office", "url": "https://a.example.ts.net"},
            {"id": "pc-office", "url": "https://b.example.ts.net"},
        ]
    }))
    with pytest.raises(ValueError, match="Duplicate"):
        FleetRouter.from_home(home)


def test_reject_symlinked_token(tmp_path):
    home = make_home(tmp_path)
    source = home / "other.token"
    source.write_text("b" * 64)
    token = home / "state" / "fleet-secrets" / "pc-office.token"
    token.unlink()
    try:
        token.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("No symlink creation permission")
    with pytest.raises(ValueError, match="symlink"):
        load_secret(home, "pc-office")


class FakeBackend:
    def __init__(self):
        self.calls = []

    def request(self, method, args, timeout=60):
        self.calls.append((method, args))
        return {"result": {"content": [{"type": "text", "text": "ok"}]}}


def test_agent_loopback_only_and_owner_control_denied():
    # No Tailscale needed to test the local security boundary.
    import http.client
    import threading

    backend = FakeBackend()
    with FleetHTTPServer(
        ("127.0.0.1", 0), FleetHandler,
        token="a" * 64, device_id="pc-office", backend=backend,
        tool_names={"bridge_status", "computer_desktop"}, allow_control=False,
    ) as server:
        assert server.server_address[0] == "127.0.0.1"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(tool, auth):
                c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                payload = json.dumps({"tool": tool, "arguments": {}}).encode()
                c.request("POST", "/v1/call", payload, {
                    "Authorization": auth, "Content-Length": str(len(payload)),
                })
                r = c.getresponse()
                status, body = r.status, json.loads(r.read())
                c.close()
                return status, body
            assert post("bridge_status", "Bearer wrong")[0] == 403
            assert post("computer_desktop", "Bearer " + "a" * 64)[0] == 403
            code, payload = post("bridge_status", "Bearer " + "a" * 64)
            assert code == 200 and payload["device_id"] == "pc-office"
            assert len(backend.calls) == 1
        finally:
            server.shutdown()
            thread.join(timeout=5)
