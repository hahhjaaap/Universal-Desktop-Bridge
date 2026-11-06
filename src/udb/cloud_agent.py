"""Experimental opt-in Cloudflare relay client for the existing UDB stdio proxy.

No account login, grants, tunnel creation or privilege escalation is performed here.
The optional OAuth gateway independently filters read-only device/identity grants;
the local proxy retains the existing project boundaries and owner approvals.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from ._version import VERSION
from .cloud_secrets import load_device_token, read_token_file
from .config import serve_options
from .launcher import child_environment, command

CLOUD_USER_AGENT = f"UniversalDesktopBridge/{VERSION}"

_DEVICE_ID = re.compile(r"[a-f0-9]{32}\Z")
_ALLOWED_METHODS = {"initialize", "ping", "tools/list", "tools/call"}
_MAX_FRAME = 1024 * 1024
_MIN_RETRY_SECONDS = 5
_MAX_RETRY_SECONDS = 120
_MAX_PARALLEL_CALLS = 10
_REMOTE_READ_TOOLS = frozenset(
    {
        "bridge_status",
        "list_projects",
        "list_files",
        "read_file",
        "search_files",
        "check_python_syntax",
    }
)


def is_parallel_read_rpc(rpc: dict) -> bool:
    return rpc["method"] in {"initialize", "ping", "tools/list"} or (
        rpc["method"] == "tools/call" and rpc["params"]["name"] in _REMOTE_READ_TOOLS
    )


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
        self.initialized = False

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
        deadline = time.monotonic() + timeout
        if rpc["method"] != "initialize" and not self.initialized:
            # A new WebSocket owns a fresh local proxy. Existing MCP clients
            # can resume with tools/list/call without another edge initialize.
            # Bootstrap locally before dispatch, never retry the caller's RPC.
            answer = self._exchange(
                {
                    "jsonrpc": "2.0",
                    "id": "udb-init-" + uuid.uuid4().hex,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "udb-cloud-agent", "version": VERSION},
                    },
                },
                deadline,
            )
            self._accept_initialize(answer)
        answer = self._exchange(rpc, deadline)
        if rpc["method"] == "initialize":
            self._accept_initialize(answer)
        return answer

    def _accept_initialize(self, answer):
        result = answer.get("result")
        if not isinstance(result, dict) or result.get("protocolVersion") not in {
            "2025-03-26",
            "2025-06-18",
            "2025-11-25",
        }:
            self.unusable = True
            raise RuntimeError("Local UDB initialization rejected")
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.initialized = True

    def _write(self, rpc):
        wire = (
            json.dumps(rpc, ensure_ascii=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(wire) > _MAX_FRAME:
            raise ValueError("RPC frame too large")
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(wire)
            self.process.stdin.flush()
        except OSError:
            self.unusable = True
            raise RuntimeError("Local UDB proxy disconnected") from None

    def _exchange(self, rpc, deadline):
        if time.monotonic() >= deadline:
            self.unusable = True
            raise TimeoutError("RPC deadline expired before dispatch")
        self._write(rpc)
        try:
            answer = self.replies.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            # TimeoutError is an OSError subclass: keep this outside any pipe
            # error handler so an unknown outcome retains its correct category.
            self.unusable = True
            raise TimeoutError("Outcome unknown; do not retry a mutation") from None
        if answer is None:
            self.unusable = True
            raise RuntimeError("Local UDB proxy disconnected") from None
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

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            for name in ("stdin", "stdout"):
                stream = getattr(self.process, name, None)
                if stream is not None:
                    stream.close()
            reader = getattr(self, "reader", None)
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=1)


class ParallelLocalProxies:
    """Ten lazy, independent stdio workers, one outstanding RPC per worker.

    A separate proxy per thread is intentional: the legacy stdio proxy is
    serial, and sharing its response queue would misroute concurrent IDs.
    """

    def __init__(self, settings):
        self.settings = settings
        self.executor = ThreadPoolExecutor(
            max_workers=_MAX_PARALLEL_CALLS, thread_name_prefix="udb-cloud-rpc"
        )
        self.local = threading.local()
        self.lock = threading.Lock()
        self.proxies = []
        self.failed = threading.Event()
        self.closed = False

    def _invoke(self, rpc: dict) -> dict:
        proxy = getattr(self.local, "proxy", None)
        if proxy is None:
            try:
                proxy = LocalProxy(self.settings)
            except OSError:
                self.failed.set()
                raise
            self.local.proxy = proxy
            with self.lock:
                self.proxies.append(proxy)
        try:
            return proxy.call(rpc)
        except (RuntimeError, TimeoutError, ValueError):
            # A dead child process can be unusable without setting its flag:
            # LocalProxy.call() detects process.poll() before _exchange().
            child = getattr(proxy, "process", None)
            if proxy.unusable or (child is not None and child.poll() is not None):
                self.failed.set()
            raise

    def submit(self, rpc: dict):
        with self.lock:
            # A poisoned local stdio worker may have completed a mutation with
            # an unknown outcome. Fail closed until a fresh device connection.
            if self.closed:
                raise RuntimeError("Cloud RPC pool is closed")
            if self.failed.is_set():
                raise RuntimeError("Cloud RPC pool is unavailable")
            return self.executor.submit(self._invoke, rpc)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        # Wait for in-flight calls to finish or reach their own bounded
        # deadlines; never cancel an already dispatched mutation and replay it.
        self.executor.shutdown(wait=True, cancel_futures=True)
        for proxy in self.proxies:
            try:
                proxy.close()
            except Exception:
                # One damaged process/pipe must not strand the other workers.
                # The WebSocket is already closing, so no RPC is retried.
                self.failed.set()


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
    # Worker processes are lazy and exist only during an active connection.
    retry_seconds = _MIN_RETRY_SECONDS
    print("UDB cloud agent: private relay enabled for this Windows user.")
    try:
        while True:
            try:
                ws = websocket.create_connection(
                    url,
                    header=[
                        f"Authorization: Bearer {token}",
                        f"User-Agent: {CLOUD_USER_AGENT}",
                    ],
                    timeout=30,
                    max_size=_MAX_FRAME,
                    redirect_limit=0,  # Never forward bearer tokens to redirects.
                )
                connected_at = time.monotonic()
                # Keep idle WebSockets open for Cloudflare hibernation.
                ws.settimeout(None)
                print("UDB cloud agent: connected.")
                pool = ParallelLocalProxies(settings)
                send_lock = threading.Lock()
                admission_lock = threading.Lock()
                state = {"inflight": 0, "mutation_active": False}

                def send_reply(relay_id, reply, *, socket=ws, lock=send_lock):
                    # websocket-client serializes sends, but keep the result
                    # framing and close decision ordered across callbacks.
                    with lock:
                        socket.send(
                            json.dumps(
                                {"kind": "rpc_result", "id": relay_id, "rpc": reply}
                            )
                        )

                def rejected(rpc, error):
                    return {
                        "jsonrpc": "2.0",
                        "id": rpc.get("id") if isinstance(rpc, dict) else None,
                        "error": {"code": -32000, "message": error},
                    }

                def finished(
                    future,
                    relay_id,
                    rpc,
                    read_only,
                    *,
                    session=state,
                    local_pool=pool,
                    socket=ws,
                    lock=admission_lock,
                    reply_sender=send_reply,
                ):
                    try:
                        try:
                            reply = future.result()
                        except (
                            OSError,
                            RuntimeError,
                            TimeoutError,
                            ValueError,
                        ) as error:
                            # Never include local filenames, arguments or secrets.
                            reply = rejected(rpc, type(error).__name__)
                        except Exception:
                            # An unexpected worker exception may have occurred
                            # after dispatch. Fail closed instead of silently
                            # dropping its response until the relay times out.
                            local_pool.failed.set()
                            reply = rejected(rpc, "InternalError")
                        reply_sender(relay_id, reply)
                    except Exception:
                        # A send/framing failure also makes the reply outcome
                        # uncertain. Never reuse this device connection.
                        local_pool.failed.set()
                    finally:
                        with lock:
                            session["inflight"] -= 1
                            if not read_only:
                                session["mutation_active"] = False
                    if local_pool.failed.is_set():
                        # At least one stdio outcome may be unknown. Close the
                        # connection so the DO fails other requests closed.
                        try:
                            socket.close()
                        except (OSError, websocket.WebSocketException):
                            pass

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
                        if not valid_remote_rpc(rpc):
                            send_reply(relay_id, rejected(rpc, "ValueError"))
                            continue
                        read_only = is_parallel_read_rpc(rpc)
                        with admission_lock:
                            busy = state["inflight"] >= _MAX_PARALLEL_CALLS or (
                                state["inflight"] > 0
                                and (not read_only or state["mutation_active"])
                            )
                            if not busy:
                                state["inflight"] += 1
                                if not read_only:
                                    state["mutation_active"] = True
                        if busy:
                            send_reply(relay_id, rejected(rpc, "DeviceBusy"))
                            continue
                        try:
                            future = pool.submit(rpc)
                        except RuntimeError:
                            with admission_lock:
                                state["inflight"] -= 1
                                if not read_only:
                                    state["mutation_active"] = False
                            send_reply(relay_id, rejected(rpc, "RuntimeError"))
                            break
                        future.add_done_callback(
                            lambda f, rid=relay_id, request_rpc=rpc, ro=read_only, finish_call=finished: (
                                finish_call(f, rid, request_rpc, ro)
                            )
                        )
                finally:
                    # WebSocket shutdown itself can raise after network loss.
                    # Always release the local processes and threads regardless.
                    try:
                        ws.close()
                    finally:
                        pool.close()
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
