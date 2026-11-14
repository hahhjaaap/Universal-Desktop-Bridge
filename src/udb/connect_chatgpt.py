"""Safe ChatGPT handoff for an already owner-paired UDB device.

This supports a private custom MCP server, not self-service signup.
Opening ChatGPT never installs a plugin or grants Windows permissions.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from collections.abc import Callable

from .connection import cloud_mcp_url
from .onboarding import CHATGPT_URL, paired_cloud


def _print_status(status: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(status, sort_keys=True))
        return
    if status["state"] == "needs_enrollment":
        print("UDB: This device is not yet enrolled in the private UDB relay.")
        print("From a trusted local terminal: udb connect --setup")
        print("A one-time private invitation is required from the relay owner.")
        print("Never paste a shared administrator key or someone else's device token.")
        return
    if status["state"] == "invalid_pairing":
        print(
            "UDB: Existing device pairing is invalid. No fallback or auto-registration was attempted."
        )
        print(
            "Contact the service operator to revoke/recover this device; do not copy tokens."
        )
        return
    print("UDB: Device paired, but ChatGPT authorization is NOT verified.")
    print("MCP endpoint for this device: " + status["mcp_url"])
    print("ChatGPT Plugins: " + CHATGPT_URL)
    print("In ChatGPT Plugins, select Add custom MCP server (private).")
    print("Paste the MCP endpoint above and choose the configured OAuth method.")
    print("Approve access in ChatGPT, then call bridge_status to verify.")
    print("Keep the Cloud Agent running: udb start; check it with udb status.")
    if not status["browser_opened"]:
        print("Browser was not opened; use the ChatGPT Plugins link above.")


def run(
    settings,
    *,
    as_json: bool = False,
    open_browser: bool = True,
    opener: Callable[[str], object] | None = None,
    setup: bool = False,
    autostart: bool = False,
) -> int:
    """Optional owner-attended private setup; never bypass ChatGPT OAuth consent."""
    if (setup or autostart) and as_json:
        print("UDB: Setup/autostart cannot run in JSON mode.", file=sys.stderr)
        return 2
    if autostart and not setup:
        print(
            "UDB: Use --setup --autostart from your own Windows console.",
            file=sys.stderr,
        )
        return 2
    if setup:
        from .onboarding import attended_console, setup_cloud

        if not attended_console():
            print(
                "UDB: Private enrollment must run in an attended Windows terminal.",
                file=sys.stderr,
            )
            return 2
        # Reuse existing one-time code and Credential Manager pairing; never
        # accept an admin token or invitation in command-line arguments.
        try:
            if setup_cloud(settings):
                return 2
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt):
            print(
                "UDB: Private pairing failed or was canceled; no ChatGPT authorization.",
                file=sys.stderr,
            )
            return 2
        if autostart:
            try:
                from .autostart import run as autostart_run
                from .owner_command import CommandError

                if settings.enable_terminal:
                    raise CommandError(
                        "Cloud Agent autostart requires terminal access off"
                    )
                if autostart_run(settings, "enable", cloud_agent=True):
                    return 2
            except (CommandError, OSError, ValueError):
                print(
                    "UDB: Pairing kept; automatic Cloud Agent startup was not enabled. "
                    "Run udb autostart status and retry from a local console.",
                    file=sys.stderr,
                )
                return 2

    try:
        paired = paired_cloud(settings.home)
    except (OSError, ValueError, KeyError, TypeError):
        _print_status(
            {"state": "invalid_pairing", "paired": False, "chatgpt_verified": False},
            as_json=as_json,
        )
        return 2
    if not paired:
        _print_status(
            {"state": "needs_enrollment", "paired": False, "chatgpt_verified": False},
            as_json=as_json,
        )
        return 2

    # This device URL identifies a resource, not a device token or local grant.
    try:
        url = cloud_mcp_url(settings.home)
    except (OSError, ValueError, KeyError, TypeError):
        _print_status(
            {"state": "invalid_pairing", "paired": False, "chatgpt_verified": False},
            as_json=as_json,
        )
        return 2

    opened = False
    if open_browser and not as_json:
        try:
            opened = bool((opener or webbrowser.open)(CHATGPT_URL))
        except (OSError, RuntimeError, webbrowser.Error):
            opened = False
    _print_status(
        {
            "state": "ready_to_authorize_in_chatgpt",
            "paired": True,
            "chatgpt_verified": False,
            "mcp_url": url,
            "chatgpt_plugins_url": CHATGPT_URL,
            "browser_opened": opened,
        },
        as_json=as_json,
    )
    return 0
