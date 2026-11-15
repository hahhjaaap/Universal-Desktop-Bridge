"""Opt-in, payload-free timing for UDB HyperSpeed benchmark investigations.

Never record URLs, selectors, keystrokes, tool arguments, file paths, device
identifiers or credentials. Measurements are local to the owner profile.
Disabled by default; exceptions in telemetry must not affect UDB execution.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_ENABLED = "UDB_HYPERSPEED_TRACE"
_PHASES = frozenset(
    {"queue", "dispatch", "execution", "observation", "response", "startup"}
)
_OPERATIONS = frozenset(
    {
        "cloud.queue",
        "cloud.local_rpc",
        "cloud.initialize",
        "cloud.stdio",
        "mcp.dispatch",
        "mcp.response",
        "host.dispatch",
        "host.mailbox",
        "browser.cdp",
        "browser.batch",
        "desktop.uia",
        "desktop.batch",
    }
)
_CURRENT = contextvars.ContextVar("udb_hyperspeed_rpc", default=None)
_LOCK = threading.Lock()
_SINK: Path | None = None
_WARM: set[str] = set()


def correlation_id(rpc_id) -> str | None:
    """Stable across RPC processes, without exposing the original request ID."""
    if type(rpc_id) not in (str, int) or len(str(rpc_id)) > 160:
        return None
    raw = f"{type(rpc_id).__name__}:{rpc_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def configure(home: Path) -> bool:
    """Enable only when the Windows owner opted in; never fail application start."""
    global _SINK
    if os.environ.get(_ENABLED) != "1":
        return False
    try:
        base = Path(home)
        folder = base / "hyperspeed"
        if base.is_symlink() or folder.is_symlink():
            return False
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        sink = folder / "traces.jsonl"
        if sink.is_symlink():
            return False
        with _LOCK:
            _SINK = sink
        return True
    except (OSError, ValueError, TypeError):
        return False


def disable() -> None:
    """Useful for tests and for stopping a local trace without restarting UDB."""
    global _SINK
    with _LOCK:
        _SINK = None
        _WARM.clear()


@contextmanager
def rpc_scope(rpc_id):
    token = _CURRENT.set(correlation_id(rpc_id))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def _record(operation: str, phase: str, started_ns: int, ended_ns: int, ok: bool):
    if _SINK is None or operation not in _OPERATIONS or phase not in _PHASES:
        return
    try:
        with _LOCK:
            if _SINK is None:
                return
            cold = operation not in _WARM
            _WARM.add(operation)
            event = {
                "schema": 1,
                "trace_id": _CURRENT.get(),
                "operation": operation,
                "phase": phase,
                "startup": "cold" if cold else "warm",
                "started_ns": started_ns,
                "duration_ns": max(0, ended_ns - started_ns),
                # Absolute process CPU counter, not a per-operation delta.
                "process_cpu_total_ns": time.process_time_ns(),
                "ok": ok,
                "pid": os.getpid(),
            }
            # Bounded fixed-field JSON; no untrusted text is written.
            wire = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
            descriptor = os.open(_SINK, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, wire)
            finally:
                os.close(descriptor)
    except (OSError, TypeError, ValueError):
        pass  # Optional metrics may never alter the result of a tool call.


@contextmanager
def span(operation: str, phase: str):
    if _SINK is None:
        yield
        return
    started = time.perf_counter_ns()
    ok = False
    try:
        yield
        ok = True
    finally:
        _record(operation, phase, started, time.perf_counter_ns(), ok)


def interval(
    operation: str,
    phase: str,
    started_ns: int,
    *,
    ok: bool = True,
    rpc_id=None,
):
    """Measure a completed phase, optionally correlating with its JSON-RPC ID."""
    if rpc_id is None:
        _record(operation, phase, started_ns, time.perf_counter_ns(), ok)
    else:
        with rpc_scope(rpc_id):
            _record(operation, phase, started_ns, time.perf_counter_ns(), ok)


def timed_call(operation, phase, callback, *args, **kwargs):
    """Measure a callable without changing its return value or exceptions."""
    with span(operation, phase):
        return callback(*args, **kwargs)


def read_trace(path: Path, limit=10000):
    """Read bounded diagnostic events for offline analysis only."""
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("Trace read limit must be 1..100000")
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 32 * 1048576:
        raise ValueError("Unsafe or oversized trace input")
    events = []
    with path.open("r", encoding="utf-8") as stream:
        for index, raw in enumerate(stream):
            if index >= limit:
                raise ValueError("Trace exceeds event limit")
            if len(raw) > 2048:
                raise ValueError("Oversized trace event")
            event = json.loads(raw)
            if (
                not isinstance(event, dict)
                or event.get("schema") != 1
                or event.get("operation") not in _OPERATIONS
                or event.get("phase") not in _PHASES
                or type(event.get("duration_ns")) is not int
            ):
                raise ValueError("Invalid trace event")
            events.append(event)
    return events
