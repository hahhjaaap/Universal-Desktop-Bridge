"""Prepare exact runtime pins and evaluate a pip-audit JSON report in CI."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9.+!-]*")
_ADVISORY = re.compile(r"[A-Z][A-Z0-9-]{2,80}")


def package_key(value):
    if not isinstance(value, str) or not _PACKAGE.fullmatch(value):
        raise ValueError("Invalid package name in dependency audit")
    return re.sub(r"[-_.]+", "-", value).lower()


def pins():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    requirements = [
        *project["dependencies"],
        *project["optional-dependencies"]["office"],
    ]
    # Send Windows-only pins to the advisory service from Linux as well.
    result = [entry.split(";", 1)[0].strip() for entry in requirements]
    if not result or any(not _PIN.fullmatch(pin) for pin in result):
        raise ValueError("Every audited runtime dependency must be exactly pinned")
    return result


def unallowed(report, allowlist, today):
    allowed = set()
    keys = {"package", "id", "reason", "expires"}
    if not isinstance(allowlist, list):
        raise ValueError("Allowlist requires a JSON array")
    for entry in allowlist:
        if not isinstance(entry, dict) or set(entry) != keys:
            raise ValueError("Allowlist entries require package, ID, reason and expiry")
        name = package_key(entry["package"])
        advisory, reason, expiry = entry["id"], entry["reason"], entry["expires"]
        if not isinstance(advisory, str) or not _ADVISORY.fullmatch(advisory):
            raise ValueError("Invalid allowlist advisory ID")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError("Allowlist reason required")
        if not isinstance(expiry, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", expiry
        ):
            raise ValueError("Allowlist expiry must be YYYY-MM-DD")
        if today < date.fromisoformat(expiry):
            allowed.add((name, advisory))
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise ValueError("Invalid pip-audit report")
    issues = []
    for dependency in report["dependencies"]:
        name = package_key(dependency["name"])
        if "skip_reason" in dependency:
            raise ValueError(f"Audit skipped a required dependency: {name}")
        for finding in dependency["vulns"]:
            advisory = finding["id"]
            identifiers = [advisory, *finding.get("aliases", [])]
            if not any((name, identifier) in allowed for identifier in identifiers):
                issues.append((name, dependency["version"], advisory))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--requirements", type=Path)
    source.add_argument("--report", type=Path)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if args.requirements:
        args.requirements.write_text("\n".join(pins()) + "\n", encoding="utf-8")
        return 0
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        allowlist = json.loads(
            (ROOT / ".github" / "pip-audit-allowlist.json").read_text(encoding="utf-8")
        )
        findings = unallowed(report, allowlist, datetime.now(UTC).date())
        expected = {
            package_key(pin.split("==")[0]): pin.split("==")[1] for pin in pins()
        }
        observed = {
            package_key(row["name"]): row["version"] for row in report["dependencies"]
        }
        if observed != expected or len(report["dependencies"]) != len(expected):
            raise ValueError(
                "Audit did not cover exactly the pinned runtime dependencies"
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Runtime audit validation failed: {exc}")
        return 2
    for name, version, advisory in findings:
        print(f"{name} {version} {advisory}")
    print(f"Unallowed runtime advisories: {len(findings)}")
    return int(args.enforce and bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
