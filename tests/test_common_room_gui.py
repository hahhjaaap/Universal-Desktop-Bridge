"""Qt Common Room integration on a disposable v3 database, with no AI grant."""

import datetime
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def qt_components():
    # No Qt import during test collection: headless tests verify the module
    # was not imported by the standalone manager.
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from udb.common_room_gui import CommonRoomDialog, database_for_project

    app = QApplication.instance() or QApplication([])
    return app, CommonRoomDialog, database_for_project


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
    app, CommonRoomDialog, _ = qt_components()
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


def test_room_in_repository_examples_is_discovered(tmp_path):
    _, _, database_for_project = qt_components()
    source = tmp_path / "source"
    example = source / "examples" / "chatgpt-workspace"
    example.mkdir(parents=True)
    db_file = example / "workspace.sqlite3"
    with sqlite3.connect(db_file) as db:
        db.execute("PRAGMA user_version=3")
    assert database_for_project(source) == db_file


def test_missing_workspace_never_created(tmp_path):
    _, _, database_for_project = qt_components()
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(FileNotFoundError, match="workspace.sqlite3"):
        database_for_project(root)
    assert not (root / "chatgpt-workspace").exists()


def test_task_revision_refuses_stale_writes(tmp_path):
    app, CommonRoomDialog, _ = qt_components()
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


def test_switching_topics_clears_selected_message_details(tmp_path):
    _, CommonRoomDialog, _ = qt_components()
    root, path = room_fixture(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO topics(name,goal,created_at) VALUES('later','later','now')"
        )
        db.execute(
            "INSERT INTO participants(name,role,last_seen) VALUES('Human','user','now')"
        )
        db.execute(
            "INSERT INTO messages(request_id,topic,author,kind,body,created_at) "
            "VALUES('message1','general','Human','message','Old private message','now')"
        )
    dialog = CommonRoomDialog(root)
    assert dialog.messages.topLevelItemCount() == 1
    dialog.messages.setCurrentItem(dialog.messages.topLevelItem(0))
    assert dialog.message_detail.toPlainText() == "Old private message"
    dialog.topic.setCurrentText("later")
    assert dialog.messages.topLevelItemCount() == 0
    assert dialog.message_detail.toPlainText() == ""
    dialog.close()


def test_read_failure_clears_stale_room_rows_and_browser_preview(tmp_path):
    _, CommonRoomDialog, _ = qt_components()
    root, path = room_fixture(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO participants(name,role,last_seen) VALUES('Human','user','now')"
        )
        db.execute(
            "INSERT INTO messages(request_id,topic,author,kind,body,created_at) "
            "VALUES('message2','general','Human','message','Stale message','now')"
        )
        db.execute(
            "INSERT INTO tasks(request_id,topic,title,state,revision,created_at,updated_at) "
            "VALUES('task2','general','Stale task','todo',1,'now','now')"
        )
    dialog = CommonRoomDialog(root)
    assert dialog.messages.topLevelItemCount() == 1
    assert dialog.tasks.topLevelItemCount() == 1
    dialog.messages.setCurrentItem(dialog.messages.topLevelItem(0))
    assert dialog.message_detail.toPlainText() == "Stale message"

    # Simulate a project folder being detached while the GUI stays open.
    path.rename(path.with_suffix(".unavailable"))
    dialog.load_content()
    assert dialog.messages.topLevelItemCount() == 0
    assert dialog.tasks.topLevelItemCount() == 0
    assert dialog.message_detail.toPlainText() == ""
    assert "Không đọc được" in dialog.browser_status.text()
    assert dialog.browser_image.pixmap() is None
    dialog.close()


def test_no_topics_remain_does_not_display_previous_results(tmp_path):
    _, CommonRoomDialog, _ = qt_components()
    root, path = room_fixture(tmp_path)
    dialog = CommonRoomDialog(root)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM topics")
    dialog.reload()
    assert dialog.topic.currentText() == ""
    assert dialog.messages.topLevelItemCount() == 0
    assert dialog.tasks.topLevelItemCount() == 0
    assert "Chưa có chủ đề" in dialog.browser_status.text()
    dialog.close()


def test_room_connection_releases_sqlite_handle_after_context(tmp_path):
    pytest.importorskip("PySide6")
    from udb.common_room_gui import open_room

    _, path = room_fixture(tmp_path)
    with open_room(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        db.execute("SELECT 1")
    # This rename fails on Windows when an old read connection is still open.
    moved = path.rename(path.with_suffix(".unavailable"))
    assert moved.is_file()


def test_refresh_failure_hides_stale_messages_and_topic(tmp_path):
    _, CommonRoomDialog, _ = qt_components()
    root, path = room_fixture(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO participants(name,role,last_seen) VALUES('Human','user','now')")
        db.execute(
            "INSERT INTO messages(request_id,topic,author,kind,body,created_at) "
            "VALUES('message3','general','Human','message','Old topic body','now')"
        )
    dialog = CommonRoomDialog(root)
    assert dialog.messages.topLevelItemCount() == 1
    path.rename(path.with_suffix(".gone"))
    with pytest.raises(FileNotFoundError):
        dialog.reload()
    assert dialog.topic.currentText() == ""
    assert dialog.messages.topLevelItemCount() == 0
    assert dialog.message_detail.toPlainText() == ""
    assert "Không đọc được" in dialog.browser_status.text()
    assert not dialog.topic.signalsBlocked()
    dialog.close()
