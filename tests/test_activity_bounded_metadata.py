"""Oversized metadata must not consume unbounded CPU/RAM or leak tokens."""

import tracemalloc
from types import SimpleNamespace

from udb import activity


def test_regular_metadata_retains_redaction_and_truncation_contract():
    assert activity.clean("a" * 241) == "a" * 240 + "..."
    assert activity.clean("hello\n\x1bworld") == "helloworld"
    assert "sk-supersecretkey" not in activity.clean("sk-supersecretkey")
    assert "Bearer private-token" not in activity.clean("Bearer private-token")
    assert "secret=password" not in activity.clean("secret=password")
    assert "\u202e" not in activity.clean("abc\u202edef")


def test_oversized_metadata_fails_closed_before_regex_or_large_copies(monkeypatch):
    secret = "secret=do-not-log-me"
    massive = "X" * (8 * 1024 * 1024) + secret

    def forbidden_regex(*args, **kwargs):
        raise AssertionError("oversized input must not reach regex")

    # Never patch re.sub itself: re is a process-global module and pytest
    # calls it during teardown and exception rendering.
    monkeypatch.setattr(activity, "re", SimpleNamespace(sub=forbidden_regex))
    tracemalloc.start()
    try:
        result = activity.clean(massive)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result == "[oversized metadata]"
    assert secret not in result
    assert peak < 1024 * 1024


def test_oversized_activity_details_do_not_enter_sqlite(tmp_path):
    secret = "secret=private-value"
    log = activity.Activity(tmp_path)
    log.emit("call", "fixture", details={"path": secret + "x" * 4096})
    rows = activity.read_events(tmp_path)
    assert len(rows) == 1
    assert rows[0]["details"]["path"] == "[oversized metadata]"
    assert secret not in str(rows)
