"""Component programs run in subprocesses through test_regressions.py."""

# Several programs launch fixtures at import time; do not collect them twice.
collect_ignore = ["components"]


def pytest_sessionfinish(session, exitstatus):
    """Finalize only test-owned Qt objects while Python/Qt modules are alive.

    Plain `pytest` previously returned zero while a shared QApplication was
    still live, then aborted in pyside6.abi3.dll at interpreter teardown.
    Running cleanup inside pytest makes raw and managed Windows test paths
    obey the same native lifetime contract without hiding an abort.
    """
    from udb.qt_test_shutdown import release_qt_test_resources

    release_qt_test_resources()
