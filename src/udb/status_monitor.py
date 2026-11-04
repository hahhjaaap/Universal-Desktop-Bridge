"""Read-only, metadata-only headless console monitoring. Never starts a job."""

from __future__ import annotations

import json
import math
import re
import sys
import threading
import time
from types import SimpleNamespace

from .activity import EventReader
from .host_client import status as host_status


def operation_metadata(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for key in ("op", "action"):
        text = value.get(key)
        if isinstance(text, str) and re.fullmatch(r"[a-z_]{0,40}", text):
            result[key] = text
    for key in ("started_at", "finished_at", "elapsed_ms"):
        number = value.get(key)
        if type(number) in (int, float) and math.isfinite(number) and number >= 0:
            result[key] = number
    for key in ("completed_steps", "total_steps"):
        if type(value.get(key)) is int and 0 <= value[key] <= 12:
            result[key] = value[key]
    if type(value.get("ok")) is bool:
        result["ok"] = value["ok"]
    return result or None


def snapshot(home, exe, *, inspect_report=None, reader=None):
    from .owner_command import headless_state, inspect

    report = (inspect_report or inspect)(home, exe)
    heartbeat = headless_state(home) or {}
    host = host_status(SimpleNamespace(state=home / "state"))
    events = (reader or EventReader(home)).read(limit=10)
    recent = []
    for event in events:
        tool = event.get("tool", "")
        if not isinstance(tool, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,80}", tool
        ):
            continue
        recent.append(
            {
                key: event.get(key)
                for key in ("seq", "at", "kind", "tool", "status", "elapsed_ms")
            }
        )
    # Do not copy selectors, URLs, commands, result bodies or exception text.
    active = operation_metadata(host.get("operation_detail"))
    return {
        "at": time.time(),
        "manager_running": report["manager_running"],
        "manager_mode": report["manager_mode"],
        "agent_heartbeat_at": heartbeat.get("at"),
        "uptime_seconds": heartbeat.get("uptime_seconds"),
        "reconnect_pending": heartbeat.get("reconnect_pending", False),
        "local_tunnel_ready": report["local_tunnel_ready"],
        "chatgpt_connection_verified": False,
        "background": report["background"],
        "worker_ready": host.get("worker_ready", False),
        "paused": host.get("resources", {}).get("paused", True),
        "active_operation": active or None,
        "last_operation": operation_metadata(host.get("last_operation")),
        "recent_activity": recent,
        "next_action": report["next_action"],
        "permissions_changed": False,
    }


def watch(
    home,
    exe,
    *,
    interval=1.0,
    count=0,
    as_json=False,
    output=None,
    stop_event=None,
    inspect_report=None,
):
    if (
        type(interval) not in (int, float)
        or not math.isfinite(interval)
        or not 0.25 <= interval <= 60
    ):
        raise ValueError("Monitor interval must be 0.25..60 seconds")
    if type(count) is not int or not 0 <= count <= 100000:
        raise ValueError("Monitor count must be 0..100000 (0 means until Ctrl+C)")
    output = sys.stdout if output is None else output
    stop = threading.Event() if stop_event is None else stop_event
    reader = EventReader(home)
    emitted = 0
    try:
        while not stop.is_set():
            value = snapshot(home, exe, inspect_report=inspect_report, reader=reader)
            if as_json:
                print(json.dumps(value, ensure_ascii=True), file=output, flush=True)
            else:
                active = value["active_operation"] or {}
                print(
                    f"UDB {value['manager_mode']} | tunnel={value['local_tunnel_ready']} | worker={value['worker_ready']} | paused={value['paused']} | action={active.get('action', 'idle')}",
                    file=output,
                    flush=True,
                )
            emitted += 1
            if count and emitted >= count:
                break
            stop.wait(interval)
    except KeyboardInterrupt:
        return 130
    finally:
        reader.close()
    return 0
