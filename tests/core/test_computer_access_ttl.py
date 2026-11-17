"""WS4: DPAPI grants must expire; test only synthetic records under tmp_path."""

from __future__ import annotations

import io
import json
import sys
import time
from types import SimpleNamespace

import pytest

from udb import computer_access as access
from udb.core import Agent, PolicyError


@pytest.fixture
def agent(tmp_path):
    return Agent(tmp_path / "agent")


def record(agent, *, issued=None, expires_at=None):
    now = time.time()
    return {
        "policy": 1,
        "id": "a" * 32,
        "home": str(agent.home.resolve()),
        "sid": "synthetic-sid",
        "capabilities": list(access.CAPABILITIES),
        "acknowledged_unsandboxed": True,
        "issued": now - 60 if issued is None else issued,
        "expires_at": now + 3600 if expires_at is None else expires_at,
    }


def synthetic_read(agent, payload):
    (agent.state / access.NAME).write_bytes(json.dumps(payload).encode("utf-8"))
    return access.load(agent, unprotect=lambda data: data, sid="synthetic-sid")


def test_unexpired_attended_grant_is_accepted(agent):
    payload = record(agent)
    assert synthetic_read(agent, payload)["id"] == "a" * 32


@pytest.mark.parametrize(
    "modify",
    [
        lambda p, now: p.update(issued=now - 9 * 3600, expires_at=now - 3600),
        lambda p, now: p.update(issued=now + 3600, expires_at=now + 9 * 3600),
        lambda p, now: p.update(issued=now, expires_at=now + 25 * 3600),
        lambda p, now: p.pop("expires_at"),
        lambda p, now: p.pop("issued"),
        lambda p, now: p.update(issued=True),
        lambda p, now: p.update(expires_at=True),
        lambda p, now: p.update(expires_at="tomorrow"),
        lambda p, now: p.update(issued=float("nan")),
    ],
)
def test_missing_expired_future_or_oversized_grants_fail_closed(agent, modify):
    now = time.time()
    payload = record(agent, issued=now, expires_at=now + 8 * 3600)
    modify(payload, now)
    assert synthetic_read(agent, payload) is None


def test_24_hour_maximum_is_allowed_at_issue_time(agent):
    now = time.time()
    payload = record(agent, issued=now - 10, expires_at=now + 24 * 3600 - 10)
    assert synthetic_read(agent, payload) is not None


class AttendedTTY(io.StringIO):
    def isatty(self):
        return True


def fake_dpapi(monkeypatch):
    crypt = SimpleNamespace(
        CryptProtectData=lambda data, *args: data,
        CryptUnprotectData=lambda data, *args: (None, data),
    )
    monkeypatch.setitem(sys.modules, "win32crypt", crypt)
    monkeypatch.setattr(access, "identity", lambda: "synthetic-sid")
    monkeypatch.setattr(access, "os", SimpleNamespace(name="nt"))


def test_local_consent_issues_eight_hour_grant_without_remote_setter(
    agent, monkeypatch
):
    fake_dpapi(monkeypatch)
    before = time.time()
    result = access.enable_local(agent, AttendedTTY("ALLOW COMPUTER\n"), AttendedTTY())
    payload = json.loads((agent.state / access.NAME).read_bytes())
    assert result["enabled"] is True
    assert payload["issued"] >= before
    assert payload["expires_at"] - payload["issued"] == 8 * 3600
    assert access.load(agent)["id"] == payload["id"]


@pytest.mark.parametrize("seconds", [0, -1, 24 * 3600 + 1, float("inf"), True])
def test_local_grant_duration_rejects_invalid_or_over_max(agent, monkeypatch, seconds):
    fake_dpapi(monkeypatch)
    with pytest.raises((PolicyError, ValueError, TypeError)):
        access.enable_local(
            agent,
            AttendedTTY("ALLOW COMPUTER\n"),
            AttendedTTY(),
            ttl_seconds=seconds,
        )
    assert not (agent.state / access.NAME).exists()


def test_expired_grant_denies_runtime_require_and_summary(agent, monkeypatch):
    fake_dpapi(monkeypatch)
    now = time.time()
    payload = record(agent, issued=now - 9 * 3600, expires_at=now - 3600)
    (agent.state / access.NAME).write_bytes(json.dumps(payload).encode("utf-8"))
    assert access.summary(agent)["enabled"] is False
    with pytest.raises(PolicyError, match="must run"):
        access.require(agent)


def test_expired_grant_requires_fresh_attended_confirmation(agent, monkeypatch):
    fake_dpapi(monkeypatch)
    clock = [time.time()]
    monkeypatch.setattr(access.time, "time", lambda: clock[0])

    assert access.enable_local(agent, AttendedTTY("ALLOW COMPUTER\n"), AttendedTTY())[
        "enabled"
    ]
    old = (agent.state / access.NAME).read_bytes()
    old_id = json.loads(old)["id"]

    clock[0] += access.DEFAULT_TTL_SECONDS + 1
    assert access.load(agent) is None
    with pytest.raises(PolicyError, match="not enabled"):
        access.enable_local(agent, AttendedTTY("\n"), AttendedTTY())
    assert (agent.state / access.NAME).read_bytes() == old

    renewed = access.enable_local(agent, AttendedTTY("ALLOW COMPUTER\n"), AttendedTTY())
    assert renewed["enabled"] is True
    current = json.loads((agent.state / access.NAME).read_bytes())
    assert current["id"] != old_id
    assert current["issued"] == clock[0]
    assert current["expires_at"] == clock[0] + access.DEFAULT_TTL_SECONDS


def test_attended_console_accepts_exact_24_hour_maximum(agent, monkeypatch):
    fake_dpapi(monkeypatch)
    result = access.enable_local(
        agent,
        AttendedTTY("ALLOW COMPUTER\n"),
        AttendedTTY(),
        ttl_seconds=access.MAX_TTL_SECONDS,
    )
    payload = json.loads((agent.state / access.NAME).read_bytes())
    assert result["enabled"] is True
    assert payload["expires_at"] - payload["issued"] == access.MAX_TTL_SECONDS
