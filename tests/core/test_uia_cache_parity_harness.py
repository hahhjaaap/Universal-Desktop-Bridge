"""Cross-platform contract checks for the Windows-only UIA cache parity harness."""

import os
from contextlib import nullcontext

import pytest

from tools import compare_uia_snapshot_cache as canary
from tools.compare_uia_snapshot_cache import compare, percentile


def test_percentiles_are_deterministic_and_interpolated():
    assert percentile([100.0, 10.0, 40.0, 20.0], 0.5) == 30.0
    assert percentile([100.0, 10.0, 40.0, 20.0], 0.95) == 91.0
    assert percentile([12.0], 0.99) == 12.0


@pytest.mark.parametrize(
    ("size", "samples"),
    [(0, 1), (49, 1), (501, 1), (1001, 1), (50, 0), (50, 31)],
)
def test_invalid_canary_sizes_or_sample_count_fail_before_windows_access(size, samples):
    with pytest.raises(ValueError, match="Allowed fixture sizes"):
        compare(size, samples)


@pytest.mark.parametrize("mismatch", [False, True])
def test_warm_comparison_reuses_private_workers_and_checks_parity(
    monkeypatch, mismatch
):
    original = os.environ.get("UDB_UIA_SNAPSHOT_CACHE")
    workers = []

    class Worker:
        def __init__(self, *_):
            self._process = None
            self.calls = 0
            self.closed = False
            workers.append(self)

        def call(self, request, *, timeout):
            assert request == {"mode": "snapshot", "hwnd": 17, "pid": 18}
            assert 0 < timeout <= 22
            flag = os.environ["UDB_UIA_SNAPSHOT_CACHE"]
            if self._process is None:
                self._process = object()
                self.flag = flag
            assert flag == self.flag
            self.calls += 1
            elements = ["one", "two"]
            if mismatch and flag == "1" and self.calls == 2:
                elements.append("unexpected")
            return {"ok": True, "elements": elements, "truncated": False}

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        canary, "_fixture", lambda _: nullcontext({"hwnd": 17, "pid": 18})
    )
    monkeypatch.setattr(canary, "_powershell", lambda: "fixture")
    if mismatch:
        with pytest.raises(AssertionError, match="snapshots differ"):
            canary.compare_warm(50, 2, worker_factory=Worker)
    else:
        report = canary.compare_warm(50, 2, worker_factory=Worker)
        assert report["samples"] == 2 and report["same_output"] is True
        assert report["truncated_samples"] == 0
        assert set(report["cold_ms"]) == {"cached", "uncached"}
        assert [worker.calls for worker in workers] == [3, 3]
    assert all(worker.closed for worker in workers)
    assert os.environ.get("UDB_UIA_SNAPSHOT_CACHE") == original


def test_dynamic_transition_rejects_a_stale_persistent_worker_snapshot():
    before = {"ok": True, "elements": [{"name": "UDB_DYNAMIC_BEFORE"}]}
    after = {"ok": True, "elements": [{"name": "UDB_DYNAMIC_AFTER"}]}
    canary._check_dynamic_transition(before, after)
    with pytest.raises(AssertionError, match="stale control value"):
        canary._check_dynamic_transition(before, before)


def test_dynamic_warm_validates_fixture_size_before_windows_access():
    with pytest.raises(ValueError, match="Allowed fixture sizes"):
        canary.compare_dynamic_warm(49, 1)


def test_dynamic_replacement_requires_old_child_and_automation_id_to_disappear():
    before = {
        "ok": True,
        "elements": [
            {
                "name": "UDB_DYNAMIC_BEFORE",
                "automation_id": "FixtureDynamicTarget",
            }
        ],
    }
    after = {
        "ok": True,
        "elements": [
            {
                "name": "UDB_DYNAMIC_REPLACED",
                "automation_id": "FixtureDynamicReplacement",
            }
        ],
    }
    canary._check_dynamic_replacement(before, after)
    with pytest.raises(AssertionError, match="removed control value"):
        canary._check_dynamic_replacement(before, before)
    stale_identity = {
        "ok": True,
        "elements": [
            {
                "name": "UDB_DYNAMIC_REPLACED",
                "automation_id": "FixtureDynamicTarget",
            }
        ],
    }
    with pytest.raises(AssertionError, match="removed automation ID"):
        canary._check_dynamic_replacement(before, stale_identity)


def test_dynamic_replacement_rejects_invalid_mutation_before_fixture_access():
    with pytest.raises(ValueError, match="Dynamic mutation"):
        canary.compare_dynamic_warm(50, 1, mutation="delete")


def test_dynamic_fixture_replacement_disposes_old_control_before_adding_new_one():
    fixture = canary.FIXTURE.read_text(encoding="utf-8")
    assert "[ValidateSet('rename','replace')]" in fixture
    assert "$panel.Controls.Remove($target)" in fixture
    assert "$target.Dispose()" in fixture
    assert "$replacement.Name='FixtureDynamicReplacement'" in fixture
    assert "$replacement.AccessibleName='UDB_DYNAMIC_REPLACED'" in fixture
