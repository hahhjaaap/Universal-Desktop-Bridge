"""Cloudflare Agent lifecycle, recovery limits and owner-only activation."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from udb import cloud_agent, cloud_secrets, desktop
from udb.core import PolicyError
from udb.desktop import DesktopController


@pytest.fixture
def controller(tmp_path):
    ctl = DesktopController(tmp_path / "bridge", monitor=False)
    yield ctl
    ctl.close()


def test_queue_failure_does_not_expose_private_exception(controller):
    secret = "PRIVATE_JOB_PAYLOAD"
    controller.closed = Mock()
    controller.closed.wait.side_effect = [False, True]

    def fail():
        raise RuntimeError(secret)

    controller.agent.pump_sandbox_queue_local = fail
    controller._sandbox_monitor()
    assert secret not in controller.error
    assert "Automation queue failed" in controller.error


def test_cloud_connection_requires_owner_pairing(controller, monkeypatch):
    monkeypatch.setattr(
        cloud_agent,
        "load_pairing",
        lambda _: (_ for _ in ()).throw(ValueError("not paired")),
    )
    with pytest.raises(ValueError, match="not paired"):
        controller.start_cloud()
    assert controller.cloud_wanted is False


def test_cloud_agent_uses_local_credential_store_without_leaking_token(
    controller, monkeypatch
):
    monkeypatch.setattr(
        cloud_agent, "load_pairing",
        lambda _: ("https://bridge.workers.dev", "a" * 32, None),
    )
    monkeypatch.setattr(
        cloud_secrets, "load_device_token", lambda *a: "PRIVATE_DEVICE_SECRET"
    )
    started = []
    monkeypatch.setattr(
        controller,
        "start_process",
        lambda name, cmd: started.append((name, cmd)),
    )
    controller.start_cloud()
    assert controller.cloud_wanted is True
    assert len(started) == 1 and started[0][0] == "cloud"
    assert "cloud-agent" in started[0][1]
    assert "PRIVATE_DEVICE_SECRET" not in str(started)


def test_cloud_authentication_denial_does_not_auto_retry(controller):
    controller.cloud_wanted = True
    controller.children["cloud"] = SimpleNamespace(poll=lambda: 2)
    controller.closed = Mock()
    controller.closed.wait.side_effect = [False, True]
    controller._monitor()
    assert controller.cloud_wanted is False
    assert "rejected pairing" in controller.error
    assert controller._cloud_recovery_count == 0


def test_unexpected_agent_exit_uses_bounded_process_restart(controller, monkeypatch):
    controller.cloud_wanted = True
    controller.children["cloud"] = SimpleNamespace(poll=lambda: 1)
    controller.closed = Mock()
    controller.closed.wait.side_effect = [False, True]
    calls = []
    monkeypatch.setattr(controller, "start_cloud", lambda: calls.append(True))
    controller._monitor()
    assert calls == [True]
    assert controller._cloud_retry_attempt == 1
    assert controller._cloud_recovery_count == 1


def test_stop_cancels_cloud_restart_without_killing_foreign_process(controller):
    controller.cloud_wanted = True
    controller.stop_process("cloud")
    assert controller.cloud_wanted is False
    assert controller.status()["cloud_connection_verified"] is False


def test_repeated_child_restarts_close_old_handles(controller, monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(poll=lambda: 0)
    )
    controller.start_process("mcp", ["synthetic"])
    previous = controller.handles["mcp"]
    controller.start_process("mcp", ["synthetic"])
    assert previous.closed and len(controller.handles) == 1


def test_status_reads_sandbox_without_recomputing_full_diagnostics(controller, monkeypatch):
    from udb import sandbox

    monkeypatch.setattr(
        controller.agent,
        "diagnostics",
        lambda: pytest.fail("Status must not call full diagnostics"),
    )
    monkeypatch.setattr(sandbox, "available", lambda: True)
    assert controller.status()["sandbox"] is True
    assert not controller.status()["cloud_connection_verified"]
