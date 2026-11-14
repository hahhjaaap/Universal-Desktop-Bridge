"""Synthetic setup acceptance. Live owner OAuth and fresh-PC tests are separate."""

import json
import os
import uuid
from contextlib import nullcontext
from urllib.error import HTTPError

import pytest

from udb import cli, cloud_secrets, credentials, setup, setup_enrollment
from udb.config import Settings

RELAY = setup.PRIVATE_RELAY
DEVICE = "a" * 32
TOKEN = "synthetic-token-" + "b" * 48


@pytest.fixture
def selected(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "owner", tmp_path / "workspace")
    monkeypatch.setattr(setup, "attended_console", lambda: True)
    monkeypatch.setattr(setup, "installation_status", lambda: {"integrity": "source"})
    monkeypatch.setattr(setup.autostart, "status", lambda _: {"enabled": False})
    monkeypatch.setattr(
        setup.owner_command, "launch_gate", lambda *a, **kw: nullcontext()
    )
    monkeypatch.setattr(cloud_secrets, "load_device_token", lambda *a: TOKEN)
    return settings


def pair(settings):
    settings.home.mkdir(parents=True, exist_ok=True)
    path = settings.home / "cloud-pairing.json"
    path.write_text(json.dumps({"relay": RELAY, "device_id": DEVICE}), encoding="ascii")
    return path.read_bytes()


def remote(online=True, verified=False):
    return {
        "token_valid": True,
        "cloud_agent_online": online,
        "authenticated_mcp_verified": verified,
        "chatgpt_connected": True,
    }


def test_fresh_device_runs_every_phase_without_typing_secrets(
    selected, monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(
        setup,
        "_request_json",
        lambda *a, **kw: (200, {"protocol": 2, "browser_enrollment": True}),
    )
    monkeypatch.setattr(
        setup,
        "enroll",
        lambda home, **kw: (calls.append("owner_approval"), pair(selected)),
    )
    monkeypatch.setattr(setup, "device_status", lambda *a: remote())
    monkeypatch.setattr(
        setup, "ensure_agent", lambda _: pytest.fail("Online agent must be reused")
    )
    assert (
        setup.run(
            selected,
            browser=lambda url: calls.append(url),
            prompt=lambda _: "n",
            verification_wait=0,
        )
        == 2
    )
    assert calls[0] == "owner_approval"
    assert calls[-1] == RELAY + "/v1/devices/" + DEVICE + "/connect-chatgpt"
    journal = setup.read_journal(selected.home)
    assert journal["autostart_decision"] == "declined"
    assert "token" not in json.dumps(journal) and TOKEN not in capsys.readouterr().out


def test_paired_verified_rerun_preserves_pairing_credentials_and_decision(
    selected, monkeypatch
):
    before = pair(selected)
    monkeypatch.setattr(
        setup, "enroll", lambda *a, **kw: pytest.fail("Must not re-enroll")
    )
    monkeypatch.setattr(setup, "device_status", lambda *a: remote(verified=True))
    for _ in range(2):
        assert (
            setup.run(
                selected,
                browser=lambda _: pytest.fail("Already verified"),
                prompt=lambda _: "n",
            )
            == 0
        )
    assert (selected.home / "cloud-pairing.json").read_bytes() == before
    assert setup.read_journal(selected.home)["phase"] == "authenticated_mcp_verified"
    assert not (selected.home / "state/computer-access.dpapi").exists()


def test_server_cannot_claim_chatgpt_identity_from_agent_status(
    selected, monkeypatch, capsys
):
    pair(selected)
    monkeypatch.setattr(setup, "device_status", lambda *a: remote(verified=True))
    assert setup.run(selected, prompt=lambda _: "n") == 0
    output = capsys.readouterr().out
    assert "Authenticated MCP: verified" in output
    assert "ChatGPT Connected" not in output
    assert "not independently attested" in output


def test_agent_crash_or_reboot_starts_one_replacement_without_repairing(
    selected, monkeypatch
):
    before = pair(selected)
    results = iter([remote(False), remote(False), remote(True, True)])
    monkeypatch.setattr(setup, "device_status", lambda *a: next(results))
    calls = []
    monkeypatch.setattr(setup, "ensure_agent", lambda settings: calls.append(settings))
    assert setup.run(selected, prompt=lambda _: "n", pause=lambda _: None) == 0
    assert len(calls) == 1 and calls[0].enable_terminal is False
    assert (selected.home / "cloud-pairing.json").read_bytes() == before


def test_revoked_token_does_not_reenroll_start_agent_or_overwrite_pairing(
    selected, monkeypatch, capsys
):
    before = pair(selected)

    def revoked(*args):
        raise HTTPError("https://not-printed.invalid", 403, "secret detail", {}, None)

    monkeypatch.setattr(setup, "device_status", revoked)
    monkeypatch.setattr(
        setup, "enroll", lambda *a, **kw: pytest.fail("No automatic re-enrollment")
    )
    monkeypatch.setattr(setup, "ensure_agent", lambda *a: pytest.fail("Invalid token"))
    assert setup.run(selected) == 2
    assert (selected.home / "cloud-pairing.json").read_bytes() == before
    output = capsys.readouterr().out
    assert "revoked" in output and "secret detail" not in output


def test_offline_resume_preserves_journal_and_existing_pairing(selected, monkeypatch):
    before = pair(selected)
    setup.save_journal(selected.home, {"schema": 1, "phase": "owner_approval"})

    def offline(*args):
        raise OSError("secret network diagnostics")

    monkeypatch.setattr(setup, "device_status", offline)
    assert setup.run(selected) == 2
    assert setup.read_journal(selected.home)["phase"] == "owner_approval"
    assert (selected.home / "cloud-pairing.json").read_bytes() == before


@pytest.mark.parametrize("flag", ["--status", "--json", "--no-browser"])
def test_readonly_flags_never_create_files_browse_spawn_or_write_credentials(
    selected, monkeypatch, flag, capsys
):
    monkeypatch.setattr(
        setup, "_request_json", lambda *a, **kw: (200, {"browser_enrollment": True})
    )
    monkeypatch.setattr(setup, "ensure_agent", lambda *a: pytest.fail("Read only"))
    monkeypatch.setattr(
        setup, "configure_autostart", lambda *a: pytest.fail("Read only")
    )
    monkeypatch.setattr(setup, "enroll", lambda *a, **kw: pytest.fail("Read only"))
    assert cli.main(["setup", flag, "--home", str(selected.home)]) == 2
    if flag == "--json":
        assert json.loads(capsys.readouterr().out)["chatgpt_connected"] is False
    assert not selected.home.exists()


@pytest.mark.parametrize(("verified", "expected"), [(False, 2), (True, 0)])
def test_readonly_setup_requires_authenticated_mcp_verification(
    selected, monkeypatch, capsys, verified, expected
):
    report = {
        "credential_valid": True,
        "cloud_agent_online": True,
        "authenticated_mcp_verified": verified,
        "chatgpt_connected": False,
    }
    monkeypatch.setattr(setup, "inspect", lambda *_: report)

    assert setup.run(selected, readonly=True, json_output=True) == expected
    output = json.loads(capsys.readouterr().out)
    assert output["authenticated_mcp_verified"] is verified
    assert output["chatgpt_connected"] is False
    assert not selected.home.exists()


def test_existing_autostart_is_never_rewritten(selected, monkeypatch):
    monkeypatch.setattr(
        setup.autostart,
        "status",
        lambda _: {
            "enabled": True,
            "matches_current": True,
            "cloud_agent_enabled": True,
        },
    )
    monkeypatch.setattr(
        setup.autostart, "run", lambda *a, **kw: pytest.fail("Already enabled")
    )
    setup.configure_autostart(selected, {}, prompt=lambda _: pytest.fail("No prompt"))
    assert not selected.home.exists()


def test_saved_autostart_consent_recovers_after_registry_failure(selected, monkeypatch):
    state = {"schema": 1, "phase": "autostart"}
    calls = []
    monkeypatch.setattr(setup.autostart, "run", lambda *a, **kw: calls.append(kw) or 2)
    with pytest.raises(setup.SetupError):
        setup.configure_autostart(selected, state, prompt=lambda _: "y")
    assert setup.read_journal(selected.home)["autostart_decision"] == "accepted"
    monkeypatch.setattr(setup.autostart, "run", lambda *a, **kw: calls.append(kw) or 0)
    setup.configure_autostart(
        selected, state, prompt=lambda _: pytest.fail("Consent already saved")
    )
    assert len(calls) == 2 and calls[1] == {"cloud_agent": True}


def test_pending_store_roundtrip_uses_separate_credential_target(tmp_path, monkeypatch):
    values = {}

    def read(*, target):
        if target not in values:
            raise FileNotFoundError()
        return values[target]

    monkeypatch.setattr(credentials, "load_key", read)
    monkeypatch.setattr(
        credentials,
        "save_key",
        lambda value, *, target: values.setdefault(target, value),
    )
    store = setup_enrollment.PendingStore(tmp_path)
    pending = {"id": DEVICE, "proof": "d" * 64, "token": TOKEN, "relay": RELAY}
    store.save_new(pending)
    assert store.load() == pending
    assert store.target.startswith("UniversalDesktopBridge/Enrollment/")
    assert store.target != cloud_secrets.credential_target(DEVICE)
    assert TOKEN not in values[store.target]
    with pytest.raises(setup_enrollment.EnrollmentError, match="pending"):
        store.save_new(pending)


def test_pairing_commit_recovers_after_credential_save_without_replacing_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cloud_secrets, "on_windows", lambda: False)
    pending = {"id": DEVICE, "proof": "d" * 64, "token": TOKEN, "relay": RELAY}
    home = tmp_path / "isolated"
    cloud_secrets.save_device_token(home, DEVICE, TOKEN)
    before = cloud_secrets.token_file(home).read_bytes()
    setup_enrollment.commit_pairing(home, pending)
    setup_enrollment.commit_pairing(home, pending)
    assert cloud_secrets.token_file(home).read_bytes() == before
    assert setup.paired_cloud(home) == (RELAY, DEVICE)


def test_pairing_commit_never_replaces_different_credential(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_secrets, "on_windows", lambda: False)
    home = tmp_path / "isolated"
    cloud_secrets.save_device_token(home, DEVICE, "x" * 48)
    with pytest.raises(setup_enrollment.EnrollmentError, match="differs"):
        setup_enrollment.commit_pairing(
            home, {"id": DEVICE, "token": TOKEN, "relay": RELAY}
        )
    assert cloud_secrets.token_file(home).read_text().strip() == "x" * 48
    assert not (home / "cloud-pairing.json").exists()


def test_enrollment_lost_post_response_reuses_exact_saved_identity(
    tmp_path, monkeypatch
):
    class Store:
        value = None

        def load(self):
            return self.value

        def save_new(self, value):
            self.value = value

    store = Store()
    requests = []

    def offline(*args, **kwargs):
        requests.append(kwargs["data"])
        assert store.value is not None
        raise OSError("response lost")

    monkeypatch.setattr(setup_enrollment, "_request_json", offline)
    for _ in range(2):
        with pytest.raises(OSError):
            setup_enrollment.enroll(tmp_path / "owner", store=store, opener=object())
    assert requests[0] == requests[1]
    assert requests[0]["request_id"] == store.value["id"]
    assert store.value["token"] not in json.dumps(requests)


@pytest.mark.parametrize("state", ["rejected", "registering", "pending"])
def test_owner_denial_or_interrupt_never_saves_device_token(
    tmp_path, monkeypatch, state
):
    pending = {"id": DEVICE, "proof": "d" * 64, "token": TOKEN, "relay": RELAY}

    class Store:
        def load(self):
            return pending

    responses = iter(
        [
            (201, {"device_id": DEVICE, "state": state}),
            (200, {"device_id": DEVICE, "state": state}),
        ]
    )
    monkeypatch.setattr(
        setup_enrollment, "_request_json", lambda *a, **kw: next(responses)
    )
    monkeypatch.setattr(
        setup_enrollment, "commit_pairing", lambda *a: pytest.fail("Not approved")
    )
    now = [0]

    def pause(seconds):
        now[0] += seconds

    with pytest.raises((setup_enrollment.EnrollmentError, TimeoutError)):
        setup_enrollment.enroll(
            tmp_path / "owner",
            store=Store(),
            opener=object(),
            wait=1,
            clock=lambda: now[0],
            pause=pause,
        )
    assert not (tmp_path / "owner").exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows Credential Manager")
def test_native_pending_enrollment_roundtrip_uses_only_synthetic_target(tmp_path):
    import win32cred

    store = setup_enrollment.PendingStore(tmp_path / uuid.uuid4().hex)
    pending = {
        "id": uuid.uuid4().hex,
        "proof": "d" * 64,
        "token": TOKEN,
        "relay": RELAY,
    }
    assert store.load() is None
    try:
        store.save_new(pending)
        assert store.load() == pending
        with pytest.raises(setup_enrollment.EnrollmentError):
            store.save_new(pending)
    finally:
        win32cred.CredDelete(store.target, win32cred.CRED_TYPE_GENERIC, 0)


def test_running_agent_lifetime_lease_prevents_duplicate_process(selected, monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path

    @contextmanager
    def gate(home, **kwargs):
        if Path(home).name == "cloud-agent":
            raise setup.owner_command.CommandError("Synthetic running agent")
        yield

    monkeypatch.setattr(setup.owner_command, "launch_gate", gate)
    monkeypatch.setattr(
        setup.owner_command, "executable", lambda _: selected.home / "udb.exe"
    )
    monkeypatch.setattr(setup.owner_command, "manager_running", lambda *a: True)
    monkeypatch.setattr(
        setup.subprocess, "Popen", lambda *a, **kw: pytest.fail("Duplicate agent")
    )
    assert setup.ensure_agent(selected) is False


def test_local_only_autostart_adds_cloud_agent_only_after_attended_consent(
    selected, monkeypatch
):
    monkeypatch.setattr(
        setup.autostart,
        "status",
        lambda _: {
            "enabled": True,
            "matches_current": True,
            "cloud_agent_enabled": False,
        },
    )
    calls = []
    monkeypatch.setattr(setup.autostart, "run", lambda *a, **kw: calls.append(kw) or 0)
    state = {"schema": 1, "phase": "autostart"}
    setup.configure_autostart(selected, state, prompt=lambda _: "y")
    assert calls == [{"cloud_agent": True}]
    assert setup.read_journal(selected.home)["autostart_decision"] == "accepted"


def test_frozen_integrity_checks_actual_exe_hash_and_never_claims_signature(
    tmp_path, monkeypatch
):
    import hashlib

    from udb import maintenance

    executable = tmp_path / "udb.exe"
    executable.write_bytes(b"synthetic executable")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    executable.with_name("STANDALONE-SHA256SUMS").write_text(digest + "  udb.exe\n")
    monkeypatch.setattr(setup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(setup.sys, "executable", str(executable))
    monkeypatch.setattr(maintenance, "installation", lambda: None)
    monkeypatch.setattr(
        setup, "runtime_identity", lambda: {"publisher_verified": False}
    )
    assert setup.installation_status()["integrity"] == "manifest_sha256"
    assert setup.installation_status()["publisher_verified"] is False
    executable.write_bytes(b"modified executable")
    with pytest.raises(setup.SetupError, match="integrity failed"):
        setup.installation_status()


def test_approved_pending_recovery_does_not_request_owner_approval_again(
    tmp_path, monkeypatch
):
    pending = {"id": DEVICE, "proof": "d" * 64, "token": TOKEN, "relay": RELAY}

    class Store:
        def load(self):
            return pending

    responses = iter(
        [
            (201, {"device_id": DEVICE, "state": "approved"}),
            (200, {"device_id": DEVICE, "state": "approved"}),
        ]
    )
    monkeypatch.setattr(
        setup_enrollment, "_request_json", lambda *a, **kw: next(responses)
    )
    saved = []
    monkeypatch.setattr(setup_enrollment, "commit_pairing", lambda *a: saved.append(a))
    assert (
        setup_enrollment.enroll(
            tmp_path / "owner",
            store=Store(),
            opener=object(),
            browser=lambda _: pytest.fail("Already approved"),
        )
        == DEVICE
    )
    assert saved[0][1] == pending


def test_agent_lost_during_oauth_never_reports_online_or_complete(
    selected, monkeypatch, capsys
):
    pair(selected)
    results = iter([remote(), remote(False, True)])
    monkeypatch.setattr(setup, "device_status", lambda *a: next(results))
    monkeypatch.setattr(
        setup, "_request_json", lambda *a, **kw: (200, {"challenge_ready": True})
    )
    assert (
        setup.run(
            selected,
            prompt=lambda _: "n",
            browser=lambda _: True,
            clock=lambda: 0,
            verification_wait=1,
        )
        == 2
    )
    assert "Cloud Agent: pending" in capsys.readouterr().out
    assert setup.read_journal(selected.home)["phase"] == "cloud_agent"


def test_account_fleet_setup_links_existing_device_and_uses_single_mcp_url(
    selected, monkeypatch, capsys
):
    before = pair(selected)
    report = {**remote(verified=False), "account_fleet": True}
    monkeypatch.setattr(setup, "device_status", lambda *a: report)
    calls = []

    def relay(opener, url, **kw):
        if url.endswith("/fleet/status"):
            assert kw["proof"] == TOKEN
            return 200, {"linked": False}
        if url.endswith("/setup/challenge"):
            return 200, {"challenge_ready": True}
        pytest.fail("Unexpected relay request " + url)

    monkeypatch.setattr(setup, "_request_json", relay)
    monkeypatch.setattr(
        setup,
        "link_existing",
        lambda home, relay, device_id, token, **kw: calls.append(
            (home, relay, device_id, token)
        ),
    )
    assert (
        setup.run(
            selected,
            browser=lambda _: True,
            prompt=lambda _: "n",
            verification_wait=0,
        )
        == 2
    )
    assert calls == [(selected.home, RELAY, DEVICE, TOKEN)]
    assert (selected.home / "cloud-pairing.json").read_bytes() == before
    output = capsys.readouterr().out
    assert RELAY + "/v1/account/mcp" in output
    assert TOKEN not in output
    assert not (selected.home / "state/computer-access.dpapi").exists()


def test_fleet_setup_when_already_linked_never_reapproves_or_reenrolls(
    selected, monkeypatch, capsys
):
    before = pair(selected)
    report = {**remote(verified=True), "account_fleet": True}
    monkeypatch.setattr(setup, "device_status", lambda *a: report)
    monkeypatch.setattr(
        setup,
        "_request_json",
        lambda opener, url, **kw: (200, {"linked": True}),
    )
    monkeypatch.setattr(
        setup, "link_existing", lambda *a, **kw: pytest.fail("Already linked")
    )
    monkeypatch.setattr(setup, "enroll", lambda *a, **kw: pytest.fail("Already paired"))
    assert setup.run(selected, prompt=lambda _: "n") == 0
    assert (selected.home / "cloud-pairing.json").read_bytes() == before
    assert RELAY + "/v1/account/mcp" in capsys.readouterr().out


def test_fleet_link_resumes_same_challenge_without_rotating_credential(
    selected, monkeypatch
):
    before = pair(selected)
    saved = {}
    opened = []

    class Store:
        def load(self):
            return saved.get("value")

        def save_new(self, value):
            assert "value" not in saved
            saved["value"] = dict(value)

    def relay(opener, url, **kw):
        if url.endswith("/v1/setup/enrollments"):
            assert kw["proof"] == TOKEN
            assert kw["data"]["mode"] == "link"
            assert kw["data"]["device_id"] == DEVICE
            assert "device_token_sha256" not in kw["data"]
            return 201, {"device_id": kw["data"]["request_id"], "state": "pending"}
        assert url.endswith("/status")
        assert kw["proof"] == saved["value"]["proof"]
        return 200, {"device_id": saved["value"]["id"], "state": "approved"}

    monkeypatch.setattr(setup_enrollment, "_request_json", relay)
    for _ in range(2):
        assert (
            setup_enrollment.link_existing(
                selected.home,
                RELAY,
                DEVICE,
                TOKEN,
                store=Store(),
                opener=object(),
                browser=lambda url: opened.append(url) or True,
            )
            == DEVICE
        )
    assert len(opened) == 2
    assert all(DEVICE not in value.split("/approval")[0] for value in opened)
    assert (selected.home / "cloud-pairing.json").read_bytes() == before
    assert saved["value"]["id"] != DEVICE
    assert "token" not in saved["value"]
