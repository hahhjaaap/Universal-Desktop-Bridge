"""Regression tests for bounded cleanup and performance changes."""

from __future__ import annotations

import time
from pathlib import Path

from tools.audit_repository import audit, reason
from udb import resources
from udb.companion.files import ScopedFiles
from udb.fileops import search_files


def test_scoped_list_is_sorted_bounded_and_excludes_protected_paths(tmp_path):
    for i in range(320):
        (tmp_path / f"file-{i:04}.py").write_text("ok", encoding="utf-8")
    (tmp_path / ".env").write_text("private", encoding="utf-8")
    (tmp_path / "training_data").mkdir()
    (tmp_path / "training_data" / "weights.py").write_text("private")
    files = ScopedFiles(str(tmp_path))
    rows = files.list(limit=17)["items"]
    assert len(rows) == 17
    assert [row["name"] for row in rows] == [f"file-{i:04}.py" for i in range(17)]
    assert files.list(limit=500)["items"][-1]["name"] == "file-0319.py"


def test_scoped_search_does_not_descend_into_protected_data(tmp_path):
    (tmp_path / "visible.py").write_text("needle", encoding="utf-8")
    protected = tmp_path / "training_data"
    protected.mkdir()
    for i in range(15):
        (protected / f"private-{i}.py").write_text("needle", encoding="utf-8")
    files = ScopedFiles(str(tmp_path))
    result = files.search(pattern="*.py", text="needle")
    assert result["matches"] == ["visible.py"]
    assert result["scanned"] == 1


def test_scoped_search_preserves_multiline_and_unicode_matching(tmp_path):
    (tmp_path / "sample.txt").write_text("Tiếng Việt\nSECOND LINE\n", encoding="utf-8")
    files = ScopedFiles(str(tmp_path))
    assert files.search(pattern="*.txt", text="tiếng việt")["matches"] == ["sample.txt"]
    assert files.search(pattern="*.txt", text="Việt\nSECOND")["matches"] == [
        "sample.txt"
    ]


def test_source_search_returns_only_first_ten_hits_with_original_line_numbers(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(f"row {i} FiNdMe" for i in range(100)), encoding="utf-8"
    )

    class Agent:
        def project(self, project):
            return project, tmp_path

        def path(self, project, path):
            return tmp_path / Path(path)

        def read_bytes(self, project, path):
            return (tmp_path / path).read_bytes()

    result = search_files(Agent(), "demo", pattern="*.PY", text="findme", limit=10)
    assert len(result["items"]) == 1
    hits = result["items"][0]["matches"]
    assert len(hits) == 10
    assert [item["line"] for item in hits] == list(range(1, 11))
    assert result["scanned"] == 1


def test_source_search_prefilters_unmatched_files_before_scope_lookup(tmp_path):
    for index in range(200):
        (tmp_path / f"binary-{index:04}.bin").write_bytes(b"unrelated")
    for index in range(5):
        (tmp_path / f"match-{index:04}.py").write_text("needle\\n")
    checked = []

    class SpyAgent:
        def project(self, project):
            return project, tmp_path

        def path(self, project, rel):
            checked.append(str(rel))
            return tmp_path / Path(rel)

        def read_bytes(self, project, rel):
            return (tmp_path / rel).read_bytes()

    response = search_files(SpyAgent(), "test", pattern="*.py", limit=50)
    assert {r["path"] for r in response["items"]} == {
        f"match-{n:04}.py" for n in range(5)
    }
    assert response["scanned"] == 205
    assert response["truncated"] is False
    assert len(checked) == 7
    assert all("binary-" not in path for path in checked)


def test_source_search_still_checks_directories_before_traversal(tmp_path):
    (tmp_path / "allowed").mkdir()
    (tmp_path / "blocked").mkdir()
    (tmp_path / "allowed" / "yes.py").write_text("yes")
    (tmp_path / "blocked" / "no.py").write_text("no")
    checked = []

    class SpyAgent:
        def project(self, project):
            return project, tmp_path

        def path(self, project, rel):
            checked.append(str(rel))
            if str(rel) == "blocked":
                from udb.core import PolicyError

                raise PolicyError("No access")
            return tmp_path / Path(rel)

    response = search_files(SpyAgent(), "test", pattern="*.py", limit=50)
    assert {r["path"] for r in response["items"]} == {"allowed/yes.py"}
    assert "blocked" in checked
    assert "blocked/no.py" not in checked


def test_governor_computes_light_capacity_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        resources,
        "light_capacity_reason",
        lambda sample: calls.append(sample) or "",
    )
    sample = {
        "at": time.time(),
        "cpu_percent": 10,
        "ram_percent": 50,
        "available_mib": 4000,
        "commit_available_mib": 4000,
    }
    status = resources.Governor().status(sample)
    assert calls == [sample]
    assert status["light_operations_ready"] is True
    assert status["light_reason"] == ""


def test_repository_audit_identifies_only_high_confidence_junk(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "src" / "b.py").write_text("x = 1\n")
    paths = [
        "src/a.py",
        "src/b.py",
        "src/__pycache__/a.pyc",
        "credentials.json",
        "THIRD_PARTY_NOTICES/license.txt",
    ]
    result = audit(tmp_path, paths)
    assert result["tracked_files"] == 5
    assert {x["path"] for x in result["unsafe_files"]} == {
        "src/__pycache__/a.pyc",
        "credentials.json",
    }
    assert result["identical_source_groups"] == [["src/a.py", "src/b.py"]]
    assert reason("src/udb/manager.py") == ""
    assert reason("src/udb/credentials.py") == ""
    assert reason("THIRD_PARTY_NOTICES/lib.dist-info/LICENSE") == ""


def test_audit_separates_required_compatibility_shims_from_real_duplicates(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "udb_unified.py").write_text("from udb.proxy import run\n")
    (tmp_path / "src" / "udb_unified.py").write_text("from udb.proxy import run\n")
    (tmp_path / "src" / "one.py").write_text("x = 1\n")
    (tmp_path / "src" / "two.py").write_text("x = 1\n")
    report = audit(
        tmp_path,
        [
            "udb_unified.py",
            "src/udb_unified.py",
            "src/one.py",
            "src/two.py",
        ],
    )
    assert report["intentional_compatibility_duplicates"] == [
        ["src/udb_unified.py", "udb_unified.py"]
    ]
    assert report["identical_source_groups"] == [["src/one.py", "src/two.py"]]
