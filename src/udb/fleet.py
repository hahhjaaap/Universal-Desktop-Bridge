"""Opt-in Multi-PC routing for UDB over an owner-managed Tailscale Serve URL.

Transport: verified HTTPS *.ts.net to a loopback-only local agent, with a
separate high-entropy bearer token. No public listening socket or credential
configuration is exposed as a ChatGPT tool. No failover to the wrong machine.
"""

from __future__ import annotations

import hmac
import json
import re
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,31}")
MAX_RESPONSE = 8 * 1024 * 1024
READ_ONLY_TOOLS = frozenset({
    "bridge_status", "computer_status", "host_status", "list_projects",
    "list_files", "read_file", "search_files", "check_python_syntax",
    "file_list", "file_read", "file_stat", "file_search", "file_read_lines",
    "system_process_list", "terminal_list",
})


def valid_device_id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value))


def validate_url(value: Any) -> str:
    """Only Tailscale-issued HTTPS hostnames; no embedded credentials or path."""
    if not isinstance(value, str) or len(value) > 253:
        raise ValueError("Invalid remote URL")
    try:
        u = urlsplit(value)
        hostname = u.hostname or ""
        if (
            u.scheme != "https"
            or u.username or u.password
            or u.port not in (None, 443)
            or u.path not in ("", "/")
            or u.query or u.fragment
            or not hostname.endswith(".ts.net")
            or len(hostname) <= len(".ts.net")
            or any(not re.fullmatch(r"[a-zA-Z0-9-]{1,63}", part)
                   for part in hostname.split(".")[:-2])
        ):
            raise ValueError("Invalid remote URL")
    except (ValueError, AttributeError):
        raise ValueError("Remote URL must be an HTTPS *.ts.net origin") from None
    return "https://" + hostname.lower()


def secret_path(home: Path, device_id: str) -> Path:
    if not valid_device_id(device_id):
        raise ValueError("Invalid device ID")
    return home / "state" / "fleet-secrets" / (device_id + ".token")


def load_secret(home: Path, device_id: str) -> str:
    path = secret_path(home, device_id)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Fleet token path may not be a symlink")
    value = path.read_text(encoding="ascii").strip()
    if not (43 <= len(value) <= 256 and re.fullmatch(r"[A-Za-z0-9_-]+", value)):
        raise ValueError("Invalid fleet token")
    return value


class FleetRouter:
    """Configured on the hub only; configuration cannot be changed via MCP."""

    def __init__(self, home: Path, local_id: str, remotes: dict[str, str]):
        self.home = home
        self.local_id = local_id
        self.remotes = dict(remotes)

    @classmethod
    def from_home(cls, home: Path) -> "FleetRouter | None":
        path = home / "state" / "fleet.json"
        if not path.exists():
            return None
        if path.is_symlink() or path.stat().st_size > 16_384:
            raise ValueError("Invalid fleet configuration")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema", "local_id", "remotes"}:
            raise ValueError("Invalid fleet configuration schema")
        if data["schema"] != 1 or not valid_device_id(data["local_id"]):
            raise ValueError("Invalid fleet configuration version or local ID")
        remotes = data["remotes"]
        if not isinstance(remotes, list) or not 1 <= len(remotes) <= 16:
            raise ValueError("Fleet needs 1..16 remotes")
        mapping: dict[str, str] = {}
        for remote in remotes:
            if not isinstance(remote, dict) or set(remote) != {"id", "url"}:
                raise ValueError("Invalid fleet remote")
            key = remote["id"]
            if not valid_device_id(key) or key == data["local_id"] or key in mapping:
                raise ValueError("Duplicate, invalid, or local device ID")
            mapping[key] = validate_url(remote["url"])
        return cls(home, data["local_id"], mapping)

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        return [
            {
                "name": "fleet_list_computers",
                "description": (
                    "List the configured local and remote UDB machines. "
                    "A configured remote is not necessarily online."
                ),
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "fleet_call",
                "description": (
                    "Run exactly one UDB tool on the specified device. "
                    "Use fleet_list_computers first; computer_id is required. "
                    "No cross-device fallback, auto-retry or permission escalation. "
                    "The destination machine retains its own UDB owner grants."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "computer_id": {"type": "string"},
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["computer_id", "tool", "arguments"],
                    "additionalProperties": False,
                },
            },
        ]

    def list_computers(self) -> dict[str, Any]:
        return {
            "computers": [
                {"id": self.local_id, "kind": "local"},
                *[{"id": x, "kind": "remote", "endpoint": self.remotes[x]}
                  for x in sorted(self.remotes)],
            ],
            "note": "Remote entries are configured, not verified online.",
        }

    def invoke(self, computer_id: str, tool: str, arguments: dict[str, Any]) -> dict:
        if computer_id not in self.remotes:
            raise ValueError("Unknown remote computer; no fallback")
        if not isinstance(tool, str) or not tool or tool.startswith("fleet_"):
            raise ValueError("Invalid remote tool")
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be an object")
        payload = json.dumps(
            {"tool": tool, "arguments": arguments}, ensure_ascii=False
        ).encode("utf-8")
        if len(payload) > 256 * 1024:
            raise ValueError("Remote tool arguments exceed 256 KiB")
        req = Request(
            self.remotes[computer_id] + "/v1/call",
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer " + load_secret(self.home, computer_id),
                "Content-Type": "application/json",
            },
        )
        # Never use a proxy from the environment for local tailnet addresses.
        client = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()))
        try:
            with client.open(req, timeout=15) as response:
                if response.status != 200:
                    raise RuntimeError("Remote UDB unavailable")
                raw = response.read(MAX_RESPONSE + 1)
        except Exception as exc:
            # Never expose a token or target URL in an error.
            raise RuntimeError(
                "Remote UDB failed or timed out; outcome unknown. Inspect before retry."
            ) from None
        if len(raw) > MAX_RESPONSE:
            raise RuntimeError("Remote UDB response too large; outcome unknown")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise RuntimeError("Invalid remote UDB response; outcome unknown") from None
        if not isinstance(data, dict) or set(data) != {"device_id", "result"}:
            raise RuntimeError("Invalid remote UDB response; outcome unknown")
        if data["device_id"] != computer_id or not isinstance(data["result"], dict):
            raise RuntimeError("Remote device identity mismatch; no fallback")
        return data["result"]


def text_result(data: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
