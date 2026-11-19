"""Release provenance and advisory audit preserve explicit security boundaries."""

import re
import tomllib
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_actions_use_full_shas_with_tag_comments():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in path.read_text().splitlines():
            if re.search(r"\buses:\s+\w[\w./-]+@", line):
                assert re.search(r"@[0-9a-f]{40}\s+#\s+v[\d.]+\s*$", line), (
                    path.name,
                    line,
                )


def test_build_backend_dependencies_are_exact_pins():
    with (ROOT / "pyproject.toml").open("rb") as source:
        build = tomllib.load(source)["build-system"]["requires"]
    assert build == ["setuptools==84.2.1", "wheel==0.48.0"]


def test_audit_exceptions_are_package_specific_and_expire():
    from tools.audit_runtime_dependencies import unallowed

    report = {
        "dependencies": [
            {
                "name": "fixture",
                "version": "1.0",
                "vulns": [{"id": "PYSEC-2000-1", "aliases": ["CVE-2000-1234"]}],
            },
            {"name": "other", "version": "1.0", "vulns": [{"id": "PYSEC-2000-1"}]},
        ]
    }
    allowance = {
        "package": "fixture",
        "id": "CVE-2000-1234",
        "reason": "Temporary synthetic exception",
        "expires": "2026-11-18",
    }
    assert unallowed(report, [allowance], date(2026, 11, 17)) == [
        ("other", "1.0", "PYSEC-2000-1")
    ]
    assert len(unallowed(report, [allowance], date(2026, 11, 18))) == 2
    with pytest.raises(ValueError, match="reason"):
        unallowed(report, [{**allowance, "reason": ""}], date(2026, 11, 17))


def test_pip_audit_cannot_silently_pass_a_skipped_dependency():
    from tools.audit_runtime_dependencies import unallowed

    with pytest.raises(ValueError, match="skipped"):
        unallowed(
            {"dependencies": [{"name": "fixture", "skip_reason": "not found"}]},
            [],
            date(2026, 11, 18),
        )
