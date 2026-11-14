"""Verify aggregate simulation results are complete and never leak case text."""

import json

import pytest

from tools.report_system_simulation import main, summarize


def test_report_counts_cross_domain_scenarios_without_echoing_parameters(
    tmp_path, capsys
):
    source = tmp_path / "results.xml"
    source.write_text(
        """<testsuite name="pytest" tests="4">
        <testcase classname="tests.test_protocol_scenarios" name="test_ok"/>
        <testcase classname="tests.test_fault_scenarios" name="test_unsafe_SECRET">
          <skipped message="excluded"/>
        </testcase>
        <testcase classname="tests.core.test_browser_cdp_channel" name="test_cdp"/>
        <testcase classname="tests.test_manager_refresh" name="test_gui"/>
        </testsuite>""",
        encoding="utf-8",
    )
    target = tmp_path / "sim.json"
    assert main(["--junitxml", str(source), "--output", str(target)]) == 0
    report = json.loads(target.read_text("utf-8"))
    assert report["cases"] == 4
    assert (report["passed"], report["failed"], report["skipped"]) == (3, 0, 1)
    assert report["domains"]["mcp_protocol"]["passed"] == 1
    assert report["domains"]["browser_desktop"]["passed"] == 1
    assert report["domains"]["gui_manager"]["passed"] == 1
    assert report["domains"]["fault_injection"]["skipped"] == 1
    assert "SECRET" not in capsys.readouterr().out
    assert "SECRET" not in target.read_text()


def test_simulation_reports_failures_as_failure(tmp_path):
    source = tmp_path / "results.xml"
    source.write_text(
        """<testsuite><testcase classname="tests.core.test_policy" name="failure">
        <failure message="not safe">synthetic stack</failure>
        </testcase></testsuite>""",
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    assert main(["--junitxml", str(source), "--output", str(out)]) == 1
    report = json.loads(out.read_text())
    assert report["domains"]["owner_policy"]["failed"] == 1
    assert "synthetic stack" not in out.read_text()


def test_report_rejects_empty_results(tmp_path):
    p = tmp_path / "empty.xml"
    p.write_text("<testsuite/>", encoding="utf-8")
    with pytest.raises(ValueError, match="No pytest cases"):
        summarize(p)


def test_required_domains_do_not_count_skipped_or_missing_subsystems(tmp_path):
    source = tmp_path / "results.xml"
    source.write_text(
        """<testsuite>
        <testcase classname="tests.test_protocol_scenarios" name="pass"/>
        <testcase classname="tests.test_manager_refresh" name="skipped">
          <skipped message="Qt unavailable"/>
        </testcase>
        </testsuite>""",
        encoding="utf-8",
    )
    target = tmp_path / "sim.json"
    args = ["--junitxml", str(source), "--output", str(target), "--require-domains"]
    assert main(args) == 1
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["failed"] == 0
    assert report["domains"]["gui_manager"]["skipped"] == 1
    assert "gui_manager" in report["missing_domains"]
    assert "mcp_protocol" not in report["missing_domains"]
    assert "ChatGPT" in " ".join(report["unverified"])


def test_required_domains_accept_full_disposable_simulation(tmp_path):
    # Distinct synthetic cases for each of the eight test-suite areas; no
    # owner data, credentials, machine interactions or remote services used.
    categories = (
        "tests.test_protocol_scenarios",
        "tests.test_owner_policy",
        "tests.test_file_operations",
        "tests.test_browser_cdp",
        "tests.test_host_lifecycle",
        "tests.test_installation",
        "tests.test_manager_refresh",
        "tests.test_fault_scenarios",
    )
    source = tmp_path / "results.xml"
    cases = "".join(
        f'<testcase classname="{name}" name="test_fixture"/>' for name in categories
    )
    source.write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")
    target = tmp_path / "sim.json"
    args = ["--junitxml", str(source), "--output", str(target), "--require-domains"]
    assert main(args) == 0
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["cases"] == len(categories)
    assert report["missing_domains"] == []
    assert report["passed"] == len(categories)


def test_required_domains_never_hide_actual_failure(tmp_path):
    source = tmp_path / "results.xml"
    source.write_text(
        """<testsuite><testcase classname="tests.test_policy" name="denied">
        <failure message="synthetic fault">SECRET_FIXTURE</failure>
        </testcase></testsuite>""",
        encoding="utf-8",
    )
    target = tmp_path / "sim.json"
    args = ["--junitxml", str(source), "--output", str(target), "--require-domains"]
    assert main(args) == 1
    assert "SECRET_FIXTURE" not in target.read_text(encoding="utf-8")
