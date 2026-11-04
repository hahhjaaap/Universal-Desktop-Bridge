"""Common Room snapshot budgeting and consistent SQLite cursor regressions."""

import copy
import importlib.util
import json
import random
import tempfile
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "chatgpt-workspace"


def mirror_module(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    spec = importlib.util.spec_from_file_location(
        "udb_workspace_mirror_under_test", EXAMPLE / "fast_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def slow_reference(snapshot, max_bytes=48000):
    while (
        len(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        > max_bytes
    ):
        if len(snapshot["participants"]) > 4:
            snapshot["participants"].pop()
            snapshot["participants_truncated"] = True
        elif len(snapshot["topics"]) > 4:
            snapshot["topics"].pop()
            snapshot["topics_truncated"] = True
        elif len(snapshot["messages"]) > 1:
            snapshot["messages"].pop(0)
            snapshot["oldest_included_id"] = snapshot["messages"][0]["id"]
            snapshot["history_truncated"] = True
        else:
            raise ValueError("Unexpected oversized snapshot")
    return snapshot


def synthetic_snapshot(seed):
    rand = random.Random(seed)
    participants = [
        {"name": f"user-{i}", "role": ("🙂" if i % 2 else "role") * rand.randint(2, 70)}
        for i in range(rand.randrange(1, 110))
    ]
    topics = [
        {"name": f"topic-{i}", "goal": ("中文" if i % 2 else "goal") * rand.randint(3, 120)}
        for i in range(rand.randrange(1, 110))
    ]
    messages = [
        {"id": i + 1, "body": ("Xin chào🙂" if i % 2 else "Hello") * rand.randint(4, 180)}
        for i in range(rand.randrange(1, 25))
    ]
    return {
        "format": 1,
        "captured_at": "2026-11-04T00:00:00Z",
        "latest_id": messages[-1]["id"],
        "oldest_included_id": messages[0]["id"],
        "history_truncated": False,
        "topics_truncated": False,
        "participants_truncated": False,
        "messages": messages,
        "topics": topics,
        "participants": participants,
    }


@pytest.mark.parametrize("seed", range(50))
def test_fast_budget_matches_original_byte_for_byte(monkeypatch, seed):
    module = mirror_module(monkeypatch)
    snapshot = synthetic_snapshot(seed)
    fast = copy.deepcopy(snapshot)
    slow = copy.deepcopy(snapshot)
    assert module.bound_snapshot(fast) == slow_reference(slow)


def test_too_large_even_at_minimum_remains_a_fail_closed_error(monkeypatch):
    module = mirror_module(monkeypatch)
    snap = synthetic_snapshot(8)
    with pytest.raises(ValueError, match="oversized"):
        module.bound_snapshot(snap, max_bytes=20)


def test_history_cursor_is_checked_inside_the_read_transaction(monkeypatch):
    module = mirror_module(monkeypatch)
    import room

    with tempfile.TemporaryDirectory(prefix="udb-read-tx-") as tmp:
        root = Path(tmp)
        db = room.connect(root / "workspace.sqlite3")
        room.join(db, "tester", "tester")
        with db:
            for i in range(20):
                db.execute(
                    "INSERT INTO messages(request_id,topic,author,kind,body,reply_to,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (f"r{i}", "general", "tester", "message", "ok", None, room.now()),
                )
        db.close()
        mirror = module.Mirror(root, interval_ms=25)
        seen = []
        mirror.db.set_trace_callback(seen.append)
        try:
            changed, _ = mirror.refresh(force=True)
            assert changed
            begin = next(i for i, s in enumerate(seen) if s.upper() == "BEGIN")
            check = next(
                i
                for i, s in enumerate(seen)
                if "SELECT 1 FROM MESSAGES WHERE ID<" in s.upper()
            )
            rollback = next(i for i, s in enumerate(seen) if s.upper() == "ROLLBACK")
            assert begin < check < rollback
        finally:
            mirror.close()
