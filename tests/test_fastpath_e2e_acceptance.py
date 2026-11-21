"""Focused coverage for the offline FastPath acceptance scorer."""

import pytest

from tools.check_fastpath_e2e import evaluate

BASELINE = "a" * 40
CANDIDATE = "b" * 40


def report():
    return {
        "schema_version": 1,
        "scope": "chatgpt-cloudflare-windows",
        "environment": "isolated-staging",
        "revisions": {"baseline": BASELINE, "candidate": CANDIDATE},
        "fixture_sha256": "c" * 64,
        "safety_checks": {
            "permission_parity": True,
            "navigation_parity": True,
            "no_replay": True,
        },
        "trials": [
            {
                "variant": variant,
                "request_id": f"{variant}-{trial}",
                "elapsed_ms": elapsed,
                "outcome": "verified",
            }
            for trial in range(50)
            for variant, elapsed in (("baseline", 10_000), ("candidate", 6_000))
        ],
    }


def score(data, profile="fastpath"):
    return evaluate(
        data, baseline_sha=BASELINE, candidate_sha=CANDIDATE, profile=profile
    )


def test_limits_are_inclusive():
    result = score(report())
    assert result["result"] == "thresholds_met"
    assert result["metrics"]["candidate"]["p95_ms"] == 6000
    assert result["p95_reduction_percent"] == 40


def test_short_report_and_failed_safety_check_block_acceptance():
    data = report()
    del data["trials"][-1]
    data["safety_checks"]["no_replay"] = False
    result = score(data)
    assert result["result"] == "blocked"
    assert not result["checks"]["minimum_samples_per_build"]
    assert not result["checks"]["no_replay"]


def test_fast_failures_cannot_improve_reported_latency():
    data = report()
    for index in (1, 3, 5):
        data["trials"][index].update(outcome="timed_out", elapsed_ms=10)
    result = score(data)
    assert result["result"] == "blocked"
    candidate = result["metrics"]["candidate"]
    assert candidate["p50_ms"] == 6000
    assert candidate["p95_ms"] is None
    assert candidate["p99_ms"] is None
    assert candidate["outcomes"]["timed_out"] == 3
    assert candidate["error_rate_percent"] == 6


def test_duplicate_request_is_rejected_even_across_builds():
    data = report()
    data["trials"][1]["request_id"] = data["trials"][0]["request_id"]
    with pytest.raises(ValueError, match="Duplicate trial"):
        score(data)


@pytest.mark.parametrize("field", ["scope", "revisions"])
def test_different_scope_or_revision_is_rejected(field):
    data = report()
    data[field] = "windows-host-only"
    with pytest.raises(ValueError):
        score(data)


def test_release_does_not_require_fastpath_relative_reduction():
    data = report()
    for trial in data["trials"]:
        trial["elapsed_ms"] = 5900
    assert score(data, "release")["result"] == "thresholds_met"
    assert score(data, "fastpath")["result"] == "blocked"
