"""Local Qt view of the existing Common Room database in a registered project.

No external Python interpreter, project script, browser process, or AI permission
is started by this UI. The owner must explicitly choose the project and actions.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core import reject_links

STATES = ("todo", "doing", "blocked", "done")
KINDS = ("message", "proposal", "question", "review", "decision", "summary")


def database_for_project(root: str | Path) -> Path:
    """Find the existing Common Room in a chosen registered project only."""
    project = Path(root).absolute()
    reject_links(project)
    if not project.is_dir() or project.resolve() != project:
        raise ValueError("Thư mục dự án đã thay đổi.")
    # Common Room can be registered as its own root, a standalone child,
    # or the example included in the canonical UDB source checkout.
    candidates = (
        [project]
        if project.name == "chatgpt-workspace"
        else [
            project / "chatgpt-workspace",
            project / "examples" / "chatgpt-workspace",
        ]
    )
    for room in candidates:
        path = room / "workspace.sqlite3"
        reject_links(room)
        reject_links(path)
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Không thấy workspace.sqlite3 trong chatgpt-workspace/ hoặc "
        "examples/chatgpt-workspace/ của dự án đã đăng ký. "
        "UDB không tự tạo cơ sở dữ liệu mới."
    )


@contextmanager
def open_room(path: Path):
    """Open an existing database, commit/rollback and ALWAYS release its file lock.

    sqlite3.Connection.__exit__ manages transactions but does not close the
    connection. That leaves workspace.sqlite3 locked on Windows after reloads.
    """
    reject_links(path)
    if not path.is_file():
        raise FileNotFoundError("Common Room database không còn tồn tại.")
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA user_version").fetchone()[0] < 3:
            raise ValueError(
                "Common Room chưa có schema v3; hãy mở Workspace v2 để nâng cấp."
            )
        with connection:
            yield connection
    finally:
        connection.close()


def checked_text(value: str, length: int, field: str):
    value = value.strip()
    if not value or len(value) > length:
        raise ValueError(field + " phải có 1–" + str(length) + " ký tự.")
    return value


class CommonRoomDialog(QDialog):
    """Work on the same SQLite/WAL database used by workspace.py and chain.py."""

    def __init__(self, project_root, parent=None):
        super().__init__(parent)
        self.room_path = database_for_project(project_root)
        self.room_dir = self.room_path.parent
        self.setWindowTitle("UDB · Common Room")
        self.resize(1000, 720)
        self.setMinimumSize(790, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        layout = QVBoxLayout(self)
        info = QLabel(
            "Phòng chung trong dự án · dữ liệu SQLite gốc · "
            "thành viên là nhãn tự khai, không xác thực danh tính"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        header = QHBoxLayout()
        self.topic = QComboBox()
        self.topic.setAccessibleName("Chủ đề Common Room")
        self.topic.currentTextChanged.connect(self.load_content)
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setPlaceholderText("Tên thành viên")
        self.name.setAccessibleName("Tên người tham gia")
        join = QPushButton("Tham gia")
        join.clicked.connect(lambda: self.action(self.join))
        refresh = QPushButton("Làm mới")
        refresh.clicked.connect(lambda: self.action(self.reload))
        header.addWidget(QLabel("Chủ đề"))
        header.addWidget(self.topic, 2)
        header.addWidget(self.name, 1)
        header.addWidget(join)
        header.addWidget(refresh)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_discussion()
        self._build_tasks()
        self._build_browser()
        self.reload()

    def _page(self, title):
        widget = QWidget()
        area = QVBoxLayout(widget)
        self.tabs.addTab(widget, title)
        return area

    def _build_discussion(self):
        area = self._page("Thảo luận")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Lọc nội dung/tác giả trong 200 tin gần nhất")
        self.search.textChanged.connect(self.load_content)
        area.addWidget(self.search)
        self.messages = QTreeWidget()
        self.messages.setHeaderLabels(["#", "Tác giả", "Loại", "Nội dung"])
        self.messages.setRootIsDecorated(False)
        self.messages.setColumnWidth(0, 50)
        self.messages.setColumnWidth(1, 130)
        self.messages.setColumnWidth(2, 100)
        self.messages.itemSelectionChanged.connect(self.message_selected)
        area.addWidget(self.messages, 3)
        self.message_detail = QPlainTextEdit()
        self.message_detail.setReadOnly(True)
        self.message_detail.setPlaceholderText("Chọn một tin để xem toàn bộ nội dung")
        area.addWidget(self.message_detail, 1)
        self.composer = QPlainTextEdit()
        self.composer.setPlaceholderText("Nhập nội dung muốn đăng…")
        self.composer.setMaximumHeight(110)
        area.addWidget(self.composer)
        actions = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(KINDS)
        send = QPushButton("Gửi tin")
        send.clicked.connect(lambda: self.action(self.post))
        actions.addWidget(QLabel("Loại tin"))
        actions.addWidget(self.kind)
        actions.addStretch()
        actions.addWidget(send)
        area.addLayout(actions)

    def _build_tasks(self):
        area = self._page("Công việc")
        self.tasks = QTreeWidget()
        self.tasks.setHeaderLabels(["#", "Công việc", "Phụ trách", "Trạng thái", "Bản"])
        self.tasks.setRootIsDecorated(False)
        self.tasks.setColumnWidth(0, 50)
        self.tasks.setColumnWidth(1, 340)
        self.tasks.setColumnWidth(2, 140)
        self.tasks.setColumnWidth(3, 105)
        area.addWidget(self.tasks, 1)
        actions = QHBoxLayout()
        new = QPushButton("+ Tạo việc")
        new.clicked.connect(lambda: self.action(self.add_task))
        self.state = QComboBox()
        self.state.addItems(STATES)
        update = QPushButton("Cập nhật trạng thái")
        update.clicked.connect(lambda: self.action(self.update_task))
        actions.addWidget(new)
        actions.addStretch()
        actions.addWidget(self.state)
        actions.addWidget(update)
        area.addLayout(actions)
        area.addWidget(
            QLabel(
                "Cập nhật có kiểm tra revision để tránh ghi đè việc chat khác vừa thay đổi. "
                "Trạng thái 'done' không chứng minh tác vụ đã được kiểm tra."
            )
        )

    def _build_browser(self):
        area = self._page("Browser")
        self.browser_status = QLabel("Chưa kiểm tra browser cache")
        self.browser_status.setWordWrap(True)
        area.addWidget(self.browser_status)
        self.browser_image = QLabel("Chưa có ảnh")
        self.browser_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browser_image.setMinimumHeight(300)
        area.addWidget(self.browser_image, 1)
        area.addWidget(
            QLabel(
                "Chỉ xem cache của Common Room; không khởi động browser hoặc "
                "sử dụng hồ sơ Chrome cá nhân."
            )
        )

    def action(self, callback):
        try:
            callback()
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Common Room", str(exc))

    def reload(self):
        try:
            with open_room(self.room_path) as db:
                topics = [
                    r["name"]
                    for r in db.execute("SELECT name FROM topics ORDER BY name LIMIT 200")
                ]
        except (OSError, ValueError, sqlite3.Error) as exc:
            # Refresh button errors otherwise left a previous topic and
            # previously read messages visible even after the DB disappeared.
            self._clear_content("Không đọc được Common Room: " + str(exc))
            was_blocked = self.topic.blockSignals(True)
            try:
                self.topic.clear()
            finally:
                self.topic.blockSignals(was_blocked)
            raise
        selected = self.topic.currentText()
        self.topic.blockSignals(True)
        self.topic.clear()
        self.topic.addItems(topics)
        self.topic.setCurrentIndex(topics.index(selected) if selected in topics else 0)
        self.topic.blockSignals(False)
        self.load_content()

    def _clear_content(self, status: str):
        """Fail closed visually: never show stale rows from another topic/read."""
        self.messages.clear()
        self.message_detail.clear()
        self.tasks.clear()
        self.browser_image.clear()
        self.browser_image.setText("Chưa có ảnh browser")
        self.browser_status.setText(status)

    def load_content(self, *_):
        current = self.topic.currentText()
        if not current:
            self._clear_content("Chưa có chủ đề Common Room.")
            return
        try:
            with open_room(self.room_path) as db:
                term = self.search.text().casefold()
                rows = db.execute(
                    "SELECT id, author, kind, body, created_at FROM messages "
                    "WHERE topic=? ORDER BY id DESC LIMIT 200",
                    (current,),
                ).fetchall()
                tasks = db.execute(
                    "SELECT id,title,assignee,state,revision FROM tasks "
                    "WHERE topic=? ORDER BY id DESC LIMIT 200",
                    (current,),
                ).fetchall()
            self.messages.clear()
            self.message_detail.clear()
            for row in reversed(rows):
                if term and term not in (row["body"] + " " + row["author"]).casefold():
                    continue
                item = QTreeWidgetItem(
                    [str(row["id"]), row["author"], row["kind"], row["body"][:180]]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, row["body"])
                self.messages.addTopLevelItem(item)
            self.tasks.clear()
            for item in tasks:
                entry = QTreeWidgetItem(
                    [
                        str(item["id"]),
                        item["title"],
                        item["assignee"] or "Chưa giao",
                        item["state"],
                        str(item["revision"]),
                    ]
                )
                self.tasks.addTopLevelItem(entry)
            self.load_browser()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._clear_content("Không đọc được Common Room: " + str(exc))

    def message_selected(self):
        selected = self.messages.selectedItems()
        self.message_detail.setPlainText(
            selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else ""
        )

    def join(self):
        member = checked_text(self.name.text(), 80, "Tên thành viên")
        with open_room(self.room_path) as db:
            db.execute(
                "INSERT INTO participants(name,role,last_seen) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen",
                (
                    member,
                    "Người dùng UDB GUI",
                    datetime.datetime.now(datetime.timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                ),
            )
        self.reload()

    def post(self):
        author = checked_text(self.name.text(), 80, "Tên thành viên")
        body = checked_text(self.composer.toPlainText(), 32000, "Nội dung")
        topic = self.topic.currentText()
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        )
        with open_room(self.room_path) as db:
            if not db.execute(
                "SELECT 1 FROM participants WHERE name=?", (author,)
            ).fetchone():
                raise ValueError("Hãy bấm Tham gia trước khi gửi tin.")
            db.execute(
                "INSERT INTO messages(request_id,topic,author,kind,body,reply_to,created_at) "
                "VALUES(?,?,?,?,?,NULL,?)",
                (
                    str(uuid.uuid4()),
                    topic,
                    author,
                    self.kind.currentText(),
                    body,
                    stamp,
                ),
            )
            db.execute(
                "UPDATE participants SET last_seen=? WHERE name=?", (stamp, author)
            )
        self.composer.clear()
        self.reload()

    def add_task(self):
        title, ok = QInputDialog.getText(self, "Tạo công việc", "Nội dung công việc")
        if not ok:
            return
        title = checked_text(title, 1000, "Công việc")
        with open_room(self.room_path) as db:
            db.execute(
                "INSERT INTO tasks(request_id,topic,title,assignee,initial_assignee,"
                "state,revision,created_at,updated_at) VALUES(?,?,?,NULL,NULL,'todo',1,?,?)",
                (
                    str(uuid.uuid4()),
                    self.topic.currentText(),
                    title,
                    datetime.datetime.now(datetime.timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    datetime.datetime.now(datetime.timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                ),
            )
        self.reload()

    def update_task(self):
        selected = self.tasks.selectedItems()
        if not selected:
            raise ValueError("Hãy chọn công việc cần cập nhật.")
        item = selected[0]
        task_id, revision = int(item.text(0)), int(item.text(4))
        new_state = self.state.currentText()
        with open_room(self.room_path) as db:
            db.execute("BEGIN IMMEDIATE")
            before = db.execute(
                "SELECT revision,state FROM tasks WHERE id=? AND topic=?",
                (task_id, self.topic.currentText()),
            ).fetchone()
            if not before or before["revision"] != revision:
                raise ValueError("Công việc đã thay đổi. Bấm Làm mới rồi thử lại.")
            if before["state"] != new_state:
                db.execute(
                    "UPDATE tasks SET state=?,revision=revision+1,updated_at=? "
                    "WHERE id=? AND revision=?",
                    (
                        new_state,
                        datetime.datetime.now(datetime.timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                        task_id,
                        revision,
                    ),
                )
        self.reload()

    def load_browser(self):
        cache = self.room_dir / "browser-cache"
        try:
            health_path, meta_path = cache / "health.json", cache / "latest.json"
            reject_links(cache)
            reject_links(health_path)
            reject_links(meta_path)
            if health_path.stat().st_size > 32768 or meta_path.stat().st_size > 32768:
                raise ValueError("Cache metadata vượt giới hạn")
            health = json.loads(health_path.read_text(encoding="utf-8"))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            image = (self.room_dir / meta["file"]).absolute()
            reject_links(image)
            if image.parent != cache or image.suffix.lower() != ".jpg":
                raise ValueError("Ảnh nằm ngoài cache")
            if image.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Ảnh cache quá lớn")
            raw = image.read_bytes()
            if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                raise ValueError("Checksum ảnh không khớp")
            age = max(0, time.time() - int(meta["captured_unix_ms"]) / 1000)
            heartbeat = max(0, time.time() - int(health["heartbeat_unix_ms"]) / 1000)
            live = health.get("running") is True and heartbeat < 10
            self.browser_status.setText(
                ("Browser đang chạy" if live else "Browser chưa xác minh đang chạy")
                + f" · ảnh cách đây {age:.0f}s"
            )
            pixmap = QPixmap()
            if (
                not pixmap.loadFromData(raw, "JPG")
                or pixmap.width() > 4096
                or pixmap.height() > 4096
            ):
                raise ValueError("Ảnh cache không hợp lệ")
            self.browser_image.setPixmap(
                pixmap.scaled(
                    720,
                    420,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.browser_status.setText("Không có cache browser hợp lệ: " + str(exc))
            self.browser_image.clear()
            self.browser_image.setText("Chưa có ảnh browser")
