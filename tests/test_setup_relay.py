"""Canary setup origin and pending identity isolation; no network or Windows grants."""

import pytest

from udb import private_enrollment, setup_enrollment

OLD = private_enrollment.PRIVATE_RELAY
FLEET = private_enrollment.FLEET_TEST_RELAY


class MemoryStore:
    def __init__(self):
        self.value = None
        self.writes = 0

    def load(self):
        return self.value

    def save_new(self, value):
        assert self.value is None
        self.value = value
        self.writes += 1


def test_setup_relay_override_is_exact_and_never_arbitrary(monkeypatch):
    monkeypatch.delenv("UDB_SETUP_RELAY", raising=False)
    assert private_enrollment.setup_relay() == OLD
    monkeypatch.setenv("UDB_SETUP_RELAY", FLEET)
    assert private_enrollment.setup_relay() == FLEET
    for invalid in (
        FLEET + "/v1/setup",
        FLEET + "/",
        "http://udb-fleet-isolated-staging.hkhoinguyen72.workers.dev",
        "https://attacker.invalid",
        FLEET + "@attacker.invalid",
    ):
        monkeypatch.setenv("UDB_SETUP_RELAY", invalid)
        with pytest.raises(ValueError, match="Unsupported UDB setup relay"):
            private_enrollment.setup_relay()


def test_canary_pending_credential_is_reused_and_cannot_switch_relays(
    tmp_path, monkeypatch
):
    home = tmp_path / "fresh-owner-profile"
    store = MemoryStore()
    monkeypatch.setenv("UDB_SETUP_RELAY", FLEET)
    first = setup_enrollment.prepare_pending(home, store=store)
    second = setup_enrollment.prepare_pending(home, store=store)
    assert first == second
    assert first["relay"] == FLEET
    assert len(first["id"]) == 32 and len(first["proof"]) == 64
    assert store.writes == 1
    assert not home.exists()

    monkeypatch.delenv("UDB_SETUP_RELAY", raising=False)
    with pytest.raises(setup_enrollment.EnrollmentError, match="another relay"):
        setup_enrollment.prepare_pending(home, store=store)
    assert store.load() == first
    assert store.writes == 1


def test_legacy_setup_still_uses_existing_default_relay(tmp_path, monkeypatch):
    monkeypatch.delenv("UDB_SETUP_RELAY", raising=False)
    store = MemoryStore()
    assert (
        setup_enrollment.prepare_pending(tmp_path / "legacy", store=store)["relay"]
        == OLD
    )
