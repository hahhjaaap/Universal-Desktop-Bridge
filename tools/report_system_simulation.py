"""Summarize full pytest simulation domains from CI's existing JUnit XML.

This does not claim exhaustive coverage. No private user device or browser is
contacted, and only aggregate counts (not test parameters) are exported.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree

DOMAINS = {
    "mcp_protocol": (
        "protocol",
        "stdio",
        "unified",
        "tool_consolidation",
        "proxy",
        "backend_recovery",
        "session_lifecycle",
        "mcp",
    ),
    "owner_policy": (
        "policy",
        "grant",
        "credential",
        "security",
        "access",
        "sandbox",
        "source_access",
        "permissions",
    ),
    "files_documents": (
        "file",
        "document",
        "spreadsheet",
        "upload",
        "download",
        "media",
        "search",
        "accounting",
    ),
    "browser_desktop": (
        "browser",
        "chrome",
        "cdp",
        "desktop",
        "uia",
        "pointer",
        "tab",
    ),
    "background_jobs": (
        "job",
        "process",
        "terminal",
        "host",
        "background",
        "work",
    ),
    "windows_installation": (
        "release",
        "install",
        "build",
        "package",
        "windows",
    ),
    "gui_manager": (
        "manager",
        "onboarding",
        "quick_controls",
        "refresh",
    ),
    "fault_injection": (
        "fault",
        "recovery",
        "simulation",
        "runtime_audit",
    ),
}


def summarize(path: Path) -> dict:
    root = ElementTree.parse(path).getroot()
    cases = root.findall(".//testcase")
    if not cases:
        raise ValueError("No pytest cases found in simulation report")
    result = {
        "scope": "CI pytest simulation; physical remote devices NOT tested",
        "cases": len(cases),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "domains": {name: {"passed": 0, "failed": 0, "skipped": 0} for name in DOMAINS},
    }
    result["domains"]["uncategorized"] = {"passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        cls = (case.get("classname") or "").lower()
        # Classnames are names from our test suite, not test parameter values.
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        result[status] += 1
        matched = [
            name
            for name, terms in DOMAINS.items()
            if any(term in cls for term in terms)
        ]
        for name in matched or ["uncategorized"]:
            result["domains"][name][status] += 1
    # Count a domain as exercised only when a real test passed; skipped
    # and failing tests never establish coverage for that subsystem.
    result["missing_domains"] = sorted(
        name for name in DOMAINS if result["domains"][name]["passed"] == 0
    )
    result["unverified"] = [
        "two real Windows PCs on different networks",
        "live Cloudflare deployment and ChatGPT OAuth grant",
        "physical mouse/keyboard behavior",
        "Windows Sandbox guest boot",
        "installed UDB CPU/RAM and antivirus impact",
    ]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--require-domains",
        action="store_true",
        help="Fail CI if any required subsystem has zero passing tests",
    )
    args = parser.parse_args(argv)
    report = summarize(args.junitxml)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    missing_required = bool(args.require_domains and report["missing_domains"])
    return int(bool(report["failed"]) or missing_required)


if __name__ == "__main__":
    raise SystemExit(main())
