"""UDB native Qt UI. Host approvals and Sandbox autonomy grants stay local."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QLockFile,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyleFactory,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .activity_presenter import ActivityFeed
from .core import reject_links
from .desktop import DesktopController
from .manager_dialogs import ApprovalDialog, ConnectionDialog, SourceDialog
from .manager_host import ManagerHostMixin
from .manager_refresh import ManagerRefreshMixin
from .manager_widgets import (
    ACCENT,
    DiffHighlighter,
    MotionButton,
    StatusBand,
    StatusPill,
    Worker,
    empty_state,
    icon,
    label,
    panel,
    row,
)
from .ui_theme import apply_theme, current_theme, normalize_preference

# Personal plugin IDs do not exist in every user's ChatGPT account.
PLUGIN_URL = "https://chatgpt.com/plugins"


class MainWindow(ManagerHostMixin, ManagerRefreshMixin, QMainWindow):
    def __init__(self, home, controller=None):
        super().__init__()
        self.controller = controller or DesktopController(Path(home))
        self.agent = self.controller.agent
        self.busy = False
        self.worker = None
        self.workers = []
        self.pending_rows = {}
        self.selected_project = None
        self.last_signature = None
        self.last_pending = None
        self.last_job_signature = None
        self.connection_signature = None
        self.activity_feed = ActivityFeed(self.agent.home)
        self.activity_signature = None
        self._closing = False
        self._last_project_auth_check = 0.0
        self.setWindowTitle("Universal Desktop Bridge · " + __version__)
        self.resize(1220, 820)
        self.setMinimumSize(940, 640)
        self.setWindowIcon(icon("brand", ACCENT, 32))
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)
        sidebar = QFrame()
        self.sidebar = sidebar
        self._sidebar_compact = False
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)
        nav = QVBoxLayout(sidebar)
        self.sidebar_nav = nav
        nav.setContentsMargins(16, 26, 16, 20)
        nav.setSpacing(9)
        self.brand_label = label("UDB", "Brand")
        self.brand_caption = label("DESKTOP WORKSPACE", "Eyebrow")
        nav.addWidget(self.brand_label)
        nav.addWidget(self.brand_caption)
        self.sidebar_toggle = MotionButton("Thu gọn menu", "cursor")
        self.sidebar_toggle.setToolTip("Thu gọn thanh điều hướng")
        self.sidebar_toggle.setAccessibleName("Thu gọn thanh điều hướng")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        nav.addWidget(self.sidebar_toggle)
        nav.addSpacing(12)
        self.nav_buttons = []
        self.nav_names = (
            "Dự án",
            "Quyền AI",
            "Tiến trình",
            "Bảo vệ",
            "Kết nối",
            "Máy tính",
        )
        for i, (text, glyph) in enumerate(
            (
                ("Dự án", "projects"),
                ("Quyền AI", "review"),
                ("Tiến trình", "activity"),
                ("Bảo vệ", "shield"),
                ("Kết nối", "settings"),
                ("Máy tính", "cursor"),
            )
        ):
            btn = MotionButton(text, glyph, "nav")
            btn.setMinimumHeight(44)
            btn.setToolTip(text)
            btn.setAccessibleName(text)
            btn.clicked.connect(lambda checked=False, index=i: self.navigate(index))
            nav.addWidget(btn)
            self.nav_buttons.append(btn)
        nav.addStretch()
        self.protected_caption = label("Bạn quyết định\nAI được làm gì", "Muted", True)
        nav.addWidget(self.protected_caption)
        nav.addSpacing(12)
        self.sidebar_footer = label("DESKTOP BRIDGE", "Eyebrow")
        nav.addWidget(self.sidebar_footer)
        self.sidebar_version = label("Agent " + __version__, "Fine")
        nav.addWidget(self.sidebar_version)
        body.addWidget(sidebar)
        self.stack = QStackedWidget()
        content_column = QVBoxLayout()
        content_column.setContentsMargins(0, 0, 0, 0)
        content_column.setSpacing(0)
        header = QFrame()
        header.setObjectName("AppHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(26, 10, 26, 10)
        header_row.setSpacing(14)
        self.header_title = label("Máy tính", "H2")
        self.header_title.setAccessibleName("Trang đang xem")
        header_row.addWidget(self.header_title)
        header_row.addStretch()
        self.header_connection = StatusPill("Tunnel chưa kiểm tra", "neutral")
        self.header_connection.setAccessibleDescription(
            "Chỉ là trạng thái tunnel, không xác minh công cụ ChatGPT."
        )
        self.header_connection.setToolTip(
            "Kết nối tunnel không xác minh ChatGPT đã gọi được công cụ."
        )
        header_row.addWidget(self.header_connection)
        self.header_privilege = StatusPill("Quyền máy: chưa xác minh", "neutral")
        self.header_privilege.setAccessibleDescription(
            "Cảnh báo quyền điều khiển Windows toàn diện, không phải quyền dự án."
        )
        self.header_privilege.setToolTip(
            "Trạng thái quyền máy không sandbox, đọc từ tài khoản Windows cục bộ."
        )
        header_row.addWidget(self.header_privilege)
        content_column.addWidget(header)
        content_column.addWidget(self.stack, 1)
        body.addLayout(content_column, 1)
        self.dashboard = self.build_dashboard()
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.build_approvals())
        self.stack.addWidget(self.build_jobs())
        self.stack.addWidget(self.build_protection())
        self.stack.addWidget(self.build_connection())
        self.stack.addWidget(self.build_host())
        foot = QFrame()
        foot.setObjectName("Footer")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(22, 9, 22, 9)
        self.footer_status = label("MCP riêng tư · Quyền tự động theo dự án", "Fine")
        fl.addWidget(self.footer_status)
        fl.addStretch()
        quick = MotionButton("Thu gọn", "cursor")
        quick.setFixedHeight(30)
        quick.clicked.connect(self.open_quick_controls)
        fl.addWidget(quick)
        self.footer_project = label("Chưa chọn dự án", "Fine")
        fl.addWidget(self.footer_project)
        outer.addWidget(foot)
        # Keep stacked pages opaque. A graphics effect on the entire stack can
        # retain stale page pixels on Windows when pages change or resize.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.navigation_shortcuts = []
        for index in range(6):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda index=index: self.navigate(index))
            self.navigation_shortcuts.append(shortcut)
        job_search_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        job_search_shortcut.activated.connect(self.focus_job_search)
        self.navigation_shortcuts.append(job_search_shortcut)
        self.navigate(5)
        self.refresh()

    def page(self, title, subtitle):
        p = QWidget()
        p.setObjectName("Page")
        layout = QVBoxLayout(p)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(16)
        header = QWidget()
        header.setObjectName("PageHeader")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        h = label(title, "H1", True)
        h.setMinimumHeight(40)
        hl.addWidget(h)
        hl.addWidget(label(subtitle, "Subtitle", True))
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(header)
        return p, layout

    def tree(self, columns):
        w = QTreeWidget()
        w.setHeaderLabels(columns)
        w.setRootIsDecorated(False)
        w.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        w.setUniformRowHeights(True)
        w.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        w.header().setStretchLastSection(True)
        return w

    def build_dashboard(self):
        p, lay = self.page(
            "Không gian làm việc",
            "AI tự thao tác trong dự án đã cấp quyền. Checkpoint và dữ liệu nhạy cảm luôn bị chặn.",
        )
        top = row(label("DỰ ÁN / WINDOWS", "Eyebrow"), None)
        self.status_label = label("●  Chưa kết nối", "Badge")
        top.addWidget(self.status_label)
        lay.insertLayout(0, top)
        self.band = StatusBand()
        band = QVBoxLayout(self.band)
        band.setContentsMargins(22, 15, 22, 15)
        band.setSpacing(10)
        heading = QHBoxLayout()
        info = QVBoxLayout()
        info.setSpacing(4)
        info.addWidget(label("Trạng thái kết nối UDB", "H2"))
        self.connection_hint = label(
            "Tunnel và ChatGPT là hai bước xác minh riêng biệt.",
            "Muted",
            True,
        )
        info.addWidget(self.connection_hint)
        heading.addLayout(info, 1)
        self.configure_button = MotionButton("Cấu hình", "settings")
        self.configure_button.clicked.connect(self.configure)
        heading.addWidget(self.configure_button)
        self.connect_button = MotionButton("Kết nối", "power", "primary")
        self.connect_button.clicked.connect(self.toggle_tunnel)
        heading.addWidget(self.connect_button)
        band.addLayout(heading)
        health = QHBoxLayout()
        health.setSpacing(8)
        self.local_health = StatusPill("Chưa kiểm tra", "neutral")
        self.tunnel_health = StatusPill("Chưa kiểm tra", "neutral")
        self.chatgpt_health = StatusPill("Chưa xác minh", "neutral")
        for title, pill, description in (
            (
                "Agent",
                self.local_health,
                "Trạng thái tác nhân UDB trên máy tính này.",
            ),
            (
                "Tunnel",
                self.tunnel_health,
                "Tình trạng đường truyền MCP trên máy tính này.",
            ),
            (
                "ChatGPT",
                self.chatgpt_health,
                "Không thể xác minh công cụ ChatGPT từ trạng thái tunnel.",
            ),
        ):
            title_label = label(title, "Fine")
            health.addWidget(title_label)
            pill.setAccessibleDescription(description)
            pill.setToolTip(description)
            health.addWidget(pill)
        health.addStretch()
        band.addLayout(health)
        lay.addWidget(self.band)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        lay.addWidget(split, 1)
        left = panel()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 16, 18, 16)
        ll.setSpacing(12)
        add = MotionButton("Thêm dự án", "plus")
        add.clicked.connect(self.add_project)
        ll.addLayout(row(label("Dự án nguồn", "H2"), None, add))
        self.projects = self.tree(["Dự án", "Quyền truy cập"])
        self.projects.setMinimumHeight(110)
        self.projects.setColumnWidth(0, 180)
        self.projects.itemSelectionChanged.connect(self.project_selected)
        self.projects.itemDoubleClicked.connect(lambda *_: self.open_source())
        ll.addWidget(self.projects, 1)
        self.project_path = QLineEdit()
        self.project_path.setObjectName("ProjectPath")
        self.project_path.setReadOnly(True)
        self.project_path.setMinimumWidth(0)
        self.project_path.setPlaceholderText("Thư mục nguồn")
        ll.addWidget(self.project_path)
        self.project_access = label("Chọn dự án để xem quyền truy cập.", "Fine", True)
        ll.addWidget(self.project_access)
        self.common_room_button = MotionButton("Mở Common Room", "activity")
        self.common_room_button.setToolTip(
            "Đọc/gửi tin và theo dõi công việc từ SQLite của dự án đã đăng ký."
        )
        self.common_room_button.clicked.connect(self.open_common_room)
        self.common_room_button.setEnabled(False)
        ll.addWidget(self.common_room_button)
        self.sandbox_auto = QCheckBox("AI tự làm việc trong Sandbox")
        self.sandbox_auto.setToolTip(
            "Cho dự án này tự mở desktop và chạy script trong VM. Không cấp quyền ghi file gốc hoặc điều khiển host. Bỏ chọn để thu hồi và dừng phiên tự động."
        )
        self.sandbox_auto.toggled.connect(self.set_sandbox_autonomy)
        ll.addWidget(self.sandbox_auto)
        self.source_auto = QCheckBox("AI tự sửa mã nguồn (không duyệt từng file)")
        self.source_auto.setToolTip(
            "Chỉ trong dự án đã đăng ký có quyền ghi. Không sửa checkpoint, dữ liệu, bí mật, file cấu hình quan trọng. Mỗi lần sửa có backup + SHA256; có thể tắt ngay."
        )
        self.source_auto.toggled.connect(self.set_source_autonomy)
        ll.addWidget(self.source_auto)
        view = MotionButton("Xem nguồn", "file")
        view.clicked.connect(self.open_source)
        revoke = MotionButton("Thu hồi", "", "danger")
        revoke.clicked.connect(self.revoke)
        ll.addLayout(row(view, revoke, None))
        split.addWidget(left)
        rail = panel()
        rail.setMinimumWidth(236)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(18, 18, 18, 18)
        rl.setSpacing(13)
        rl.addWidget(label("AN TOÀN & NGOẠI LỆ", "Eyebrow"))
        self.pending_title = label("Không có yêu cầu chờ duyệt", "H2", True)
        rl.addWidget(self.pending_title)
        self.pending_hint = label(
            "Trong phạm vi đã cấp quyền, AI sửa tự động; trường hợp ngoại lệ hiện tại đây.",
            "Muted",
            True,
        )
        rl.addWidget(self.pending_hint)
        self.pending_code = QPlainTextEdit()
        self.pending_code.setReadOnly(True)
        self.pending_code.setMaximumHeight(155)
        self.pending_code.setPlaceholderText("Chưa có thay đổi mới.")
        rl.addWidget(self.pending_code)
        self.rail_highlight = DiffHighlighter(self.pending_code.document())
        self.review_button = MotionButton("Xem đề xuất", "review")
        self.review_button.clicked.connect(self.review_first)
        rl.addWidget(self.review_button)
        rl.addStretch()
        self.sandbox_label = label("", "Warning", True)
        rl.addWidget(self.sandbox_label)
        rl.addWidget(
            label(
                "Tự sửa mã nguồn đã cho phép; file quan trọng luôn bị chặn.",
                "Fine",
                True,
            )
        )
        split.addWidget(rail)
        split.setHandleWidth(14)
        split.setSizes([540, 290])
        self.dashboard_split = split
        return p

    def build_approvals(self):
        p, lay = self.page(
            "Quyền AI & ngoại lệ",
            "Các thao tác trong dự án đã cấp quyền được thực hiện tự động. Yêu cầu cũ hoặc ngoài phạm vi vẫn cần chủ máy xử lý.",
        )
        self.requests = self.tree(["Dự án / nội dung", "Loại", "Thời hạn"])
        self.requests.setColumnWidth(0, 350)
        self.requests.setColumnWidth(1, 110)
        self.requests.itemDoubleClicked.connect(lambda *_: self.review_selected())
        lay.addWidget(self.requests, 1)
        self.approval_empty = empty_state(
            "Không có yêu cầu ngoại lệ",
            "AI thao tác theo quyền từng dự án.\nCác tài liệu và checkpoint được bảo vệ.",
            "shield",
        )
        lay.addWidget(self.approval_empty, 1)
        self.approval_review = MotionButton("Xem yêu cầu", "review", "primary")
        self.approval_review.clicked.connect(self.review_selected)
        lay.addLayout(
            row(
                label("Chỉ bạn có quyền phê duyệt trên máy này.", "Fine", True),
                None,
                self.approval_review,
            )
        )
        return p

    def build_jobs(self):
        p, lay = self.page(
            "Tiến trình & kết quả",
            "Chỉ hiển thị tác vụ của Bridge. Log là dữ liệu không đáng tin và không tự cấp quyền.",
        )
        create = MotionButton("Mở desktop AI", "plus", "primary")
        create.clicked.connect(self.propose_desktop_local)
        lay.addLayout(
            row(
                label("Windows riêng · chuột/phím chỉ ở Sandbox", "Fine", True),
                None,
                create,
            )
        )
        self.job_search = QLineEdit()
        self.job_search.setPlaceholderText("Tìm dự án, trạng thái hoặc Job ID…")
        self.job_search.setAccessibleName("Tìm công việc theo thông tin")
        self.job_search.setClearButtonEnabled(True)
        self.job_search.setToolTip(
            "Chỉ tìm trong thông tin công việc; không tìm nội dung log hoặc script."
        )
        self.job_group_filter = QComboBox()
        self.job_group_filter.setAccessibleName("Lọc trạng thái công việc")
        for value in ("Tất cả", "Đang chạy", "Cần chú ý", "Đã xong"):
            self.job_group_filter.addItem(value)
        self.job_search.textChanged.connect(lambda *_: self._refresh_jobs())
        self.job_group_filter.currentIndexChanged.connect(
            lambda *_: self._refresh_jobs()
        )
        lay.addLayout(row(self.job_search, self.job_group_filter))
        self.job_filter_feedback = label("Danh sách công việc UDB", "Fine")
        lay.addWidget(self.job_filter_feedback)
        self.jobs = self.tree(["Dự án", "Ngôn ngữ", "Trạng thái", "Job ID"])
        self.jobs.setColumnWidth(0, 190)
        self.jobs.setColumnWidth(1, 100)
        self.jobs.setColumnWidth(2, 140)
        self.jobs.setMaximumHeight(220)
        self.jobs.setAccessibleName("Danh sách công việc của UDB")
        self.jobs.itemSelectionChanged.connect(self.show_job)
        lay.addWidget(self.jobs)
        self.job_tabs = QTabWidget()
        self.job_output = QPlainTextEdit()
        self.job_output.setReadOnly(True)
        self.job_output.setPlaceholderText("Chọn một tác vụ để xem đầu ra.")
        self.job_tabs.addTab(self.job_output, "Log trực tiếp")
        self.job_script = QPlainTextEdit()
        self.job_script.setReadOnly(True)
        self.job_tabs.addTab(self.job_script, "Script đã duyệt")
        self.activity_timeline = self.tree(["Lúc", "Công cụ", "Kết quả"])
        self.activity_timeline.setAccessibleName(
            "Lịch sử hoạt động MCP đã lược bỏ dữ liệu nhạy cảm"
        )
        self.activity_timeline.setToolTip(
            "Tối đa 40 bản ghi metadata; không chứa log, script hoặc tài liệu gốc."
        )
        self.activity_timeline.setColumnWidth(0, 85)
        self.activity_timeline.setColumnWidth(1, 210)
        activity_panel = QWidget()
        activity_layout = QVBoxLayout(activity_panel)
        activity_layout.setContentsMargins(8, 8, 8, 8)
        activity_layout.setSpacing(8)
        activity_layout.addWidget(self.activity_timeline, 1)
        self.activity_export_button = MotionButton(
            "Xuất metadata đã ẩn thông tin nhạy cảm", "file"
        )
        self.activity_export_button.clicked.connect(self.export_activity)
        activity_layout.addLayout(row(None, self.activity_export_button))
        self.job_tabs.addTab(activity_panel, "Hoạt động MCP")
        lay.addWidget(self.job_tabs, 1)
        self.jobs_empty = empty_state(
            "Chưa có tác vụ",
            "Các tác vụ Python và PowerShell đã được duyệt sẽ hiển thị tiến trình và kết quả tại đây.",
            "activity",
        )
        lay.addWidget(self.jobs_empty, 1)
        self.stop_desktop = MotionButton("Dừng Sandbox", "power", "danger")
        self.stop_desktop.clicked.connect(self.stop_selected_desktop)
        self.stop_desktop.setEnabled(False)
        lay.addLayout(
            row(
                label(
                    "Chuột/phím chỉ ở guest. Đóng cửa sổ Sandbox hoặc bấm Dừng để kết thúc phiên.",
                    "Fine",
                    True,
                ),
                None,
                self.stop_desktop,
            )
        )
        return p

    def build_protection(self):
        p, lay = self.page(
            "Bảo vệ và quyền truy cập",
            "Đường dẫn bảo vệ áp dụng cho thao tác giới hạn theo dự án, không phải quyền Windows toàn diện.",
        )
        computer = panel()
        cl = QVBoxLayout(computer)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(9)
        self.computer_grant_pill = StatusPill("Đang kiểm tra", "neutral")
        self.computer_grant_pill.setAccessibleDescription(
            "Quyền máy rộng trên Windows hiện tại; không phải quyền Sandbox."
        )
        cl.addLayout(
            row(label("Quyền Windows toàn diện", "H2"), None, self.computer_grant_pill)
        )
        self.computer_grant_detail = label(
            "Đang kiểm tra quyền chủ máy. Không thể cấp quyền tại trang này.",
            "Muted",
            True,
        )
        cl.addWidget(self.computer_grant_detail)
        cl.addWidget(
            label(
                "Chỉ chủ máy có thể cấp hoặc thu hồi qua terminal Windows cục bộ. "
                "Quyền toàn diện không chạy trong Sandbox.",
                "Fine",
                True,
            )
        )
        lay.addWidget(computer)
        posture = panel()
        posture_layout = QVBoxLayout(posture)
        posture_layout.setContentsMargins(20, 16, 20, 16)
        posture_layout.setSpacing(10)
        posture_layout.addWidget(label("Tổng quan quyền và hoạt động", "H2"))
        posture_layout.addWidget(
            label(
                "Chỉ hiển thị dữ liệu vừa đọc trên máy này. Không phải chứng nhận "
                "an toàn hoặc quyền truy cập của ChatGPT.",
                "Muted",
                True,
            )
        )
        self.security_approval_status = StatusPill("Chưa kiểm tra", "neutral")
        self.security_pause_status = StatusPill("Chưa kiểm tra", "neutral")
        self.security_autonomy_status = StatusPill("Chưa kiểm tra", "neutral")
        for heading, pill, description in (
            (
                "Yêu cầu phê duyệt cục bộ",
                self.security_approval_status,
                "Số yêu cầu đang chờ chủ máy xem.",
            ),
            (
                "Đầu vào Windows",
                self.security_pause_status,
                "Chỉ trạng thái tạm dừng chuột/phím host; không dừng tác vụ nền.",
            ),
            (
                "Tự sửa mã nguồn",
                self.security_autonomy_status,
                "Số dự án đang bật quyền tự sửa mã nguồn theo phạm vi.",
            ),
        ):
            pill.setToolTip(description)
            pill.setAccessibleDescription(description)
            heading_label = label(heading, "Fine")
            posture_layout.addLayout(row(heading_label, None, pill))
        self.security_observed = label("Chưa có trạng thái vừa xác minh.", "Fine", True)
        posture_layout.addWidget(self.security_observed)
        lay.addWidget(posture)
        self.protected = self.tree(["Đường dẫn bị chặn trong phạm vi dự án"])
        lay.addWidget(self.protected, 1)
        note = panel()
        nl = QVBoxLayout(note)
        nl.setContentsMargins(20, 18, 20, 18)
        nl.addWidget(label("Bảo vệ nhiều lớp", "H2"))
        nl.addWidget(
            label(
                "Trong chế độ giới hạn theo dự án: chặn checkpoint, weights, datasets, credential và đường dẫn ngoài dự án; kiểm tra symlink/junction/hardlink, hash và backup. Quyền máy rộng được cấp riêng có thể truy cập dữ liệu mà tài khoản Windows đọc được.",
                "Muted",
                True,
            )
        )
        lay.addWidget(note)
        protect = MotionButton("Bảo vệ thêm thư mục", "shield", "primary")
        protect.clicked.connect(self.protect)
        lay.addLayout(row(None, protect))
        return p

    def build_connection(self):
        p, lay = self.page(
            "Kết nối & cài đặt",
            "Kết nối ChatGPT Chat qua tunnel riêng. API key không xuất hiện trong giao diện hay log.",
        )
        setup = panel()
        setup_layout = QVBoxLayout(setup)
        setup_layout.setContentsMargins(23, 20, 23, 20)
        setup_layout.setSpacing(10)
        setup_layout.addWidget(label("Bắt đầu với UDB · 3 bước", "H2"))
        setup_layout.addWidget(
            label(
                "Đây là trạng thái từng bước, không phải một nút cấp quyền AI. "
                "Chỉ chủ máy mới có thể phê duyệt thao tác cần quyền.",
                "Muted",
                True,
            )
        )
        self.setup_agent_health = StatusPill("Chưa kiểm tra", "neutral")
        self.setup_tunnel_health = StatusPill("Chưa kiểm tra", "neutral")
        self.setup_chatgpt_health = StatusPill("Chưa xác minh", "neutral")
        for heading, description, pill in (
            (
                "1 · Tác nhân trên Windows",
                "Mở UDB trên máy này; trạng thái được đọc từ worker cục bộ.",
                self.setup_agent_health,
            ),
            (
                "2 · Kết nối Tunnel",
                "Dùng Kết nối bên dưới. Tunnel xanh chưa chứng minh ChatGPT gọi được.",
                self.setup_tunnel_health,
            ),
            (
                "3 · Xác minh tại ChatGPT",
                "Chọn plugin UDB trong ChatGPT và gọi công cụ trạng thái chỉ đọc. "
                "Giao diện không thể tự xác minh bước này.",
                self.setup_chatgpt_health,
            ),
        ):
            heading_label = label(heading, "Fine")
            heading_label.setToolTip(description)
            pill.setToolTip(description)
            pill.setAccessibleDescription(description)
            setup_layout.addLayout(row(heading_label, None, pill))
            setup_layout.addWidget(label(description, "Muted", True))
        lay.addWidget(setup)
        card = panel()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(23, 23, 23, 23)
        cl.setSpacing(15)
        cl.addWidget(label("Secure MCP Tunnel", "H2"))
        cl.addWidget(
            label(
                "1. Kiểm tra tác nhân cục bộ → 2. Kiểm tra Tunnel → "
                "3. Gọi một công cụ chỉ đọc trong ChatGPT. "
                "Màu xanh ở Tunnel không chứng minh ChatGPT đã truy cập.",
                "Muted",
                True,
            )
        )
        doctor = MotionButton("Sao chép lệnh kiểm tra", "file")
        doctor.setAccessibleName("Sao chép lệnh udb doctor --json")
        doctor.clicked.connect(
            lambda: QApplication.clipboard().setText("udb doctor --json")
        )
        cl.addLayout(row(doctor, None))
        self.detail_status = label("", "Muted", True)
        cl.addWidget(self.detail_status)
        self.media_auto = QCheckBox(
            "AI tự tải HLS → MP4 từ tên miền đã cho phép (không duyệt từng video)"
        )
        self.media_auto.setToolTip(
            "Chỉ HTTPS từ state/media-allowed-hosts.json, file MP4 ở Downloads, không ghi đè; giới hạn kích thước và thời lượng. Không mở host shell."
        )
        self.media_auto.toggled.connect(self.set_media_autonomy)
        cl.addWidget(self.media_auto)
        config = MotionButton("Cài đặt kết nối", "settings")
        config.clicked.connect(self.configure)
        plugin = MotionButton("Quản lý plugin ChatGPT", "external")
        plugin.clicked.connect(lambda: self.open_url(PLUGIN_URL))
        cl.addLayout(row(config, plugin, None))
        lay.addWidget(card)
        cloud_panel = panel()
        cloud_layout = QVBoxLayout(cloud_panel)
        cloud_layout.setContentsMargins(23, 20, 23, 20)
        cloud_layout.setSpacing(12)
        cloud_layout.addWidget(
            label("Cloudflare · Ghép nối thiết bị (thử nghiệm)", "H2")
        )
        cloud_layout.addWidget(
            label(
                "Chỉ dùng với mã mời được chủ hệ thống cấp. Mã hết hạn sau 10 phút. "
                "Ghép nối không cấp quyền điều khiển Windows và không tự cài plugin ChatGPT.",
                "Muted",
                True,
            )
        )
        self.cloud_pair_button = MotionButton("Nhập mã mời Cloud", "settings")
        self.cloud_pair_button.clicked.connect(self.cloud_pair)
        self.cloud_session_button = MotionButton("Bật Cloud Agent", "power")
        self.cloud_session_button.clicked.connect(self.toggle_cloud)
        cloud_layout.addLayout(
            row(self.cloud_pair_button, self.cloud_session_button, None)
        )
        self.cloud_session_status = label(
            "Chưa bật Cloud Agent. Ghép nối không tự tạo phiên điều khiển.",
            "Muted",
            True,
        )
        cloud_layout.addWidget(self.cloud_session_status)
        lay.addWidget(cloud_panel)
        local = panel()
        ll = QVBoxLayout(local)
        ll.setContentsMargins(23, 23, 23, 23)
        ll.setSpacing(14)
        ll.addWidget(label("MCP cục bộ · chẩn đoán nâng cao", "H2"))
        ll.addWidget(
            label(
                "127.0.0.1:17843/mcp · bearer-protected. Không cần bật mục này khi dùng tuyến tunnel STDIO.",
                "Muted",
                True,
            )
        )
        self.local_button = MotionButton("Bật MCP cục bộ", "power")
        self.local_button.clicked.connect(self.toggle_local)
        ll.addLayout(row(self.local_button, None))
        lay.addWidget(local)
        help_text = label(
            "Sau khi Windows khởi động lại: mở Bridge và Kết nối. Trong Chat mới, chọn @Universal Desktop Bridge. Nếu cần chạy mã, gửi đề xuất từ Chat rồi duyệt script chính xác ở Phê duyệt.\n\nBản cài không gọi model API và không tự mua hay nâng cấp dịch vụ. ChatGPT và tunnel vẫn có điều kiện, hạn mức riêng.",
            "Muted",
            True,
        )
        lay.addWidget(help_text)
        appearance = panel()
        al = QVBoxLayout(appearance)
        al.setContentsMargins(23, 20, 23, 20)
        al.setSpacing(12)
        al.addWidget(label("Giao diện ứng dụng", "H2"))
        al.addWidget(
            label(
                "Chọn chế độ sáng, tối hoặc tự động theo Windows. "
                "Tùy chọn này chỉ thay đổi cách hiển thị, không thay đổi quyền AI.",
                "Muted",
                True,
            )
        )
        self.theme_picker = QComboBox()
        self.theme_picker.setAccessibleName("Chế độ giao diện UDB")
        for name, value in (
            ("Theo hệ thống Windows", "system"),
            ("Sáng", "light"),
            ("Tối", "dark"),
        ):
            self.theme_picker.addItem(name, value)
        choice = normalize_preference(self.controller.settings().get("theme"))
        self.theme_picker.setCurrentIndex(self.theme_picker.findData(choice))
        self.theme_picker.currentIndexChanged.connect(self.change_theme)
        al.addWidget(self.theme_picker)
        self.reduce_motion = QCheckBox("Giảm chuyển động trong giao diện")
        self.reduce_motion.setAccessibleName("Giảm chuyển động giao diện UDB")
        self.reduce_motion.setToolTip(
            "Tắt hiệu ứng hover và chuyển cảnh không thiết yếu; không đổi quyền AI."
        )
        self.reduce_motion.setChecked(
            self.controller.settings().get("motion", True) is False
        )
        self.reduce_motion.toggled.connect(self.change_motion)
        al.addWidget(self.reduce_motion)
        lay.addWidget(appearance)
        lay.addStretch()
        return p

    def change_theme(self, index):
        choice = self.theme_picker.itemData(index)
        if choice not in ("system", "light", "dark"):
            return
        settings = self.controller.settings()
        previous = normalize_preference(settings.get("theme"))
        if choice == previous:
            return
        try:
            self.controller.save_settings(
                {
                    "motion": settings.get("motion", True),
                    "autoconnect": settings.get("autoconnect", False),
                    "theme": choice,
                }
            )
        except Exception:
            self.theme_picker.blockSignals(True)
            self.theme_picker.setCurrentIndex(self.theme_picker.findData(previous))
            self.theme_picker.blockSignals(False)
            QMessageBox.warning(
                self,
                "Không lưu được giao diện",
                "Không thể lưu thay đổi giao diện. Cài đặt trước đó được giữ nguyên.",
            )
            return
        apply_theme(QApplication.instance(), choice)
        self._update_window_chrome()
        self.refresh()

    def change_motion(self, reduce_motion):
        settings = self.controller.settings()
        previous_motion = settings.get("motion", True) is not False
        desired_motion = not bool(reduce_motion)
        if desired_motion == previous_motion:
            QApplication.instance().setProperty("motion", desired_motion)
            return
        try:
            self.controller.save_settings(
                {
                    "motion": desired_motion,
                    "autoconnect": settings.get("autoconnect", False),
                    "theme": normalize_preference(settings.get("theme")),
                }
            )
        except Exception:
            self.reduce_motion.blockSignals(True)
            self.reduce_motion.setChecked(not previous_motion)
            self.reduce_motion.blockSignals(False)
            QMessageBox.warning(
                self,
                "Không lưu được chuyển động",
                "Cài đặt chuyển động trước đó được giữ nguyên.",
            )
            return
        QApplication.instance().setProperty("motion", desired_motion)

    def toggle_sidebar(self):
        self._sidebar_compact = not self._sidebar_compact
        compact = self._sidebar_compact
        self.sidebar.setFixedWidth(72 if compact else 200)
        self.sidebar_nav.setSpacing(6 if compact else 9)
        self.sidebar_toggle.setMaximumWidth(56 if compact else 10000)
        for button in self.nav_buttons:
            button.setMaximumWidth(56 if compact else 10000)
        self.sidebar_nav.setContentsMargins(
            8 if compact else 16,
            20 if compact else 26,
            8 if compact else 16,
            18 if compact else 20,
        )
        self.brand_label.setText("U" if compact else "UDB")
        for item in (
            self.brand_caption,
            self.protected_caption,
            self.sidebar_footer,
            self.sidebar_version,
        ):
            item.setVisible(not compact)
        self.sidebar_toggle.setText("" if compact else "Thu gọn menu")
        self.sidebar_toggle.setAccessibleName(
            "Mở rộng thanh điều hướng" if compact else "Thu gọn thanh điều hướng"
        )
        self.sidebar_toggle.setToolTip(self.sidebar_toggle.accessibleName())
        for index, button in enumerate(self.nav_buttons):
            name = self.nav_names[index]
            button.setText("" if compact else name)
            button.setAccessibleName(name)
            button.setToolTip(name)
        self._refresh_requests()

    def focus_job_search(self):
        self.navigate(2)
        self.job_search.setFocus()
        self.job_search.selectAll()

    def export_activity(self):
        # Explicit local-only export: no raw log contents, script, paths or IDs.
        from .activity_presenter import describe, event_state

        try:
            events = self.activity_feed.poll()
        except (OSError, ValueError):
            QMessageBox.warning(
                self, "Chưa xuất được", "Không đọc được metadata hoạt động."
            )
            return
        if not events:
            QMessageBox.information(
                self, "Không có dữ liệu", "Chưa có hoạt động nào để xuất."
            )
            return
        consent = QMessageBox.question(
            self,
            "Xác nhận xuất nhật ký",
            "Chỉ xuất tối đa 40 bản ghi: thời gian, tên công cụ và trạng thái. "
            "Không xuất nội dung file, script, khóa hay ID phiên. Tiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if consent != QMessageBox.StandardButton.Yes:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu nhật ký UDB (metadata)",
            "udb-activity-redacted.json",
            "JSON (*.json)",
        )
        if not destination:
            return
        records = [
            {
                "time": (
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event["at"]))
                    if event.get("at") and event["at"] > 0
                    else "unknown"
                ),
                "tool": describe(event),
                "state": event_state(event),
            }
            for event in events[:40]
        ]
        try:
            with Path(destination).open("x", encoding="utf-8") as stream:
                json.dump(records, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        except OSError:
            QMessageBox.warning(
                self, "Chưa xuất được", "Không thể tạo tệp mới hoặc tệp đã tồn tại."
            )
            return
        QMessageBox.information(
            self, "Đã tạo bản xuất", "Đã lưu metadata hoạt động đã lược bỏ dữ liệu."
        )

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        self.header_title.setText(self.nav_names[index])
        for i, btn in enumerate(self.nav_buttons):
            btn.selected(i == index)
        self.stack.currentWidget().updateGeometry()
        self.stack.currentWidget().update()

    def open_quick_controls(self):
        from .manager_quick import QuickControls

        if not getattr(self, "quick_controls", None):
            self.quick_controls = QuickControls(self)
        self.quick_controls.show_panel()
        self.hide()

    def guarded(self, fn):
        try:
            return fn()
        except Exception as e:
            QMessageBox.warning(self, "Bridge · không thực hiện được", str(e))

    def run_background(self, fn, done=None):
        if self.busy:
            return
        self.busy = True
        self.connect_button.setEnabled(False)
        self.local_button.setEnabled(False)
        self.configure_button.setEnabled(False)
        self.status_label.setText("●  Đang xử lý…")
        for button in (
            self.browser_start_button,
            self.browser_login_button,
            self.browser_background_button,
            self.workspace_start_button,
        ):
            button.setEnabled(False)
        if getattr(self, "quick_controls", None):
            self.quick_controls.sync()
        self.band.flash()
        worker = Worker(fn)
        self.workers.append(worker)

        def complete(result):
            self.busy = False
            self.configure_button.setEnabled(True)
            self.refresh()
            if done:
                done(result)
            if worker in self.workers:
                self.workers.remove(worker)

        def failed(message):
            complete(None)
            QMessageBox.warning(self, "Không thực hiện được", message)

        worker.signals.done.connect(complete, Qt.ConnectionType.QueuedConnection)
        worker.signals.error.connect(failed, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def toggle_tunnel(self):
        if self.controller.tunnel_wanted:
            self.run_background(lambda: self.controller.stop_process("tunnel"))
        else:
            self.run_background(self.controller.start_tunnel)

    def toggle_local(self):
        self.run_background(
            lambda: (
                self.controller.stop_process("mcp")
                if self.controller.alive("mcp")
                else self.controller.start_local()
            )
        )

    def configure(self):
        if not self.busy:
            ConnectionDialog(self.controller, self).exec()

    def toggle_cloud(self):
        """Only a local GUI action may enable the experimental cloud session."""
        if self.busy:
            return
        if self.controller.alive("cloud"):
            self.run_background(lambda: self.controller.stop_process("cloud"))
            return
        answer = QMessageBox.question(
            self,
            "UDB Cloud · Bật phiên thử nghiệm",
            "Bật phiên Cloud Agent ra Internet cho máy Windows này?\\n"
            "Cloudflare có thể chuyển các yêu cầu được xác thực về UDB.\\n"
            "Chỉ bật khi bạn tin tưởng chủ hệ thống và đã ghép nối máy.\\n"
            "UDB vẫn kiểm tra quyền máy tính riêng và tự tắt phiên khi thoát ứng dụng.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.run_background(self.controller.start_cloud)

    def cloud_pair(self):
        if self.busy:
            return
        relay, ok = QInputDialog.getText(
            self,
            "UDB Cloud · Ghép nối",
            "Địa chỉ Cloudflare HTTPS (workers.dev):",
        )
        if not ok or not relay.strip():
            return
        device_id, ok = QInputDialog.getText(
            self,
            "UDB Cloud · Ghép nối",
            "Mã thiết bị trong lời mời:",
        )
        if not ok or not device_id.strip():
            return
        invitation, ok = QInputDialog.getText(
            self,
            "UDB Cloud · Ghép nối",
            "Mã mời một lần (ẩn):",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not invitation.strip():
            return
        answer = QMessageBox.question(
            self,
            "Xác nhận ghép nối Cloud",
            "Đăng ký thiết bị Windows này với Cloudflare?\n"
            "Thao tác không cấp thêm quyền máy tính cho AI.\n"
            "Chỉ tiếp tục nếu bạn tin tưởng chủ hệ thống cấp mã mời.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def pair_in_background():
            from .cloud_pair import claim_device

            claim_device(
                Path(self.agent.home),
                relay.strip(),
                device_id.strip(),
                invitation.strip(),
            )
            return True

        self.run_background(
            pair_in_background,
            done=lambda success: (
                QMessageBox.information(
                    self,
                    "UDB Cloud",
                    "Đã ghép nối thiết bị. Chưa cấp quyền Windows hoặc plugin ChatGPT. "
                    "Kết nối Cloud Agent vẫn là chức năng thử nghiệm.",
                )
                if success
                else None
            ),
        )

    def open_common_room(self):
        """Open the real, existing room of the selected registered project."""
        if not self.selected_project:
            QMessageBox.information(
                self, "Common Room", "Hãy chọn dự án chứa chatgpt-workspace."
            )
            return
        try:
            _, root = self.agent.project(self.selected_project["id"])
            from .common_room_gui import CommonRoomDialog

            dialog = CommonRoomDialog(root, self)
            dialog.exec()
        except (OSError, ValueError, sqlite3.Error) as exc:
            # Show a controlled local error, without replacing a damaged DB.
            QMessageBox.warning(self, "Common Room", str(exc))

    def project_selected(self):
        self._last_project_auth_check = time.monotonic()
        selected = self.projects.selectedItems()
        self.selected_project = (
            selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else None
        )
        self.common_room_button.setEnabled(bool(self.selected_project))
        automatic = False
        source_granted = False
        permissions_verified = not self.selected_project
        if self.selected_project:
            try:
                automatic = bool(
                    self.agent.sandbox_authorization(
                        self.selected_project["id"], self.selected_project["root"]
                    )
                )
                source_granted = bool(
                    self.agent.source_autonomy_authorization(
                        self.selected_project["id"], self.selected_project["root"]
                    )
                )
            except (OSError, ValueError, sqlite3.Error):
                # A failed grant read is UNKNOWN, not an implicit rejection
                # or permission to keep an old checked toggle active.
                automatic = source_granted = False
            else:
                permissions_verified = True

        for checkbox, granted, available in (
            (
                self.sandbox_auto,
                automatic,
                bool(self.selected_project) and permissions_verified,
            ),
            (
                self.source_auto,
                source_granted,
                bool(self.selected_project)
                and bool(self.selected_project["writable"])
                and permissions_verified,
            ),
        ):
            was_blocked = checkbox.blockSignals(True)
            try:
                checkbox.setChecked(granted)
                checkbox.setEnabled(available)
            finally:
                checkbox.blockSignals(was_blocked)
        if self.selected_project:
            self.footer_project.setText("Dự án: " + self.selected_project["id"])
            self.project_path.setText(self.selected_project["root"])
            self.project_path.setCursorPosition(0)
            self.project_path.setToolTip(self.selected_project["root"])
            self.project_access.setText(
                "Không xác minh được quyền dự án; làm mới trước khi thay đổi."
                if not permissions_verified
                else (
                    "AI tự sửa mã nguồn hợp lệ, có backup."
                    if source_granted
                    else "Được ghi: bật AI tự sửa để không phải duyệt."
                    if self.selected_project["writable"]
                    else "File gốc: chỉ đọc."
                )
                + (
                    " Sandbox: tự động."
                    if automatic
                    else " Sandbox: chưa cấp quyền tự động."
                )
            )
        else:
            self.footer_project.setText("Chưa chọn dự án")
            self.project_path.clear()
            self.project_path.setToolTip("")
            self.project_access.setText("Thêm thư mục nguồn để bắt đầu.")

    def set_sandbox_autonomy(self, enabled):
        if self.selected_project:
            self.guarded(
                lambda: self.agent.set_sandbox_autonomy_local(
                    self.selected_project["id"], enabled
                )
            )
        self.project_selected()
        self.refresh()

    def set_source_autonomy(self, enabled):
        if not self.selected_project:
            return
        if enabled:
            ok = QMessageBox.question(
                self,
                "Bật AI tự sửa mã nguồn",
                "Cấp quyền ghi tự động cho AI trong dự án "
                + self.selected_project["id"]
                + "?\n"
                "Không cần phê duyệt từng file. File quan trọng vẫn bị chặn; mỗi lần sửa lưu backup.\n"
                "Chọn No để giữ quyền hiện tại.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ok != QMessageBox.StandardButton.Yes:
                self.project_selected()
                return
        self.guarded(
            lambda: self.agent.set_source_autonomy_local(
                self.selected_project["id"], enabled
            )
        )
        self.project_selected()
        self.refresh()

    def set_media_autonomy(self, enabled):
        if enabled:
            ok = QMessageBox.question(
                self,
                "Cho phép tải video tự động",
                "Cấp quyền tải HLS HTTPS từ các tên miền được chủ máy cho phép, "
                "chỉ lưu MP4 trong Downloads, không hỏi từng video?\n"
                "Có thể tốn băng thông/dung lượng. Không cho phép chạy lệnh Windows.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ok != QMessageBox.StandardButton.Yes:
                self.media_auto.blockSignals(True)
                self.media_auto.setChecked(False)
                self.media_auto.blockSignals(False)
                return
        self.guarded(lambda: self.agent.set_media_autonomy_local(enabled))
        self.refresh()

    def open_source(self):
        if self.selected_project:
            self.guarded(
                lambda: SourceDialog(
                    self.agent, self.selected_project["id"], self
                ).exec()
            )

    def add_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục CHỈ mã nguồn")
        if not folder:
            return
        name, ok = QInputDialog.getText(
            self, "Tên dự án", "ID ngắn: chữ, số, gạch nối hoặc gạch dưới"
        )
        if not ok or not name:
            return
        writable = (
            QMessageBox.question(
                self,
                "Quyền dự án",
                "Cho phép AI sửa mã nguồn trong dự án này khi bật Tự sửa?\n\nCheckpoint và file quan trọng luôn được bảo vệ. Chọn No để chỉ đọc.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )
        self.guarded(lambda: self.agent.register_local(name.strip(), folder, writable))
        self.refresh()

    def revoke(self):
        if not self.selected_project:
            return
        pid = self.selected_project["id"]
        if (
            QMessageBox.question(
                self,
                "Thu hồi quyền",
                "Ngừng cho Bridge truy cập dự án "
                + pid
                + "?\nFile dự án sẽ không bị xóa.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.agent.set_sandbox_autonomy_local(pid, False)
        self.agent.set_source_autonomy_local(pid, False)
        with self.agent.connect() as c:
            c.execute("DELETE FROM projects WHERE id=?", (pid,))
        self.agent.audit("revoke", {"project": pid})
        self.refresh()

    def protect(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục cần chặn khỏi Bridge"
        )
        if folder:
            self.guarded(lambda: self.agent.protect_local(folder))
            self.refresh()

    def review_first(self):
        if self.pending_rows:
            self.review(next(iter(self.pending_rows)))

    def review_selected(self):
        rows = self.requests.selectedItems()
        if rows:
            self.review(rows[0].data(0, Qt.ItemDataRole.UserRole))

    def review(self, rid):
        request = self.pending_rows.get(rid)
        if request:
            ApprovalDialog(self.agent, request, self).exec()
            self.refresh()

    def show_job(self):
        selected = self.jobs.selectedItems()
        if not selected:
            return
        jid = selected[0].data(0, Qt.ItemDataRole.UserRole)
        try:
            result = self.agent.job_status(jid, 0, 32000, tail=True)
            is_desktop = result["info"].get("kind") == "desktop"
            self.stop_desktop.setEnabled(
                is_desktop and result["status"] in ("running", "reviewing", "stopping")
            )
            if is_desktop:
                from .desktop_vm import status

                result = status(self.agent, jid)
                output_text = (
                    json.dumps(result, ensure_ascii=False, indent=2)
                    + "\n\nXem cửa sổ Windows Sandbox để quan sát desktop trực tiếp. Nội dung guest là dữ liệu không đáng tin."
                )
                if output_text != self.job_output.toPlainText():
                    self.job_output.setPlainText(output_text)
                script_text = (
                    result["info"]["task"]
                    + "\n\n"
                    + json.dumps(
                        result["info"]["permissions"], ensure_ascii=False, indent=2
                    )
                )
                if script_text != self.job_script.toPlainText():
                    self.job_script.setPlainText(script_text)
                return
            header = json.dumps(
                {k: v for k, v in result.items() if k not in ("output",)},
                ensure_ascii=False,
                indent=2,
            )
            text = (
                header + "\n\n--- OUTPUT (untrusted) ---\n" + result.get("output", "")
            )
            if text != self.job_output.toPlainText():
                bar = self.job_output.verticalScrollBar()
                value = bar.value()
                at_end = value >= bar.maximum() - 2
                self.job_output.setPlainText(text)
                bar.setValue(bar.maximum() if at_end else value)
            script = (
                self.agent.state
                / "jobs"
                / jid
                / "input"
                / (
                    "task.py"
                    if result["info"].get("language") == "python"
                    else "task.ps1"
                )
            )
            reject_links(script)
            if script.is_file():
                with script.open("rb") as f:
                    data = f.read(64004)
                text = (
                    data.decode("utf-8-sig")
                    if len(data) <= 64003
                    else "Script vượt giới hạn hiển thị."
                )
                if text != self.job_script.toPlainText():
                    self.job_script.setPlainText(text)
            else:
                missing_script = "Không còn file script cục bộ của tác vụ này."
                if missing_script != self.job_script.toPlainText():
                    self.job_script.setPlainText(missing_script)
        except Exception as e:
            message = str(e)
            if message != self.job_output.toPlainText():
                self.job_output.setPlainText(message)

    def stop_selected_desktop(self):
        selected = self.jobs.selectedItems()
        if selected:
            from .desktop_vm import stop

            self.guarded(
                lambda: stop(self.agent, selected[0].data(0, Qt.ItemDataRole.UserRole))
            )
            self.refresh()

    def propose_desktop_local(self):
        if not self.selected_project:
            QMessageBox.information(
                self, "Chọn dự án", "Chọn dự án nguồn ở trang Dự án trước."
            )
            return
        task, ok = QInputDialog.getMultiLineText(
            self,
            "Nhiệm vụ cho desktop AI",
            "AI được làm gì trong Sandbox? Phiên 10 phút, mạng/clipboard tắt.",
            "Mở UDB Sandbox Pad, gõ UDB_SANDBOX_INPUT_OK, bấm Confirm và chụp màn hình kiểm tra. Chỉ thao tác trong guest Windows Sandbox.",
        )
        if ok and task.strip():
            response = self.guarded(
                lambda: self.agent.propose_desktop(
                    self.selected_project["id"], task.strip(), 600
                )
            )
            self.refresh()
            if response:
                if response["status"] == "queued_sandbox":
                    self.navigate(2)
                else:
                    self.review(response["request_id"])

    def open_url(self, url):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(
                self,
                "Không mở được liên kết",
                "Windows không mở được trình duyệt mặc định. "
                "Hãy mở liên kết này trong trình duyệt:\n" + url,
            )

    def _update_window_chrome(self):
        if os.name == "nt":
            try:
                import ctypes

                value = ctypes.c_int(1 if current_theme().name == "dark" else 0)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    int(self.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
                )
            except Exception:
                pass  # DWM styling is cosmetic and must never block the UI.

    def showEvent(self, event):
        super().showEvent(event)
        self._update_window_chrome()

    def closeEvent(self, event):
        if getattr(self, "_keep_in_tray", False) and not getattr(
            self, "_quit_requested", False
        ):
            self.hide()
            event.ignore()
            return
        if self.busy:
            event.ignore()
            return
        if not self._closing:
            self._closing = True
            self.timer.stop()
            try:
                self.controller.close()
            except Exception as exc:
                self._closing = False
                self.timer.start(1500)
                event.ignore()
                QMessageBox.warning(self, "Chưa thể đóng UDB", str(exc))
                return
        if getattr(self, "quick_controls", None):
            self.quick_controls.hide()
            if self.quick_controls.tray:
                self.quick_controls.tray.hide()
        event.accept()


def make_app():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Universal Desktop Bridge")
    app.setOrganizationName("UniversalDesktopBridge")
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont("Segoe UI", 10))
    app.setProperty("motion", True)
    # Deterministic default for synthetic Qt tests; run() applies user settings.
    apply_theme(app, "dark")
    return app


def run(home: Path, start_tunnel=False, screenshot=None):
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.FreeConsole()
    app = make_app()
    from .core import Agent

    agent = Agent(home)
    lock = QLockFile(str(agent.state / "manager.lock"))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(50):
        from .headless import manager_status

        headless = manager_status(agent.state)["mode"] == "headless"
        QMessageBox.information(
            None,
            "Bridge đang mở",
            "UDB đang chạy ẩn, không có cửa sổ hoặc biểu tượng khay. Để chuyển sang GUI, dùng udb stop rồi udb gui. Dừng tác nhân sẽ đóng các phiên UDB đang chạy."
            if headless
            else "Ứng dụng đã được mở. Kiểm tra biểu tượng UDB ở khay hệ thống hoặc thanh tác vụ Windows.",
        )
        return
    controller = DesktopController(home)
    settings = controller.settings()
    app.setProperty("motion", settings.get("motion", True))
    apply_theme(app, settings.get("theme", "system"))
    controller.start_host()
    window = MainWindow(home, controller)
    # The full manager remains the fallback when a tray cannot be reached.
    # Screenshots retain the full-page capture contract.
    from .manager_quick import QuickControls

    window.quick_controls = QuickControls(window)
    if not screenshot and window.quick_controls.install_tray():
        window.quick_controls.show_panel()
    else:
        window.show()
    if start_tunnel or settings.get("autoconnect", False):
        QTimer.singleShot(350, window.toggle_tunnel)
    if screenshot:
        dest = Path(screenshot)

        def capture():
            if not window.grab().save(str(dest)):
                raise OSError("GUI screenshot failed")
            app.quit()

        QTimer.singleShot(7000 if start_tunnel else 550, capture)
    code = app.exec()
    controller.close()
    lock.unlock()
    return code


def self_test(preview_dir=None):
    """Run the disposable Qt GUI self-test while preserving the public API."""
    from .manager_selftest import self_test as run_self_test

    return run_self_test(preview_dir)
