"""Run Windows pytest and explicitly retire its native Qt test application.

A passing pytest summary does not justify ignoring a native interpreter abort.
All test and Qt teardown errors must still fail CI. This runner is for isolated
GitHub Actions Windows test processes, never the installed owner's UDB agent.
"""

from __future__ import annotations

import sys

import pytest

from udb.qt_test_shutdown import release_qt_test_resources


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
