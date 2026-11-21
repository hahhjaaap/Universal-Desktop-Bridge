"""Score redacted ChatGPT-to-Windows staging A/B timing evidence offline."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

MAX_BYTES = 1_048_576
MIN_TRIALS = 50
TARGET_P95_MS = 6_000
FASTPATH_REDUCTION = 40
VARIANTS = ("baseline", "candidate")
OUTCOMES = ("verified", "failed", "timed_out", "outcome_unknown")
SAFETY_CHECKS = ("permission_parity", "navigation_parity", "no_replay")
TOP_FIELDS = {
    "schema_version",
    "scope",
    "environment",
    "revisions",
    "fixture_sha256",
    "safety_checks",
    "trials",
}
TRIAL_FIELDS = {"variant", "request_id", "elapsed_ms", "outcome"}


def _is_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch("[a-f0-9]{" + str(length) + "}", value) is not None
        and value != "0" * length
    )


def _metrics(trials):
    counts = Counter(trial["outcome"] for trial in trials)
    verified = sorted(
        trial["elapsed_ms"] for trial in trials if trial["outcome"] == "verified"
    )
    attempts = len(trials)
    # Non-verified attempts rank after every verified completion. A fast
    # rejection or timeout cannot make a latency percentile look better.
    percentiles = {}
    for p in (50, 95, 99):
        index = (p * attempts + 99) // 100 - 1
        percentiles[f"p{p}_ms"] = (
            verified[index] if 0 <= index < len(verified) else None
        )
    return {
        "attempts": attempts,
        "outcomes": {outcome: counts[outcome] for outcome in OUTCOMES},
        "error_rate_percent": (
            round(100 * (attempts - len(verified)) / attempts, 2) if attempts else None
        ),
        **percentiles,
    }


def evaluate(report, *, baseline_sha, candidate_sha, profile):
    if profile not in ("release", "fastpath"):
        raise ValueError("Unknown acceptance profile.")
    if (
        not _is_hex(baseline_sha, 40)
        or not _is_hex(candidate_sha, 40)
        or baseline_sha == candidate_sha
    ):
        raise ValueError("Specify two distinct full source revisions.")
    if (
        not isinstance(report, dict)
        or set(report) != TOP_FIELDS
        or type(report["schema_version"]) is not int
        or report["schema_version"] != 1
        or report["scope"] != "chatgpt-cloudflare-windows"
        or report["environment"] != "isolated-staging"
        or not _is_hex(report["fixture_sha256"], 64)
    ):
        raise ValueError("Expected a version 1 isolated end-to-end evidence report.")
    if report["revisions"] != {"baseline": baseline_sha, "candidate": candidate_sha}:
        raise ValueError("Evidence revisions do not match the expected builds.")

    safety = report["safety_checks"]
    if (
        not isinstance(safety, dict)
        or set(safety) != set(SAFETY_CHECKS)
        or any(type(safety[check]) is not bool for check in SAFETY_CHECKS)
    ):
        raise ValueError("Invalid safety checklist.")
    if not isinstance(report["trials"], list):
        raise ValueError("Trials must be a list.")

    seen = set()
    groups = {variant: [] for variant in VARIANTS}
    for trial in report["trials"]:
        if (
            not isinstance(trial, dict)
            or set(trial) != TRIAL_FIELDS
            or trial["variant"] not in VARIANTS
            or trial["outcome"] not in OUTCOMES
            or not isinstance(trial["request_id"], str)
            or re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", trial["request_id"]) is None
            or type(trial["elapsed_ms"]) is not int
            or not 0 < trial["elapsed_ms"] <= 2**53 - 1
        ):
            raise ValueError("Invalid trial.")
        if trial["request_id"] in seen:
            raise ValueError("Duplicate trial request ID.")
        seen.add(trial["request_id"])
        groups[trial["variant"]].append(trial)

    metrics = {variant: _metrics(groups[variant]) for variant in VARIANTS}
    baseline = metrics["baseline"]["p95_ms"]
    candidate = metrics["candidate"]["p95_ms"]
    checks = {
        "minimum_samples_per_build": all(
            row["attempts"] >= MIN_TRIALS for row in metrics.values()
        ),
        "candidate_p95_at_most_6_seconds": (
            candidate is not None and candidate <= TARGET_P95_MS
        ),
        **safety,
    }
    reduction = (
        round(100 * (1 - candidate / baseline), 2)
        if baseline is not None and candidate is not None
        else None
    )
    if profile == "fastpath":
        checks["p95_reduction_at_least_40_percent"] = (
            baseline is not None
            and candidate is not None
            and candidate * 100 <= baseline * (100 - FASTPATH_REDUCTION)
        )
    return {
        "result": "thresholds_met" if all(checks.values()) else "blocked",
        "checks": checks,
        "metrics": metrics,
        "p95_reduction_percent": reduction,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--profile", choices=("release", "fastpath"), required=True)
    args = parser.parse_args(argv)
    try:
        with args.report.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Evidence report exceeds the size limit.")
        result = evaluate(
            json.loads(raw),
            baseline_sha=args.baseline_sha,
            candidate_sha=args.candidate_sha,
            profile=args.profile,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        parser.error("Could not read the evidence report as JSON.")
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "thresholds_met" else 1


if __name__ == "__main__":
    raise SystemExit(main())
