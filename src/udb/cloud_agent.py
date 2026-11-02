"""Experimental opt-in Cloudflare relay client for the existing UDB stdio proxy.

No account login, grants, tunnel creation or privilege escalation is performed here.
The relay is private/admin-only until an audited OAuth MCP front end is added.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .cloud_secrets import load_device_token, read_token_file
from .config import serve_options
from .launcher import child_environment, command

_DEVICE_ID = re.compile(r"[a-f0-9]{32}\Z")
_ALLOWED_METHODS = {"initialize", "ping", "tools/list", "tools/call"}
_MAX_FRAME = 1024 * 1024
_MIN_RETRY_SECONDS = 5
_MAX_RETRY_SECONDS = 120


def device_url(relay: str, device_id: str) -> str:
    """Only the configured Cloudflare workers.dev TLS relay may receive the token."""
    if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
        raise ValueError("Invalid device ID")
    parts = urlsplit(relay)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or not parts.hostname.endswith(".workers.dev")
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
        or parts.port not in (None, 443)
    ):
        raise ValueError("Relay must be a plain HTTPS origin")
    return f"wss://{parts.netloc}/v1/devices/{device_id}/connect"


def read_device_token(path: str | Path) -> str:
    """Backwards-compatible file reader for source-only test environments."""
    return read_token_file(Path(path))


def valid_remote_rpc(rpc: object) -> bool:
    if not isinstance(rpc, dict) or rpc.get("jsonrpc") != "2.0":
        return False
    if rpc.get("method") not in _ALLOWED_METHODS:
        return False
    ident = rpc.get("id")
    if not (type(ident) in (int, str) and ident != ""):
        return False
    params = rpc.get("params", {})
    if not isinstance(params, dict):
        return False
    if rpc["method"] == "tools/call":
        return isinstance(params.get("name"), str) and isinstance(
            params.get("arguments"), dict
        )
    return True


class LocalProxy:
    """One outstanding MCP RPC per local worker; unknown outcomes aren't retried."""

    def __init__(self, settings):
        args = command(serve_options(settings.home))
        self.process = subprocess.Popen(
            args,
            cwd=str(settings.project_root),
            env=child_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.replies: queue.Queue = queue.Queue(maxsize=16)
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        self.unusable = False

    def _read_loop(self):
        assert self.process.stdout is not None
        while True:
            raw = self.process.stdout.readline(_MAX_FRAME + 1)
            if not raw:
                break
            if len(raw) > _MAX_FRAME or not raw.endswith(b"\n"):
                break
            try:
                result = json.loads(raw)
            except (UnicodeDecodeError, ValueError):
                break
            if isinstance(result, dict) and "id" in result:
                try:
                    self.replies.put_nowait(result)
                except queue.Full:
                    break
        try:
            self.replies.put_nowait(None)
        except queue.Full:
            pass

    def call(self, rpc: dict, timeout: float = 22) -> dict:
        if self.unusable or self.process.poll() is not None:
            raise RuntimeError("Local UDB proxy is unavailable")
        if not valid_remote_rpc(rpc):
            raise ValueError("Unsupported remote RPC")
        wire = (
            json.dumps(rpc, ensure_ascii=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(wire) > _MAX_FRAME:
            raise ValueError("RPC frame too large")
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(wire)
            self.process.stdin.flush()
            while True:
                try:
                    answer = self.replies.get(timeout=timeout)
                except queue.Empty:
                    self.unusable = True
                    raise TimeoutError(
                        "Outcome unknown; do not retry a mutation"
                    ) from None
                if answer is None:
                    self.unusable = True
                    raise RuntimeError("Local UDB proxy disconnected")
                if (
                    type(answer.get("id")) is type(rpc["id"])
                    and answer["id"] == rpc["id"]
                    and answer.get("jsonrpc") == "2.0"
                    and ("result" in answer) != ("error" in answer)
                ):
                    return answer
                # A single outstanding proxy request cannot legitimately receive
                # another ID or an incomplete envelope. Fail closed, never replay.
                self.unusable = True
                raise RuntimeError("Local UDB proxy returned an invalid RPC reply")
        except OSError:
            self.unusable = True
            raise RuntimeError("Local UDB proxy disconnected") from None

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


def load_pairing(home: Path) -> tuple[str, str, Path]:
    file = home / "cloud-pairing.json"
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 2048:
        raise ValueError("Cloud pairing file missing or invalid")
    data = json.loads(file.read_text(encoding="utf-8"))
    relay, device_id = data["relay"], data["device_id"]
    device_url(relay, device_id)
    # Refuse arbitrary secret paths supplied by a cloud or config file.
    token_file = home / "cloud-device-token"
    return relay, device_id, token_file


def run(settings) -> int:
    """Connect only after local owner provisioned a paired device secret."""
    import websocket

    relay, device_id, _token_file = load_pairing(settings.home)
    url = device_url(relay, device_id)
    # Windows uses Credential Manager keyed by device ID; no plaintext file.
    token = load_device_token(settings.home, device_id)
    # Avoid spawning the local MCP process when the cloud is offline or idle.
    proxy = None
    retry_seconds = _MIN_RETRY_SECONDS
    print("UDB cloud agent: private relay enabled for this Windows user.")
    try:
        while True:
            try:
                ws = websocket.create_connection(
                    url,
                    header=[f"Authorization: Bearer {token}"],
                    timeout=30,
                    max_size=_MAX_FRAME,
                    redirect_limit=0,  # Never forward bearer tokens to redirects.
                )
                connected_at = time.monotonic()
                # Keep idle WebSockets open for Cloudflare hibernation.
                ws.settimeout(None)
                print("UDB cloud agent: connected.")
                try:
                    while True:
                        frame = ws.recv()
                        if not frame:
                            break
                        if (
                            not isinstance(frame, str)
                            or len(frame.encode("utf-8")) > _MAX_FRAME
                        ):
                            break
                        try:
                            request = json.loads(frame)
                        except ValueError:
                            break
                        if (
                            not isinstance(request, dict)
                            or request.get("kind") != "rpc"
                        ):
                            break
                        relay_id = request.get("id")
                        rpc = request.get("rpc")
                        if not isinstance(relay_id, str) or len(relay_id) > 80:
                            break
                        try:
                            if not valid_remote_rpc(rpc):
                                raise ValueError("Unsupported remote RPC")
                            if proxy is None:
                                proxy = LocalProxy(settings)
                            response = proxy.call(rpc)
                        except (RuntimeError, TimeoutError, ValueError) as error:
                            # Do not leak file paths, arguments, data or credentials.
                            response = {
                                "jsonrpc": "2.0",
                                "id": rpc.get("id") if isinstance(rpc, dict) else None,
                                "error": {
                                    "code": -32000,
                                    "message": type(error).__name__,
                                },
                            }
                            if proxy is not None and proxy.unusable:
                                ws.send(
                                    json.dumps(
                                        {
                                            "kind": "rpc_result",
                                            "id": relay_id,
                                            "rpc": response,
                                        }
                                    )
                                )
                                return 2
                        ws.send(
                            json.dumps(
                                {"kind": "rpc_result", "id": relay_id, "rpc": response}
                            )
                        )
                finally:
                    ws.close()
                    if proxy is not None:
                        proxy.close()
                        proxy = None
                # Reset backoff only after a sustained healthy connection.
                # Brief accept/close cycles otherwise hammer Cloudflare Free.
                if time.monotonic() - connected_at >= 60:
                    retry_seconds = _MIN_RETRY_SECONDS
                time.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, _MAX_RETRY_SECONDS)
            except websocket.WebSocketBadStatusException as error:
                if error.status_code in (401, 403):
                    print("UDB cloud agent: pairing rejected; stop and re-pair.")
                    return 2
                print("UDB cloud agent: remote endpoint unavailable.")
                time.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, _MAX_RETRY_SECONDS)
            except (OSError, websocket.WebSocketException):
                print("UDB cloud agent: connection unavailable; retrying.")
                time.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, _MAX_RETRY_SECONDS)
    except KeyboardInterrupt:
        return 0
    finally:
        if proxy is not None:
            proxy.close()
