"""Offline synthetic staging fixture must be repeatable and never overwrite data."""

import hashlib
import json
import sys

from tools import prepare_staging_fixture as fixture


def test_fixture_hashes_and_negative_paths(tmp_path):
    root = tmp_path / "udb-staging"
    manifest = fixture.create_fixture(root)
    saved = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    assert manifest["project_name"] == "udb-staging-fixture"
    for relative_path, digest in manifest["expected_reads"].items():
        data = (root / "project" / relative_path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
    assert manifest["expected_denials"] == [".env", "../outside.txt"]
    assert (root / "project" / ".env").read_bytes() == fixture.PROTECTED
    assert (root / "outside.txt").read_bytes() == fixture.OUTSIDE
    assert "not-a-credential" not in json.dumps(manifest)


def test_fixture_refuses_existing_directory_without_touching_it(tmp_path):
    root = tmp_path / "udb-staging"
    root.mkdir()
    sentinel = root / "existing.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    try:
        fixture.create_fixture(root)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Must not overwrite an existing fixture")
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert sorted(path.name for path in root.iterdir()) == ["existing.txt"]


def test_fixture_refuses_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    try:
        fixture.create_fixture(fixture.Path("relative-fixture"))
    except ValueError:
        pass
    else:
        raise AssertionError("Relative directory should be rejected")
    assert not (tmp_path / "relative-fixture").exists()


def test_fixture_deterministic_across_two_roots(tmp_path):
    one = fixture.create_fixture(tmp_path / "one")
    two = fixture.create_fixture(tmp_path / "two")
    assert one == two


def test_cli_reports_only_sanitized_hashes(tmp_path, monkeypatch, capsys):
    root = tmp_path / "private-owner-location"
    monkeypatch.setattr(sys, "argv", ["prepare_staging_fixture.py", "--root", str(root)])
    assert fixture.main() == 0
    output = capsys.readouterr().out
    reported = json.loads(output)
    assert reported["result"] == "created"
    assert reported["expected_reads"] == json.loads(
        (root / "manifest.json").read_text(encoding="utf-8")
    )["expected_reads"]
    assert str(root) not in output
    assert "not-a-credential" not in output
    assert fixture.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "result": "failed",
        "reason": "fixture_directory_unavailable",
    }
