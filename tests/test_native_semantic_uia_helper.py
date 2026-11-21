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


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell sorting semantics")
def test_ranked_control_sorts_numeric_top_then_left_not_hashtable_enumeration():
    """Use the exact checked-in sorter against a disposable candidate fixture."""
    path = Path(__file__).resolve().parents[1] / "src" / "udb" / "computer_uia.ps1"
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip().startswith("$ordered=@($candidates|Sort-Object -Property ")
    ]
    assert len(lines) == 1, "Expected exactly one ranked-control sort expression"
    script = "\n".join(
        [
            "$ErrorActionPreference='Stop'",
            "$candidates=[Collections.Generic.List[object]]::new()",
            "$candidates.Add(@{name='Beta';top=[double]196;left=[double]125})",
            "$candidates.Add(@{name='Gamma';top=[double]141;left=[double]150})",
            "$candidates.Add(@{name='Alpha';top=[double]141;left=[double]125})",
            lines[0],
            "$names=@($ordered|ForEach-Object {$_.name})",
            "if(($names -join ',') -cne 'Alpha,Gamma,Beta'){",
            "  throw ('Incorrect visual ranking: '+($names -join ','))",
            "}",
        ]
    )
    exe = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    result = subprocess.run(
        [str(exe), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
