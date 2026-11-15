"""Regression for source search preflight (roadmap step 21)."""

from __future__ import annotations

from udb.core import Agent
from udb.fileops import search_files


def test_search_byte_budget_rejects_oversized_file_without_open(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "oversized.py").write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("oversized source must not be opened")

    monkeypatch.setattr(agent, "read_bytes", forbidden_read)
    result = search_files(agent, "demo", pattern="*.py", text="x")
    assert result["truncated"] is True
    assert result["truncation_reason"] == "byte_budget"
    assert result["bytes_searched"] == 0
    assert result["matches_returned"] == 0
    assert result["items"] == []


def test_search_small_source_keeps_existing_match_shape(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "demo.py").write_text("one\nneedle here\n", encoding="utf-8")
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)

    result = search_files(agent, "demo", pattern="*.py", text="needle")
    assert result["truncated"] is False
    assert result["truncation_reason"] is None
    assert result["matches_returned"] == 1
    assert result["items"] == [
        {"path": "demo.py", "matches": [{"line": 2, "text": "needle here"}]}
    ]
    assert result["bytes_searched"] == len("one\nneedle here\n".encode("utf-8"))


def test_search_order_is_stable_for_unchanged_small_tree(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    # Creation order deliberately differs from casefold + original-name order.
    for name in ("zeta.py", "Beta.py", "alpha.py", "ALPHA.py"):
        (root / name).write_text("needle\n", encoding="utf-8")
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)
    expected = ["ALPHA.py", "alpha.py", "Beta.py", "zeta.py"]
    first = search_files(agent, "demo", pattern="*.py", text="needle")
    second = search_files(agent, "demo", pattern="*.py", text="needle")
    assert [row["path"] for row in first["items"]] == expected
    assert first["items"] == second["items"]


def test_search_invalid_utf8_file_does_not_block_safe_matches(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "a_bad.py").write_bytes(b"needle\xff")
    (root / "b_good.py").write_text("needle\n", encoding="utf-8")
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)
    result = search_files(agent, "demo", pattern="*.py", text="needle")
    assert [row["path"] for row in result["items"]] == ["b_good.py"]
    assert result["truncated"] is False
    assert result["bytes_searched"] == len(b"needle\xff") + len(b"needle\n")


def test_batch_read_rechecks_postread_utf8_byte_budget(tmp_path, monkeypatch):
    import pytest

    from udb.core import MAX_TEXT, PolicyError
    from udb.fileops import read_files

    root = tmp_path / "source"
    root.mkdir()
    (root / "small.py").write_text("ok\n", encoding="utf-8")
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)

    # Preflight passes, but a concurrently changed read must still be bounded.
    monkeypatch.setattr(
        agent,
        "read",
        lambda project, path: {"path": path, "text": "💡" * (MAX_TEXT // 4 + 1)},
    )
    with pytest.raises(PolicyError, match="Combined"):
        read_files(agent, "demo", ["small.py"])


def test_listing_keyset_cursor_resists_insertions_before_cursor(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for name in ("Alpha.py", "beta.py", "delta.py"):
        (root / name).write_text("x=1\n", encoding="utf-8")
    agent = Agent(tmp_path / "bridge")
    agent.register_local("demo", str(root), True)

    page = agent.listing("demo", limit=2)
    assert [row["path"] for row in page["items"]] == ["Alpha.py", "beta.py"]
    (root / "AA.py").write_text("x=2\n", encoding="utf-8")
    subsequent = agent.listing("demo", limit=2, after=page["next_after"])
    assert [row["path"] for row in subsequent["items"]] == ["delta.py"]
