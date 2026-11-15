"""Regression checks for UDB 100-step optimization group 81–90.

All inputs are disposable local fixtures. No owner files, application state,
Cloudflare deployment or actual Windows UI is touched.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from udb.companion import accounting, background, documents
from udb.companion.background import Background
from udb.companion.files import ScopedFiles
from udb.companion.jobs import Task


@pytest.fixture
def files(tmp_path):
    return ScopedFiles(str(tmp_path))


@pytest.fixture
def bg(files):
    return Background(files, capacity=object())


def test_81_invalid_chunk_cursor_rejected_before_scoped_path_lookup(bg, monkeypatch):
    monkeypatch.setattr(
        bg.files, "path", lambda *_a, **_kw: pytest.fail("No scoped I/O on bad range")
    )
    for offset, limit in ((-1, 100), (0, 0), (0, background.CHUNK + 1)):
        with pytest.raises(ValueError, match="Chunk limit"):
            bg.read_chunk("anything.bin", offset=offset, limit=limit)


def test_81_chunk_identity_and_base64_paging_stay_stable(bg, files):
    data = b"0123456789" * 80
    source = files.root / "source.bin"
    source.write_bytes(data)
    first = bg.read_chunk("source.bin", offset=0, limit=13)
    assert first["content"] == base64.b64encode(data[:13]).decode()
    assert first["chunk_sha256"] == hashlib.sha256(data[:13]).hexdigest()
    assert first["next_offset"] == 13
    assert first["size"] == len(data)
    second = bg.read_chunk(
        "source.bin", offset=13, limit=17, expected_version=first["version"]
    )
    assert second["content"] == base64.b64encode(data[13:30]).decode()
    assert second["version"] == first["version"]
    source.write_bytes(data + b"different")
    with pytest.raises(ValueError, match="changed"):
        bg.read_chunk("source.bin", expected_version=first["version"])


@pytest.mark.parametrize(
    "size,digest",
    [(-1, "a" * 64), (background.MAX_LARGE + 1, "a" * 64), (0, "bad"), (0, 7)],
)
def test_82_bad_upload_begin_rejected_before_scoped_path(bg, monkeypatch, size, digest):
    monkeypatch.setattr(
        bg.files, "path", lambda *_a, **_kw: pytest.fail("Bad size/hash must not traverse")
    )
    with pytest.raises(ValueError, match="Expected size"):
        bg.upload("begin", path="new.bin", size=size, sha256=digest)


def test_83_bad_upload_cursor_does_not_touch_staging_file(bg):
    data = b"hello"
    uid = bg.upload(
        "begin", path="received.bin", size=len(data),
        sha256=hashlib.sha256(data).hexdigest()
    )["upload_id"]
    original = bg.uploads[uid]["temp"]

    class NoStat:
        def stat(self):
            pytest.fail("Invalid payload/cursor must not stat stage")

    bg.uploads[uid]["temp"] = NoStat()
    try:
        with pytest.raises(ValueError, match="Expected next offset"):
            bg.upload(
                "write", upload_id=uid,
                content=base64.b64encode(data).decode(), offset=1
            )
        with pytest.raises(ValueError, match="Chunk exceeds"):
            bg.upload("write", upload_id=uid, content="A" * (2 * 1024 * 1024))
    finally:
        bg.uploads[uid]["temp"] = original
        bg.upload("abort", upload_id=uid)


def test_83_84_upload_write_status_abort_and_owned_staging_cleanup(bg, files):
    data = b"some limited bytes"
    uid = bg.upload(
        "begin", path="received.bin", size=len(data),
        sha256=hashlib.sha256(data).hexdigest()
    )["upload_id"]
    path = bg.uploads[uid]["temp"]
    written = bg.upload(
        "write", upload_id=uid,
        content=base64.b64encode(data).decode(), offset=0
    )
    assert written["next_offset"] == len(data)
    assert bg.upload("status", upload_id=uid)["offset"] == len(data)
    assert path.read_bytes() == data
    assert bg.upload("abort", upload_id=uid)["state"] == "aborted"
    assert not path.exists()
    assert not (files.root / "received.bin").exists()
    assert bg.upload("status", upload_id=uid)["state"] == "aborted"
    with pytest.raises(ValueError, match="already finalized"):
        bg.upload("write", upload_id=uid, offset=0, content="")


def test_84_stage_replaced_after_begin_is_never_deleted(bg, files):
    data = b"test"
    uid = bg.upload(
        "begin", path="private.bin", size=len(data),
        sha256=hashlib.sha256(data).hexdigest()
    )["upload_id"]
    path = bg.uploads[uid]["temp"]
    moved = path.with_suffix(".retained")
    path.rename(moved)
    path.write_bytes(b"unrelated replacement")
    try:
        assert bg.upload("abort", upload_id=uid)["state"] == "aborted"
        assert path.read_bytes() == b"unrelated replacement"
    finally:
        moved.unlink(missing_ok=True)
        path.unlink(missing_ok=True)


def test_85_create_only_file_copy_preserves_tree_and_rejects_overwrite(bg, files):
    source = files.root / "input"
    source.mkdir()
    (source / "part.txt").write_text("unicode: Việt Nam", encoding="utf-8")
    observed = []

    def synchronous(kind, fn, recovery=None):
        task = Task(kind)
        observed.append(recovery)
        return fn(task)

    bg.new = synchronous
    result = bg.file_operation("copy", source="input", destination="output")
    assert result["sha256_verified"] is True
    assert (files.root / "output" / "part.txt").read_text("utf-8") == "unicode: Việt Nam"
    assert observed[0]["tool"] == "file_operation"
    with pytest.raises(FileExistsError):
        bg.file_operation("copy", source="input", destination="output")


def test_86_xlsx_range_preflight_happens_before_openpyxl_parse(
    files, monkeypatch
):
    import openpyxl

    source = files.root / "sheet.xlsx"
    book = openpyxl.Workbook()
    book.save(source)
    book.close()
    monkeypatch.setattr(
        openpyxl, "load_workbook",
        lambda *_a, **_kw: pytest.fail("Invalid read range must not parse workbook")
    )
    with pytest.raises(ValueError, match="Read range limit"):
        documents.spreadsheet(
            files, {"action": "read", "path": "sheet.xlsx", "range": "A1:AZ101"}, None
        )


def test_86_xlsx_read_counts_truncated_text_in_one_pass(files):
    import openpyxl

    book = openpyxl.Workbook()
    ws = book.active
    ws["A1"] = "x" * 2001
    ws["B1"] = "ok"
    path = files.root / "sheet.xlsx"
    book.save(path)
    book.close()
    got = documents.spreadsheet(
        files, {"action": "read", "path": "sheet.xlsx", "range": "A1:B1"}, None
    )
    assert got["rows"] == [["x" * 2000, "ok"]]
    assert got["truncated_cells"] == 1


def test_87_invalid_xlsx_edit_preflight_happens_before_load(files, monkeypatch):
    import openpyxl

    source = files.root / "sheet.xlsx"
    wb = openpyxl.Workbook()
    wb.save(source)
    wb.close()
    monkeypatch.setattr(
        openpyxl, "load_workbook",
        lambda *_a, **_kw: pytest.fail("Malformed cells must not parse XLSX")
    )
    with pytest.raises(ValueError, match="Invalid cell address"):
        documents.spreadsheet(
            files, {"action": "edit_cells", "path": "sheet.xlsx",
                    "cells": {"A0": "bad"}}, files.root / "output.xlsx"
        )


def test_87_xlsx_edits_still_preserve_literal_formula_protection(files):
    import openpyxl

    source = files.root / "source.xlsx"
    base = openpyxl.Workbook()
    base.save(source)
    base.close()
    target = files.root / "output.xlsx"
    documents.spreadsheet(
        files,
        {"action": "edit_cells", "path": "source.xlsx", "sheet": "Sheet",
         "cells": {"A1": "=1+1"}, "allow_formulas": False},
        target,
    )
    output = openpyxl.load_workbook(target)
    assert output["Sheet"]["A1"].value == "=1+1"
    assert output["Sheet"]["A1"].data_type == "s"
    output.close()


def test_88_accounting_header_lookup_and_safe_export_rows(files, monkeypatch):
    assert accounting._column("Invoice Number", ["invoice number", "VAT"]) == 0
    issues = [(n, "ISSUE", "=HYPERLINK(\"bad\")") for n in range(2, 32)]
    report = {
        "source": "input.xlsx", "sheet": "Data", "header_row": 1,
        "rows_checked": 30, "issue_count": len(issues),
        "issues_by_code": {"ISSUE": len(issues)},
        "amount_totals": {}, "note": "Review only", "issues": issues,
    }
    monkeypatch.setattr(accounting, "analyze", lambda *_a: dict(report))
    output = files.root / "audit.xlsx"
    accounting.accounting_spreadsheet(files, {"action": "export_audit"}, output)
    import openpyxl

    book = openpyxl.load_workbook(output)
    sheet = book["Canh bao"]
    assert sheet.max_row == len(issues) + 1
    assert sheet["A2"].value == 2
    assert sheet["A31"].value == 31
    assert sheet["C2"].data_type == "s"
    book.close()


def test_89_docx_read_paging_counts_all_paragraphs_without_materializing(files):
    from docx import Document

    doc = Document()
    for index in range(300):
        doc.add_paragraph("Z" * 4001 if index == 260 else f"Line {index}")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Table content"
    path = files.root / "paragraphs.docx"
    doc.save(path)
    got = documents.word_document(
        files, {"action": "read", "path": "paragraphs.docx", "offset": 260, "limit": 3},
        None,
    )
    assert got["total"] == 301
    assert got["next_offset"] == 263
    assert got["truncated_paragraphs"] == [260]
    assert got["paragraphs"] == ["Z" * 4000, "Line 261", "Line 262"]
    tail = documents.word_document(
        files, {"action": "read", "path": "paragraphs.docx", "offset": 500}, None
    )
    assert tail["paragraphs"] == [] and tail["next_offset"] == 500


def test_90_pdf_rejects_invalid_page_window_before_opening_document(
    files, monkeypatch
):
    import pypdf

    monkeypatch.setattr(
        pypdf, "PdfReader",
        lambda *_a, **_kw: pytest.fail("Invalid paging must not parse a PDF"),
    )
    with pytest.raises(ValueError, match="Page range"):
        documents.pdf_document(
            files, {"action": "read", "path": "missing.pdf",
                    "start_page": 0, "limit": 1}, None
        )


def test_90_pdf_page_paging_and_merge_keep_exact_order(files):
    from pypdf import PdfReader, PdfWriter

    paths = []
    for idx, length in enumerate((2, 1)):
        writer = PdfWriter()
        for _ in range(length):
            writer.add_blank_page(width=400, height=600)
        path = files.root / f"part-{idx}.pdf"
        with path.open("wb") as stream:
            writer.write(stream)
        writer.close()
        paths.append(path)
    read = documents.pdf_document(
        files, {"action": "read", "path": paths[0].name, "start_page": 2,
                "limit": 2}, None
    )
    assert read["total_pages"] == 2
    assert [page["page"] for page in read["pages"]] == [2]
    output = files.root / "joined.pdf"
    merged = documents.pdf_document(
        files, {"action": "merge", "inputs": [p.name for p in paths]}, output
    )
    assert merged["pages"] == 3
    assert len(PdfReader(output).pages) == 3
