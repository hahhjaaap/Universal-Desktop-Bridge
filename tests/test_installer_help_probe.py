"""Verify installer feature detection across old and simplified CLI help."""

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 contract")
def test_installer_detects_both_help_formats_without_touching_owner_state():
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    start = installer.index("function Test-CloudflareOnlyHelp")
    end = installer.index("function Start-Agent", start)
    # Source only these pure helper functions. Never run the installer body.
    pure_functions = installer[start:end]
    assertions = r"""
if (-not (Test-CloudflareOnlyHelp 'usage: udb {start,stop,live,doctor}')) { exit 11 }
$short = "UDB help" + [Environment]::NewLine + "  udb live        Watch activity"
if (-not (Test-CloudflareOnlyHelp $short)) { exit 12 }
if (Test-CloudflareOnlyHelp 'usage: udb {start,stop,logs,doctor}') { exit 13 }
$old = "UDB help" + [Environment]::NewLine + "  udb logs        Old logs"
if (Test-CloudflareOnlyHelp $old) { exit 14 }
if (Test-CloudflareOnlyHelp 'A sentence mentions live activity') { exit 15 }
"""
    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            pure_functions + "\n" + assertions,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_installer_detection_remains_a_read_only_help_probe():
    # Prevent refactors that replace the non-mutating capability probe
    # with an update, pairing or network endpoint call.
    source = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    start = source.index("function Test-CloudflareOnlyRelease")
    end = source.index("function Start-Agent", start)
    probe = source[start:end]
    assert "& $Image --help" in probe
    assert "Test-CloudflareOnlyHelp $helpText" in probe
    assert not any(
        command in probe
        for command in ("& $Image start", "& $Image setup", "Invoke-WebRequest")
    )
