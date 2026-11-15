"""Fast, no-worker regression tests for normalized document request plans."""

from __future__ import annotations

import json
import zipfile

import pytest

from udb.companion.documents import prepare_document_request, sha
from udb.companion.files import ScopedFiles


def test_read_plan_is_scoped_and_replay_bound_to_fresh_input_hash(tmp_path):
    archive = tmp_path / "sample.docx"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("word/document.xml", "<document/>")
    files = ScopedFiles(str(tmp_path))
    params = {"action": "read", "path": "sample.docx", "timeout_seconds": 9}
    plan = prepare_document_request(files, "word_document", params)
    assert plan.action == "read"
    assert plan.extension == ".docx"
    assert plan.writing is False
    assert plan.seconds == 9
    assert plan.fingerprints == {str(archive): sha(archive)}
    assert plan.request["inputs"] == plan.fingerprints
    assert plan.replay_args["expected_sha256"] == sha(archive)
    assert "timeout_seconds" not in params
    assert plan.target == archive
    assert json.loads(json.dumps(plan.request))["format"] == "word_document"


def test_write_plan_does_not_touch_destination_or_launch_worker(tmp_path):
    files = ScopedFiles(str(tmp_path))
    target = tmp_path / "fresh.xlsx"
    plan = prepare_document_request(
        files, "spreadsheet", {"action": "write", "path": "fresh.xlsx"}
    )
    assert plan.writing is True
    assert plan.target == target
    assert plan.target_expected == "NEW"
    assert plan.fingerprints == {}
    assert plan.request["inputs"] == {}
    assert not target.exists()


def test_existing_target_and_source_hash_conflicts_remain_rejected(tmp_path):
    files = ScopedFiles(str(tmp_path))
    source = tmp_path / "old.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ValueError, match="Current source expected_sha256"):
        prepare_document_request(
            files,
            "pdf_document",
            {
                "action": "extract",
                "path": "old.pdf",
                "destination": "part.pdf",
                "pages": [1],
            },
        )
    with pytest.raises(ValueError, match="Source SHA256 mismatch"):
        prepare_document_request(
            files,
            "pdf_document",
            {"action": "read", "path": "old.pdf", "expected_sha256": "0" * 64},
        )
    with pytest.raises(FileExistsError, match="Destination exists"):
        prepare_document_request(
            files, "pdf_document", {"action": "write", "path": "old.pdf"}
        )
    for value in (-1, True, 61):
        with pytest.raises(ValueError, match="Document timeout"):
            prepare_document_request(
                files,
                "pdf_document",
                {"action": "read", "path": "old.pdf", "timeout_seconds": value},
            )


def test_merge_plan_hashes_all_sources_and_blocks_outside_paths(tmp_path):
    files = ScopedFiles(str(tmp_path))
    for name in ("a.pdf", "b.pdf"):
        (tmp_path / name).write_bytes(("%PDF-" + name).encode())
    plan = prepare_document_request(
        files,
        "pdf_document",
        {"action": "merge", "path": "joined.pdf", "inputs": ["a.pdf", "b.pdf"]},
    )
    assert len(plan.fingerprints) == 2
    assert plan.writing and plan.target_expected == "NEW"
    for file_name in ("../outside.pdf", "checkpoints/private.pdf"):
        with pytest.raises((ValueError, PermissionError)):
            prepare_document_request(
                files, "pdf_document", {"action": "read", "path": file_name}
            )
