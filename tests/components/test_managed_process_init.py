"""Strict shared ConPTY bounds without requiring a Windows desktop."""

from __future__ import annotations

import os
import sys

import pytest

from udb.companion.processes import ManagedProcess, _valid_terminal_dimensions


@pytest.mark.parametrize(
    ("columns", "rows", "expected"),
    [
        (20, 5, True),
        (400, 200, True),
        (100, 30, True),
        (19, 30, False),
        (401, 30, False),
        (100, 4, False),
        (100, 201, False),
        (True, 30, False),
        (100, False, False),
        (100.0, 30, False),
        ("100", 30, False),
    ],
)
def test_conpty_dimensions_are_strict(columns, rows, expected):
    assert _valid_terminal_dimensions(columns, rows) is expected


def test_posix_process_initialization_preserves_std_streams_and_exit(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX fallback test")
    proc = ManagedProcess(
        [sys.executable, "-c", "print('udb-managed-process-ok')"],
        str(tmp_path),
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.close()
        assert b"udb-managed-process-ok" in proc.stdout.read()
        assert proc.wait(timeout=5) == 0
    finally:
        proc.close()


def test_non_windows_conpty_request_is_rejected(tmp_path):
    if os.name == "nt":
        pytest.skip("ConPTY is supported on Windows")
    with pytest.raises(ValueError, match="ConPTY requires Windows"):
        ManagedProcess(
            [sys.executable, "-c", "pass"],
            str(tmp_path),
            conpty=True,
        )
