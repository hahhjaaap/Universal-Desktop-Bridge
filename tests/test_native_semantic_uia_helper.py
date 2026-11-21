"""Native PowerShell parser check for the bounded semantic UIA helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell parser only")
def test_checked_in_semantic_uia_helper_has_valid_powershell_syntax():
    path = Path(__file__).resolve().parents[1] / "src" / "udb" / "computer_uia.ps1"
    exe = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    # This parses the fixed checked-in helper; it does not run UIA,
    # touch user windows, enable permissions or send keyboard input.
    quoted = str(path).replace("'", "''")
    script = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{quoted}',[ref]$tokens,[ref]$errors)|Out-Null; "
        "if($errors.Count -gt 0){$errors | ForEach-Object {$_.Message}; exit 2}"
    )
    result = subprocess.run(
        [str(exe), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
