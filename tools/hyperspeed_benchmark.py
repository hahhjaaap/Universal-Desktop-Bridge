"""UDB HyperSpeed 2.0 baseline harness: deterministic OFFLINE workflow shapes.

No browser, desktop, Windows process, relay, credential, user file or network
resource is ever touched by the synthetic runner. Opt-in real-operation timing
is collected separately by udb.hyperspeed_perf.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import threading
import time
import tracemalloc
from collections import Counter, defaultdict
from pathlib import Path

from udb.hyperspeed_perf import read_trace

FIXTURES = Path(__file__).with_name("hyperspeed_scenarios.json")
FAMILIES = frozenset({"browser", "desktop", "files", "office", "terminal", "transport"})
OPERATIONS = frozenset(
    {"queue", "startup", "dispatch", "lookup", "execute", "verify",
     "observe", "digest", "response", "poll"}
)
TRACE_PHASES = frozenset(
    {"queue", "dispatch", "execution", "observation", "response", "startup"}
)
MAX_FIXTURE_SIZE = 1024


def load_catalog(path=FIXTURES):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Unsupported HyperSpeed fixture schema")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 30:
        raise ValueError("Exactly 30 representative scenarios are required")
    ids = set()
    for scenario in scenarios:
        name = scenario.get("id")
        steps = scenario.get("steps")
        if (
            not isinstance(name, str)
            or not name.replace("_", "").isalnum()
            or len(name) > 64
            or name in ids
            or scenario.get("family") not in FAMILIES
            or type(scenario.get("fixture_size")) is not int
            or not 64 <= scenario["fixture_size"] <= MAX_FIXTURE_SIZE
            or not isinstance(steps, list)
            or not 2 <= len(steps) <= 12
        ):
            raise ValueError("Invalid, duplicated or oversized fixture scenario")
        ids.add(name)
        seen = set()
        for step in steps:
            if (
                not isinstance(step, dict)
                or step.get("op") not in OPERATIONS
                or not isinstance(step.get("id"), str)
                or step["id"] in seen
                or not isinstance(step.get("after"), list)
                or any(parent not in seen for parent in step["after"])
            ):
                raise ValueError("Invalid or cyclic fixture dependency")
            seen.add(step["id"])
    return scenarios


def percentile(values, fraction):
    if not values or not 0 <= fraction <= 1:
        raise ValueError("Provide samples and a percentile in 0..1")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(values):
    if not values:
        raise ValueError("At least one timing sample is required")
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 4),
        "p50_ms": round(percentile(values, 0.5), 4),
        "p95_ms": round(percentile(values, 0.95), 4),
        "p99_ms": round(percentile(values, 0.99), 4),
        "max_ms": round(max(values), 4),
    }


def critical_path(steps):
    """Longest dependency chain, not a sum of parallel branches."""
    distance, route = {}, {}
    for step in steps:
        key = step["id"]
        if key in distance:
            raise ValueError("Duplicate critical-path step")
        parents = step.get("after", [])
        if any(parent not in distance for parent in parents):
            raise ValueError("Critical path must be topologically ordered")
        parent = max(parents, key=lambda p: distance[p]) if parents else None
        duration = step["duration_ms"]
        if type(duration) not in (float, int) or duration < 0 or not math.isfinite(duration):
            raise ValueError("Invalid step duration")
        distance[key] = duration + (distance[parent] if parent else 0)
        route[key] = (route[parent] if parent else []) + [key]
    if not distance:
        return {"duration_ms": 0.0, "steps": []}
    winner = max(distance, key=distance.get)
    return {"duration_ms": round(distance[winner], 4), "steps": route[winner]}


def _fixture_step(op, payload):
    """Fixed in-memory work: shape only, NOT Chrome/Windows timing."""
    if op in {"queue", "startup", "dispatch", "lookup", "poll"}:
        return bytes(memoryview(payload)[:])
    if op in {"execute", "digest", "verify"}:
        return hashlib.sha256(payload).digest() + payload[:64]
    if op == "observe":
        encoded = json.dumps(
            {"status": "fixture", "size": len(payload), "phase": op},
            separators=(",", ":"),
        )
        return json.loads(encoded)["status"].encode("ascii") + payload[:64]
    if op == "response":
        return json.loads(json.dumps({"length": len(payload)}))["length"].to_bytes(4, "big")
    raise ValueError("Unknown synthetic operation")


def _resource_snapshot():
    """Use psutil when installed; unknown RSS/I/O is null, never fabricated zero."""
    sample = {"cpu_ns": time.process_time_ns(), "threads": threading.active_count()}
    try:
        import psutil

        proc = psutil.Process()
        sample["rss_bytes"] = proc.memory_info().rss
        sample["child_processes"] = len(proc.children(recursive=False))
        try:
            io = proc.io_counters()
            sample["read_bytes"] = io.read_bytes
            sample["write_bytes"] = io.write_bytes
        except (AttributeError, OSError, psutil.Error):
            pass
    except (ImportError, OSError):
        pass
    return sample


def run_synthetic(scenario, iteration):
    payload = (scenario["id"].encode("ascii") + b":fixture") * 64
    payload = payload[: scenario["fixture_size"]]
    before = _resource_snapshot()
    started_ns = time.perf_counter_ns()
    steps = []
    for step in scenario["steps"]:
        tick = time.perf_counter_ns()
        payload = _fixture_step(step["op"], payload)
        steps.append(
            {
                "id": step["id"],
                "after": step["after"],
                "duration_ms": (time.perf_counter_ns() - tick) / 1e6,
            }
        )
    wall_ns = time.perf_counter_ns() - started_ns
    after = _resource_snapshot()
    return {
        "scenario": scenario["id"],
        "family": scenario["family"],
        "startup": "cold" if iteration == 0 else "warm",
        "elapsed_ms": wall_ns / 1e6,
        "cpu_ms": max(0, after["cpu_ns"] - before["cpu_ns"]) / 1e6,
        "rss_bytes": after.get("rss_bytes"),
        "child_processes": after.get("child_processes"),
        "thread_count": after["threads"],
        "read_bytes": (
            max(0, after["read_bytes"] - before["read_bytes"])
            if "read_bytes" in before and "read_bytes" in after
            else None
        ),
        "write_bytes": (
            max(0, after["write_bytes"] - before["write_bytes"])
            if "write_bytes" in before and "write_bytes" in after
            else None
        ),
        "allocation_peak_bytes": None,  # Set when tracemalloc is explicitly enabled.
        "critical_path": critical_path(steps),
        "poll_steps": sum(s["op"] == "poll" for s in scenario["steps"]),
        "startup_steps": sum(s["op"] == "startup" for s in scenario["steps"]),
        "verified": bool(payload),
    }


def diagnostics(samples, traces=None):
    repeated = Counter(s["scenario"] for s in samples if s["poll_steps"] > 2)
    launches = Counter(s["scenario"] for s in samples if s["startup_steps"] > 1)
    unusual = [
        {"scenario": scenario, "issue": "repeated_polling", "samples": count}
        for scenario, count in sorted(repeated.items())
    ] + [
        {"scenario": scenario, "issue": "repeated_startup", "samples": count}
        for scenario, count in sorted(launches.items())
    ]
    if traces:
        by_rpc = Counter(
            (e.get("trace_id"), e["operation"])
            for e in traces
            if e["operation"] in {"cloud.initialize", "desktop.uia"}
        )
        unusual.extend(
            {"trace_id": key[0], "operation": key[1], "issue": "repeated_call", "count": count}
            for key, count in by_rpc.items()
            if count > 3 and key[0] is not None
        )
    return unusual


def analyze_samples(samples, *, mode="synthetic", traces=None):
    grouped = defaultdict(list)
    cold = defaultdict(list)
    warm = defaultdict(list)
    resources = defaultdict(list)
    paths = defaultdict(list)
    for sample in samples:
        name = sample["scenario"]
        grouped[name].append(sample["elapsed_ms"])
        resources[name].append(sample)
        paths[name].append(sample["critical_path"]["duration_ms"])
        (cold if sample["startup"] == "cold" else warm)[name].append(
            sample["elapsed_ms"]
        )
    stage_groups = defaultdict(list)
    for event in traces or []:
        if event.get("phase") in TRACE_PHASES:
            stage_groups[event["phase"]].append(event["duration_ns"] / 1e6)

    def optional_max(rows, key):
        known = [r[key] for r in rows if r.get(key) is not None]
        return max(known) if known else None

    def optional_total(rows, key):
        known = [r[key] for r in rows if r.get(key) is not None]
        return sum(known) if known else None

    return {
        "schema": 1,
        "mode": mode,
        "sample_count": len(samples),
        "scenario_count": len(grouped),
        "overall": summarize([x["elapsed_ms"] for x in samples]),
        "scenarios": {
            name: {
                **summarize(values),
                "cold": summarize(cold[name]) if cold[name] else None,
                "warm": summarize(warm[name]) if warm[name] else None,
                "critical_path_ms": summarize(paths[name]),
                "resources": {
                    "cpu_ms": summarize([r["cpu_ms"] for r in resources[name]]),
                    "observed_rss_bytes": optional_max(resources[name], "rss_bytes"),
                    "child_processes": optional_max(resources[name], "child_processes"),
                    "thread_count": optional_max(resources[name], "thread_count"),
                    "read_bytes_total": optional_total(resources[name], "read_bytes"),
                    "write_bytes_total": optional_total(resources[name], "write_bytes"),
                    "allocation_peak_bytes": optional_max(
                        resources[name], "allocation_peak_bytes"
                    ),
                },
            }
            for name, values in sorted(grouped.items())
        },
        "observed_trace_stages": {
            phase: summarize(values) for phase, values in sorted(stage_groups.items())
        },
        "diagnostics": diagnostics(samples, traces),
        "disclaimer": (
            "Synthetic in-memory fixture overhead only; not browser, desktop, "
            "network, cloud, model or installed-Windows latency."
        ),
    }


def regression_candidates(report, baseline, factor=1.3, minimum_samples=30):
    if factor < 1 or type(minimum_samples) is not int or minimum_samples < 2:
        raise ValueError("Invalid regression threshold")
    if report.get("mode") != baseline.get("mode"):
        raise ValueError("Cannot compare unlike measurement modes")
    alerts = []
    for key, latest in report["scenarios"].items():
        previous = baseline.get("scenarios", {}).get(key)
        if (
            previous
            and latest["count"] >= minimum_samples
            and previous["count"] >= minimum_samples
            and latest["p95_ms"] > previous["p95_ms"] * factor
        ):
            alerts.append(
                {"scenario": key, "old_p95_ms": previous["p95_ms"],
                 "new_p95_ms": latest["p95_ms"]}
            )
    return alerts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--catalog", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trace", type=Path, help="Opt-in owned UDB JSONL trace")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--regression-factor", type=float, default=1.3)
    parser.add_argument("--minimum-samples", type=int, default=30)
    parser.add_argument("--sample-allocations", action="store_true")
    args = parser.parse_args(argv)
    if not 2 <= args.iterations <= 1000:
        parser.error("--iterations must be between 2 and 1000")
    scenarios = load_catalog(args.catalog)
    samples = []
    if args.sample_allocations:
        tracemalloc.start()
    for scenario in scenarios:
        for index in range(args.iterations):
            if args.sample_allocations:
                tracemalloc.reset_peak()
            result = run_synthetic(scenario, index)
            if args.sample_allocations:
                result["allocation_peak_bytes"] = tracemalloc.get_traced_memory()[1]
            samples.append(result)
    traces = read_trace(args.trace) if args.trace else None
    report = analyze_samples(samples, traces=traces)
    report["iterations_per_scenario"] = args.iterations
    report["trace_event_count"] = len(traces) if traces is not None else None
    report["regressions"] = []
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report["regressions"] = regression_candidates(
            report, baseline, args.regression_factor, args.minimum_samples
        )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if args.fail_on_regression and report["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
