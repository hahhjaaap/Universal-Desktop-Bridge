"""Fast, local-only UDB startup without an OAuth or tunnel dependency.

An offline manager can run independently of Cloudflare, ChatGPT, or Desktop
Commander. This command does not enroll a remote device or grant host control.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout

from . import owner_command
from .owner_command import CommandError


def _emit(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    if payload["result"] == "local_ready":
        print("UDB local manager: READY (offline).")
        print("Local MCP client setup: udb mcp-config")
        print("Open the desktop GUI: udb gui")
        if payload["autostart"] == "enabled":
            print("Automatic Windows logon startup: enabled.")
        else:
            print("Automatic Windows logon startup: unchanged (opt in separately).")
        print("ChatGPT remote connection: NOT VERIFIED; local mode is independent.")
    else:
        print(
            "UDB local quickstart: " + payload["reason"]
            + ". Run udb doctor --json for local diagnostics.",
            file=sys.stderr,
        )


def run(settings, *, wait: int = 30, as_json=False, enable_autostart=False) -> int:
    """Start the existing owner-scoped local manager; never switch a live mode."""
    if type(wait) is not int or not 1 <= wait <= 60:
        raise ValueError("Quickstart wait must be between 1 and 60 seconds.")

    try:
        if enable_autostart:
            if os.name != "nt":
                raise ValueError("Autostart requires Windows.")
            from .onboarding import paired_cloud, saved_connection, saved_mode

            # A one-command local shortcut cannot silently replace a remote
            # profile's startup behavior. The explicit attended setup remains
            # the way to switch a profile between local and remote.
            if (
                paired_cloud(settings.home)
                or saved_connection(settings)
                or saved_mode(settings) == "online"
            ):
                _emit(
                    {"result": "blocked", "reason": "remote_profile_requires_setup"},
                    as_json=as_json,
                )
                return 2

        report = owner_command.start(
            settings.home,
            owner_command.executable(settings.home),
            wait=wait,
            connect=False,
        )
        if not (
            report.get("manager_running") is True
            and report.get("manager_mode") == "headless"
            and report.get("connection_mode") == "offline"
        ):
            _emit(
                {"result": "blocked", "reason": "local_manager_not_ready"},
                as_json=as_json,
            )
            return 2

        startup = "unchanged"
        if enable_autostart:
            from .autostart import run as autostart_run
            from .onboarding import save_mode, saved_mode

            # Only an explicit --autostart writes the local startup preference
            # and current-user HKCU Run entry. A normal quickstart is ephemeral.
            if saved_mode(settings) is None:
                save_mode(settings, "offline")
            with redirect_stdout(io.StringIO()):
                autostart_run(settings, "enable")
            startup = "enabled"

        _emit(
            {
                "result": "local_ready",
                "local_manager": "running",
                "connection_mode": "offline",
                "autostart": startup,
                "chatgpt_remote_verified": False,
                "next_step": "udb mcp-config",
            },
            as_json=as_json,
        )
        return 0
    except (CommandError, OSError, ValueError):
        # Never echo arbitrary host paths, credentials, child output or
        # details read from a malformed local pairing/connection file.
        _emit(
            {"result": "blocked", "reason": "local_configuration_or_mode_error"},
            as_json=as_json,
        )
        return 2
