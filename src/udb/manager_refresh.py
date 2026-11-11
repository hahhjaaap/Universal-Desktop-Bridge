"""Project/status refresh logic for the UDB desktop manager."""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QTreeWidgetItem

from .activity_presenter import describe, event_state
from .manager_job_refresh import should_reload_job_details
from .manager_widgets import icon
from .ui_connection import unknown_indicator, worker_indicator
from .ui_jobs import job_metadata, visible_jobs
from .ui_security import (
    approval_indicator,
    input_pause_indicator,
    source_autonomy_indicator,
)
from .ui_theme import current_theme


class ManagerRefreshMixin:
    def refresh(self):
        if self._closing:
            return
        errors = []
        source_auto_projects = set()
        for name, refresh in (
            ("Dự án", self._refresh_projects),
            ("Máy tính", self._refresh_host),
            ("Quyền AI", self._refresh_requests),
            ("Tiến trình", self._refresh_jobs),
            ("Hoạt động", self._refresh_activity),
            ("Bảo mật", self._refresh_security),
        ):
            try:
                result = refresh()
                if name == "Dự án":
                    source_auto_projects = result
            except Exception as exc:
                if name == "Bảo mật":
                    errors.append("Bảo mật: không đọc được trạng thái")
                    self.computer_grant_pill.set_status("Chưa xác minh", "neutral")
                    self.header_privilege.set_status(
                        "Quyền máy: chưa xác minh", "neutral"
                    )
                    self.header_privilege.setToolTip(
                        "Không thể đọc trạng thái quyền Windows toàn diện cục bộ."
                    )
                    self.computer_grant_detail.setText(
                        "Không xác minh được quyền Windows; xem kiểm tra cục bộ."
                    )
                    self.security_observed.setText(
                        "Kiểm tra quyền Windows thất bại · Chưa xác minh."
                    )
                else:
                    errors.append(name + ": " + str(exc))
                if name == "Máy tính":
                    indicator = unknown_indicator()
                    self.local_health.set_status(indicator.text, indicator.tone)
                    self.local_health.setToolTip(indicator.detail)
                    self.setup_agent_health.set_status(indicator.text, indicator.tone)
                    self.setup_agent_health.setToolTip(indicator.detail)
                    self.security_pause_status.set_status("Chưa xác minh", "neutral")
                elif name == "Dự án":
                    self.security_autonomy_status.set_status("Chưa xác minh", "neutral")
                elif name == "Quyền AI":
                    # Never keep a previously actionable approval visible
                    # after the backend's latest pending-list read fails.
                    self.security_approval_status.set_status("Chưa xác minh", "neutral")
                    self.security_approval_status.setToolTip(
                        "Không đọc được yêu cầu chờ duyệt hiện tại."
                    )
                    self.pending_rows = {}
                    self.last_pending = None
                    self.requests.clear()
                    self.requests.setVisible(False)
                    self.pending_title.setText("Chưa xác minh yêu cầu chờ duyệt")
                    self.pending_hint.setText(
                        "Không đọc được danh sách mới. Thử Làm mới trước khi duyệt."
                    )
                    self.pending_code.clear()
                    self.pending_code.setVisible(False)
                    self.approval_empty.setVisible(True)
                    self.approval_review.setEnabled(False)
                    self.review_button.setEnabled(False)
                    self.media_auto.setEnabled(False)
                    permission_nav = self.nav_buttons[1]
                    permission_nav.setText(
                        "" if getattr(self, "_sidebar_compact", False) else "Quyền AI"
                    )
                    permission_nav.setAccessibleName("Quyền AI · Chưa xác minh")
                    permission_nav.setToolTip("Yêu cầu chờ duyệt chưa được xác minh.")
        try:
            self._refresh_connection(source_auto_projects)
        except Exception as exc:
            errors.append("Kết nối: " + str(exc))
            indicator = unknown_indicator()
            self.cloud_health.set_status(indicator.text, indicator.tone)
            self.cloud_health.setToolTip(indicator.detail)
            self.setup_cloud_health.set_status(indicator.text, indicator.tone)
            self.setup_cloud_health.setToolTip(indicator.detail)
            self.header_connection.set_status(
                "Tunnel: " + indicator.text, indicator.tone
            )
            self.header_connection.setToolTip(
                indicator.detail + " ChatGPT chưa được xác minh bằng lời gọi công cụ."
            )
            self._connection_ready = False
            self.status_label.setText("●  Không đọc được Cloudflare")
            theme = current_theme()
            self.status_label.setStyleSheet(
                f"color:{theme.muted}; background:{theme.raised};"
                " border-radius:9px; padding:4px 10px;"
            )
            self.connect_button.setEnabled(False)
            self.connection_hint.setText(
                "Chưa xác minh kết nối mới; thử kiểm tra lại từ ChatGPT."
            )
        if errors:
            self.footer_status.setText(
                "Không tải được trạng thái · " + " · ".join(errors)
            )
        if getattr(self, "quick_controls", None):
            self.quick_controls.sync(
                status_error=any(
                    e.startswith(("Máy tính:", "Kết nối:")) for e in errors
                )
            )

    def _refresh_projects(self):
        projects = self.agent.projects()
        source_auto_projects = set(self.agent.source_autonomy_projects())
        auto = source_autonomy_indicator(len(source_auto_projects))
        self.security_autonomy_status.set_status(auto.text, auto.tone)
        self.security_autonomy_status.setToolTip(auto.detail)
        signature = tuple(
            (p["id"], p["root"], p["writable"], p["id"] in source_auto_projects)
            for p in projects
        )
        if signature != self.last_signature:
            self.last_signature = signature
            selected = self.selected_project["id"] if self.selected_project else None
            with QSignalBlocker(self.projects):
                self.projects.clear()
                for proj in projects:
                    item = QTreeWidgetItem(
                        [
                            proj["id"],
                            "AI tự sửa"
                            if proj["id"] in source_auto_projects
                            else "Ghi có giới hạn"
                            if proj["writable"]
                            else "Chỉ đọc",
                        ]
                    )
                    item.setIcon(0, icon("folder", current_theme().muted))
                    item.setData(0, Qt.ItemDataRole.UserRole, proj)
                    item.setToolTip(0, proj["root"])
                    self.projects.addTopLevelItem(item)
                    if proj["id"] == selected:
                        self.projects.setCurrentItem(item)
                if not self.projects.selectedItems() and projects:
                    self.projects.setCurrentItem(self.projects.topLevelItem(0))
            self.project_selected()
        elif time.monotonic() - self._last_project_auth_check >= 10.0:
            self.project_selected()
        return source_auto_projects

    def _refresh_host(self):
        from .desktop_control import paused
        from .host_client import status as host_status

        hs = host_status(self.agent)
        rs = hs["resources"]
        is_paused = paused(self.agent)
        pause_state = input_pause_indicator(is_paused)
        self.security_pause_status.set_status(pause_state.text, pause_state.tone)
        self.security_pause_status.setToolTip(pause_state.detail)
        sessions = hs.get("sessions", [])
        handed_off = any(x.get("presentation") == "visible" for x in sessions)
        self._browser_handed_off = handed_off
        closing = any(x.get("closing") for x in sessions)
        ready = hs.get("worker_ready") is True
        enabled = hs.get("enabled") is True
        if is_paused:
            tone, state = "paused", "Đã tạm dừng"
            title = "Điều khiển Windows đang tạm dừng"
            hint = "Bạn có thể tiếp tục bất cứ lúc nào. Các phiên nền vẫn làm việc theo quyền đã cấp."
        elif closing:
            tone, state = "neutral", "Đang đóng phiên"
            title = "UDB đang thu dọn phiên riêng"
            hint = "Phiên đang đóng sẽ không nhận thêm thao tác. Nếu chưa đóng xong, bạn có thể bấm Tắt phiên nền để thử thu dọn lại."
        elif handed_off:
            tone, state = "owner", "Bạn điều khiển"
            title = "Browser đang được nhường cho bạn"
            hint = "Đăng nhập trực tiếp trong cửa sổ UDB. Bấm Trả về cho AI khi bạn đã xong."
        elif not ready:
            tone, state = "neutral", "Chưa sẵn sàng"
            title = "Đang chờ tác nhân UDB"
            hint = "Trạng thái sẽ cập nhật khi tác nhân cục bộ sẵn sàng. Bạn vẫn có thể tạm dừng Windows."
        elif not enabled:
            tone, state = "neutral", "Chưa bật phiên nền"
            title = "Bạn chọn khi nào AI được chạy nền"
            hint = "Mở UDB đầy đủ → Máy tính để cho phép AI mở browser riêng khi bạn giao việc."
        elif not rs.get("admission_ready"):
            tone, state = "paused", "Đang chờ tài nguyên"
            title = "UDB đang chờ máy bớt bận"
            hint = "Chưa mở thêm phiên mới. Các nút tạm dừng và đóng phiên luôn ở đây."
        else:
            tone, state = "ready", "Sẵn sàng chạy nền"
            title = "Bạn luôn nắm quyền điều khiển"
            hint = "AI ưu tiên chạy nền. Khi dùng desktop, UDB nhường nếu bạn thao tác."
        self.desktop_state_pill.set_status(state, tone)
        self.desktop_state_title.setText(title)
        self.desktop_pause_status.setText(hint)
        self.desktop_pause_button.setEnabled(not is_paused)
        self.desktop_resume_button.setEnabled(is_paused)
        self.desktop_hotkey_hint.setText(
            "Tạm dừng nhanh · Ctrl + Alt + Shift + Backspace"
            if hs.get("emergency_hotkey_available")
            else "Tạm dừng bằng nút ở trên · Phím tắt chưa sẵn sàng"
        )
        self.host_enabled.blockSignals(True)
        self.host_enabled.setChecked(enabled)
        self.host_enabled.blockSignals(False)
        capacity = rs.get("admission_ready") is True
        self.browser_start_button.setEnabled(
            not self.busy
            and ready
            and enabled
            and capacity
            and not any(x["kind"] == "browser" for x in sessions)
        )
        self.browser_login_button.setEnabled(
            not self.busy
            and ready
            and enabled
            and capacity
            and not handed_off
            and not closing
        )
        self.browser_background_button.setEnabled(
            not self.busy
            and ready
            and enabled
            and capacity
            and handed_off
            and not closing
        )
        self.workspace_start_button.setEnabled(
            not self.busy
            and ready
            and enabled
            and capacity
            and not any(x["kind"] == "workspace" for x in sessions)
        )
        browser_open = any(x["kind"] == "browser" for x in sessions)
        self.browser_remember.setEnabled(ready and not browser_open)
        self.browser_remember.setToolTip(
            "Đóng browser trước khi đổi lựa chọn nhớ đăng nhập."
            if browser_open
            else "Chỉ nhớ đăng nhập trong browser riêng của UDB."
        )
        self.host_stop_button.setEnabled(enabled or bool(sessions))
        cpu, ram = rs.get("cpu_percent"), rs.get("ram_percent")
        self.host_resource.setText(
            f"CPU {cpu if cpu is not None else '—'}%  ·  RAM {ram if ram is not None else '—'}%  ·  Trống {rs.get('available_mib', 0)} MB"
        )
        self.host_pressure.setText(
            "Đủ tài nguyên để mở phiên."
            if rs.get("admission_ready")
            else "Máy đang bận hoặc chưa có số liệu mới; UDB đang chờ."
        )
        signature = tuple(
            (
                x["session_id"],
                x["kind"],
                x.get("presentation"),
                x.get("tabs"),
                x.get("task", ""),
                x.get("closing", False),
            )
            for x in sessions
        )
        if signature != getattr(self, "_host_sessions_signature", None):
            self._host_sessions_signature = signature
            self.host_sessions.clear()
            for session in sessions:
                browser = session["kind"] == "browser"
                item = QTreeWidgetItem(
                    [
                        "Browser riêng" if browser else "Không gian ghi chú",
                        "Đang đóng"
                        if session.get("closing")
                        else "Bạn điều khiển"
                        if session.get("presentation") == "visible"
                        else "Chạy nền",
                        str(session.get("tabs", 0)) if browser else "—",
                    ]
                )
                item.setIcon(
                    0, icon("browser" if browser else "file", current_theme().accent)
                )
                item.setToolTip(
                    0, session.get("task", "") + "\n" + session["session_id"]
                )
                self.host_sessions.addTopLevelItem(item)
        self.host_sessions.setVisible(bool(sessions))
        self.host_sessions_empty.setVisible(not sessions)
        indicator = worker_indicator(hs.get("worker_ready"))
        self.local_health.set_status(indicator.text, indicator.tone)
        self.local_health.setToolTip(indicator.detail)
        self.setup_agent_health.set_status(indicator.text, indicator.tone)
        self.setup_agent_health.setToolTip(indicator.detail)

    def _refresh_requests(self):
        # An unavailable settings store must not permanently block the
        # checkbox's signals. Preserve the pre-existing block state as well.
        was_blocked = self.media_auto.blockSignals(True)
        try:
            self.media_auto.setChecked(self.agent.media_autonomy())
        finally:
            self.media_auto.blockSignals(was_blocked)
        rows = self.agent.pending_local()
        approval_state = approval_indicator(len(rows))
        self.security_approval_status.set_status(
            approval_state.text, approval_state.tone
        )
        self.security_approval_status.setToolTip(approval_state.detail)
        self.pending_rows = {r["id"]: r for r in rows}
        signature = tuple((r["id"], r["kind"], r["payload"]) for r in rows)
        if signature != self.last_pending:
            self.last_pending = signature
            current = self.requests.currentItem()
            selected = current.data(0, Qt.ItemDataRole.UserRole) if current else None
            self.requests.clear()
            for request in rows:
                p = json.loads(request["payload"])
                item = QTreeWidgetItem(
                    [
                        p["project"]
                        + " / "
                        + p.get("path", p.get("task", p.get("language", ""))),
                        "Sửa file"
                        if request["kind"] == "write"
                        else "Chuột/phím"
                        if request["kind"] == "desktop"
                        else "Sandbox",
                        "",
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, request["id"])
                self.requests.addTopLevelItem(item)
                if request["id"] == selected:
                    self.requests.setCurrentItem(item)
            if rows and not self.requests.selectedItems():
                self.requests.setCurrentItem(self.requests.topLevelItem(0))
            if rows:
                p = json.loads(rows[0]["payload"])
                self.pending_title.setText(
                    p.get("path", p.get("language", "Phiên chuột/phím"))
                )
                self.pending_hint.setText(
                    p["project"]
                    + " · "
                    + (
                        "Thay đổi file"
                        if rows[0]["kind"] == "write"
                        else "Chuột/phím trong Sandbox"
                        if rows[0]["kind"] == "desktop"
                        else "Tải video FFmpeg"
                        if rows[0]["kind"] == "media"
                        else "Chạy trong Sandbox"
                    )
                )
                self.pending_code.setPlainText(
                    p.get("diff", p.get("script", p.get("task", "")))[:8000]
                )
            else:
                self.pending_title.setText("Không có yêu cầu chờ duyệt")
                self.pending_hint.setText(
                    "Đề xuất sửa và chạy mã từ Chat sẽ xuất hiện tại đây."
                )
                self.pending_code.clear()
        for i, r in enumerate(rows):
            self.requests.topLevelItem(i).setText(
                2, str(max(0, int(r["created"] + 600 - time.time()))) + " giây"
            )
        self.pending_code.setVisible(bool(rows))
        self.requests.setVisible(bool(rows))
        self.approval_empty.setVisible(not rows)
        self.approval_review.setEnabled(bool(rows))
        self.review_button.setEnabled(bool(rows))
        self.media_auto.setEnabled(not self.busy)
        permission_text = "Quyền AI" + (f"  {len(rows)}" if rows else "")
        permission_nav = self.nav_buttons[1]
        permission_nav.setText(
            "" if getattr(self, "_sidebar_compact", False) else permission_text
        )
        permission_nav.setAccessibleName(permission_text)
        permission_nav.setToolTip(permission_text)

    def _refresh_security(self):
        from .computer_access import summary

        state = summary(self.agent)
        self.security_observed.setText(
            "Lần kiểm tra trên máy: "
            + time.strftime("%H:%M:%S", time.localtime())
            + " · Trạng thái chưa đọc được hiển thị riêng."
        )
        if state.get("enabled") is True:
            self.computer_grant_pill.set_status("Đã bật · không sandbox", "paused")
            self.header_privilege.set_status("Windows: không sandbox", "paused")
            self.header_privilege.setToolTip(
                "Quyền máy rộng đang bật; AI có thể truy cập dữ liệu của tài khoản "
                "Windows. Các hạn chế theo dự án không áp dụng cho quyền này."
            )
            self.computer_grant_detail.setText(
                "Quyền điều khiển Windows toàn diện đang được cấp. "
                "AI có thể thao tác tệp, chạy chương trình và dùng chuột/phím "
                "trong phạm vi tài khoản Windows, kể cả dữ liệu được chặn "
                "đối với dự án. Thu hồi cục bộ: udb revoke-access."
            )
        elif state.get("enabled") is False:
            self.computer_grant_pill.set_status("Không khả dụng", "neutral")
            self.header_privilege.set_status("Quyền máy: không bật", "neutral")
            self.header_privilege.setToolTip(
                "Không có quyền máy rộng được xác minh. Quyền dự án và Sandbox "
                "vẫn được quản lý riêng."
            )
            self.computer_grant_detail.setText(
                "Quyền máy Windows toàn diện không khả dụng. "
                "Quyền dự án và Windows Sandbox được quản lý riêng."
            )
        else:
            self.computer_grant_pill.set_status("Chưa xác minh", "neutral")
            self.header_privilege.set_status("Quyền máy: chưa xác minh", "neutral")
            self.header_privilege.setToolTip(
                "Không có bằng chứng mới để xác minh quyền máy Windows."
            )
            self.computer_grant_detail.setText(
                "Chưa có bằng chứng xác minh trạng thái quyền máy."
            )

    def _refresh_jobs(self):
        with self.agent.connect() as c:
            protected = [
                r[0] for r in c.execute("SELECT root FROM protected ORDER BY root")
            ]
            jobs = [
                dict(r)
                for r in c.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT 30")
            ]
        all_jobs = jobs
        jobs = visible_jobs(
            all_jobs, self.job_search.text(), self.job_group_filter.currentText()
        )
        self.job_filter_feedback.setText(
            f"Hiển thị {len(jobs)}/{len(all_jobs)} công việc"
        )
        protected_signature = tuple(protected)
        if protected_signature != getattr(self, "_protected_signature", None):
            self._protected_signature = protected_signature
            self.protected.clear()
            for path in protected:
                self.protected.addTopLevelItem(QTreeWidgetItem([path]))
        job_sig = tuple((j["id"], j["status"], j["info"]) for j in jobs)
        jobs_changed = job_sig != self.last_job_signature
        if jobs_changed:
            self.last_job_signature = job_sig
            current = self.jobs.currentItem()
            old = current.data(0, Qt.ItemDataRole.UserRole) if current else None
            with QSignalBlocker(self.jobs):
                self.jobs.clear()
                for j in jobs:
                    info = job_metadata(j)
                    status_text = {
                        "running": "Đang chạy",
                        "reviewing": "Đã xong · đang xem",
                        "completed": "Hoàn tất",
                        "failed": "Lỗi",
                        "timeout": "Hết thời gian",
                        "output_limit": "Log vượt giới hạn",
                        "stopping": "Đang dừng",
                        "stopped": "Đã dừng",
                    }.get(j["status"], j["status"])
                    item = QTreeWidgetItem(
                        [
                            info.get("project", ""),
                            info.get(
                                "language",
                                "Desktop" if info.get("kind") == "desktop" else "",
                            ),
                            status_text,
                            j["id"],
                        ]
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, j["id"])
                    self.jobs.addTopLevelItem(item)
                    if j["id"] == old:
                        self.jobs.setCurrentItem(item)
                if jobs and not self.jobs.selectedItems():
                    self.jobs.setCurrentItem(self.jobs.topLevelItem(0))
        self.jobs.setVisible(bool(jobs))
        # MCP activity exists independently of Sandbox/background job records.
        self.job_tabs.setVisible(True)
        self.jobs_empty.setVisible(
            not jobs and self.activity_timeline.topLevelItemCount() == 0
        )
        if not jobs:
            self.job_output.clear()
            self.job_script.clear()
        selected = self.jobs.selectedItems()
        if selected:
            selected_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
            selected_status = next(
                (j["status"] for j in jobs if j["id"] == selected_id), None
            )
            if should_reload_job_details(jobs_changed, selected_status):
                self.show_job()

    def _refresh_activity(self):
        try:
            events = self.activity_feed.poll()
        except (OSError, ValueError):
            self.activity_timeline.clear()
            self.activity_signature = None
            self.jobs_empty.setVisible(self.jobs.topLevelItemCount() == 0)
            return
        signature = tuple(
            (
                row.get("seq"),
                row.get("kind"),
                row.get("status"),
                row.get("tool"),
            )
            for row in events
        )
        if signature == self.activity_signature:
            return
        self.activity_signature = signature
        self.jobs_empty.setVisible(self.jobs.topLevelItemCount() == 0 and not events)
        with QSignalBlocker(self.activity_timeline):
            self.activity_timeline.clear()
            for event in events:
                stamp = event.get("at")
                clock = (
                    time.strftime("%H:%M:%S", time.localtime(stamp))
                    if isinstance(stamp, (int, float)) and stamp > 0
                    else "—"
                )
                self.activity_timeline.addTopLevelItem(
                    QTreeWidgetItem([clock, describe(event), event_state(event)])
                )

    def _refresh_connection(self, source_auto_projects):
        status = self.controller.status()
        pairing = self.agent.home / "cloud-pairing.json"
        paired = pairing.exists() or pairing.is_symlink()
        running = status.get("cloud_running") is True
        state = "Đang chạy" if running else "Chưa bật" if paired else "Chưa ghép nối"
        tone = "paused" if running else "neutral"
        self._connection_ready = False
        for pill in (
            self.cloud_health,
            self.setup_cloud_health,
            self.header_connection,
        ):
            pill.set_status("Cloudflare: " + state, tone)
            pill.setToolTip("Gọi bridge_status trong ChatGPT để xác minh.")
        if not self.busy:
            self.status_label.setText("●  Cloud Agent " + state.lower())
        theme = current_theme()
        self.status_label.setStyleSheet(
            "color:"
            + (theme.warning if running else theme.muted)
            + "; background:"
            + theme.raised
            + "; border-radius:9px; padding:4px 10px;"
        )
        action = "Tắt Cloud Agent" if running else "Bật Cloud Agent"
        self.connect_button.setText(action if paired else "Ghép Cloudflare")
        self.connect_button.setEnabled(not self.busy)
        self.cloud_session_button.setText(action)
        self.cloud_session_button.setEnabled(paired and not self.busy)
        self.cloud_pair_button.setEnabled(not paired and not self.busy)
        self.cloud_probe_button.setEnabled(paired and not self.busy)
        self.live_button.setEnabled(paired)
        self.cloud_session_status.setText("Cloud Agent " + state.lower())
        self.connection_hint.setText(
            "Cloudflare MCP · xác minh bằng bridge_status trong ChatGPT."
        )
        self.detail_status.setText("Cloudflare: " + state)
        setup = self.agent.state / "sandbox-setup-result.json"
        needs_restart = False
        if setup.exists():
            try:
                needs_restart = bool(
                    json.loads(setup.read_text("utf-8-sig")).get("RestartNeeded")
                )
            except (OSError, ValueError):
                pass
        self.sandbox_label.setText(
            (
                "Sandbox: chưa sẵn sàng. Lần bật tính năng trước yêu cầu khởi động lại Windows."
                if needs_restart
                else "Sandbox chưa khả dụng. Chạy mã đang bị khóa."
            )
            if not status["sandbox"]
            else "Sandbox: thành phần đã cài, chờ kiểm thử chạy mã."
        )
        sig = (running, paired)
        if sig != self.connection_signature:
            self.connection_signature = sig
            self.band.flash()
        self.footer_status.setText(
            "Cloud Agent "
            + state.lower()
            + " · "
            + ("AI tự sửa theo quyền" if source_auto_projects else "Chưa bật tự sửa")
            + " · Quyền do bạn cấp"
        )
