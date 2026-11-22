"""Tests for payload-free, cross-process UDB trace correlation."""

import json

import pytest

from tools.hyperspeed_trace_report import analyze_trace_events


def event(
    operation,
    phase,
    started_ns,
    duration_ns,
    *,
    trace_id="a" * 24,
    pid=100,
    startup="warm",
    ok=True,
):
    return {
        "schema": 1,
        "trace_id": trace_id,
        "operation": operation,
        "phase": phase,
        "startup": startup,
        "started_ns": started_ns,
        "duration_ns": duration_ns,
        "process_cpu_total_ns": 1000,
        "ok": ok,
        "pid": pid,
    }


def test_correlates_process_spans_and_reports_unattributed_gap_without_ids():
    trace_id = "b" * 24
    events = [
        event("cloud.queue", "queue", 1_000_000_000, 10_000_000, trace_id=trace_id),
        event(
            "cloud.stdio",
            "execution",
            1_020_000_000,
            30_000_000,
            trace_id=trace_id,
            pid=200,
            startup="cold",
        ),
        event(
            "host.mailbox",
            "observation",
            1_030_000_000,
            15_000_000,
            trace_id=trace_id,
            pid=300,
        ),
        event(
            "desktop.uia",
            "execution",
            1_040_000_000,
            5_000_000,
            trace_id=trace_id,
            pid=300,
        ),
        event(
            "mcp.response",
            "response",
            1_060_000_000,
            2_000_000,
            trace_id=trace_id,
            pid=100,
        ),
    ]

    report = analyze_trace_events(events)

    assert report["trace_event_count"] == 5
    assert report["correlated_rpc_count"] == 1
    assert report["uncorrelated_event_count"] == 0
    timeline = report["rpc_timelines"][0]
    assert timeline["observed_span_ms"] == 62.0
    assert timeline["instrumented_union_ms"] == 42.0
    assert timeline["unattributed_gap_ms"] == 20.0
    assert timeline["summed_stage_ms"] == 62.0
    assert timeline["process_count"] == 3
    assert timeline["failed_event_count"] == 0
    assert timeline["operations"]["cloud.stdio"]["duration_ms"] == 30.0
    assert report["operation_phases"]["cloud.stdio/execution"]["cold"]["count"] == 1
    assert report["rpc_observed_span_ms"]["p95_ms"] == 62.0
    serialized = json.dumps(report)
    assert trace_id not in serialized
    assert '"pid"' not in serialized


def test_stage_summaries_keep_cold_warm_and_failed_counts_separate():
    events = [
        event("desktop.uia", "execution", 10, 1_000_000, startup="cold"),
        event("desktop.uia", "execution", 20, 3_000_000, startup="warm"),
        event("desktop.uia", "execution", 30, 5_000_000, startup="warm", ok=False),
        event("host.dispatch", "execution", 40, 7_000_000, trace_id=None),
    ]

    report = analyze_trace_events(events)
    stage = report["operation_phases"]["desktop.uia/execution"]
    assert stage["all"]["count"] == 3
    assert stage["cold"]["count"] == 1
    assert stage["cold"]["p50_ms"] == 1.0
    assert stage["warm"]["count"] == 2
    assert stage["warm"]["p50_ms"] == 4.0
    assert stage["outcomes"] == {"ok": 2, "failed": 1}
    assert report["uncorrelated_event_count"] == 1
    assert report["correlated_rpc_count"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        event("desktop.uia", "execution", -1, 1),
        event("desktop.uia", "execution", 1, -1),
        event("desktop.uia", "execution", 1, 1, pid=0),
        event("desktop.uia", "execution", 1, 1, trace_id="not-a-hash"),
        event("desktop.uia", "execution", 1, 1, startup="unknown"),
        event("desktop.uia", "execution", 1, 1, ok=1),
        event("unknown.operation", "execution", 1, 1),
        event("desktop.uia", "unknown.phase", 1, 1),
    ],
)
def test_invalid_event_is_rejected(bad):
    with pytest.raises(ValueError, match="Invalid UDB trace event"):
        analyze_trace_events([bad])


def test_empty_trace_and_invalid_detail_limit_are_rejected():
    with pytest.raises(ValueError, match="At least one"):
        analyze_trace_events([])
    with pytest.raises(ValueError, match="max_rpcs"):
        analyze_trace_events([event("desktop.uia", "execution", 1, 1)], max_rpcs=0)


def test_rpc_detail_limit_is_bounded():
    events = [
        event(
            "desktop.uia",
            "execution",
            index * 10,
            1,
            trace_id=f"{index + 1:024x}",
        )
        for index in range(5)
    ]
    report = analyze_trace_events(events, max_rpcs=2)
    assert report["correlated_rpc_count"] == 5
    assert len(report["rpc_timelines"]) == 2
    assert report["omitted_rpc_timeline_count"] == 3
    assert [row["rpc_index"] for row in report["rpc_timelines"]] == [1, 2]
