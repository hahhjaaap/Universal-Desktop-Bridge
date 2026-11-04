"""Describe connectivity and owner capabilities without changing either."""

from __future__ import annotations


def report(manager: dict, host: dict, computer: dict, projects: list) -> dict:
    worker_ready = host.get("worker_ready") is True
    agent_ready = manager.get("mode") == "headless" or worker_ready
    background = host.get("enabled") is True
    computer_enabled = computer.get("enabled") is True
    writable = sum(bool(p.get("writable")) for p in projects)
    paused = host.get("resources", {}).get("paused", True) is not False
    if not agent_ready or not worker_ready:
        state = "agent_unavailable"
    elif paused:
        state = "paused"
    elif computer_enabled or background:
        state = "ready"
    elif writable:
        state = "project_only"
    else:
        state = "read_only"
    actions = []
    if not agent_ready or not worker_ready:
        actions.append("Run udb start in the local owner terminal.")
    if paused and worker_ready:
        actions.append(
            "Inspect local pause/resource status; remote calls cannot clear an owner pause."
        )
    if not computer_enabled:
        actions.append(
            "For computer control, the owner must run udb --access computer locally."
        )
    if not background:
        actions.append(
            "For owned browser sessions, enable background access in the local UDB manager."
        )
    return {
        "state": state,
        "transport_verified": False,
        "agent_ready": agent_ready,
        "worker_ready": worker_ready,
        "computer_authorized": computer_enabled,
        "background_authorized": background,
        "readable_projects": len(projects),
        "writable_projects": writable,
        "resource_paused": paused,
        "next_actions": actions,
        "catalog_hint": "Refresh the MCP tool catalog after updating. Clients/plugins with fixed tool allowlists must expose the required canonical tools; refreshing cannot change that allowlist or grant access.",
        "permissions_changed": False,
    }
