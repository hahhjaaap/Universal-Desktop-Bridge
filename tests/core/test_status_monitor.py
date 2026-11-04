"""Read-only readiness and live headless monitoring."""

import io
import json
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from udb import cli, headless, owner_command, readiness, status_monitor
from udb.activity import Activity
from udb.core import PolicyError
from udb.host_client import atomic_json


@pytest.mark.parametrize(
    "worker,paused,computer,background,writable,state",
    [
        (False, False, True, True, True, "agent_unavailable"),
        (True, True, True, True, True, "paused"),
        (True, False, True, False, False, "ready"),
        (True, False, False, True, False, "ready"),
        (True, False, False, False, True, "project_only"),
        (True, False, False, False, False, "read_only"),
    ],
)
def test_readiness_separates_transport_worker_and_grants(
    worker, paused, computer, background, writable, state
):
    result = readiness.report(
        {"mode": "headless"},
        {
            "worker_ready": worker,
            "enabled": background,
            "resources": {"paused": paused},
        },
        {"enabled": computer},
        [{"writable": writable}],
    )
    assert result["state"] == state
    assert not result["permissions_changed"] and not result["transport_verified"]


def test_headless_gui_status_describes_lifecycle_even_after_qt_import(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", object())
    ctl = Mock(agent=Mock(state=tmp_path), offline_mode=False)
    ctl.status.return_value = dict(cloud_running=False, cloud_wanted=False)
    ctl._headless_started = time.monotonic()
    ctl._last_reconnect_request = ""
    ctl._reconnect_pending = False
    headless.publish(ctl, "a" * 32)
    result = json.loads((tmp_path / headless.STATUS_NAME).read_text())
    assert not result["gui_loaded"] and result["qt_widgets_imported"]


def test_monitor_strips_payloads_and_never_creates_missing_home(tmp_path, monkeypatch):
    home = tmp_path / "missing"
    host = dict(
        worker_ready=True,
        resources={"paused": False},
        operation_detail={
            "op": "browser",
            "action": "batch",
            "completed_steps": 1,
            "total_steps": 2,
            "url": "secret",
        },
        last_operation={"op": "computer", "ok": False, "error": "private text"},
    )
    monkeypatch.setattr(status_monitor, "host_status", lambda _: host)
    report = dict(
        manager_running=False,
        manager_mode="unknown",
        cloud_agent_running=False,
        background=False,
        next_action="start",
    )
    output = io.StringIO()
    assert (
        status_monitor.watch(
            home,
            home / "udb.exe",
            count=1,
            as_json=True,
            output=output,
            inspect_report=lambda *_: report,
        )
        == 0
    )
    result = json.loads(output.getvalue())
    assert result["active_operation"]["completed_steps"] == 1
    assert result["last_operation"]["ok"] is False
    assert "secret" not in output.getvalue() and "private text" not in output.getvalue()
    assert not home.exists() and not result["permissions_changed"]


def test_monitor_recent_activity_has_no_command_or_path_payload(tmp_path, monkeypatch):
    Activity(tmp_path).emit("call", "computer", details={"path": "private-path"})
    monkeypatch.setattr(status_monitor, "host_status", lambda _: {})
    report = dict(
        manager_running=False,
        manager_mode="unknown",
        cloud_agent_running=False,
        background=False,
        next_action="start",
    )
    value = status_monitor.snapshot(
        tmp_path, tmp_path / "udb.exe", inspect_report=lambda *_: report
    )
    assert len(value["recent_activity"]) == 1 and "private-path" not in json.dumps(
        value
    )


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf"), 61])
def test_monitor_rejects_unbounded_polling(tmp_path, interval):
    with pytest.raises(ValueError):
        status_monitor.watch(tmp_path, tmp_path / "udb.exe", interval=interval, count=1)


def test_cli_monitor_routes_without_starting_owner_manager(tmp_path, monkeypatch):
    watch = Mock(return_value=0)
    monkeypatch.setattr(status_monitor, "watch", watch)
    monkeypatch.setattr(owner_command, "executable", lambda _: tmp_path / "udb.exe")
    monkeypatch.setattr(
        owner_command, "main", Mock(side_effect=AssertionError("must not start"))
    )
    assert (
        cli.main(
            ["status", "--home", str(tmp_path), "--watch", "--json", "--count", "2"]
        )
        == 0
    )
    assert watch.call_args.kwargs["count"] == 2 and watch.call_args.kwargs["as_json"]


def test_reconnect_requests_are_process_scoped_and_leave_grants_unchanged(
    tmp_path, monkeypatch
):
    state = tmp_path / "state"
    state.mkdir()
    grants = state / "host-settings.json"
    grants.write_text('{"enabled":false}')
    instance = "a" * 32

    def heartbeat(_):
        path = state / headless.RECONNECT_NAME
        request = json.loads(path.read_text()) if path.exists() else {}
        return dict(
            instance=instance,
            reconnect_request=request.get("request_id", ""),
            reconnect_pending=False,
        )

    monkeypatch.setattr(owner_command, "headless_state", heartbeat)
    result = owner_command.reconnect(
        tmp_path, tmp_path / "udb.exe", snapshot=lambda *_: {"cloud_agent_running": True}
    )
    request = json.loads((state / headless.RECONNECT_NAME).read_text())
    assert request["instance"] == instance and headless.stop_requested(
        state / headless.RECONNECT_NAME, instance
    )
    assert (
        result["reconnect_acknowledged"] and grants.read_text() == '{"enabled":false}'
    )


@pytest.mark.parametrize(
    "foreign,expired", [(False, False), (True, False), (False, True)]
)
def test_headless_reconnect_is_accepted_once_only_for_current_lifetime(
    tmp_path, foreign, expired
):
    instance, rid = "a" * 32, "b" * 32
    stop = threading.Event()
    calls = []

    class Controller:
        agent = Mock(state=tmp_path)

        def start_host(self):
            pass

        def stop_process(self, name):
            calls.append(name)

        def start_cloud(self):
            calls.append("connect")
            raise PolicyError("synthetic")

        def status(self):
            return dict(cloud_running=False, cloud_wanted=False)

        def close(self):
            pass

    atomic_json(
        tmp_path / headless.RECONNECT_NAME,
        dict(
            instance="c" * 32 if foreign else instance,
            request_id=rid,
            expires=time.time() + (-1 if expired else 30),
        ),
    )
    ctl = Controller()
    # Bound lifetime without depending on wall-clock scheduling of a daemon thread.
    count = [0]

    def wait(_):
        count[0] += 1
        if count[0] >= 20:
            stop.set()
        else:
            time.sleep(0.001)

    stop.wait = wait
    headless.run_loop(ctl, instance, stop, connect=False)
    assert calls == ([] if foreign or expired else ["cloud", "connect"])
