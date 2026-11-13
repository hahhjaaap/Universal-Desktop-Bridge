"""Run Windows pytest and explicitly retire its native Qt test application.

A passing pytest summary does not justify ignoring a native interpreter abort.
All test and Qt teardown errors must still fail CI. This runner is for isolated
GitHub Actions Windows test processes, never the installed owner's UDB agent.
"""

from __future__ import annotations

import os
import sys

import pytest


def release_qt_test_resources() -> None:
    """Dispose only the test process's Qt state before Python module shutdown."""
    if os.name != "nt" or "PySide6.QtWidgets" not in sys.modules:
        return

    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete, isValid

    app = QApplication.instance()
    if app is None:
        return

    # The UDB GUI tests exercise background Qt workers. A live runnable at
    # interpreter shutdown can race destruction of the native Qt DLLs.
    pool = QThreadPool.globalInstance()
    if pool is not None and not pool.waitForDone(15_000):
        raise RuntimeError("Qt test worker did not stop before process shutdown")

    for widget in QApplication.topLevelWidgets():
        if isValid(widget):
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    app.quit()
    if isValid(app):
        delete(app)
    print("UDB_QT_TEST_CLEANUP=completed", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("Usage: run_windows_pytest.py JUNIT_XML_PATH")
    code = int(pytest.main(["--junitxml=" + argv[0]]))
    print("UDB_PYTEST_RETURN=" + str(code), flush=True)
    # Teardown errors propagate as failures; do NOT return 0 on a crash.
    release_qt_test_resources()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
