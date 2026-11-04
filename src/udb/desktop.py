"""Local desktop process owner. No methods here are exported through MCP."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .core import Agent, PolicyError, reject_links
from .windows_paths import system_executable

CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def command(home: Path, *args):
    from .launcher import worker_command

    return worker_command("core", [*args, "--home", str(home)])


def mcp_command(home: Path):
    """Use the installed stdio manifest, retaining the legacy default.

    This selects a transport process; it cannot create owner permissions.
    Invalid existing manifests fail closed rather than silently downgrade.
    """
    # A frozen distribution owns its worker executable; legacy manifests may
    # point at a development venv that does not exist on the destination PC.
    if getattr(sys, "frozen", False):
        from .config import serve_options
        from .launcher import command as unified_command

        return unified_command(serve_options(home))
    manifest = home / "mcp.json"
    if not manifest.exists():
        from .config import serve_options
        from .launcher import command as unified_command

        return unified_command(serve_options(home))
    reject_links(manifest)
    with manifest.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise PolicyError("MCP manifest exceeds size limit")
    try:
        config = json.loads(raw.decode("utf-8-sig"))["mcpServers"][
            "universal-desktop-bridge"
        ]
        exe, args = config["command"], config["args"]
        if config.get("type", "stdio") != "stdio" or not isinstance(exe, str):
            raise ValueError()
        if (
            not isinstance(args, list)
            or len(args) > 128
            or any(not isinstance(a, str) or "\0" in a for a in args)
        ):
            raise ValueError()
        argv = [a.replace("${PLUGIN_ROOT}", str(home)) for a in [exe, *args]]
        target = Path(argv[0])
        if not target.is_absolute() or not target.is_file() or "\0" in argv[0]:
            raise ValueError()
        reject_links(target)
        return argv
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise PolicyError("Invalid installed stdio MCP manifest") from None


class DesktopController:
    def __init__(self, home: Path, monitor=True):
        self.home = Path(home)
        self.agent = Agent(self.home)
        self.children = {}
        self.handles = {}
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.error = ""
        self.host_service = None
        self.cloud_wanted = False
        self._cloud_retry_attempt = 0
        self._cloud_retry_at = 0.0
        self._cloud_recovery_count = 0
        if monitor:
            threading.Thread(target=self._monitor, daemon=True).start()
            threading.Thread(target=self._sandbox_monitor, daemon=True).start()

    def start_host(self):
        if self.host_service is None:
            from .host_service import HostService

            self.host_service = HostService(self.agent)

    def settings(self):
        from .owner_command import CommandError, read_object

        try:
            return read_object(self.agent.state / "gui.json", 4096)
        except (FileNotFoundError, ValueError, OSError, CommandError):
            return {}

    def save_settings(self, settings):
        from .host_client import atomic_json
        from .ui_theme import normalize_preference

        # Only allow-listed presentation/launch preferences; never credentials.
        safe = {k: bool(settings.get(k)) for k in ("motion", "autoconnect")}
        if "theme" in settings:
            safe["theme"] = normalize_preference(settings["theme"])
        atomic_json(self.agent.state / "gui.json", safe)

    def alive(self, name):
        with self.lock:
            p = self.children.get(name)
            return p is not None and p.poll() is None

    def start_process(self, name, argv, env=None):
        with self.lock:
            if self.closed.is_set():
                raise PolicyError("Ứng dụng đang đóng.")
            if self.alive(name):
                return
            previous = self.handles.pop(name, None)
            if previous:
                previous.close()
            log = (self.agent.state / (name + ".log")).open("ab")
            try:
                self.children[name] = subprocess.Popen(
                    argv,
                    cwd=self.home,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    shell=False,
                    creationflags=CREATE_FLAGS,
                )
            except Exception:
                log.close()
                raise
            self.handles[name] = log

    def start_local(self):
        self.start_process("mcp", command(self.home, "--serve"))

    def start_cloud(self):
        """Start only the owner-paired Cloudflare agent; never grant access."""
        from .cloud_agent import load_pairing
        from .cloud_secrets import load_device_token
        from .launcher import command as cli_command

        _relay, device_id, _token_file = load_pairing(self.agent.home)
        load_device_token(self.agent.home, device_id)
        with self.lock:
            self.cloud_wanted = True
            self.error = ""
        self.start_process(
            "cloud",
            cli_command(["cloud-agent", "--home", str(self.agent.home)]),
        )

    def stop_process(self, name):
        with self.lock:
            if name == "cloud":
                self.cloud_wanted = False
            p = self.children.get(name)
            if p is None or p.poll() is not None:
                return
            # Terminate only children this manager owns; never use name-wide kills.
            if os.name == "nt":
                subprocess.run(
                    [system_executable("taskkill.exe"), "/PID", str(p.pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=CREATE_FLAGS,
                    timeout=15,
                )
            else:
                p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    def _sandbox_monitor(self):
        while not self.closed.wait(1):
            try:
                self.agent.pump_sandbox_queue_local()
                self.agent.pump_media_queue_local()
            except Exception:
                # Exception text can contain private paths or payloads from a
                # failed automation job; status is visible outside that job.
                self.error = "Automation queue failed; inspect redacted logs."

    def _monitor(self):
        """Recover unexpected Cloud Agent exits with bounded backoff.

        Authentication denial exits with code 2 and is never retried
        automatically; the owner must repair or revoke the pairing.
        """
        while not self.closed.wait(2):
            try:
                with self.lock:
                    child = self.children.get("cloud")
                    wanted = self.cloud_wanted
                    if not wanted or self.closed.is_set() or not child:
                        continue
                    code = child.poll()
                    if code is None:
                        continue
                    if code == 2:
                        self.cloud_wanted = False
                        self.error = (
                            "Cloud Agent rejected pairing; check credentials locally."
                        )
                        continue
                    if time.monotonic() < self._cloud_retry_at:
                        continue
                    self._cloud_retry_attempt += 1
                    self._cloud_retry_at = time.monotonic() + min(
                        120, 5 * (2 ** min(self._cloud_retry_attempt, 5))
                    )
                try:
                    self.start_cloud()
                    self._cloud_recovery_count += 1
                except Exception:
                    # Authentication and runtime failures are not exposed to MCP.
                    self.error = (
                        "Cloud Agent stopped; use udb doctor to inspect pairing."
                    )
            except Exception:
                self.error = "Cloud Agent monitor could not check the process."

    def status(self):
        from .sandbox import available

        return {
            "cloud_running": self.alive("cloud"),
            "cloud_wanted": self.cloud_wanted,
            # Running is not a verified WebSocket or ChatGPT tool call.
            "cloud_connection_verified": False,
            "cloud_retry_in_seconds": max(
                0, round(self._cloud_retry_at - time.monotonic(), 1)
            )
            if self.cloud_wanted and not self.alive("cloud")
            else 0,
            "connection_error": self.error,
            "recovery_count": self._cloud_recovery_count,
            "local_running": self.alive("mcp"),
            "sandbox": available(),
        }

    def close(self):
        self.closed.set()
        failures = []
        if self.host_service is not None:
            try:
                self.host_service.close()
            except Exception:
                failures.append("host sessions")
            else:
                self.host_service = None
        from .desktop_vm import close_owned

        try:
            close_owned(self.agent)
        except Exception:
            failures.append("Sandbox")
        for name in list(self.children):
            try:
                self.stop_process(name)
            except Exception:
                failures.append(name)
        for name, handle in list(self.handles.items()):
            try:
                handle.close()
            except Exception:
                failures.append(name + " log")
            else:
                self.handles.pop(name, None)
        if failures:
            raise PolicyError(
                "Cleanup incomplete; retry closing: " + ", ".join(failures)
            )
