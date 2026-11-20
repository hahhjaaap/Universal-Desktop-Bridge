"""Bounded cloud-RPC task admission with conservative resource isolation.

This is per authenticated device WebSocket, not a permission/grant manager.
At most ten RPCs are admitted. One physical desktop and one owned background
browser can each run a bounded batch while independent read operations proceed.
Unknown/mixed-resource mutations retain the original exclusive semantics.

Waiting RPCs never execute an uncertain action after their queue deadline.
No replay, arbitrary resource labels, persistent jobs, or owner-grant changes.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

MAX_TASKS = 10
RESOURCE_WAIT_SECONDS = 6.0


class ResourceBusyError(RuntimeError):
    """Resource lane timed out before any tool action was dispatched."""


READ_TOOLS = frozenset(
    {
        "bridge_status",
        "list_projects",
        "list_files",
        "read_file",
        "search_files",
        "check_python_syntax",
        "host_status",
        "computer_status",
    }
)
_DESKTOP_TOOLS = frozenset({"computer_desktop", "computer_utilities", "open_chatgpt"})
_HOST_TOOLS = frozenset(
    {
        "host_browser",
        "host_screenshot",
        "host_start_session",
        "host_close_session",
        "host_workspace",
        "host_app",
    }
)
_FILE_READ_ACTIONS = frozenset({"read", "stat", "list"})
_PROCESS_READ_ACTIONS = frozenset({"read", "list"})


def resource_for_rpc(rpc: dict) -> str:
    """Fail closed: only known isolated resources can overlap mutations."""
    if not isinstance(rpc, dict):
        return "exclusive"
    method = rpc.get("method")
    if method in {"initialize", "ping", "tools/list"}:
        return "read"
    if method != "tools/call":
        return "exclusive"
    params = rpc.get("params")
    if not isinstance(params, dict):
        return "exclusive"
    name = params.get("name")
    args = params.get("arguments")
    if not isinstance(name, str):
        return "exclusive"
    if name in READ_TOOLS:
        return "read"
    if not isinstance(args, dict):
        return "exclusive"
    action = args.get("action")
    if not isinstance(action, str):
        action = ""
    if name == "computer_files" and action in _FILE_READ_ACTIONS:
        return "read"
    if name == "computer_process" and action in _PROCESS_READ_ACTIONS:
        return "read"
    if name in _DESKTOP_TOOLS:
        return "desktop"
    if name in _HOST_TOOLS:
        return "owned_browser"
    # OS process execution can itself inject input or touch another resource.
    # Treat it as exclusive during launch. The existing TaskPool continues to
    # allow up to ten supervised processes to run after each launch returns.
    return "exclusive"


class DeviceTaskScheduler:
    """Admission and FIFO scheduling for per-device independent resource lanes.

    Shared GUI lanes are serialized. Requests waiting for a lane consume one
    of the ten in-flight slots and fail before dispatch after a short timeout.
    Calls classified as exclusive keep the pre-existing no-overlap policy.
    """

    def __init__(self, max_tasks: int = MAX_TASKS):
        # A connection may lower admission pressure, never exceed the
        # hard ceiling of ten. Reject bool (an int subclass) as a config.
        if type(max_tasks) is not int or not 1 <= max_tasks <= MAX_TASKS:
            raise ValueError("Cloud RPC admission must be 1..10")
        self.max_tasks = max_tasks
        self.condition = threading.Condition()
        self.inflight = 0
        self.exclusive = False
        self.active = set()
        self.waiting = {"desktop": [], "owned_browser": []}
        self.closed = False

    def admit(self, kind: str) -> bool:
        if kind not in {"read", "desktop", "owned_browser", "exclusive"}:
            return False
        with self.condition:
            if (
                self.closed
                or self.inflight >= self.max_tasks
                or self.exclusive
                or (kind == "exclusive" and self.inflight != 0)
            ):
                return False
            self.inflight += 1
            if kind == "exclusive":
                self.exclusive = True
            return True

    @contextmanager
    def execution(self, kind: str):
        if kind not in self.waiting:
            yield
            return

        # A unique ticket is kept only within this device connection.
        # Event objects are identity-based; no page or caller data is retained.
        ticket = object()
        deadline = time.monotonic() + RESOURCE_WAIT_SECONDS
        with self.condition:
            self.waiting[kind].append(ticket)
            while not self.closed and (
                kind in self.active or self.waiting[kind][0] is not ticket
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(timeout=remaining)
            if (
                self.closed
                or kind in self.active
                or self.waiting[kind][0] is not ticket
            ):
                self.waiting[kind].remove(ticket)
                self.condition.notify_all()
                raise ResourceBusyError("ResourceBusy")
            self.waiting[kind].pop(0)
            self.active.add(kind)
        try:
            yield
        finally:
            with self.condition:
                self.active.remove(kind)
                self.condition.notify_all()

    def release(self, kind: str) -> None:
        with self.condition:
            if self.inflight <= 0:
                raise RuntimeError("Unbalanced device task release")
            self.inflight -= 1
            if kind == "exclusive":
                self.exclusive = False
            self.condition.notify_all()

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()
