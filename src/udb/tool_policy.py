"""Single, explicit security policy for the public 59-tool UDB catalog.

This module is intentionally independent of registry.py to avoid import cycles.
The registry validates that this policy covers every public tool exactly once.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Iterable

SCOPES = MappingProxyType(
    {
        "udb:read": "Read files and metadata inside owner-registered UDB projects.",
        "udb:observe": "Observe approved sandbox, browser and host status or screenshots.",
        "udb:write": "Create or modify files and supported project documents.",
        "udb:execute": "Start, interact with or stop project-scoped terminal processes.",
        "udb:sandbox": "Create and control owner-approved UDB sandbox sessions.",
        "udb:host": "Control UDB-owned browser and workspace sessions.",
        "udb:computer": "Access or control the current Windows user's computer resources.",
        "udb:download": "Download content from external sources into an approved project.",
        "udb:jobs": "Resume or manage persisted UDB work that may have side effects.",
    }
)

# Each public tool has one primary scope. Mixed read/write tools intentionally
# require the stronger scope; the local UDB permission layer remains authoritative.
_RAW_POLICY = {
    # Registered-project reads. These are the only tools enabled by the base
    # udb:read scope after the user grants the connection.
    "bridge_status": (
        "project.read",
        "udb:read",
        True,
        True,
        False,
        False,
        "low",
        False,
    ),
    "list_projects": (
        "project.read",
        "udb:read",
        True,
        True,
        False,
        False,
        "low",
        False,
    ),
    "list_files": ("project.read", "udb:read", True, True, False, False, "low", False),
    "read_file": (
        "project.read",
        "udb:read",
        True,
        True,
        False,
        False,
        "medium",
        False,
    ),
    "check_python_syntax": (
        "project.read",
        "udb:read",
        True,
        True,
        False,
        False,
        "low",
        False,
    ),
    "get_request_status": (
        "project.read",
        "udb:jobs",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "get_job_status": (
        "project.read",
        "udb:jobs",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "list_jobs": ("project.read", "udb:jobs", True, False, False, False, "low", False),
    "search_files": (
        "project.read",
        "udb:read",
        True,
        True,
        False,
        False,
        "low",
        False,
    ),
    "terminal_read": (
        "project.read",
        "udb:execute",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "file_list": ("project.read", "udb:read", True, False, False, False, "low", False),
    "file_read": (
        "project.read",
        "udb:read",
        True,
        False,
        False,
        False,
        "medium",
        False,
    ),
    "file_search": (
        "project.read",
        "udb:read",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "file_stat": ("project.read", "udb:read", True, False, False, False, "low", False),
    "file_read_lines": (
        "project.read",
        "udb:read",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "terminal_list": (
        "project.read",
        "udb:execute",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "search_start": (
        "project.read",
        "udb:jobs",
        False,
        False,
        False,
        False,
        "low",
        False,
    ),
    "search_read": (
        "project.read",
        "udb:jobs",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    "search_stop": (
        "project.read",
        "udb:jobs",
        False,
        False,
        False,
        False,
        "low",
        False,
    ),
    "file_read_chunk": (
        "project.read",
        "udb:read",
        True,
        False,
        False,
        False,
        "low",
        False,
    ),
    # Sensitive observation is opt-in and never included in the default read grant.
    "desktop_status": (
        "sandbox.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "medium",
        False,
    ),
    "desktop_screenshot": (
        "sandbox.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "high",
        False,
    ),
    "desktop_snapshot": (
        "sandbox.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "high",
        False,
    ),
    "desktop_wait_for": (
        "sandbox.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "medium",
        False,
    ),
    "host_status": (
        "host.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "medium",
        False,
    ),
    "host_screenshot": (
        "host.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "high",
        False,
    ),
    "computer_status": (
        "computer.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "medium",
        False,
    ),
    "system_process_list": (
        "computer.observe",
        "udb:observe",
        True,
        False,
        False,
        False,
        "medium",
        False,
    ),
    # Project writes and mixed document tools.
    "propose_file_write": (
        "project.write",
        "udb:write",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "file_write": (
        "project.write",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "file_replace": (
        "project.write",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "file_mkdir": (
        "project.write",
        "udb:write",
        False,
        False,
        False,
        False,
        "medium",
        False,
    ),
    "file_upload": (
        "project.write",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "file_operation": (
        "project.write",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "file_transfer": (
        "project.write",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "spreadsheet": (
        "project.documents",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "word_document": (
        "project.documents",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    "pdf_document": (
        "project.documents",
        "udb:write",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
    # Project execution. Local terminal enablement and owner grants still apply.
    "terminal_start": (
        "project.execute",
        "udb:execute",
        False,
        False,
        True,
        False,
        "critical",
        True,
    ),
    "terminal_interact": (
        "project.execute",
        "udb:execute",
        False,
        False,
        True,
        False,
        "critical",
        True,
    ),
    "terminal_stop": (
        "project.execute",
        "udb:execute",
        False,
        False,
        True,
        False,
        "high",
        True,
    ),
    # UDB sandbox operations remain separate from access to the real desktop.
    "propose_sandbox_job": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "propose_desktop_session": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "desktop_action": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "critical",
        False,
    ),
    "desktop_element_action": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "critical",
        False,
    ),
    "desktop_stop": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "desktop_app": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "desktop_batch": (
        "sandbox.control",
        "udb:sandbox",
        False,
        False,
        False,
        False,
        "critical",
        False,
    ),
    # UDB-owned browser/workspace sessions, not arbitrary Windows desktop access.
    "host_start_session": (
        "host.session",
        "udb:host",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "host_browser": (
        "host.browser",
        "udb:host",
        False,
        False,
        False,
        True,
        "critical",
        False,
    ),
    "host_workspace": (
        "host.workspace",
        "udb:host",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    "host_close_session": (
        "host.session",
        "udb:host",
        False,
        False,
        False,
        False,
        "high",
        False,
    ),
    # Current-user Windows access is a separate, explicit trust boundary.
    "computer_files": (
        "computer.files",
        "udb:computer",
        False,
        False,
        True,
        True,
        "critical",
        False,
    ),
    "computer_process": (
        "computer.process",
        "udb:computer",
        False,
        False,
        True,
        True,
        "critical",
        False,
    ),
    "computer_desktop": (
        "computer.desktop",
        "udb:computer",
        False,
        False,
        True,
        True,
        "critical",
        False,
    ),
    "system_process_terminate": (
        "computer.process",
        "udb:computer",
        False,
        False,
        True,
        True,
        "critical",
        False,
    ),
    "virtual_pointer": (
        "computer.desktop",
        "udb:computer",
        False,
        False,
        True,
        True,
        "high",
        False,
    ),
    # External network access and resumable jobs are separately granted.
    "propose_media_download": (
        "project.download",
        "udb:download",
        False,
        False,
        False,
        True,
        "high",
        False,
    ),
    "work_recovery": (
        "jobs.recovery",
        "udb:jobs",
        False,
        False,
        True,
        False,
        "high",
        False,
    ),
}

DEFAULT_READ_TOOLS = frozenset(
    {
        "bridge_status",
        "list_projects",
        "list_files",
        "read_file",
        "search_files",
        "check_python_syntax",
    }
)


def _entry(name: str, row: tuple) -> dict:
    (
        category,
        scope,
        read_only,
        _legacy_default,
        destructive,
        open_world,
        risk,
        local_approval,
    ) = row
    return {
        "category": category,
        "scopes": [scope],
        "readOnly": read_only,
        "defaultEnabled": name in DEFAULT_READ_TOOLS,
        "destructive": destructive,
        "idempotent": read_only or name in {"desktop_stop", "host_close_session"},
        "openWorld": open_world,
        "risk": risk,
        "requiresLocalApproval": local_approval,
        "parallelSafe": name in DEFAULT_READ_TOOLS,
    }


TOOL_POLICY = MappingProxyType(
    {name: MappingProxyType(_entry(name, row)) for name, row in _RAW_POLICY.items()}
)
ALL_TOOL_NAMES = tuple(_RAW_POLICY)
READ_ONLY_TOOLS = frozenset(
    name for name, policy in TOOL_POLICY.items() if policy["readOnly"]
)
PRIVILEGED_TOOLS = frozenset(
    name for name, policy in TOOL_POLICY.items() if not policy["defaultEnabled"]
)


def validate_tool_policy(tools: Iterable[str | dict]) -> None:
    items = list(tools)
    names = [item.get("name") if isinstance(item, dict) else item for item in items]
    if any(not isinstance(name, str) for name in names):
        raise RuntimeError("Public tool catalog contains malformed entries")
    if len(names) != len(set(names)):
        raise RuntimeError("Public tool catalog contains duplicate names")
    expected, actual = set(TOOL_POLICY), set(names)
    missing, unknown = sorted(actual - expected), sorted(expected - actual)
    if missing or unknown:
        raise RuntimeError(
            "Tool policy/catalog mismatch: "
            f"unclassified={missing}; catalog_missing={unknown}"
        )
    if len(names) != 59:
        raise RuntimeError(
            f"UDB public tool catalog must contain 59 tools, found {len(names)}"
        )
    if DEFAULT_READ_TOOLS != frozenset(
        {
            "bridge_status",
            "list_projects",
            "list_files",
            "read_file",
            "search_files",
            "check_python_syntax",
        }
    ):
        raise RuntimeError("Default tool grant changed without review")
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item["name"]
        policy = TOOL_POLICY[name]
        scopes = policy["scopes"]
        if len(scopes) != 1 or scopes[0] not in SCOPES:
            raise RuntimeError(f"Invalid scope policy for {name}")
        if policy["defaultEnabled"] and not policy["readOnly"]:
            raise RuntimeError(f"Mutating tool cannot be enabled by default: {name}")
        annotations = item.get("annotations") or {}
        for field, policy_field in (
            ("readOnlyHint", "readOnly"),
            ("destructiveHint", "destructive"),
            ("openWorldHint", "openWorld"),
        ):
            if field in annotations and annotations[field] != policy[policy_field]:
                raise RuntimeError(
                    f"Tool annotation/policy mismatch for {name}: "
                    f"{field}={annotations[field]!r}, "
                    f"policy={policy[policy_field]!r}"
                )


def policy_for(name: str) -> dict | None:
    policy = TOOL_POLICY.get(name)
    return dict(policy) if policy is not None else None


def required_scopes(name: str) -> tuple[str, ...]:
    policy = TOOL_POLICY.get(name)
    return tuple(policy["scopes"]) if policy else ()
