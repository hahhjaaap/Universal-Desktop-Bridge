"""Owner-grant-scoped native FastPath receipts: no real Windows input."""

import hashlib
import json
import threading

import pytest

from udb.core import PolicyError
from udb.desktop_fastpath_receipts import run_once

GRANT = "a" * 32
PLAN = [{"action": "type", "text": "sensitive user content"}]


def test_one_shot_receipt_is_persisted_before_input_and_never_replays(tmp_path):
    invoked = []

    def run():
        invoked.append(True)
        receipt = (
            tmp_path
            / "desktop-fastpath-receipts"
            / GRANT
            / (hashlib.sha256(b"job-1").hexdigest() + ".json")
        )
        row = json.loads(receipt.read_text())
        assert row["state"] == "running"
        assert "sensitive user content" not in receipt.read_text()
        return {"ok": True, "completed_steps": 1, "results": [{"index": 0}]}

    first = run_once(tmp_path, GRANT, "job-1", PLAN, run)
    assert first["ok"] and first["state"] == "completed" and not first["replayed"]
    later = run_once(
        tmp_path, GRANT, "job-1", PLAN, lambda: pytest.fail("must not replay")
    )
    assert later["ok"] and later["cached_result"] and not later["result_available"]
    assert later["replayed"] is False and later["replay_safe"] is False
    assert len(invoked) == 1


def test_changed_plan_under_same_request_id_refused_without_input(tmp_path):
    run_once(tmp_path, GRANT, "job-2", PLAN, lambda: {"ok": True, "completed_steps": 1})
    with pytest.raises(PolicyError, match="different actions"):
        run_once(
            tmp_path,
            GRANT,
            "job-2",
            [{"action": "key", "key": "ENTER"}],
            lambda: pytest.fail("must not send input"),
        )


def test_interrupted_mutation_remains_unknown_on_repeat(tmp_path):
    def break_after_input():
        raise RuntimeError("backend terminated just after input")

    first = run_once(tmp_path, GRANT, "lost-response", PLAN, break_after_input)
    assert first["state"] == "outcome_unknown" and first["replay_safe"] is False
    repeated = run_once(
        tmp_path, GRANT, "lost-response", PLAN, lambda: pytest.fail("unsafe retry")
    )
    assert repeated["outcome_unknown"] and not repeated["replayed"]
    assert repeated["completed_steps"] == 0


def test_uncertain_legacy_batch_result_is_not_retried(tmp_path):
    result = run_once(
        tmp_path,
        GRANT,
        "verification-mismatch",
        PLAN,
        lambda: {
            "ok": False,
            "completed_steps": 0,
            "outcome_unknown": True,
            "failed_index": 0,
        },
    )
    assert result["state"] == "outcome_unknown"
    assert run_once(
        tmp_path,
        GRANT,
        "verification-mismatch",
        PLAN,
        lambda: pytest.fail("must not replay"),
    )["outcome_unknown"]


def test_receipts_are_scoped_by_local_grant(tmp_path):
    first = run_once(
        tmp_path, GRANT, "same-name", PLAN, lambda: {"ok": True, "completed_steps": 1}
    )
    second = run_once(
        tmp_path,
        "b" * 32,
        "same-name",
        PLAN,
        lambda: {"ok": True, "completed_steps": 1},
    )
    assert first["ok"] and second["ok"]
    assert len(list((tmp_path / "desktop-fastpath-receipts").glob("*/*.json"))) == 2


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "/path",
        "../escape",
        "üñíçødé",
        "a" * 81,
    ],
)
def test_invalid_request_id_rejected_before_any_action(tmp_path, bad):
    with pytest.raises(PolicyError):
        run_once(tmp_path, GRANT, bad, PLAN, lambda: pytest.fail("no input"))
    assert not (tmp_path / "desktop-fastpath-receipts").exists()


def test_missing_or_non_json_steps_rejected_before_any_action(tmp_path):
    for steps in (None, [], [{"action": "type", "text": object()}]):
        with pytest.raises(PolicyError):
            run_once(
                tmp_path, GRANT, "bad-plan", steps, lambda: pytest.fail("no input")
            )


def test_existing_running_receipt_is_never_reexecuted(tmp_path):
    path = tmp_path / "desktop-fastpath-receipts" / GRANT
    path.mkdir(parents=True)
    digest = hashlib.sha256(
        json.dumps(
            PLAN, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()
    file = path / (hashlib.sha256(b"running-job").hexdigest() + ".json")
    file.write_text(
        json.dumps(
            {
                "request_id": "running-job",
                "digest": digest,
                "state": "running",
                "completed_steps": 0,
            }
        ),
        encoding="ascii",
    )
    report = run_once(
        tmp_path, GRANT, "running-job", PLAN, lambda: pytest.fail("cannot replay")
    )
    assert report["outcome_unknown"] and report["state"] == "running"
    assert report["replayed"] is False

def test_concurrent_duplicate_request_never_enters_input_lane_twice(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    invoked = []

    def execute():
        invoked.append(True)
        entered.set()
        if not release.wait(timeout=3):
            raise AssertionError("fixture did not release the first request")
        return {"ok": True, "completed_steps": 1}

    first_result = []
    first_error = []

    def first_call():
        try:
            first_result.append(
                run_once(tmp_path, GRANT, "concurrent-job", PLAN, execute)
            )
        except Exception as exc:  # pragma: no cover - asserted below
            first_error.append(exc)

    worker = threading.Thread(target=first_call, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=2), "first request did not enter its executor"

        duplicate = run_once(
            tmp_path,
            GRANT,
            "concurrent-job",
            PLAN,
            lambda: pytest.fail("concurrent duplicate must never dispatch input"),
        )
        assert duplicate["state"] == "running"
        assert duplicate["outcome_unknown"] is True
        assert duplicate["replayed"] is False
        assert duplicate["replay_safe"] is False
    finally:
        release.set()
        worker.join(timeout=3)

    assert not worker.is_alive(), "first request did not finish"
    assert first_error == []
    assert len(first_result) == 1
    assert first_result[0]["state"] == "completed"
    assert invoked == [True]

    completed = run_once(
        tmp_path,
        GRANT,
        "concurrent-job",
        PLAN,
        lambda: pytest.fail("completed duplicate must not dispatch input"),
    )
    assert completed["state"] == "completed"
    assert completed["replayed"] is False
    assert invoked == [True]
