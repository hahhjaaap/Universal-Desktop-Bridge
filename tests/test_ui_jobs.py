"""Task list filter regression: no log/script scanning, no invented completion."""

from udb.ui_jobs import job_group, job_metadata, visible_jobs


def _job(job_id, status, project, language, script="TOP SECRET"):
    import json

    return dict(
        id=job_id,
        status=status,
        info=json.dumps({"project": project, "language": language, "script": script}),
    )


def test_job_groups_fail_closed_for_unrecognized_states():
    assert job_group("running") == "Đang chạy"
    assert job_group("reviewing") == "Cần chú ý"
    assert job_group("failed") == "Cần chú ý"
    assert job_group("completed") == "Đã xong"
    assert job_group("unknown_future_state") == "Cần chú ý"


def test_metadata_filters_ignore_private_scripts():
    rows = [
        _job("job-1", "running", "Alpha", "Python"),
        _job("job-2", "failed", "Beta", "PowerShell"),
        _job("job-3", "completed", "Gamma", "Python"),
    ]
    assert [r["id"] for r in visible_jobs(rows, "alpha", "Tất cả")] == ["job-1"]
    assert [r["id"] for r in visible_jobs(rows, "job-2", "Cần chú ý")] == ["job-2"]
    assert visible_jobs(rows, "TOP SECRET", "Tất cả") == []
    assert len(visible_jobs(rows, "", "Tất cả")) == 3
    assert len(visible_jobs(rows, "", "bogus")) == 3


def test_broken_job_metadata_is_safe():
    assert job_metadata({"info": "{"}) == {}
    assert job_metadata({"info": "[]"}) == {}
    assert visible_jobs(
        [{"id": "abc", "status": "failed", "info": "{"}], "", "Cần chú ý"
    )
