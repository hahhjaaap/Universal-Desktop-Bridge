"""Compare Windows pytest shutdown with and without explicit QApplication deletion."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from run_windows_pytest import release_qt_test_resources


def cleanup(mode: str) -> None:
    import shiboken6
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None or not shiboken6.isValid(app):
        raise RuntimeError("The regression process has no live Qt test application")

    delete = shiboken6.delete
    delete_application = mode == "delete-application"
    attempts = 0

    def track_delete(obj):
        nonlocal attempts
        if obj is app:
            attempts += 1
            if not delete_application:
                return
        delete(obj)

    # Use the normal teardown in both arms. Skip only the final deletion of
    # this QApplication in the comparison arm, and restore the original API
    # before interpreter shutdown.
    with patch.object(shiboken6, "delete", track_delete):
        release_qt_test_resources()
    valid = shiboken6.isValid(app)
    if attempts != 1 or valid == delete_application:
        raise RuntimeError("The expected Qt teardown state was not reached")
    print(
        f"UDB_QT_PROBE mode={mode} delete_attempts={attempts} app_valid={valid}",
        flush=True,
    )


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in {"keep-application", "delete-application"}:
        raise SystemExit(
            "Usage: probe_windows_qt_shutdown.py keep-application|delete-application"
        )
    code = int(pytest.main(["-q"]))
    print(f"UDB_PYTEST_RETURN={code}", flush=True)
    cleanup(argv[0])
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
