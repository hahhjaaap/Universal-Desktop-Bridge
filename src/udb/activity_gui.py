"""Read-only Qt view of the tool activity recorded by the Windows agent."""

import os
import sqlite3
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .activity import event_status
from .activity_presenter import ActivityFeed, describe, event_state
from .core import PolicyError
from .ui_theme import current_theme

COLUMNS = ["Lúc", "Công cụ", "Trạng thái", "Thời gian", "Mã gọi"]
READ_ERRORS = (OSError, ValueError, PolicyError, sqlite3.Error)


def configure_timeline(tree):
    tree.setHeaderLabels(COLUMNS)
    tree.setAccessibleName("Nhật ký trực tiếp UDB Live")
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    for column, width in enumerate((90, 270, 110, 105)):
        tree.setColumnWidth(column, width)


def render_timeline(tree, events):
    tree.clear()
    theme = current_theme()
    colors = {"CALLING": theme.accent, "RUNNING": theme.warning, "ERROR": theme.danger}
    for event in events:
        stamp = event.get("at", 0)
        clock = time.strftime("%H:%M:%S", time.localtime(stamp)) if stamp else "—"
        status = event_status(event)
        elapsed = event.get("elapsed_ms")
        duration = f"{elapsed} ms" if type(elapsed) is int and elapsed >= 0 else ""
        item = QTreeWidgetItem(
            [clock, describe(event), status, duration, event.get("call_id", "")]
        )
        item.setToolTip(2, event_state(event))
        if status == "PASS":
            item.setBackground(2, QBrush(QColor(theme.success_bg)))
        elif status in colors:
            item.setForeground(2, QBrush(QColor(colors[status])))
        tree.addTopLevelItem(item)


class LiveWindow(QWidget):
    def __init__(self, home):
        super().__init__()
        self.setWindowTitle("UDB Live")
        self.resize(760, 440)
        self.feed = ActivityFeed(home, retain_transitions=True)
        self.previous = None
        layout = QVBoxLayout(self)
        self.notice = QLabel()
        layout.addWidget(self.notice)
        self.timeline = QTreeWidget()
        configure_timeline(self.timeline)
        layout.addWidget(self.timeline)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)
        self.poll()

    def poll(self):
        try:
            events = self.feed.poll()
        except READ_ERRORS:
            self.notice.setText("Chưa đọc được nhật ký. UDB Live sẽ tự thử lại.")
            self.notice.show()
            return
        self.notice.setText(
            "" if events else "Chưa có hoạt động. Gọi một công cụ UDB trong ChatGPT."
        )
        self.notice.setVisible(not events)
        if events != self.previous:
            render_timeline(self.timeline, events)
            self.previous = events


def run(home):
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.FreeConsole()
    from .manager import make_app

    app = make_app()
    window = LiveWindow(home)
    window.show()
    return app.exec()
