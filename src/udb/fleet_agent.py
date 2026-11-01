"""Loopback-only Multi-PC agent. Publish ONLY with Tailscale Serve (not Funnel).

The machine owner must start this process in an attended local terminal.
Existing UDB owner grants are checked by the normal local MCP backend.
"""
from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .desktop import mcp_command
from .fleet import READ_ONLY_TOOLS, load_secret, valid_device_id
from .onboarding import attended_console
from .transport import StdioChild

MAX_BODY = 256 * 1024
MAX_RESULT = 8 * 1024 * 1024


class FleetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "UDB-Fleet"

    def log_message(self, *args):
        # URLs/tokens/tool input are deliberately not sent to webserver logs.
        pass

    def respond(self, code, value):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.respond(404, {"error": "Not found"})

    def do_POST(self):
        agent = self.server
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(
            supplied.encode("utf-8", "ignore"),
            ("Bearer " + agent.token).encode("ascii"),
        ):
            self.respond(403, {"error": "Forbidden"})
            return
        if self.path != "/v1/call":
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            self.respond(413, {"error": "Invalid request size"})
            return
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or set(data) != {"tool", "arguments"}:
                raise ValueError("Invalid request")
            tool, args = data["tool"], data["arguments"]
            if (
                not isinstance(tool, str)
                or tool not in agent.tool_names
                or tool.startswith("fleet_")
                or not isinstance(args, dict)
            ):
                raise ValueError("Unknown tool or arguments")
            if not agent.allow_control and tool not in READ_ONLY_TOOLS:
                self.respond(403, {"error": "Owner has not enabled remote control"})
                return
            # No retries after uncertain outcomes. Every tool goes through UDB's
            # existing owner-permission and protected-path checks.
            reply = agent.backend.request(
                "tools/call", {"name": tool, "arguments": args}, timeout=60
            )
            if reply.get("error"):
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": "ERROR | Remote UDB rejected tool call"}],
                }
            else:
                result = reply.get("result", {})
            if not isinstance(result, dict):
                raise ValueError("Invalid backend result")
            serialized = json.dumps(result, ensure_ascii=False)
            if len(serialized.encode("utf-8")) > MAX_RESULT:
                raise ValueError("Backend response too large")
            self.respond(200, {"device_id": agent.device_id, "result": result})
        except (TypeError, ValueError, KeyError):
            self.respond(400, {"error": "Invalid fleet request"})
        except (OSError, RuntimeError, TimeoutError):
            self.respond(502, {"error": "Remote operation unavailable; outcome unknown"})


class FleetHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 4

    def __init__(self, address, handler, *, token, device_id, backend,
                 tool_names, allow_control):
        super().__init__(address, handler)
        self.token = token
        self.device_id = device_id
        self.backend = backend
        self.tool_names = frozenset(tool_names)
        self.allow_control = allow_control


def run_agent(home: Path, device_id: str, port: int = 18743,
              allow_control: bool = False) -> int:
    if not valid_device_id(device_id) or not (1024 <= port <= 65535):
        raise ValueError("Invalid fleet device ID or port")
    if not attended_console():
        raise ValueError("Fleet agent must be started from an attended local terminal")
    token = load_secret(home, device_id)
    if allow_control:
        response = input(
            "Remote UDB tools may control this Windows account. "
            "Type ALLOW FLEET to proceed: "
        )
        if response != "ALLOW FLEET":
            raise ValueError("Local owner did not enable fleet control")
    backend = StdioChild(
        "Fleet local UDB", mcp_command(home), str(home), lambda _message: None
    )
    backend.start()
    try:
        init = backend.request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "udb-fleet-agent", "version": "0.1"},
        }, timeout=30)
        if init.get("error"):
            raise RuntimeError("Fleet local MCP initialization failed")
        backend.notification({"jsonrpc": "2.0", "method": "notifications/initialized"})
        catalog = backend.request("tools/list", {}, timeout=30)
        if catalog.get("error"):
            raise RuntimeError("Fleet local tool discovery failed")
        tools = catalog.get("result", {}).get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("Fleet local tool catalog invalid")
        tool_names = [
            row["name"] for row in tools
            if isinstance(row, dict) and isinstance(row.get("name"), str)
        ]
        with FleetHTTPServer(
            ("127.0.0.1", port), FleetHandler, token=token,
            device_id=device_id, backend=backend,
            tool_names=tool_names, allow_control=allow_control,
        ) as server:
            print(
                f"UDB fleet agent {device_id} listens on 127.0.0.1:{port}. "
                "Use Tailscale Serve, NEVER Funnel/public port forwarding."
            )
            server.serve_forever(poll_interval=0.25)
        return 0
    finally:
        backend.close()
