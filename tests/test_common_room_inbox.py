"""Regression tests for Common Room participant inbox and concurrent sessions."""

import argparse
import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1] / "examples" / "chatgpt-workspace"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(WORKSPACE))
    return importlib.import_module("room"), importlib.import_module("chain")


def message(room, db, author, body, request_id, topic="general"):
    return room.post(
        db,
        argparse.Namespace(
            topic=topic,
            author=author,
            kind="message",
            body=body,
            reply_to=None,
            request_id=request_id,
        ),
    )


def test_inbox_separates_other_messages_and_own_tasks(modules, tmp_path):
    room, _ = modules
    db = room.connect(tmp_path / "room.sqlite3")
    try:
        for name in ("Alice", "Bob", "Charlie"):
            room.join(db, name, "Contributor")
        room.topic(db, "development", "Build the UDB room")
        alice = message(room, db, "Alice", "Task for Bob", "a1")
        message(room, db, "Bob", "Bob's own reply", "b1")
        charlie = message(room, db, "Charlie", "Review code", "c1", "development")
        pending = room.task_create(
            db, "Review implementation", "development", "Bob", "task-for-bob"
        )
        completed = room.task_create(db, "Completed", "general", "Bob", "task-done")
        room.task_update(db, completed["id"], "done", 1)
        room.task_create(db, "Someone else's task", "general", "Charlie", "other")

        first = room.inbox(db, "Bob", after=0, limit=1)
        assert [m["id"] for m in first["messages"]] == [alice["id"]]
        assert first["more"] is True
        assert first["next_after"] == alice["id"]
        assert [t["id"] for t in first["pending_tasks"]] == [pending["id"]]

        second = room.inbox(db, "Bob", after=first["next_after"], limit=1)
        assert [m["id"] for m in second["messages"]] == [charlie["id"]]
        assert second["more"] is False
        assert second["next_after"] == charlie["id"]
        assert room.inbox(db, "Bob", after=second["next_after"])["messages"] == []
        assert [m["id"] for m in room.inbox(db, "Bob", topic="development")["messages"]] == [
            charlie["id"]
        ]
        assert room.inbox(db, "Bob", topic="general")["pending_tasks"] == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db.close()


@pytest.mark.parametrize(
    "name,after,limit,topic,error",
    [
        ("Ghost", 0, 20, None, "Unknown participant"),
        ("Bob", -1, 20, None, "after"),
        ("Bob", True, 20, None, "after"),
        ("Bob", 0, 0, None, "limit"),
        ("Bob", 0, 201, None, "limit"),
        ("Bob", 0, 20, " ", "topic"),
    ],
)
def test_inbox_rejects_invalid_input(modules, tmp_path, name, after, limit, topic, error):
    room, _ = modules
    db = room.connect(tmp_path / "room.sqlite3")
    try:
        room.join(db, "Bob", "Reviewer")
        with pytest.raises(ValueError, match=error):
            room.inbox(db, name, after, limit, topic)
    finally:
        db.close()


def test_chain_inbox_works_after_join_and_prevalidates(modules, tmp_path):
    room, chain = modules
    db = room.connect(tmp_path / "room.sqlite3")
    try:
        result = chain.run(
            db,
            {
                "id": "bob-inbox-001",
                "steps": [
                    {"op": "join", "name": "Bob", "role": "Reviewer"},
                    {"op": "join", "name": "Alice", "role": "Coordinator"},
                    {"op": "post", "author": "Alice", "body": "Please review"},
                    {"op": "task", "title": "Review", "assignee": "Bob"},
                    {"op": "inbox", "name": "Bob", "after": 0, "limit": 1},
                ],
            },
        )
        assert result["ok"] is True
        inbox = result["results"][4]["result"]
        assert inbox["participant"] == "Bob"
        assert [msg["body"] for msg in inbox["messages"]] == ["Please review"]
        assert inbox["pending_tasks"][0]["title"] == "Review"

        invalid = chain.run(
            db,
            {
                "id": "invalid-inbox",
                "steps": [
                    {"op": "join", "name": "ShouldNotBeAdded"},
                    {"op": "inbox", "name": "Bob", "after": True},
                ],
            },
        )
        assert not invalid["ok"] and invalid["executed"] == 0
        assert db.execute(
            "SELECT 1 FROM participants WHERE name='ShouldNotBeAdded'"
        ).fetchone() is None
    finally:
        db.close()


def test_concurrent_writers_and_independent_inboxes(modules, tmp_path):
    room, _ = modules
    path = tmp_path / "room.sqlite3"
    db = room.connect(path)
    for name in ("Alice", "Bob", "Charlie"):
        room.join(db, name, "Contributor")
    db.close()

    def write(i):
        connection = room.connect(path)
        try:
            return message(room, connection, "Alice", str(i), f"concurrent-{i}")["id"]
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        sent_ids = list(pool.map(write, range(20)))
    assert len(set(sent_ids)) == 20

    db = room.connect(path)
    try:
        a = room.inbox(db, "Bob", after=0, limit=7)
        b = room.inbox(db, "Charlie", after=0, limit=200)
        assert len(a["messages"]) == 7 and a["more"]
        assert len(b["messages"]) == 20 and not b["more"]
        a2 = room.inbox(db, "Bob", after=a["next_after"], limit=200)
        assert len(a2["messages"]) == 13
        assert [m["id"] for m in a["messages"] + a2["messages"]] == [
            m["id"] for m in b["messages"]
        ]
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db.close()
