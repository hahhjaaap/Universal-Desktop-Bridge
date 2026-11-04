"""Compact GUI headers must reserve enough space for wrapped subtitles."""

import pytest


def test_page_header_does_not_compress_wrapped_subtitle_into_title():
    qt = pytest.importorskip("PySide6.QtWidgets")
    from udb.manager import MainWindow, make_app

    app = make_app()
    page, _layout = MainWindow.page(
        None,
        "Kết nối",
        "Trạng thái Cloud Agent, OAuth và quyền đọc từng project phải "
        "được kiểm tra độc lập, kể cả khi cửa sổ bị thu nhỏ.",
    )
    header = page.findChild(qt.QWidget, "PageHeader")
    title = header.findChild(qt.QLabel, "H1")
    subtitle = header.findChild(qt.QLabel, "Subtitle")
    assert header.minimumHeight() >= (
        title.minimumHeight() + header.layout().spacing() + subtitle.sizeHint().height()
    )

    try:
        for width, height in ((760, 583), (700, 260), (968, 723)):
            page.resize(width, height)
            page.show()
            app.processEvents()
            assert title.geometry().bottom() < subtitle.geometry().top()
    finally:
        page.close()
