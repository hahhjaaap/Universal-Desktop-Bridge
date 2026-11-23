"""Experimental opt-in Cloudflare relay client for the existing UDB stdio proxy.

No account login, grants, tunnel creation or privilege escalation is performed here.
The optional OAuth gateway independently filters read-only device/identity grants;
the local proxy retains the existing project boundaries and owner approvals.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from . import hyperspeed_perf as perf
from ._version import VERSION
from .cloud_secrets import load_device_token, read_token_file
from .cloud_worker_profile import local_worker_budget
from .config import serve_options
from .launcher import child_environment, command
from .remote_task_scheduler import (
    DeviceTaskScheduler,
    ResourceBusyError,
    resource_for_rpc,
)

CLOUD_USER_AGENT = f"UniversalDesktopBridge/{VERSION}"

_DEVICE_ID = re.compile(r"[a-f0-9]{32}\Z")
_ALLOWED_METHODS = {"initialize", "ping", "tools/list", "tools/call"}
_MAX_FRAME = 1024 * 1024
_MIN_RETRY_SECONDS = 5
_MAX_RETRY_SECONDS = 120
_MAX_PARALLEL_CALLS = 10
_RPC_WORKER_LIMIT_ENV = "UDB_CLOUD_MAX_RPC_WORKERS"
_RPC_WORKER_PROFILE_ENV = "UDB_CLOUD_WORKER_PROFILE"
_STATUS_LOCK_WAIT_SECONDS = 6.0
# Detect half-open TCP / idle WebSocket connections without replaying RPCs.
_HEARTBEAT_IDLE_SECONDS = 30
_HEARTBEAT_PONG_SECONDS = 15
_HEARTBEAT_PAYLOAD = b"udb-live"
_REMOTE_READ_TOOLS = frozenset(
    {
        "bridge_status",
        "list_projects",
        "list_files",
        "read_file",
        "search_files",
        "check_python_syntax",
        # Scheduling only. These retain their separate owner grants.
        "host_status",
        "computer_status",
    }
)


def worker_profile() -> str:
    """Auto is the Windows default; explicit legacy is the rollback switch."""
    profile = os.environ.get(_RPC_WORKER_PROFILE_ENV)
    if profile is None:
        return "auto" if os.name == "nt" else "legacy"
    if profile not in {"auto", "legacy"}:
        raise ValueError("UDB_CLOUD_WORKER_PROFILE must be auto or legacy")
    return profile


def cloud_rpc_worker_limit() -> int:
    """Conservatively size Cloud RPCs on Windows; honor manual overrides.

    Admission and executor capacity are bounded together, never above ten.
    This does not affect background jobs, browser sessions or grant scopes.
    """
    profile = worker_profile()
    raw = os.environ.get(_RPC_WORKER_LIMIT_ENV)
    if raw is None:
        return local_worker_budget() if profile == "auto" else _MAX_PARALLEL_CALLS
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 2:
        raise ValueError("UDB_CLOUD_MAX_RPC_WORKERS must be 1..10")
    count = int(raw)
    if not 1 <= count <= _MAX_PARALLEL_CALLS:
        raise ValueError("UDB_CLOUD_MAX_RPC_WORKERS must be 1..10")
    return count


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


def encode_relay_result(relay_id: str, reply: dict) -> str:
    """Bound the complete WebSocket envelope, not just the inner stdio reply.

    A valid near-1 MiB child response can exceed the Durable Object's byte
    limit once relay IDs and escaping are added. Return a redacted RPC error
    instead of letting the edge terminate every in-flight request.
    """
    wire = json.dumps(
        {"kind": "rpc_result", "id": relay_id, "rpc": reply},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(wire) <= _MAX_FRAME:
        return wire
    error = {
        "jsonrpc": "2.0",
        "id": reply.get("id") if isinstance(reply, dict) else None,
        "error": {"code": -32000, "message": "ResponseTooLarge"},
    }
    bounded = json.dumps(
        {"kind": "rpc_result", "id": relay_id, "rpc": error},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(bounded) > _MAX_FRAME:
        raise ValueError("RPC response ID exceeds relay frame limit")
    return bounded


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
            answer = perf.timed_call(
                "cloud.initialize",
                "startup",
                self._exchange,
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
        with perf.rpc_scope(rpc["id"]):
            answer = perf.timed_call(
                "cloud.stdio", "execution", self._exchange, rpc, deadline
            )
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
                # The stdio proxy's main loop exits on EOF. Let it retire its
                # own child workers and return normally so a frozen onefile
                # bootloader can clean its temporary extraction directory.
                # The caller has already drained in-flight RPCs; never replay.
                pipe = self.process.stdin
                eof_sent = False
                if pipe is not None:
                    try:
                        pipe.close()
                    except (OSError, ValueError):
                        pass
                    else:
                        eof_sent = True
                if eof_sent:
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                if self.process.poll() is None:
                    # An unresponsive worker must not hang disconnect. Retain
                    # the previous bounded terminate-then-kill fallback.
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
        finally:
            for name in ("stdin", "stdout"):
                stream = getattr(self.process, name, None)
                if stream is not None and not getattr(stream, "closed", False):
                    stream.close()
            reader = getattr(self, "reader", None)
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=1)


class ParallelLocalProxies:
    """Up to ten active RPCs over serial, lazily started stdio proxies.

    Desktop calls share one connection-scoped proxy under the physical desktop
    lane lock. That process owns window IDs and the warm UIA worker. Other
    calls use thread-local proxies so concurrent responses cannot cross.
    """

    def __init__(self, settings):
        self.settings = settings
        self.max_rpc_workers = cloud_rpc_worker_limit()
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_rpc_workers, thread_name_prefix="udb-cloud-rpc"
        )
        self.local = threading.local()
        self.desktop_proxy = None
        # Explicit staging opt-in. Only the pure bridge_status read route is
        # serialized onto one connection-scoped stdio worker; all other lanes
        # retain their existing per-thread isolation and authorization.
        self.shared_status_enabled = os.environ.get("UDB_SHARED_STATUS_PROXY") == "1"
        self.status_lock = threading.Lock()
        self.status_proxy = None
        self.lock = threading.Lock()
        self.proxies = []
        # Sample local RAM for NEW admissions only. Already-dispatched RPCs
        # are not interrupted, even when the machine becomes memory-bound.
        self.auto_worker_budget = (
            worker_profile() == "auto" and os.environ.get(_RPC_WORKER_LIMIT_ENV) is None
        )
        self.scheduler = DeviceTaskScheduler(
            max_tasks=self.max_rpc_workers,
            adaptive_limit=local_worker_budget if self.auto_worker_budget else None,
        )
        self.failed = threading.Event()
        self.closed = False

    def _invoke(
        self, rpc: dict, queued_at_ns=None, resource_kind=None, prewarm_status=False
    ) -> dict:
        kind = resource_kind or resource_for_rpc(rpc)
        with self.scheduler.execution(kind):
            return self._invoke_unlocked(
                rpc, queued_at_ns, kind, prewarm_status=prewarm_status
            )

    def _call_and_guard(self, proxy, rpc: dict):
        try:
            with perf.rpc_scope(rpc.get("id")):
                return perf.timed_call("cloud.local_rpc", "execution", proxy.call, rpc)
        except (RuntimeError, TimeoutError, ValueError):
            # An unknown mutating outcome must poison this whole connection.
            child = getattr(proxy, "process", None)
            if proxy.unusable or (child is not None and child.poll() is not None):
                self.failed.set()
            raise

    def _invoke_unlocked(
        self, rpc: dict, queued_at_ns, kind, *, prewarm_status=False
    ) -> dict:
        if queued_at_ns is not None:
            perf.interval("cloud.queue", "queue", queued_at_ns, rpc_id=rpc.get("id"))
        if self.failed.is_set():
            raise RuntimeError("Cloud RPC pool is unavailable")

        # Each thread normally owns a separate stdio proxy for concurrency.
        # A status-only storm can launch many expensive onefile subprocesses,
        # even though bridge_status does not need a per-thread session.
        params = rpc.get("params")
        shared_status = (
            self.shared_status_enabled
            and kind == "read"
            and (
                (
                    rpc.get("method") == "tools/call"
                    and isinstance(params, dict)
                    and params.get("name") == "bridge_status"
                )
                # Only the local prewarm caller may select this path for ping.
                # Untrusted relay RPC IDs never select the shared worker.
                or (prewarm_status and rpc.get("method") == "ping")
            )
        )
        if shared_status:
            # A slow status call must not park the other nine admitted tasks
            # indefinitely. Busy means *no* RPC was dispatched and is safe.
            if not self.status_lock.acquire(timeout=_STATUS_LOCK_WAIT_SECONDS):
                raise ResourceBusyError("ResourceBusy")
            try:
                # Re-check after a queued status request acquires the lock.
                if self.failed.is_set():
                    raise RuntimeError("Cloud RPC pool is unavailable")
                proxy = self.status_proxy
                if proxy is None:
                    try:
                        proxy = LocalProxy(self.settings)
                    except OSError:
                        self.failed.set()
                        raise
                    self.status_proxy = proxy
                    with self.lock:
                        self.proxies.append(proxy)
                return self._call_and_guard(proxy, rpc)
            finally:
                self.status_lock.release()

        desktop = kind == "desktop"
        proxy = self.desktop_proxy if desktop else getattr(self.local, "proxy", None)
        if proxy is None:
            try:
                proxy = LocalProxy(self.settings)
            except OSError:
                self.failed.set()
                raise
            if desktop:
                self.desktop_proxy = proxy
            else:
                self.local.proxy = proxy
            with self.lock:
                self.proxies.append(proxy)
        if self.failed.is_set():
            raise RuntimeError("Cloud RPC pool is unavailable")
        return self._call_and_guard(proxy, rpc)

    def submit(self, rpc: dict, resource_kind=None, *, prewarm_status=False):
        with self.lock:
            # A poisoned local stdio worker may have completed a mutation with
            # an unknown outcome. Fail closed until a fresh device connection.
            if self.closed:
                raise RuntimeError("Cloud RPC pool is closed")
            if self.failed.is_set():
                raise RuntimeError("Cloud RPC pool is unavailable")
            return self.executor.submit(
                self._invoke,
                rpc,
                time.perf_counter_ns(),
                resource_kind,
                prewarm_status,
            )

    def prewarm_one(self, timeout=16):
        """Initialize exactly one local stdio proxy with a read-only ping.

        Owner opt-in only; this never invokes a tool, starts input control,
        or replays an unknown user mutation. Other worker threads stay lazy.
        """
        if type(timeout) not in (int, float) or not 1 <= timeout <= 30:
            raise ValueError("Prewarm timeout must be 1..30 seconds")
        rpc = {
            "jsonrpc": "2.0",
            "id": "udb-prewarm-" + uuid.uuid4().hex,
            "method": "ping",
        }
        # When status sharing is enabled, warm that exact serial worker
        # rather than a throwaway thread-local worker that cannot serve the
        # first bridge_status call. This ping is read-only and is not a grant.
        reply = self.submit(rpc, prewarm_status=self.shared_status_enabled).result(
            timeout=timeout
        )
        if (
            not isinstance(reply, dict)
            or reply.get("error") is not None
            or not isinstance(reply.get("result"), dict)
        ):
            self.failed.set()
            raise RuntimeError("Read-only MCP prewarm ping rejected")
        return True

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        # Wait for in-flight calls to finish or reach their own bounded
        # deadlines; never cancel an already dispatched mutation and replay it.
        self.scheduler.close()
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


def receive_relay_text(ws, websocket) -> str | None:
    """Read one text RPC frame; require a matching pong after idle ping.

    This only checks transport liveness. It never retries an RPC, restarts a
    mutation, or accepts unsolicited pong frames as proof of connectivity.
    A failed heartbeat causes the caller to close this entire WebSocket and
    all local proxy workers before beginning a new transport session.
    """
    awaiting_pong = False
    ws.settimeout(_HEARTBEAT_IDLE_SECONDS)
    while True:
        try:
            opcode, frame = ws.recv_data_frame(control_frame=True)
        except websocket.WebSocketTimeoutException:
            if awaiting_pong:
                raise
            ws.ping(_HEARTBEAT_PAYLOAD)
            awaiting_pong = True
            ws.settimeout(_HEARTBEAT_PONG_SECONDS)
            continue

        if opcode == websocket.ABNF.OPCODE_PONG:
            if awaiting_pong and frame.data == _HEARTBEAT_PAYLOAD:
                awaiting_pong = False
                ws.settimeout(_HEARTBEAT_IDLE_SECONDS)
            continue
        if opcode == websocket.ABNF.OPCODE_PING:
            # websocket-client already replies to PING in recv_data_frame.
            continue
        if opcode == websocket.ABNF.OPCODE_CLOSE:
            return None
        if opcode != websocket.ABNF.OPCODE_TEXT:
            raise websocket.WebSocketProtocolException(
                "Expected text frame from Cloudflare relay"
            )
        payload = frame.data
        if isinstance(payload, bytes):
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                raise websocket.WebSocketProtocolException(
                    "Invalid WebSocket text encoding"
                ) from None
        if isinstance(payload, str):
            return payload
        raise websocket.WebSocketProtocolException("Invalid WebSocket text frame")


def run(settings) -> int:
    """Connect only after local owner provisioned a paired device secret."""
    from .owner_command import CommandError, launch_gate

    perf.configure(settings.home)

    try:
        # Older logon scripts can also start Cloud Agent. Prevent two sockets
        # for the same Windows profile from continually replacing one another.
        with launch_gate(settings.home / "cloud-agent", timeout=0):
            return _run_paired(settings)
    except CommandError:
        print("UDB cloud agent: a connection process already owns this profile.")
        return 2


def _run_paired(settings) -> int:
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
                        "X-UDB-Resource-Lanes: 1",
                    ],
                    timeout=30,
                    max_size=_MAX_FRAME,
                    redirect_limit=0,  # Never forward bearer tokens to redirects.
                )
                connected_at = time.monotonic()
                # A bounded idle heartbeat detects half-open transports.
                # Never retry unknown outcomes across a reconnect.
                print("UDB cloud agent: connected.")
                pool = ParallelLocalProxies(settings)
                send_lock = threading.Lock()

                def send_reply(relay_id, reply, *, socket=ws, lock=send_lock):
                    # websocket-client serializes sends, but keep the result
                    # framing and close decision ordered across callbacks.
                    with lock:
                        socket.send(encode_relay_result(relay_id, reply))

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
                    resource_kind,
                    *,
                    local_pool=pool,
                    socket=ws,
                    reply_sender=send_reply,
                ):
                    try:
                        try:
                            reply = future.result()
                        except ResourceBusyError:
                            # No tool action was dispatched; safe busy outcome.
                            reply = rejected(rpc, "DeviceBusy")
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
                        local_pool.scheduler.release(resource_kind)
                    if local_pool.failed.is_set():
                        # At least one stdio outcome may be unknown. Close the
                        # connection so the DO fails other requests closed.
                        try:
                            socket.close()
                        except (OSError, websocket.WebSocketException):
                            pass

                try:
                    if os.environ.get("UDB_CLOUD_PREWARM") == "1":
                        warm_start = time.monotonic()
                        try:
                            pool.prewarm_one()
                        except (RuntimeError, TimeoutError, ValueError, OSError):
                            # No mutation has been sent: only the local MCP
                            # ping failed. Close this WebSocket and retry.
                            raise OSError(
                                "Local read-only prewarm unavailable"
                            ) from None
                        print(
                            "UDB cloud agent: one MCP worker prewarmed "
                            f"in {round((time.monotonic() - warm_start) * 1000)} ms."
                        )
                    while True:
                        frame = receive_relay_text(ws, websocket)
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
                        resource_kind = resource_for_rpc(rpc)
                        busy = not pool.scheduler.admit(resource_kind)
                        if busy:
                            send_reply(relay_id, rejected(rpc, "DeviceBusy"))
                            continue
                        try:
                            future = pool.submit(rpc, resource_kind)
                        except RuntimeError:
                            pool.scheduler.release(resource_kind)
                            send_reply(relay_id, rejected(rpc, "RuntimeError"))
                            break
                        future.add_done_callback(
                            lambda f, rid=relay_id, request_rpc=rpc, lane=resource_kind, finish_call=finished: (
                                finish_call(f, rid, request_rpc, lane)
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
