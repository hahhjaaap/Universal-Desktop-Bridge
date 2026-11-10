"""Optional current-user logon startup. No elevation or permission activation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

from .config import checked
from .launcher import command
from .maintenance import installation
from .owner_command import CommandError, read_text
from .windows_paths import system_executable

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SCRIPT_HEADER = "# UDB logon startup schema 1\n"


def identity(home):
    return "UDB-" + hashlib.sha256(str(home).casefold().encode()).hexdigest()[:16]


def script_path(settings):
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    return checked(
        base / "UniversalDesktopBridge/startup" / (identity(settings.home) + ".ps1")
    )


def script_text(settings, *, cloud_agent=False):
    found = installation()
    if found:
        root, record = found
        if record["home"] != str(settings.home):
            raise CommandError("Use the managed launcher's saved home for autostart.")
        launcher = [
            system_executable("powershell.exe"),
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "bin/udb.ps1"),
        ]
        argv = [*launcher, "start", "--detach"]
    else:
        launcher = None
        argv = command(["--home", str(settings.home), "start", "--detach"])
    if cloud_agent:
        argv.append("--offline")
    argv += [
        "--root",
        str(settings.project_root),
        "--disable-terminal"
        if cloud_agent
        else (
            "--enable-terminal" if settings.enable_terminal else "--disable-terminal"
        ),
    ]
    if settings.core_exe:
        argv += ["--core-exe", str(settings.core_exe)]

    def quoted(args):
        # Literal PowerShell arguments prevent path interpolation and injection.
        return (
            "& " + " ".join("'" + part.replace("'", "''") + "'" for part in args) + "\n"
        )

    script = SCRIPT_HEADER
    if cloud_agent:
        script += "# Cloud Agent opt-in: owner-attended local installation\n"
    script += "$ErrorActionPreference = 'Stop'\n" + quoted(argv)
    if cloud_agent:
        # Cloud Agent stays in the hidden logon process; the local Manager is
        # started first in offline mode, without owner/terminal access.
        cloud_argv = (
            [*launcher, "cloud-agent", "--home", str(settings.home)]
            if launcher is not None
            else command(["--home", str(settings.home), "cloud-agent"])
        )
        cloud_argv += [
            "--root",
            str(settings.project_root),
            "--disable-terminal",
        ]
        script += "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        script += quoted(cloud_argv)
    return script + "exit $LASTEXITCODE\n"


def startup_command(settings):
    # Run-key values are limited to 260 characters. Keep arguments in an owned
    # local helper instead of putting a long encoded command in the registry.
    value = subprocess.list2cmdline(
        [
            system_executable("powershell.exe"),
            "-NoP",
            "-NonI",
            "-W",
            "Hidden",
            "-EP",
            "Bypass",
            "-F",
            str(script_path(settings)),
        ]
    )
    if len(value) > 260:
        raise CommandError(
            "The Windows startup command exceeds its path limit. Use udb start on this installation."
        )
    return value


def write_script(settings, *, cloud_agent=False):
    path = script_path(settings)
    if path.exists() and not read_text(path, 65536).startswith(SCRIPT_HEADER):
        raise CommandError(
            "The startup helper contains unrelated content; preserved it."
        )
    text = script_text(settings, cloud_agent=cloud_agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    checked(path)
    temporary = path.with_name(".startup-" + uuid.uuid4().hex + ".tmp")
    try:
        # A BOM lets Windows PowerShell 5 read Unicode account/project paths.
        with temporary.open("x", encoding="utf-8-sig", newline="\n") as stream:
            stream.write(text)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def status(settings, backend=None):
    if os.name != "nt" and backend is None:
        return {"supported": False, "enabled": False, "matches_current": False}
    if backend is None:
        import winreg as backend
    try:
        with backend.OpenKey(backend.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = backend.QueryValueEx(key, identity(settings.home))
        path = script_path(settings)
        content = read_text(path, 65536) if path.is_file() else ""
        local_match = content == script_text(settings)
        cloud_match = content == script_text(settings, cloud_agent=True)
        if cloud_match:
            from .onboarding import paired_cloud

            try:
                cloud_match = paired_cloud(settings.home) is not None
            except (OSError, ValueError, KeyError, TypeError):
                cloud_match = False
        return {
            "supported": True,
            "enabled": True,
            "matches_current": kind == backend.REG_SZ
            and value == startup_command(settings)
            and (local_match or cloud_match),
            "cloud_agent_enabled": cloud_match,
        }
    except FileNotFoundError:
        return {
            "supported": True,
            "enabled": False,
            "matches_current": False,
            "cloud_agent_enabled": False,
        }


def run(settings, action, *, as_json=False, backend=None, cloud_agent=False):
    if os.name != "nt" and backend is None:
        raise CommandError("Autostart requires Windows.")
    if backend is None:
        import winreg as backend
    if action not in ("enable", "disable", "status"):
        raise CommandError("Choose autostart enable, disable or status.")
    if cloud_agent and action != "enable":
        raise CommandError("--cloud-agent only applies to autostart enable.")
    if action == "enable":
        # Never enable an unattended cloud connection from a remote tool call.
        from .onboarding import (
            attended_console,
            paired_cloud,
            saved_connection,
            saved_mode,
        )

        pairing = paired_cloud(settings.home)
        if cloud_agent and not pairing:
            raise CommandError("Pair this Cloudflare device locally first.")
        if cloud_agent and not attended_console():
            raise CommandError(
                "Cloud Agent autostart requires an attended local Windows terminal."
            )
        if (
            saved_mode(settings) != "offline"
            and not saved_connection(settings)
            and not pairing
        ):
            raise CommandError("Run udb setup before enabling autostart.")
        if cloud_agent and settings.enable_terminal:
            raise CommandError("Disable terminal access before Cloud Agent autostart.")
        value = startup_command(settings)
        write_script(settings, cloud_agent=cloud_agent)
        with backend.CreateKeyEx(
            backend.HKEY_CURRENT_USER, RUN_KEY, 0, backend.KEY_SET_VALUE
        ) as key:
            backend.SetValueEx(key, identity(settings.home), 0, backend.REG_SZ, value)
    elif action == "disable":
        try:
            with backend.OpenKey(
                backend.HKEY_CURRENT_USER, RUN_KEY, 0, backend.KEY_SET_VALUE
            ) as key:
                backend.DeleteValue(key, identity(settings.home))
        except FileNotFoundError:
            pass
        path = script_path(settings)
        if path.is_file() and read_text(path, 65536).startswith(SCRIPT_HEADER):
            path.unlink()
    report = status(settings, backend)
    print(
        json.dumps(report)
        if as_json
        else f"UDB logon startup: {'enabled' if report['enabled'] else 'disabled'}. Run udb start to view logs."
    )
    return 0
