"""Per-user, windowless manager. Existing grants remain unchanged.

No QApplication, tray icon, user window, or input hook is created here.
Stop requests are local files bound to this exact process lifetime, not MCP tools.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from pathlib import Path

from . import __version__
from .build_identity import runtime_identity
from .core import PolicyError, reject_links
from .desktop import DesktopController
from .host_client import _read_json, atomic_json

STATUS_NAME = "headless-status.json"
STOP_NAME = "headless-stop.json"
RECONNECT_NAME = "headless-reconnect.json"
HEARTBEAT_SECONDS = 1.0


def manager_status(state: Path) -> dict:
    fallback = dict(
        mode="unknown_or_stopped", gui_loaded=None, unrestricted_host_access=False
    )
    try:
        path = Path(state) / STATUS_NAME
        reject_links(path)
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return fallback
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("mode") != "headless"
            or data.get("phase") != "running"
            or not -2 <= time.time() - data["at"] <= 6
        ):
            return fallback
        return dict(
            mode="headless",
            gui_loaded=data.get("gui_loaded") is True,
            unrestricted_host_access=False,
        )
    except (OSError, ValueError, KeyError, TypeError, PolicyError):
        return fallback


def stop_requested(path: Path, instance: str, now=None) -> bool:
    try:
        reject_links(path)
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return False
        request = json.loads(raw)
        if not isinstance(request, dict):
            return False
        stamp = time.time() if now is None else now
        expiry = request.get("expires")
        return (
            request.get("instance") == instance
            and isinstance(expiry, (int, float))
            and not isinstance(expiry, bool)
            and stamp < expiry <= stamp + 60
        )
    except (OSError, ValueError, PolicyError):
        return False


def publish(controller, instance: str, phase="running"):
    connection = controller.status()
    atomic_json(
        controller.agent.state / STATUS_NAME,
        dict(
            mode="headless",
            version=__version__,
            build=runtime_identity(),
            pid=os.getpid(),
            instance=instance,
            at=time.time(),
            phase=phase,
            # This lifecycle creates no GUI. Imported test/library modules do
            # not mean a headless manager owns a window.
            gui_loaded=False,
            qt_widgets_imported="PySide6.QtWidgets" in sys.modules,
            uptime_seconds=max(
                0,
                round(
                    time.monotonic()
                    - getattr(controller, "_headless_started", time.monotonic()),
                    1,
                ),
            ),
            tunnel_ready=connection["ready"],
            tunnel_running=connection["tunnel_running"],
            connecting=connection["connecting"],
            recovery_count=connection.get("recovery_count", 0),
            last_recovery=connection.get("last_recovery", ""),
            retry_in_seconds=connection.get("retry_in_seconds", 0),
            reconnect_request=getattr(controller, "_last_reconnect_request", ""),
            reconnect_pending=getattr(controller, "_reconnect_pending", False),
            connection_mode="offline"
            if getattr(controller, "offline_mode", False)
            else "online",
            permissions="existing_owner_grants",
            unrestricted_host_access=False,
        ),
    )


def run_loop(controller, instance, stop_event, connect=True, interval=0.3):
    """Separate lifecycle so failures and cancellation can be tested without Qt."""
    controller.offline_mode = not connect
    controller._headless_started = time.monotonic()
    controller._last_reconnect_request = ""
    controller._reconnect_pending = False

    def begin(reconnect=False):
        try:
            if reconnect:
                controller.stop_process("tunnel")
            if not stop_event.is_set():
                controller.offline_mode = False
                controller.start_tunnel()
        except (PolicyError, OSError):
            pass  # Existing controller schedules bounded retries, not tool replay.
        finally:
            controller._reconnect_pending = False

    try:
        controller.start_host()
        if connect:
            controller._reconnect_pending = True
            # Launch/retry asynchronously; local stop stays responsive during init.
            threading.Thread(
                target=begin, daemon=True, name="UDB initial connection"
            ).start()
        next_publish = 0.0
        while not stop_event.is_set():
            now = time.monotonic()
            if now >= next_publish:
                publish(controller, instance)
                next_publish = now + HEARTBEAT_SECONDS
            if stop_requested(controller.agent.state / STOP_NAME, instance):
                break
            request = controller.agent.state / RECONNECT_NAME
            if not controller._reconnect_pending and stop_requested(request, instance):
                try:
                    data = _read_json(request, 4096)
                    rid = data.get("request_id")
                    if (
                        isinstance(rid, str)
                        and re.fullmatch(r"[a-f0-9]{32}", rid)
                        and rid != controller._last_reconnect_request
                    ):
                        controller._last_reconnect_request = rid
                        controller._reconnect_pending = True
                        threading.Thread(
                            target=begin,
                            args=(True,),
                            daemon=True,
                            name="UDB owner reconnect",
                        ).start()
                except (OSError, ValueError, PolicyError):
                    pass
            stop_event.wait(interval)
    finally:
        controller.close()
        publish(controller, instance, "stopped")


def run(home: Path, connect=True):
    if os.name != "nt":
        raise PolicyError("The headless Windows manager requires Windows.")
    # QtCore supplies the SAME OS-backed lease as the optional legacy GUI.
    # Importing QtCore creates no application object or window.
    from PySide6.QtCore import QLockFile

    home = Path(home)
    reject_links(home)
    from .config import effective, prepare_workspace

    prepare_workspace(effective(home))
    state = home / "state"
    reject_links(state)
    state.mkdir(exist_ok=True)
    lock = QLockFile(str(state / "manager.lock"))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(50):
        return 0  # Reuse the existing manager; never display a dialog.
    controller = None
    try:
        controller = DesktopController(home)
        instance = uuid.uuid4().hex
        stop = threading.Event()

        def signal_stop(*_):
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal_stop)
        run_loop(controller, instance, stop, connect=connect)
    finally:
        if controller is not None and not controller.closed.is_set():
            controller.close()
        lock.unlock()
    return 0
