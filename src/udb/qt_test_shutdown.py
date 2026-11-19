"""Dispose test-owned native Qt objects before Windows interpreter finalization.

This module is *only* called by test runners. It has no side effects on import
and never changes the Qt lifetime of the installed UDB application.
"""

from __future__ import annotations

import os
import sys


def release_qt_test_resources() -> bool:
    """Close the shared QApplication and its widgets after tests finish.

    Returns whether a valid test application was finalized. Do not suppress
    teardown failures: broken native lifetimes must make CI fail.
    """
    if os.name != "nt" or "PySide6.QtWidgets" not in sys.modules:
        return False

    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete, isValid

    app = QApplication.instance()
    if app is None or not isValid(app):
        return False

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
    return True
