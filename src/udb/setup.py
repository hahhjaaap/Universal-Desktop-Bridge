"""Attended, resumable setup. Diagnostics never grant permissions or imply OAuth."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
import webbrowser
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import build_opener

from . import autostart, cloud_secrets, owner_command
from .build_identity import runtime_identity
from .cloud_pair import NoRedirect
from .config import activate, checked
from .launcher import child_environment, command
from .onboarding import CHATGPT_URL, attended_console, paired_cloud
from .private_enrollment import PRIVATE_RELAY, _request_json
from .setup_enrollment import EnrollmentError, enroll, link_existing


class SetupError(ValueError):
    pass


def installation_status():
    from .maintenance import installation

    managed = installation() if getattr(sys, "frozen", False) else None
    result = {
        **runtime_identity(),
        "managed": bool(managed),
        "integrity": "source" if not getattr(sys, "frozen", False) else "unavailable",
    }
    if getattr(sys, "frozen", False):
        executable = checked(sys.executable)
        manifest = executable.with_name("STANDALONE-SHA256SUMS")
        if manifest.exists():
            text = owner_command.read_text(manifest, 65536)
            hashes = [
                line.split()[0]
                for line in text.splitlines()
                if len(line.split()) == 2
                and line.split()[1].lstrip("*") == executable.name
            ]
            if len(hashes) != 1 or len(hashes[0]) != 64:
                raise SetupError(
                    "Installed integrity manifest is invalid; repair the installation"
                )
            actual = hashlib.sha256()
            with executable.open("rb") as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    actual.update(block)
            if actual.hexdigest() != hashes[0].lower():
                raise SetupError(
                    "Installed EXE integrity failed; repair the installation"
                )
            result["integrity"] = "manifest_sha256"
    return result


def journal_path(home):
    return checked(Path(home) / "state/setup.json")


def read_journal(home):
    path = journal_path(home)
    if not path.exists():
        return {"schema": 1, "phase": "inspect"}
    value = owner_command.read_object(path, 4096)
    if value.get("schema") != 1 or set(value) - {
        "schema",
        "phase",
        "autostart_decision",
        "challenge",
    }:
        raise SetupError("Invalid setup progress; owner repair required")
    if value.get("autostart_decision") not in (None, "accepted", "declined"):
        raise SetupError("Invalid saved startup decision")
    challenge = value.get("challenge")
    if challenge is not None and (
        not isinstance(challenge, str)
        or len(challenge) != 64
        or any(c not in "0123456789abcdef" for c in challenge)
    ):
        raise SetupError("Invalid saved verification challenge")
    return value


def save_journal(home, state):
    path = journal_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_nlink != 1:
        raise SetupError("Linked setup progress refused")
    temporary = checked(path.with_name(".setup-" + uuid.uuid4().hex + ".tmp"))
    try:
        with temporary.open("x", encoding="ascii") as stream:
            json.dump(state, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def device_status(opener, relay, device_id, token):
    status, result = _request_json(
        opener, relay + "/v1/devices/" + device_id + "/setup/status", proof=token
    )
    if (
        status != 200
        or not isinstance(result, dict)
        or result.get("token_valid") is not True
    ):
        raise SetupError("Relay could not verify this device credential")
    return result


def inspect(settings, opener=None):
    """Read-only: no journals, credentials, browser, process or Run-key writes."""
    opener = opener or build_opener(NoRedirect())
    result = {
        "installation": installation_status(),
        "phase": "inspect",
        "paired": False,
        "credential_valid": False,
        "relay_reachable": False,
        "cloud_agent_online": False,
        "authenticated_mcp_verified": False,
        "chatgpt_connected": False,
        "client_attribution": "unavailable",
        "autostart": autostart.status(settings),
        "recovery": "Run udb setup to continue.",
    }
    pairing = paired_cloud(settings.home)
    if not pairing:
        _, capabilities = _request_json(opener, PRIVATE_RELAY + "/v1/setup")
        result.update(
            relay_reachable=True,
            browser_enrollment=capabilities.get("browser_enrollment") is True,
        )
        return result
    relay, device_id = pairing
    result.update(paired=True, mcp_url=relay + "/v1/devices/" + device_id + "/mcp")
    try:
        token = cloud_secrets.load_device_token(settings.home, device_id)
    except Exception:
        result["failure"] = "credential_unavailable"
        result["recovery"] = (
            "Existing pairing retained. Restore this Windows user's device credential with the relay owner."
        )
        return result
    try:
        remote = device_status(opener, relay, device_id, token)
    except HTTPError as error:
        result["failure"] = (
            "credential_denied" if error.code in (401, 403) else "relay_unavailable"
        )
        result["recovery"] = (
            "Existing pairing retained. Check relay access with the owner, then run udb setup."
        )
        return result
    except (OSError, ValueError):
        result["failure"] = "relay_unreachable"
        return result
    result.update(
        credential_valid=True,
        relay_reachable=True,
        cloud_agent_online=remote.get("cloud_agent_online") is True,
        authenticated_mcp_verified=remote.get("authenticated_mcp_verified") is True,
        verification_method=remote.get("verification_method"),
        verified_at=remote.get("verified_at"),
    )
    return result


def ensure_agent(settings):
    """Reuse the manager and existing cloud-agent lease; never kill an instance."""
    from .config import prepare_workspace

    previous = activate(settings)
    try:
        exe = owner_command.executable(settings.home)
        if not owner_command.manager_running(settings.home, exe):
            owner_command.start(settings.home, exe, connect=False)
        prepare_workspace(settings)
        with owner_command.launch_gate(settings.home / "cloud-start", timeout=0):
            try:
                with owner_command.launch_gate(
                    settings.home / "cloud-agent", timeout=0
                ):
                    pass
            except owner_command.CommandError:
                return False  # Running agent owns its existing lifetime lease.
            subprocess.Popen(
                command(
                    [
                        "cloud-agent",
                        "--home",
                        str(settings.home),
                        "--root",
                        str(settings.project_root),
                        "--disable-terminal",
                    ]
                ),
                cwd=str(settings.home),
                env=child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return True
    finally:
        activate(previous)


def configure_autostart(settings, state, prompt=input):
    current = autostart.status(settings)
    if current.get("enabled"):
        if current.get("matches_current") and current.get("cloud_agent_enabled"):
            return
        if not current.get("matches_current"):
            print("Existing custom startup settings preserved; owner review required.")
            return
        # An owned local-only entry may add the Cloud Agent only after the
        # same explicit attended consent as a fresh autostart installation.
    decision = state.get("autostart_decision")
    if decision is None:
        print("Optional: start UDB and the Cloud Agent when you sign in to Windows.")
        decision = (
            "accepted"
            if prompt("Enable Windows sign-in startup? [y/N] ").strip().lower()
            in ("y", "yes")
            else "declined"
        )
        state["autostart_decision"] = decision
        save_journal(settings.home, state)  # Persist consent before the Run-key write.
    if (
        decision == "accepted"
        and autostart.run(settings, "enable", cloud_agent=True) != 0
    ):
        raise SetupError(
            "Windows startup configuration failed; run udb setup to resume"
        )


def run(
    settings,
    *,
    readonly=False,
    json_output=False,
    opener=None,
    browser=None,
    prompt=input,
    pause=time.sleep,
    clock=time.monotonic,
    verification_wait=120,
):
    opener = opener or build_opener(NoRedirect())
    browser = browser or webbrowser.open
    phase = "inspect"
    try:
        # Security-changing arguments are never needed. The setup controller
        # starts new components with terminal disabled and leaves grants intact.
        if readonly:
            report = inspect(settings, opener)
            print(json.dumps(report, indent=2) if json_output else render(report))
            return (
                0
                if report.get("credential_valid") and report.get("cloud_agent_online")
                else 2
            )
        if not attended_console():
            raise SetupError(
                "Setup requires an attended Windows console; use udb setup --status for diagnostics"
            )
        with owner_command.launch_gate(settings.home / "setup", timeout=0):
            installation_status()
            state = read_journal(settings.home)
            pairing = paired_cloud(settings.home)
            if not pairing:
                phase = "owner_approval"
                _, caps = _request_json(opener, PRIVATE_RELAY + "/v1/setup")
                if (
                    caps.get("protocol") != 2
                    or caps.get("browser_enrollment") is not True
                ):
                    raise SetupError(
                        "Relay owner must configure private browser enrollment first; no URL or admin key is needed on Windows"
                    )
                state["phase"] = phase
                save_journal(settings.home, state)
                enroll(
                    settings.home,
                    opener=opener,
                    browser=browser,
                    pause=pause,
                    clock=clock,
                )
                pairing = paired_cloud(settings.home)
            if pairing is None:
                raise SetupError(
                    "Enrollment completed without pairing metadata; run udb setup to resume"
                )
            relay, device_id = pairing
            token = cloud_secrets.load_device_token(settings.home, device_id)
            # Invalid/revoked/missing credentials stop here. Never auto re-enroll.
            remote = device_status(opener, relay, device_id, token)
            fleet = remote.get("account_fleet") is True
            if fleet:
                phase = "fleet_link"
                _, link_status = _request_json(
                    opener,
                    relay + "/v1/devices/" + device_id + "/fleet/status",
                    proof=token,
                )
                if (
                    not isinstance(link_status, dict)
                    or type(link_status.get("linked")) is not bool
                ):
                    raise SetupError("Fleet linking status was not verified")
                if not link_status["linked"]:
                    link_existing(
                        settings.home,
                        relay,
                        device_id,
                        token,
                        opener=opener,
                        browser=browser,
                        pause=pause,
                        clock=clock,
                    )
            safe = replace(settings, enable_terminal=False)
            phase = "cloud_agent"
            state["phase"] = phase
            save_journal(settings.home, state)
            if remote.get("cloud_agent_online") is not True:
                ensure_agent(safe)
                until = clock() + 30
                while clock() < until:
                    remote = device_status(opener, relay, device_id, token)
                    if remote.get("cloud_agent_online") is True:
                        break
                    pause(1)
                else:
                    raise TimeoutError(
                        "Cloud Agent is not online yet; run udb setup to resume"
                    )
            phase = "autostart"
            configure_autostart(safe, state, prompt)
            phase = "chatgpt_authorization"
            state["phase"] = phase
            endpoint = relay + (
                "/v1/account/mcp" if fleet else "/v1/devices/" + device_id + "/mcp"
            )
            if remote.get("authenticated_mcp_verified") is not True:
                state.setdefault("challenge", secrets.token_hex(32))
                save_journal(settings.home, state)
                _request_json(
                    opener,
                    relay + "/v1/devices/" + device_id + "/setup/challenge",
                    method="POST",
                    proof=token,
                    data={"challenge_sha256": state["challenge"]},
                )
                print("Cloud Agent online. Complete ChatGPT approval in your browser.")
                print(
                    "If this server is already added, call bridge_status through it; do not add a duplicate."
                )
                print(
                    "In "
                    + CHATGPT_URL
                    + ", choose Add custom MCP server once, paste the MCP URL and approve OAuth."
                )
                print("Cloudflare MCP: " + endpoint)
                browser(relay + "/v1/devices/" + device_id + "/connect-chatgpt")
                until = clock() + verification_wait
                while clock() < until:
                    remote = device_status(opener, relay, device_id, token)
                    if remote.get("authenticated_mcp_verified") is True:
                        break
                    pause(min(3, max(0, until - clock())))
            verified = remote.get("authenticated_mcp_verified") is True
            online = remote.get("cloud_agent_online") is True
            state["phase"] = (
                "authenticated_mcp_verified"
                if verified and online
                else "cloud_agent"
                if not online
                else phase
            )
            save_journal(settings.home, state)
            print(
                render(
                    {
                        "paired": True,
                        "cloud_agent_online": online,
                        "authenticated_mcp_verified": verified,
                        "chatgpt_connected": False,
                        "mcp_url": endpoint,
                    }
                )
            )
            return 0 if verified and online else 2
    except KeyboardInterrupt:
        print("Setup paused. Run udb setup to resume the saved request.")
        return 130
    except HTTPError as error:
        reasons = {
            401: "Authorization expired or was refused; existing pairing retained.",
            403: "Credential revoked or access refused; existing pairing retained for owner repair.",
            404: "Relay setup API is unavailable; relay owner must upgrade/configure it.",
            410: "Owner approval expired; the saved request was retained for owner review.",
            429: "Enrollment rate limited; wait before running udb setup again.",
        }
        message = reasons.get(
            error.code, "Relay unavailable. Run udb setup to resume safely."
        )
    except (SetupError, EnrollmentError) as error:
        message = str(error)
    except Exception:
        # No network exception, credential value, request body or arbitrary
        # remote error string is printed to terminal or JSON.
        message = "Setup could not complete this step. Existing pairing and recovery credentials were retained. Run udb setup to resume; use --status for diagnostics."
    print(
        json.dumps({"phase": phase, "complete": False, "error": message})
        if json_output
        else "UDB setup [" + phase + "]: " + message
    )
    return 2


def render(report):
    return "\n".join(
        [
            "Device paired: " + ("yes" if report.get("paired") else "no"),
            "Cloud Agent: "
            + ("online" if report.get("cloud_agent_online") else "pending"),
            "Authenticated MCP: "
            + (
                "verified"
                if report.get("authenticated_mcp_verified")
                else "pending user OAuth"
            ),
            "ChatGPT client identity: not independently attested by this relay",
            "MCP URL: " + report.get("mcp_url", "available after owner approval"),
            report.get(
                "recovery",
                "Run udb setup again to resume or verify. No pairing reset is needed.",
            ),
        ]
    )
