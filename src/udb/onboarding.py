"""Attended console setup. No credentials or owner decisions pass through MCP."""

from __future__ import annotations

import json
import os
import sys
import uuid

from .config import checked
from .connection import is_tunnel_id

CHATGPT_URL = "https://chatgpt.com/plugins"


def paired_cloud(home):
    """Return validated public pairing metadata, without reading device secrets.

    A malformed pairing must fail closed, never fall back to Tunnel setup.
    """
    path = home / "cloud-pairing.json"
    if not path.exists() and not path.is_symlink():
        return None
    from .cloud_agent import load_pairing

    relay, device_id, _token_path = load_pairing(home)
    return relay, device_id


def setup_cloud(settings):
    if not console_input():
        raise ValueError("Cloudflare setup requires an attended Windows terminal.")
    from .connection import cloud_mcp_url

    if not paired_cloud(settings.home):
        from .cloud_pair import run as pair

        result = pair(settings)
        if result:
            return result
    endpoint = cloud_mcp_url(settings.home)
    print("Cloudflare MCP: " + endpoint)
    print("UDB Live activity: udb live or udb live --gui")
    print("Start the Windows agent with 'udb start'. Use OAuth in " + CHATGPT_URL)
    return 0


def _console_stream(stream):
    if os.name != "nt" or stream is None:
        return False
    try:
        if not stream.isatty():
            return False
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetConsoleMode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.GetConsoleMode.restype = wintypes.BOOL
        mode = wintypes.DWORD()
        handle = msvcrt.get_osfhandle(stream.fileno())
        return bool(kernel.GetConsoleMode(wintypes.HANDLE(handle), ctypes.byref(mode)))
    except (ImportError, AttributeError, OSError, ValueError):
        return False


def console_input():
    # Windows NUL is a character device: isatty() alone does not prove a console.
    return _console_stream(sys.stdin)


def attended_console():
    return console_input() and _console_stream(sys.stdout)


def saved_connection(settings, *, repair=False):
    from . import owner_command

    path = checked(settings.home / "state/connection.json")
    if not path.exists():
        return None
    try:
        data = owner_command.read_object(path, 4096)
    except (OSError, ValueError, owner_command.CommandError):
        if repair:
            return None
        raise ValueError(
            "Saved connection could not be read. Run udb setup --edit locally."
        ) from None
    value = data.get("tunnel_id")
    return value if is_tunnel_id(value) else None


def saved_mode(settings):
    from . import owner_command

    path = checked(settings.home / "state/startup-preferences.json")
    if not path.exists():
        return None
    try:
        data = owner_command.read_object(path, 512)
        if (
            set(data) != {"schema", "mode"}
            or type(data["schema"]) is not int
            or data["schema"] != 1
            or data["mode"] not in ("online", "offline")
        ):
            raise ValueError()
    except (OSError, ValueError, owner_command.CommandError):
        raise ValueError(
            "Saved startup mode is invalid. Run udb setup to select it again."
        ) from None
    return data["mode"]


def save_mode(settings, mode):
    if mode not in ("online", "offline"):
        raise ValueError("Invalid startup mode")
    path = checked(settings.home / "state/startup-preferences.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    checked(path)
    temporary = path.with_name(".startup-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump({"schema": 1, "mode": mode}, stream)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
