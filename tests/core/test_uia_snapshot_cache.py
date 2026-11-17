"""HyperSpeed 31 experimental read-only UIA snapshot cache boundaries.

No test in this module touches a live user window or sends input.
Full per-control equivalence with a consented GUI fixture remains a gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).parents[2] / "src" / "udb" / "computer_uia.ps1"


def test_cached_properties_are_only_used_inside_snapshot_branch():
    source = HELPER.read_text(encoding="utf-8-sig")
    prefix, rest = source.split("if($r.mode -eq 'snapshot') {", 1)
    snapshot, suffix = rest.split("$conditions=[Collections.Generic.List", 1)
    assert "UDB_UIA_SNAPSHOT_CACHE" not in prefix
    assert "UDB_UIA_SNAPSHOT_CACHE" not in suffix
    assert "$env:UDB_UIA_SNAPSHOT_CACHE -ceq '1'" in snapshot
    assert "[Windows.Automation.CacheRequest]::new()" in snapshot
    assert "[Windows.Automation.TreeScope]::Element" in snapshot
    assert "[Windows.Automation.AutomationElementMode]::Full" in snapshot
    assert "$element.Cached" in snapshot
    assert "$element.Current" in snapshot
    assert "$walker.GetFirstChild($element,$snapshotCache)" in snapshot
    assert "$walker.GetNextSibling($child,$snapshotCache)" in snapshot


def test_cache_is_per_request_and_preserves_password_redaction():
    source = HELPER.read_text(encoding="utf-8-sig")
    snapshot = source.split("if($r.mode -eq 'snapshot') {", 1)[1]
    for prop in (
        "NameProperty", "AutomationIdProperty", "ControlTypeProperty",
        "IsEnabledProperty", "IsOffscreenProperty", "IsPasswordProperty",
        "BoundingRectangleProperty",
    ):
        assert f"::{prop}" in snapshot
    assert "$snapshotCache=$null" in snapshot
    assert "if($c.IsPassword)" in snapshot
    assert "name='<password>';password=$true" in snapshot
    assert "rows.Count -lt 200" in snapshot
    assert "queue.Count -lt 400" in snapshot
    assert "$root.Current.ProcessId -ne [int]$r.pid" in source
    assert "if($target.Current.IsPassword)" in source


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows helper only")
@pytest.mark.parametrize("enabled", ["0", "1"])
def test_invalid_hwnd_refused_with_cache_enabled_or_disabled(enabled):
    # The zero HWND / impossible PID is rejected before any UIA tree traversal.
    exe = Path(os.environ["SystemRoot"]) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    env = dict(os.environ, UDB_UIA_SNAPSHOT_CACHE=enabled)
    result = subprocess.run(
        [
            str(exe), "-NoLogo", "-NoProfile", "-NonInteractive", "-Sta",
            "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
        ],
        input=json.dumps({"hwnd": 0, "pid": -1, "mode": "snapshot"}),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=18, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 1
    assert json.loads(result.stdout.lstrip("\ufeff"))["ok"] is False
