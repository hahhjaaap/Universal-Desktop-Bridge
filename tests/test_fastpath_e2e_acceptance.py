"""Focused coverage for the offline FastPath acceptance scorer."""

import pytest

from tools.check_fastpath_e2e import evaluate

BASELINE = "a" * 40
CANDIDATE = "b" * 40


def report():
    trials = []
    for trial in range(50):
        order = (
            (("baseline", 10_000), ("candidate", 6_000))
            if trial % 2 == 0
            else (("candidate", 6_000), ("baseline", 10_000))
        )
        for variant, elapsed in order:
            trials.append(
                {
                    "sequence": len(trials),
                    "variant": variant,
                    "request_id": f"{variant}-{trial}",
                    "elapsed_ms": elapsed,
                    "outcome": "verified",
                }
            )
    return {
        "schema_version": 2,
        "scope": "chatgpt-cloudflare-windows",
        "environment": "isolated-staging",
        "revisions": {"baseline": BASELINE, "candidate": CANDIDATE},
        "fixture_sha256": "c" * 64,
        "worker_revision": "d" * 8,
        "safety_checks": {
            "permission_parity": True,
            "navigation_parity": True,
            "no_replay": True,
        },
        "trials": trials,
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
    for index in (1, 2, 5):
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


def test_grouped_build_runs_are_blocked_even_with_good_latency():
    data = report()
    data["trials"] = sorted(data["trials"], key=lambda row: row["variant"])
    for sequence, trial in enumerate(data["trials"]):
        trial["sequence"] = sequence
    result = score(data)
    assert result["result"] == "blocked"
    assert not result["checks"]["interleaved_order"]
    assert not result["checks"]["both_ab_and_ba_order"]


def test_noncontiguous_trial_sequence_is_rejected():
    data = report()
    data["trials"][0]["sequence"] = 99
    with pytest.raises(ValueError, match="Invalid trial"):
        score(data)


def test_worker_revision_is_required_and_pinned():
    data = report()
    del data["worker_revision"]
    with pytest.raises(ValueError, match="version 2"):
        score(data)



def test_worker_revision_rejects_unbounded_or_unsafe_identifiers():
    data = report()
    data["worker_revision"] = "worker version with spaces"
    with pytest.raises(ValueError, match="version 2"):
        score(data)
