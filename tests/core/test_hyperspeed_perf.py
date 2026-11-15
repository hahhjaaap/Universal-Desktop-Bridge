"""Offline acceptance gates for HyperSpeed 2.0 foundation steps 01–10.

No test opens Chrome, sends input, connects Cloudflare, or accesses owner files.
These are interface and diagnostic invariants, NOT real latency benchmarks.
"""

from __future__ import annotations

import json
import time

import pytest

from tools import hyperspeed_benchmark as bench
from tools import hyperspeed_dashboard as dashboard
from udb import hyperspeed_perf as perf


@pytest.fixture(autouse=True)
def reset_optional_trace():
    perf.disable()
    yield
    perf.disable()


def test_01_catalog_has_30_unique_representative_workflow_shapes():
    scenarios = bench.load_catalog()
    assert len(scenarios) == 30
    assert len({row["id"] for row in scenarios}) == 30
    assert {row["family"] for row in scenarios} == bench.FAMILIES
    assert all(2 <= len(row["steps"]) <= 12 for row in scenarios)


def test_02_same_rpc_id_correlates_across_processes_without_exposing_it():
    source = "client-id-that-is-not-a-tool-argument"
    result = perf.correlation_id(source)
    assert result == perf.correlation_id(source)
    assert len(result) == 24
    assert source not in result
    assert perf.correlation_id(None) is None
    assert perf.correlation_id(True) is None
    assert perf.correlation_id("x" * 161) is None


def test_02_trace_is_off_by_default_and_preserves_return_value(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("UDB_HYPERSPEED_TRACE", raising=False)
    assert perf.configure(tmp_path) is False
    assert perf.timed_call("desktop.uia", "execution", lambda a: a + 1, 9) == 10
    with pytest.raises(ZeroDivisionError):
        perf.timed_call("browser.cdp", "execution", lambda: 1 / 0)
    assert not (tmp_path / "hyperspeed").exists()


def test_03_opt_in_phase_spans_are_bounded_and_redacted(monkeypatch, tmp_path):
    monkeypatch.setenv("UDB_HYPERSPEED_TRACE", "1")
    assert perf.configure(tmp_path)
    started = time.perf_counter_ns()
    with perf.rpc_scope("sensitive-rpc-request-id"):
        assert perf.timed_call(
            "browser.cdp", "execution", lambda: {"ok": True}
        ) == {"ok": True}
        with perf.span("mcp.response", "response"):
            pass
        perf.interval("cloud.queue", "queue", started)
    filename = tmp_path / "hyperspeed" / "traces.jsonl"
    trace = perf.read_trace(filename)
    assert len(trace) == 3
    assert {x["phase"] for x in trace} == {
        "execution", "response", "queue"
    }
    assert all(x["trace_id"] == perf.correlation_id("sensitive-rpc-request-id") for x in trace)
    raw = filename.read_text(encoding="utf-8")
    for secret in ("sensitive-rpc-request-id", "password", "cookie", "url"):
        assert secret not in raw.lower()
    assert all(x["duration_ns"] >= 0 for x in trace)


def test_03_04_failure_and_cold_warm_labels(monkeypatch, tmp_path):
    monkeypatch.setenv("UDB_HYPERSPEED_TRACE", "1")
    assert perf.configure(tmp_path)
    with pytest.raises(RuntimeError, match="fixture"):
        with perf.span("desktop.uia", "execution"):
            raise RuntimeError("fixture")
    with perf.span("desktop.uia", "execution"):
        pass
    traces = perf.read_trace(tmp_path / "hyperspeed" / "traces.jsonl")
    assert [x["ok"] for x in traces] == [False, True]
    assert [x["startup"] for x in traces] == ["cold", "warm"]


def test_04_fixture_marks_first_iteration_cold_and_later_warm():
    scenario = bench.load_catalog()[0]
    first = bench.run_synthetic(scenario, 0)
    second = bench.run_synthetic(scenario, 1)
    assert first["startup"] == "cold"
    assert second["startup"] == "warm"
    assert first["verified"] and second["verified"]


def test_05_reject_bad_or_unsafe_scenario_dag(tmp_path):
    source = json.loads(bench.FIXTURES.read_text(encoding="utf-8"))
    source["scenarios"][0]["steps"][0]["after"] = ["future"]
    edited = tmp_path / "catalog.json"
    edited.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="cyclic"):
        bench.load_catalog(edited)


def test_06_percentile_interpolation_is_deterministic():
    samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert bench.percentile(samples, 0.5) == 30.0
    assert bench.percentile(samples, 0.95) == 48.0
    assert bench.percentile(samples, 0.99) == 49.6
    assert bench.summarize(samples)["max_ms"] == 50.0
    with pytest.raises(ValueError):
        bench.percentile([], 0.95)


def test_07_resource_samples_are_observed_or_null_never_fabricated():
    sample = bench.run_synthetic(bench.load_catalog()[0], 1)
    assert sample["cpu_ms"] >= 0
    assert sample["thread_count"] >= 1
    for field in ("read_bytes", "write_bytes", "rss_bytes", "child_processes"):
        assert sample[field] is None or sample[field] >= 0
    assert sample["allocation_peak_bytes"] is None


def test_08_critical_path_selects_longest_dependency_chain():
    graph = [
        {"id": "start", "after": [], "duration_ms": 2},
        {"id": "branch_a", "after": ["start"], "duration_ms": 7},
        {"id": "branch_b", "after": ["start"], "duration_ms": 12},
        {"id": "end", "after": ["branch_a", "branch_b"], "duration_ms": 5},
    ]
    assert bench.critical_path(graph) == {
        "duration_ms": 19, "steps": ["start", "branch_b", "end"]
    }
    with pytest.raises(ValueError, match="ordered"):
        bench.critical_path([{"id": "a", "after": ["b"], "duration_ms": 1}])


def test_09_redundant_poll_and_startup_detection_is_a_candidate_not_a_claim():
    sample = {
        "scenario": "fixture",
        "poll_steps": 4,
        "startup_steps": 2,
    }
    signals = bench.diagnostics([sample])
    assert {event["issue"] for event in signals} == {
        "repeated_polling", "repeated_startup"
    }
    assert bench.diagnostics([dict(sample, poll_steps=1, startup_steps=1)]) == []


def test_10_report_and_static_dashboard_are_offline_and_labelled(tmp_path):
    samples = [
        bench.run_synthetic(scenario, iteration)
        for scenario in bench.load_catalog()
        for iteration in range(2)
    ]
    report = bench.analyze_samples(samples)
    assert report["mode"] == "synthetic"
    assert report["scenario_count"] == 30
    assert report["sample_count"] == 60
    assert len(report["scenarios"]) == 30
    assert report["overall"]["count"] == 60
    assert "not browser" in report["disclaimer"]
    example = next(iter(report["scenarios"].values()))
    assert example["critical_path_ms"]["count"] == 2
    assert example["resources"]["cpu_ms"]["count"] == 2
    page = dashboard.render(report)
    assert "Synthetic in-memory fixture" in page
    assert "UDB HyperSpeed 2.0" in page
    assert "No live trace supplied" in page
    malicious = "<script>alert('bad')</script>"
    report["scenarios"][malicious] = report["scenarios"].pop(
        next(iter(report["scenarios"]))
    )
    assert malicious not in dashboard.render(report)
    assert "&lt;script&gt;" in dashboard.render(report)
    path = tmp_path / "report.html"
    path.write_text(page, encoding="utf-8")
    assert path.stat().st_size > 1000


def test_10_p95_regression_gate_only_acts_with_sufficient_samples():
    base_row = {"count": 40, "p95_ms": 10.0}
    now = {"count": 40, "p95_ms": 16.0}
    base = {"mode": "synthetic", "scenarios": {"fixture": base_row}}
    current = {"mode": "synthetic", "scenarios": {"fixture": now}}
    assert len(bench.regression_candidates(current, base, factor=1.3)) == 1
    current["scenarios"]["fixture"]["count"] = 2
    assert bench.regression_candidates(current, base, factor=1.3) == []
    current["mode"] = "live"
    with pytest.raises(ValueError, match="unlike"):
        bench.regression_candidates(current, base)


def test_10_smoke_runner_creates_valid_json_file(tmp_path):
    output = tmp_path / "metrics.json"
    assert bench.main(["--iterations", "2", "--output", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["sample_count"] == 60
    assert data["mode"] == "synthetic"
    assert data["iterations_per_scenario"] == 2
