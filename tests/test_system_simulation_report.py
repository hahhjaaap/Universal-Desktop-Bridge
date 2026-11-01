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
