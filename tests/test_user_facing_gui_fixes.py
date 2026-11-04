"""Source-browser and ChatGPT-link failures must remain understandable to owners."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QMessageBox

from udb.manager import PLUGIN_URL, make_app
from udb.manager_dialogs import SourceDialog


class ListingAgent:
    def listing(self, project, path, limit=200):
        assert project == "demo"
        assert limit == 200
        if path == "missing":
            raise OSError("Folder is temporarily unavailable")
        if path == "folder":
            return {
                "items": [
                    {"path": "folder/second.py", "directory": False},
                ]
            }
        return {
            "items": [
                {"path": "missing", "directory": True},
                {"path": "folder", "directory": True},
                {"path": "good.py", "directory": False},
                {"path": "bad.py", "directory": False},
            ]
        }

    def read(self, project, path):
        if path == "bad.py":
            raise OSError("File was removed before reading")
        return {"text": f"content for {path}", "sha256": "a" * 64}


def test_unavailable_folder_does_not_strand_the_source_dialog(monkeypatch):
    make_app()
    errors = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text: errors.append(text)
    )
    dialog = SourceDialog(ListingAgent(), "demo")
    try:
        dialog.open_item(dialog.files.item(2))
        assert dialog.code.toPlainText() == "content for good.py"
        assert dialog.path == "."
        dialog.open_item(dialog.files.item(0))
        assert errors == ["Folder is temporarily unavailable"]
        assert dialog.path == "." and dialog.breadcrumb.text() == "."
        assert dialog.files.count() == 4
        assert dialog.code.toPlainText() == "content for good.py"
    finally:
        dialog.close()


def test_failed_file_read_never_displays_the_previous_file(monkeypatch):
    make_app()
    errors = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, text: errors.append(text)
    )
    dialog = SourceDialog(ListingAgent(), "demo")
    try:
        dialog.open_item(dialog.files.item(2))
        assert "SHA256" in dialog.sha.text()
        dialog.open_item(dialog.files.item(3))
        assert errors == ["File was removed before reading"]
        assert dialog.code.toPlainText() == ""
        assert dialog.sha.text() == "Chưa đọc được file."
    finally:
        dialog.close()


def test_entering_another_folder_clears_old_code_and_hash():
    make_app()
    dialog = SourceDialog(ListingAgent(), "demo")
    try:
        dialog.open_item(dialog.files.item(2))
        dialog.open_item(dialog.files.item(1))
        assert dialog.path == "folder"
        assert dialog.breadcrumb.text() == "folder"
        assert dialog.code.toPlainText() == ""
        assert dialog.sha.text() == "SHA256 xuất hiện sau khi đọc file."
        assert dialog.files.item(0).text().startswith("..")
        assert dialog.files.count() == 2
    finally:
        dialog.close()


def test_chatgpt_plugins_link_is_not_tied_to_one_private_account():
    assert PLUGIN_URL == "https://chatgpt.com/plugins"


def test_browser_launch_failure_explains_how_to_open_chatgpt(monkeypatch):
    from PySide6.QtGui import QDesktopServices

    from udb.manager import MainWindow

    warnings = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: False)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, detail: warnings.append(detail),
    )
    MainWindow.open_url(None, PLUGIN_URL)
    assert warnings and PLUGIN_URL in warnings[0]
    assert "trình duyệt" in warnings[0]


def test_source_browser_loads_beyond_first_200_files_and_can_retry(monkeypatch):
    make_app()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message)
    )

    class PagedAgent:
        fail_once = True

        def listing(self, project, path, offset=0, limit=200):
            assert project == "demo" and path == "." and limit == 200
            if offset == 200 and self.fail_once:
                self.fail_once = False
                raise OSError("Temporary source listing error")
            files = [
                {"path": f"file-{index:03d}.py", "directory": False}
                for index in range(offset, min(offset + limit, 205))
            ]
            return {"items": files, "next_offset": 200 if offset == 0 else None}

    dialog = SourceDialog(PagedAgent(), "demo")
    try:
        assert dialog.files.count() == 201
        assert dialog.files.item(200).text() == "Xem thêm tệp…"
        dialog.open_item(dialog.files.item(200))
        assert warnings == ["Temporary source listing error"]
        assert dialog.files.count() == 201
        assert dialog.files.item(200).text() == "Xem thêm tệp…"
        dialog.open_item(dialog.files.item(200))
        assert dialog.files.count() == 205
        assert dialog.files.item(204).text() == "file-204.py"
        assert dialog.path == "."
    finally:
        dialog.close()
