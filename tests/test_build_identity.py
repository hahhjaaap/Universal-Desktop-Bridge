"""Build identity is bounded metadata, never code execution or a trust grant."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from udb import build, build_identity, cli
from udb._version import VERSION


def test_embedded_identity_distinguishes_same_version_revisions_and_dirty_build(
    tmp_path,
):
    path = tmp_path / "build_info.json"

    def identity(sha, dirty=False):
        path.write_text(
            json.dumps(
                dict(
                    version=VERSION,
                    source_revision=sha,
                    source_dirty=dirty,
                    build_layout="onefile",
                )
            )
        )
        return build_identity.identify(tmp_path, frozen=True)

    first = identity("a" * 40)
    second = identity("b" * 40)
    assert first["version"] == second["version"] == VERSION
    assert first["build_id"] != second["build_id"]
    assert first["identity_source"] == "embedded" and not first["publisher_verified"]
    assert identity("b" * 40, True)["build_id"].endswith(".dirty")


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {},
        {"version": "wrong"},
        {"version": VERSION, "source_revision": "private text"},
        {"version": VERSION, "source_revision": "a" * 40, "source_dirty": "false"},
        {
            "version": VERSION,
            "source_revision": "a" * 40,
            "source_dirty": False,
            "build_layout": "other",
        },
    ],
)
def test_malformed_metadata_cannot_claim_a_build_revision(tmp_path, bad):
    (tmp_path / "build_info.json").write_text(json.dumps(bad))
    value = build_identity.identify(tmp_path, frozen=True)
    assert (
        value["source_revision"] is None and value["identity_source"] == "unavailable"
    )
    assert not value["publisher_verified"] and "private text" not in json.dumps(value)


def test_oversized_metadata_is_rejected_without_echo(tmp_path):
    (tmp_path / "build_info.json").write_bytes(b"x" * 262145)
    assert build_identity.identify(tmp_path, frozen=True)["source_revision"] is None


def test_checkout_heads_loose_packed_detached_and_worktrees(tmp_path):
    repo = tmp_path / "repo"
    git = repo / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text("a" * 40 + " refs/heads/main\n")
    assert build_identity.checkout_head(repo) == "a" * 40
    (git / "refs/heads").mkdir(parents=True)
    (git / "refs/heads/main").write_text("b" * 40)
    assert build_identity.checkout_head(repo) == "b" * 40
    (git / "HEAD").write_text("c" * 40)
    assert build_identity.checkout_head(repo) == "c" * 40
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    workmeta = git / "worktrees/example"
    workmeta.mkdir(parents=True)
    (workmeta / "HEAD").write_text("ref: refs/heads/main\n")
    (workmeta / "commondir").write_text("../..\n")
    (worktree / ".git").write_text("gitdir: " + str(workmeta))
    assert build_identity.checkout_head(worktree) == "b" * 40
    (workmeta / "HEAD").write_text("ref: refs/../../outside\n")
    assert build_identity.checkout_head(worktree) is None


def test_runtime_identity_import_does_not_load_runtime_or_execute_git():
    code = "import sys;from udb.build_identity import runtime_identity;print(runtime_identity());assert 'subprocess' not in sys.modules;assert 'udb.core' not in sys.modules;assert 'PySide6.QtWidgets' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_cli_version_keeps_legacy_version_output_and_returns_identity(capsys):
    assert cli.main(["version", "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["version"] == VERSION and value["build_id"].startswith(VERSION + "+")
    assert value["identity_source"] == "checkout" and not value["publisher_verified"]
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0 and capsys.readouterr().out.strip() == VERSION


def test_build_stamp_records_dirty_worktree(tmp_path):
    git_exe = shutil.which("git")
    if not git_exe:
        pytest.skip("Git is required for build provenance")
    subprocess.run([git_exe, "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "test.txt").write_text("before")
    subprocess.run([git_exe, "-C", str(tmp_path), "add", "test.txt"], check=True)
    subprocess.run(
        [
            git_exe,
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=" + str(tmp_path / "no-hooks"),
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    clean = build.source_stamp(tmp_path)
    assert clean["source_dirty"] is False and len(clean["source_revision"]) == 40
    (tmp_path / "test.txt").write_text("after")
    assert build.source_stamp(tmp_path)["source_dirty"] is True
