"""GUI idle refresh must not repeatedly read finished job logs or scripts."""

import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from udb.manager_job_refresh import should_reload_job_details


@pytest.mark.parametrize(
    ("status", "refresh_needed"),
    [
        ("running", True),
        ("reviewing", True),
        ("stopping", True),
        ("queued", True),
        (None, True),
        ("completed", False),
        ("failed", False),
        ("timeout", False),
        ("stopped", False),
        ("output_limit", False),
    ],
)
def test_job_detail_refresh_policy_preserves_live_updates(status, refresh_needed):
    assert should_reload_job_details(False, status) is refresh_needed
    assert should_reload_job_details(True, status) is True


@pytest.mark.parametrize(
    ("status", "expected_calls"), [("completed", 0), ("failed", 0), ("running", 1)]
)
def test_unchanged_job_inventory_skips_finished_job_io(
    tmp_path, status, expected_calls
):
    pytest.importorskip("PySide6")
    from udb.manager_refresh import ManagerRefreshMixin

    path = tmp_path / "jobs.sqlite3"
    info = '{"project":"fixture"}'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE protected (root TEXT)")
        db.execute("CREATE TABLE jobs (id TEXT, status TEXT, info TEXT)")
        db.execute(
            "INSERT INTO jobs(id,status,info) VALUES (?,?,?)",
            ("job-1", status, info),
        )

    class Agent:
        def connect(self):
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            return closing(db)

    jobs = Mock()
    jobs.selectedItems.return_value = [SimpleNamespace(data=lambda *_args: "job-1")]
    screen = SimpleNamespace(
        agent=Agent(),
        last_job_signature=(("job-1", status, info),),
        _protected_signature=(),
        jobs=jobs,
        job_tabs=Mock(),
        jobs_empty=Mock(),
        job_search=SimpleNamespace(text=lambda: ""),
        job_group_filter=SimpleNamespace(currentText=lambda: "Tất cả"),
        job_filter_feedback=Mock(),
        activity_timeline=SimpleNamespace(topLevelItemCount=lambda: 0),
        job_output=Mock(),
        job_script=Mock(),
        show_job=Mock(),
    )
    ManagerRefreshMixin._refresh_jobs(screen)
    assert screen.show_job.call_count == expected_calls
    jobs.clear.assert_not_called()
