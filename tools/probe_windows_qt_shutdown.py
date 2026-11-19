"""Record Windows pytest shutdown and compare the Qt application lifetime."""

from __future__ import annotations

import sys
import threading
from unittest.mock import patch

import pytest
from run_windows_pytest import release_qt_test_resources

_EXCLUSIONS = {
    "full": (),
    "without-manager-ui": ("--ignore=tests/test_manager_ui.py",),
    "without-quick-controls": ("--ignore=tests/test_quick_controls.py",),
}


def observe_raw_state() -> None:
    qt = sys.modules.get("PySide6.QtCore")
    app_live = qt is not None and qt.QCoreApplication.instance() is not None
    win32_loaded = any(
        name.startswith(("win32", "pywintypes")) for name in tuple(sys.modules)
    )
    threads = threading.enumerate()
    print(
        f"UDB_QT_PROBE mode=raw app_live={app_live} pywin32_loaded={win32_loaded} "
        f"python_threads={len(threads)} daemon_threads={sum(t.daemon for t in threads)}",
        flush=True,
    )


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
    if not 1 <= len(argv) <= 2 or argv[0] not in {
        "raw",
        "keep-application",
        "delete-application",
    }:
        raise SystemExit(
            "Usage: probe_windows_qt_shutdown.py MODE [full|without-manager-ui|without-quick-controls]"
        )
    mode = argv[0]
    group = argv[1] if len(argv) == 2 else "full"
    if group not in _EXCLUSIONS:
        raise SystemExit("Unknown Windows shutdown probe group")
    print(f"UDB_NATIVE_GROUP={group}", flush=True)
    code = int(pytest.main(["-q", *_EXCLUSIONS[group]]))
    print(f"UDB_PYTEST_RETURN={code}", flush=True)
    if mode == "raw":
        observe_raw_state()
    else:
        cleanup(mode)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
