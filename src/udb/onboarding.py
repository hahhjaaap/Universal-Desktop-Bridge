"""Attended console setup. No credentials or owner decisions pass through MCP."""

from __future__ import annotations

import json
import os
import sys
import uuid

from .config import checked, prepare_workspace

CHATGPT_URL = "https://chatgpt.com/plugins"


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
    """Read only the owner-paired device ID; never expose a token."""
    from .cloud_agent import load_pairing

    try:
        _, device_id, _ = load_pairing(settings.home)
        return device_id
    except (OSError, ValueError, TypeError, KeyError):
        return None


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


def connection_help():
    print(
        "UDB Cloudflare-only setup:\n"
        "1/3 Configure an owner-only, path-scoped Cloudflare Access MCP application.\n"
        "2/3 Obtain a short-lived pairing invitation; enter it locally with "
        "udb cloud-pair.\n"
        "3/3 Start UDB Cloud Agent and connect the exact MCP URL at "
        + CHATGPT_URL
        + "\nNo OpenAI Tunnel ID or runtime API key is needed. "
        "The public Cloudflare gateway grants only approved read-only tools."
    )


def run(settings, *, edit=False, local=False):
    """Attended Cloudflare-only pairing and agent startup.

    Offline mode is local diagnostics, not another remote connection path.
    """
    if not console_input():
        raise ValueError(
            "Setup requires your own attended Windows terminal; redirected input is refused."
        )
    if edit and local:
        raise ValueError("Choose either Cloudflare pairing or offline diagnostics")
    from . import owner_command

    checked(settings.home / "state/startup-preferences.json")
    print("UDB Cloudflare setup. No OpenAI Tunnel or runtime API key is used.")
    if getattr(sys, "frozen", False):
        from .components import runtime_report

        try:
            runtime = runtime_report()
            if not all(runtime["office_modules"].values()):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError(
                "Bundled runtime check failed. Reinstall the verified standalone release."
            ) from None

    prepare_workspace(settings)
    paired = saved_connection(settings)
    connect = not local
    if connect and not paired:
        connection_help()
        answer = input("Pair this PC with Cloudflare now? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cloud pairing not changed; offline diagnostics are available.")
            return 0
        from .cloud_pair import run as pair_device

        pair_device(settings)
        paired = saved_connection(settings)
        if not paired:
            raise ValueError("Cloud pairing was not confirmed locally.")
    elif connect:
        print("A Cloudflare device is already paired. Existing secrets are unchanged.")
        if edit:
            print(
                "To replace a paired device, revoke the previous device in Cloudflare "
                "first and follow the owner-attended pairing procedure."
            )
            return 0

    args = ["start", "--home", str(settings.home), "--wait", "60", "--follow"]
    if connect:
        print(
            "Cloud Agent launch is not proof of ChatGPT authorization. "
            "Verify bridge_status from the udb-cloudflare plugin."
        )
        if (
            input("Open the computer-access consent prompt? [y/N]: ").strip().lower()
            == "y"
        ):
            args.extend(["--access", "computer"])
    else:
        args.append("--offline")
        print("Offline diagnostics selected. No remote connection is started.")

    state = owner_command.headless_state(settings.home) or {}
    desired = "online" if connect else "offline"
    if state.get("connection_mode") and state["connection_mode"] != desired:
        if owner_command.main(
            ["stop", "--home", str(settings.home), "--wait", "60", "--json"]
        ):
            raise ValueError("The previous agent did not stop; run udb stop locally.")
    save_mode(settings, desired)
    print("Starting UDB. Use udb doctor for pairing and agent status.")
    return owner_command.main(args)
