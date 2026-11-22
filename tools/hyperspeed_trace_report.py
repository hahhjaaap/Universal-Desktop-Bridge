"""Analyze payload-free UDB trace spans by operation and correlated RPC.

The report contains timings and fixed operation names only. It never emits the
hashed trace IDs, request payloads, paths, URLs, selectors, or device identity.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from udb import hyperspeed_perf as perf
from udb.hyperspeed_perf import read_trace

MAX_RPC_DETAILS = 1000


def _summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        low = math.floor(position)
        high = math.ceil(position)
        return round(
            ordered[low] + (ordered[high] - ordered[low]) * (position - low), 4
        )

    return {
        "count": len(ordered),
        "mean_ms": round(sum(ordered) / len(ordered), 4),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": round(max(ordered), 4),
    }


def _validate_event(event: dict) -> None:
    if (
        not isinstance(event, dict)
        or event.get("schema") != 1
        or not isinstance(event.get("operation"), str)
        or event["operation"] not in perf._OPERATIONS
        or not isinstance(event.get("phase"), str)
        or event["phase"] not in perf._PHASES
        or type(event.get("started_ns")) is not int
        or event["started_ns"] < 0
        or type(event.get("duration_ns")) is not int
        or event["duration_ns"] < 0
        or type(event.get("pid")) is not int
        or event["pid"] <= 0
        or type(event.get("ok")) is not bool
        or event.get("startup") not in ("cold", "warm")
        or (
            event.get("trace_id") is not None
            and (
                not isinstance(event["trace_id"], str)
                or len(event["trace_id"]) != 24
                or any(ch not in "0123456789abcdef" for ch in event["trace_id"])
            )
        )
    ):
        raise ValueError("Invalid UDB trace event")


def _union_duration(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    start, end = ordered[0]
    total = 0
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def analyze_trace_events(events: list[dict], *, max_rpcs: int = 200) -> dict:
    """Summarize fixed operation/phase spans and same-host JSON-RPC timelines."""
    if not isinstance(events, list) or not events:
        raise ValueError("At least one trace event is required")
    if type(max_rpcs) is not int or not 1 <= max_rpcs <= MAX_RPC_DETAILS:
        raise ValueError("max_rpcs must be between 1 and 1000")

    stage_groups = defaultdict(list)
    startup_groups = defaultdict(lambda: defaultdict(list))
    stage_outcomes = defaultdict(lambda: {"ok": 0, "failed": 0})
    rpc_groups = defaultdict(list)
    uncorrelated = 0

    for event in events:
        _validate_event(event)
        operation = event["operation"]
        phase = event["phase"]
        duration_ms = event["duration_ns"] / 1_000_000
        key = (operation, phase)
        stage_groups[key].append(duration_ms)
        startup_groups[key][event["startup"]].append(duration_ms)
        stage_outcomes[key]["ok" if event["ok"] else "failed"] += 1
        trace_id = event.get("trace_id")
        if trace_id is None:
            uncorrelated += 1
        else:
            rpc_groups[trace_id].append(event)

    operation_phases = {}
    for (operation, phase), values in sorted(stage_groups.items()):
        operation_phases[f"{operation}/{phase}"] = {
            "all": _summary(values),
            "cold": _summary(startup_groups[(operation, phase)]["cold"]),
            "warm": _summary(startup_groups[(operation, phase)]["warm"]),
            "outcomes": dict(stage_outcomes[(operation, phase)]),
        }

    timelines = []
    for rows in rpc_groups.values():
        intervals = [
            (row["started_ns"], row["started_ns"] + row["duration_ns"]) for row in rows
        ]
        first = min(start for start, _ in intervals)
        last = max(end for _, end in intervals)
        envelope_ns = max(0, last - first)
        covered_ns = _union_duration(intervals)
        by_operation = defaultdict(lambda: {"count": 0, "duration_ms": 0.0})
        for row in rows:
            item = by_operation[row["operation"]]
            item["count"] += 1
            item["duration_ms"] += row["duration_ns"] / 1_000_000
        timelines.append(
            {
                "_sort_ns": first,
                "observed_span_ms": round(envelope_ns / 1_000_000, 4),
                "instrumented_union_ms": round(covered_ns / 1_000_000, 4),
                "unattributed_gap_ms": round(
                    max(0, envelope_ns - covered_ns) / 1_000_000, 4
                ),
                "summed_stage_ms": round(
                    sum(row["duration_ns"] for row in rows) / 1_000_000, 4
                ),
                "process_count": len({row["pid"] for row in rows}),
                "event_count": len(rows),
                "failed_event_count": sum(not row["ok"] for row in rows),
                "operations": {
                    name: {
                        "count": item["count"],
                        "duration_ms": round(item["duration_ms"], 4),
                    }
                    for name, item in sorted(by_operation.items())
                },
            }
        )
    timelines.sort(key=lambda row: row["_sort_ns"])
    for index, row in enumerate(timelines):
        row.pop("_sort_ns")
        row["rpc_index"] = index + 1
    observed = [row["observed_span_ms"] for row in timelines]
    gaps = [row["unattributed_gap_ms"] for row in timelines]
    covered = [row["instrumented_union_ms"] for row in timelines]

    return {
        "schema": 1,
        "trace_event_count": len(events),
        "correlated_rpc_count": len(timelines),
        "uncorrelated_event_count": uncorrelated,
        "operation_phases": operation_phases,
        "rpc_observed_span_ms": _summary(observed),
        "rpc_instrumented_union_ms": _summary(covered),
        "rpc_unattributed_gap_ms": _summary(gaps),
        "rpc_timelines": timelines[:max_rpcs],
        "omitted_rpc_timeline_count": max(0, len(timelines) - max_rpcs),
        "interpretation": (
            "RPC spans cover only instrumented UDB processes on this host. "
            "They exclude ChatGPT model generation and any uninstrumented edge "
            "or client time. Summed stage durations can overlap; use the "
            "instrumented union and unattributed gap for the envelope."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Owner-local traces.jsonl")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-rpcs", type=int, default=200)
    args = parser.parse_args(argv)
    try:
        events = read_trace(args.trace)
        report = analyze_trace_events(events, max_rpcs=args.max_rpcs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    wire = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(wire + "\n", encoding="utf-8")
    print(wire)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
