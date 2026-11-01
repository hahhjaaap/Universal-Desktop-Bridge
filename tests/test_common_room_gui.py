"""Qt Common Room integration on a disposable v3 database, with no AI grant."""

import datetime
import sqlite3

import pytest

pytest.importorskip("PySide6")

from udb.common_room_gui import CommonRoomDialog, database_for_project
from udb.manager import make_app


def room_fixture(tmp_path):
    root = tmp_path / "source"
    folder = root / "chatgpt-workspace"
    folder.mkdir(parents=True)
    path = folder / "workspace.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            PRAGMA user_version=3;
            PRAGMA foreign_keys=ON;
            CREATE TABLE participants(name TEXT PRIMARY KEY,role TEXT,last_seen TEXT);
            CREATE TABLE topics(name TEXT PRIMARY KEY,goal TEXT,created_at TEXT);
            CREATE TABLE messages(
                id INTEGER PRIMARY KEY,request_id TEXT UNIQUE,topic TEXT REFERENCES topics(name),
                author TEXT REFERENCES participants(name),kind TEXT,body TEXT,
                reply_to INTEGER,created_at TEXT
            );
            CREATE TABLE tasks(
                id INTEGER PRIMARY KEY,request_id TEXT UNIQUE,topic TEXT REFERENCES topics(name),
                title TEXT,assignee TEXT,initial_assignee TEXT,state TEXT,
                revision INTEGER,created_at TEXT,updated_at TEXT
            );
            INSERT INTO topics(name,goal,created_at) VALUES('general','test','now');
            """
        )
    return root, path


def test_existing_room_is_edited_without_creating_a_second_database(tmp_path):
    make_app()
    root, path = room_fixture(tmp_path)
    dialog = CommonRoomDialog(root)
    assert dialog.room_path == path
    assert dialog.topic.currentText() == "general"
    dialog.name.setText("Human")
    dialog.join()
    dialog.composer.setPlainText("<unsafe-looking> text is literal")
    dialog.post()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT body FROM messages").fetchone()[0] == (
            "<unsafe-looking> text is literal"
        )
        assert db.execute("SELECT name FROM participants").fetchone()[0] == "Human"
    dialog.close()
    assert len(list(root.rglob("workspace.sqlite3"))) == 1


def test_missing_workspace_never_created(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(FileNotFoundError, match="workspace.sqlite3"):
        database_for_project(root)
    assert not (root / "chatgpt-workspace").exists()


def test_task_revision_refuses_stale_writes(tmp_path):
    make_app()
    root, path = room_fixture(tmp_path)
    with sqlite3.connect(path) as db:
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        db.execute(
            "INSERT INTO tasks(request_id,topic,title,state,revision,created_at,updated_at) "
            "VALUES('req','general','work','todo',1,?,?)",
            (stamp, stamp),
        )
    dialog = CommonRoomDialog(root)
    item = dialog.tasks.topLevelItem(0)
    assert item.text(4) == "1"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE tasks SET revision=2,state='doing' WHERE id=1")
    dialog.tasks.setCurrentItem(item)
    dialog.state.setCurrentText("done")
    with pytest.raises(ValueError, match="đã thay đổi"):
        dialog.update_task()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM tasks WHERE id=1").fetchone()[0] == "doing"
    dialog.close()
