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


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 contract")
def test_release_switch_refuses_a_separate_cloud_agent_before_stopping_the_manager(
    tmp_path,
):
    source = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    start = source.index("function Set-ActiveRelease")
    end = source.index("function Register-UdbStartMenu", start)
    pairing = tmp_path / "cloud-pairing.json"
    pairing.write_text("{}", encoding="utf-8")
    harness = r"""
$ErrorActionPreference = 'Stop'
$DataHome = $PSScriptRoot
$InstallRoot = $PSScriptRoot
function Assert-Release($Record) {}
function Assert-PinnedSigner([string]$Image) {}
function Assert-LocalPath([string]$Path) { return $Path }
function Get-AgentState([string]$Image) {
    return @{manager_running=$true;connection_mode='offline'}
}
function Assert-CloudAgentQuiescent([string]$Image) {
    if ($Image -cne $expectedImage) { throw 'Incorrect Cloud Agent probe image.' }
    throw 'Active standalone Cloud Agent.'
}
foreach ($Rollback in @($false, $true)) {
    $expectedImage = if ($Rollback) { 'current.exe' } else { 'target.exe' }
    try {
        Set-ActiveRelease @{exe='target.exe'} @{exe='current.exe'}
        exit 10
    } catch {
        if ($_.Exception.Message -cne 'Active standalone Cloud Agent.') { throw }
    }
}
"""
    script = tmp_path / "test-release-switch.ps1"
    script.write_text(source[start:end] + "\n" + harness, encoding="utf-8")
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
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert pairing.read_text(encoding="utf-8") == "{}"
    assert not (tmp_path / "install.json").exists()
    assert not (tmp_path / "mcp.json").exists()
