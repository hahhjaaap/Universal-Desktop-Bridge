"""Disposable enrollment simulations; never require real Cloudflare or Windows."""

import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from udb import cli, connect_chatgpt, private_enrollment


class Reply(io.BytesIO):
    def __init__(self, status, data):
        super().__init__(json.dumps(data).encode("utf-8"))
        self.status = status


class FakeRelay:
    def __init__(self, decision="approved"):
        self.proof = None
        self.token_hash = None
        self.device_id = "a" * 32
        self.decision = decision
        self.calls = []
        self.request_hash = None

    def open(self, request, timeout=20):
        self.calls.append((request.method, request.full_url))
        if request.method == "POST":
            body = json.loads(request.data)
            assert set(body) == {
                "request_secret_sha256", "device_token_sha256", "device_name"
            }
            self.request_hash = body["request_secret_sha256"]
            self.token_hash = body["device_token_sha256"]
            assert len(self.request_hash) == 64
            assert len(self.token_hash) == 64
            assert body["device_name"] == "Windows UDB"
            assert request.get_header("Authorization") is None
            return Reply(201, {"state": "pending", "device_id": self.device_id})
        assert request.method == "GET"
        bearer = request.get_header("Authorization")
        assert bearer.startswith("Bearer ")
        proof = bearer.split(" ", 1)[1]
        assert hashlib.sha256(proof.encode("ascii")).hexdigest() == self.request_hash
        self.proof = proof
        return Reply(200, {"state": self.decision, "device_id": self.device_id})


def test_new_windows_device_enrolls_without_admin_key_or_invite(tmp_path, monkeypatch):
    relay = FakeRelay()
    monkeypatch.setattr(private_enrollment, "attended_console", lambda: True)
    monkeypatch.setattr(private_enrollment, "paired_cloud", lambda home: None)
    saved = []
    monkeypatch.setattr(
        private_enrollment, "save_device_token",
        lambda home, ident, token: saved.append((ident, token)),
    )
    clock = [0.0]
    monkeypatch.setattr(private_enrollment.time, "monotonic", lambda: clock[0])

    def pause(seconds):
        clock[0] += seconds

    ident = private_enrollment.enroll_device(
        tmp_path, opener=relay, pause=pause
    )
    assert ident == "a" * 32
    assert len(saved) == 1
    assert saved[0][0] == ident
    assert hashlib.sha256(saved[0][1].encode("ascii")).hexdigest() == relay.token_hash
    assert (tmp_path / "cloud-pairing.json").exists()
    public_pairing = json.loads((tmp_path / "cloud-pairing.json").read_text())
    assert public_pairing["device_id"] == ident
    assert "token" not in public_pairing
    assert "secret" not in public_pairing
    assert len(relay.calls) == 2


@pytest.mark.parametrize("state", ["pending", "rejected", "unrecognized"])
def test_no_registration_until_explicit_approval(tmp_path, monkeypatch, state):
    relay = FakeRelay(state)
    monkeypatch.setattr(private_enrollment, "attended_console", lambda: True)
    monkeypatch.setattr(private_enrollment, "paired_cloud", lambda home: None)
    monkeypatch.setattr(
        private_enrollment, "save_device_token",
        lambda *args: pytest.fail("No token before approval"),
    )
    clock = [0.0]
    monkeypatch.setattr(private_enrollment.time, "monotonic", lambda: clock[0])

    def pause(seconds):
        clock[0] += seconds

    if state == "pending":
        with pytest.raises(TimeoutError):
            private_enrollment.enroll_device(tmp_path, opener=relay, pause=pause)
    else:
        with pytest.raises(ValueError):
            private_enrollment.enroll_device(tmp_path, opener=relay, pause=pause)
    assert not (tmp_path / "cloud-pairing.json").exists()


def test_refuses_unattended_windows_session_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(private_enrollment, "attended_console", lambda: False)
    with pytest.raises(ValueError, match="local Windows console"):
        private_enrollment.enroll_device(tmp_path, opener=FakeRelay())
    assert not (tmp_path / "cloud-pairing.json").exists()


def test_preexisting_pairing_cannot_be_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(private_enrollment, "attended_console", lambda: True)
    monkeypatch.setattr(
        private_enrollment, "paired_cloud",
        lambda home: ("https://a.workers.dev", "b" * 32),
    )
    with pytest.raises(ValueError, match="already paired"):
        private_enrollment.enroll_device(tmp_path, opener=FakeRelay())


def test_ambiguous_network_outcome_does_not_persist_or_retry(tmp_path, monkeypatch):
    class Uncertain:
        calls = 0

        def open(self, request, timeout=20):
            self.calls += 1
            raise TimeoutError("upstream response unknown")

    client = Uncertain()
    monkeypatch.setattr(private_enrollment, "attended_console", lambda: True)
    monkeypatch.setattr(private_enrollment, "paired_cloud", lambda home: None)
    with pytest.raises(TimeoutError):
        private_enrollment.enroll_device(tmp_path, opener=client)
    assert client.calls == 1
    assert not (tmp_path / "cloud-pairing.json").exists()


def test_connect_rejects_conflicting_or_json_enrollment(tmp_path, capsys):
    assert cli.main([
        "connect", "--home", str(tmp_path), "--enroll", "--setup",
    ]) == 2
    assert "OR --enroll" in capsys.readouterr().err
    assert cli.main([
        "connect", "--home", str(tmp_path), "--enroll", "--json",
    ]) == 2
    assert "JSON mode" in capsys.readouterr().err
    assert cli.main([
        "connect", "--home", str(tmp_path), "--relay", "https://a.workers.dev",
    ]) == 2
    assert "--relay requires" in capsys.readouterr().err


def test_connect_enrollment_opt_in_calls_client_only_after_attended_check(
    tmp_path, monkeypatch
):
    from udb import onboarding

    called = []
    monkeypatch.setattr(onboarding, "attended_console", lambda: True)
    monkeypatch.setattr(
        private_enrollment, "run",
        lambda config, relay: called.append(relay) or 2,
    )
    assert connect_chatgpt.run(
        SimpleNamespace(home=tmp_path, enable_terminal=False),
        enroll=True, open_browser=False,
    ) == 2
    assert called == [private_enrollment.PRIVATE_RELAY]


def test_private_client_never_sends_admin_key_or_credential_in_url(tmp_path, monkeypatch):
    relay = FakeRelay()
    monkeypatch.setattr(private_enrollment, "attended_console", lambda: True)
    monkeypatch.setattr(private_enrollment, "paired_cloud", lambda home: None)
    monkeypatch.setattr(
        private_enrollment, "save_device_token", lambda *args: None
    )
    clock = [0.0]
    monkeypatch.setattr(private_enrollment.time, "monotonic", lambda: clock[0])
    private_enrollment.enroll_device(
        tmp_path, opener=relay, pause=lambda delay: clock.__setitem__(0, clock[0] + delay),
    )
    assert all("?" not in url and "token" not in url for _, url in relay.calls)
