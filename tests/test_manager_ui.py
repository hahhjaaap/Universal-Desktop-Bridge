"""Real Qt layout and owner-control behavior using only disposable local state."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from udb.desktop import DesktopController
from udb.desktop_control import paused


@pytest.fixture
def manager(tmp_path, monkeypatch):
    from udb.manager import MainWindow, make_app

    app = make_app()
    app.setProperty("motion", False)
    host = dict(
        worker_ready=True,
        enabled=True,
        resources=dict(
            admission_ready=True, cpu_percent=12, ram_percent=40, available_mib=8000
        ),
        sessions=[],
        emergency_hotkey_available=True,
    )
    monkeypatch.setattr("udb.host_client.status", lambda agent: host)
    controller = DesktopController(tmp_path, monitor=False)
    window = MainWindow(tmp_path, controller)
    window.timer.stop()
    window.resize(960, 680)
    window.show()
    app.processEvents()
    yield window, host
    window.close()
    app.processEvents()


def test_emergency_controls_remain_visible_when_body_is_scrolled(manager):
    from PySide6.QtWidgets import QApplication, QScrollArea

    window, _ = manager
    assert window.stack.currentIndex() == 5
    scroll = window.stack.currentWidget().findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    QApplication.processEvents()
    for button in (
        window.desktop_pause_button,
        window.desktop_resume_button,
        window.host_stop_button,
    ):
        assert button.isVisible()
        assert window.rect().contains(button.mapTo(window, button.rect().center()))


def test_pause_and_resume_update_local_state_without_granting_access(manager):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, _ = manager
    assert not window.desktop_resume_button.isEnabled()
    QTest.mouseClick(window.desktop_pause_button, Qt.MouseButton.LeftButton)
    assert paused(window.agent) and window.desktop_resume_button.isEnabled()
    assert "tạm dừng" in window.desktop_state_title.text()
    QTest.mouseClick(window.desktop_resume_button, Qt.MouseButton.LeftButton)
    assert not paused(window.agent)
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_browser_handoff_controls_reflect_real_session_state(manager):
    window, host = manager
    assert not window.browser_background_button.isEnabled()
    host["sessions"] = [
        dict(
            session_id="a" * 32,
            kind="browser",
            tabs=2,
            task="Synthetic task",
            presentation="visible",
        )
    ]
    window._refresh_host()
    assert window.browser_background_button.isEnabled()
    assert not window.browser_login_button.isEnabled()
    assert "Bạn điều khiển" in window.desktop_state_pill.text()
    row = window.host_sessions.topLevelItem(0)
    assert row.text(0) == "Browser riêng" and row.text(1) == "Bạn điều khiển"
    assert "a" * 32 not in " ".join(row.text(i) for i in range(3))


def test_unknown_worker_does_not_claim_ai_is_ready(manager):
    window, host = manager
    host["worker_ready"] = False
    window._refresh_host()
    assert "Chưa sẵn sàng" in window.desktop_state_pill.text()
    assert not window.browser_start_button.isEnabled()
    assert window.desktop_pause_button.isEnabled()


def test_unavailable_hotkey_has_a_visible_button_fallback(manager):
    window, host = manager
    assert "Backspace" in window.desktop_hotkey_hint.text()
    host["emergency_hotkey_available"] = False
    window._refresh_host()
    assert "chưa sẵn sàng" in window.desktop_hotkey_hint.text()
    assert "Backspace" not in window.desktop_hotkey_hint.text()
    assert window.desktop_pause_button.isEnabled()


def test_cards_stack_on_compact_window_without_horizontal_clipping(manager):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea

    window, host = manager
    host["sessions"] = [
        dict(
            session_id="b" * 32,
            kind="browser",
            tabs=1,
            task="Preview",
            presentation="background",
        )
    ]
    window._refresh_host()
    window.resize(1220, 820)
    QTest.qWait(50)
    browser_card = window.browser_start_button.parentWidget()
    sessions_card = window.host_sessions.parentWidget()
    assert sessions_card.x() > browser_card.x()
    window.resize(960, 680)
    QTest.qWait(50)
    assert window.width() == 960
    assert sessions_card.y() > browser_card.y()
    scroll = window.stack.currentWidget().findChild(QScrollArea)
    scroll.ensureWidgetVisible(window.host_sessions)
    QTest.qWait(50)
    viewport = scroll.viewport()
    assert viewport.rect().contains(
        window.host_sessions.mapTo(viewport, window.host_sessions.rect().center())
    )
    assert window.host_sessions.width() <= viewport.width()


def test_project_grant_labels_update_without_changing_project_records(manager):
    window, _ = manager
    root = window.agent.home / "projects" / "demo"
    root.mkdir(parents=True)
    window.agent.register_local("demo", str(root), True)
    window._refresh_projects()
    assert window.projects.currentItem().text(1) == "Ghi có giới hạn"
    window.agent.set_source_autonomy_local("demo", True)
    window._refresh_projects()
    assert window.projects.currentItem().text(1) == "AI tự sửa"
    assert window.source_auto.isChecked()
    window.agent.set_source_autonomy_local("demo", False)
    window._refresh_projects()
    assert window.projects.currentItem().text(1) == "Ghi có giới hạn"
    assert not window.source_auto.isChecked()


def test_replacing_a_protected_root_updates_the_list_with_the_same_row_count(manager):
    window, _ = manager
    first, second = window.agent.home / "first", window.agent.home / "second"
    first.mkdir()
    second.mkdir()
    window.agent.protect_local(str(first))
    window._refresh_jobs()
    assert window.protected.topLevelItem(0).text(0) == str(first)
    with window.agent.connect() as db:
        db.execute("DELETE FROM protected")
    window.agent.protect_local(str(second))
    window._refresh_jobs()
    assert window.protected.topLevelItem(0).text(0) == str(second)


def test_project_refresh_failure_does_not_block_desktop_pause_state(
    manager, monkeypatch
):
    from udb.desktop_control import pause_local

    window, _ = manager

    def unavailable():
        raise OSError("Synthetic unavailable project")

    monkeypatch.setattr(window, "_refresh_projects", unavailable)
    pause_local(window.agent, True)
    window.refresh()
    assert "Đã tạm dừng" in window.desktop_state_pill.text()
    assert window.desktop_resume_button.isEnabled()
    assert "Synthetic unavailable project" in window.footer_status.text()


def test_pending_payload_updates_preserve_the_selected_request(manager):
    import json
    import time

    from PySide6.QtCore import Qt

    window, _ = manager
    first, second = "c" * 32, "d" * 32
    payload = {"project": "demo", "path": "first.py", "diff": "reviewed preview"}
    with window.agent.connect() as db:
        db.execute(
            "INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
            (first, "write", json.dumps(payload), "", time.time(), "pending", "{}"),
        )
    window._refresh_requests()
    assert window.pending_title.text() == "first.py"
    payload["path"] = "changed.py"
    with window.agent.connect() as db:
        db.execute(
            "UPDATE requests SET payload=? WHERE id=?", (json.dumps(payload), first)
        )
        db.execute(
            "INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
            (
                second,
                "write",
                json.dumps(payload),
                "",
                time.time() - 1,
                "pending",
                "{}",
            ),
        )
    window._refresh_requests()
    assert window.requests.currentItem().data(0, Qt.ItemDataRole.UserRole) == first
    assert window.pending_title.text() == "changed.py"


def test_closing_session_is_visible_and_does_not_offer_new_browser_actions(manager):
    window, host = manager
    host["sessions"] = [
        dict(
            session_id="a" * 32,
            kind="browser",
            tabs=1,
            presentation="visible",
            task="fixture",
            closing=True,
        )
    ]
    window._refresh_host()
    assert "Đang đóng" in window.desktop_state_pill.text()
    assert window.host_sessions.topLevelItem(0).text(1) == "Đang đóng"
    assert not window.browser_login_button.isEnabled()
    assert not window.browser_background_button.isEnabled()


def test_return_button_observes_resource_admission_like_the_host_service(manager):
    window, host = manager
    host["sessions"] = [
        dict(
            session_id="a" * 32,
            kind="browser",
            tabs=1,
            presentation="visible",
            task="fixture",
        )
    ]
    host["resources"]["admission_ready"] = False
    window._refresh_host()
    assert not window.browser_background_button.isEnabled()


def test_stop_button_retries_cleanup_when_background_mode_is_already_disabled(
    manager, monkeypatch
):
    window, host = manager
    host["enabled"] = False
    host["sessions"] = [
        dict(session_id="a" * 32, kind="browser", tabs=0, task="fixture", closing=True)
    ]
    window._refresh_host()
    calls = []
    monkeypatch.setattr(window, "run_background", lambda fn: fn())
    monkeypatch.setattr("udb.host_client.command", lambda agent, op: calls.append(op))
    assert window.host_stop_button.isEnabled()
    window.stop_host_local()
    assert calls == ["stop_all"]


def test_failed_window_close_explains_cleanup_and_allows_retry(manager, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window, _ = manager
    close = window.controller.close
    failures, warnings = [1], []

    def flaky():
        if failures[0]:
            failures[0] -= 1
            raise OSError("Simulated cleanup failure")
        close()

    monkeypatch.setattr(window.controller, "close", flaky)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    assert window.close() is False
    assert window.isVisible() and not window._closing and window.timer.isActive()
    assert warnings == ["Simulated cleanup failure"]
    assert window.close() is True


def test_theme_picker_is_persistent_without_altering_grants(manager):
    from PySide6.QtWidgets import QApplication

    from udb.ui_theme import current_theme

    window, _ = manager
    chooser = window.theme_picker
    assert chooser.accessibleName() == "Chế độ giao diện UDB"
    assert chooser.count() == 3
    before = window.agent.projects()
    try:
        chooser.setCurrentIndex(chooser.findData("light"))
        QApplication.processEvents()
        assert current_theme().name == "light"
        assert window.controller.settings()["theme"] == "light"
        assert window.agent.projects() == before
        assert not (window.agent.state / "computer-access.dpapi").exists()
        chooser.setCurrentIndex(chooser.findData("dark"))
        QApplication.processEvents()
        assert current_theme().name == "dark"
        assert window.controller.settings()["theme"] == "dark"
        assert window.desktop_pause_button.isEnabled()
    finally:
        chooser.setCurrentIndex(chooser.findData("system"))
        QApplication.processEvents()


def test_compact_navigation_keeps_accessible_routes_and_local_pause(manager):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window, _ = manager
    assert window.sidebar.width() == 200
    window.sidebar_toggle.click()
    QApplication.processEvents()
    assert window.sidebar.width() == 72
    assert window.sidebar_toggle.accessibleName() == "Mở rộng thanh điều hướng"
    for index, button in enumerate(window.nav_buttons):
        assert button.text() == ""
        assert button.accessibleName() == window.nav_names[index]
        assert button.toolTip()
        assert button.maximumWidth() == 56
    QTest.mouseClick(window.nav_buttons[2], Qt.MouseButton.LeftButton)
    assert window.stack.currentIndex() == 2
    QTest.mouseClick(window.nav_buttons[5], Qt.MouseButton.LeftButton)
    assert window.stack.currentIndex() == 5
    assert window.desktop_pause_button.isEnabled()
    window.sidebar_toggle.click()
    QApplication.processEvents()
    assert window.sidebar.width() == 200
    assert window.nav_buttons[1].text().startswith("Quyền AI")
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_dashboard_displays_independent_connection_evidence(manager, monkeypatch):
    window, _ = manager
    assert window.local_health.accessibleName() == "Sẵn sàng"
    assert window.chatgpt_health.accessibleName() == "Chưa xác minh"
    assert window.chatgpt_health._status[1] == "neutral"

    status = window.controller.status()
    status.update(ready=True, tunnel_running=True, tunnel_wanted=True)
    monkeypatch.setattr(window.controller, "status", lambda: status)
    window._refresh_connection(set())
    assert window.tunnel_health._status == ("Sẵn sàng", "ready")
    assert window.chatgpt_health._status == ("Chưa xác minh", "neutral")
    assert "ChatGPT chưa được xác minh" in window.connection_hint.text()

    status["tunnel_running"] = False
    window._refresh_connection(set())
    assert window.tunnel_health._status == ("Chưa xác định", "neutral")
    assert window._connection_ready is False


def test_failed_health_refresh_clears_stale_green_status(manager, monkeypatch):
    window, _ = manager

    def fail(_agent):
        raise OSError("Synthetic local worker failed")

    monkeypatch.setattr("udb.host_client.status", fail)
    window.refresh()
    assert window.local_health._status == ("Chưa xác định", "neutral")
    assert window.desktop_pause_button.isEnabled()
    assert window.chatgpt_health._status == ("Chưa xác minh", "neutral")

    monkeypatch.setattr(
        window.controller,
        "status",
        lambda: (_ for _ in ()).throw(OSError("Synthetic connection failure")),
    )
    window.refresh()
    assert window.tunnel_health._status == ("Chưa xác định", "neutral")
    assert window._connection_ready is False
    assert "Không đọc được tunnel" in window.status_label.text()
    from udb.ui_theme import current_theme

    assert current_theme().muted in window.status_label.styleSheet()
    assert not window.connect_button.isEnabled()
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_security_inventory_discloses_unsandboxed_access(manager, monkeypatch):
    window, _ = manager
    baseline = window.agent.projects()

    monkeypatch.setattr("udb.computer_access.summary", lambda _agent: {"enabled": True})
    window._refresh_security()
    assert window.computer_grant_pill._status[0] == "Đã bật · không sandbox"
    assert window.computer_grant_pill._status[1] == "paused"
    assert "kể cả dữ liệu được chặn" in window.computer_grant_detail.text()
    assert "udb revoke-access" in window.computer_grant_detail.text()

    monkeypatch.setattr(
        "udb.computer_access.summary", lambda _agent: {"enabled": False}
    )
    window._refresh_security()
    assert window.computer_grant_pill._status[0] == "Không khả dụng"
    assert window.agent.projects() == baseline
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_security_inventory_fails_closed_without_changing_owner_permissions(
    manager, monkeypatch
):
    window, _ = manager

    def unavailable(_agent):
        raise OSError("Synthetic grant status unavailable")

    monkeypatch.setattr("udb.computer_access.summary", unavailable)
    window.refresh()
    assert window.computer_grant_pill._status == ("Chưa xác minh", "neutral")
    assert "không đọc được" in window.footer_status.text()
    assert window.desktop_pause_button.isEnabled()
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_activity_filters_update_without_touching_job_contents(manager):
    import json

    window, _ = manager
    with window.agent.connect() as db:
        for jid, status, project in (
            ("1" * 32, "running", "alpha"),
            ("2" * 32, "failed", "beta"),
            ("3" * 32, "completed", "gamma"),
        ):
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?)",
                (
                    jid,
                    status,
                    json.dumps(
                        {"project": project, "language": "python", "script": "SECRET"}
                    ),
                ),
            )
    window._refresh_jobs()
    assert window.jobs.topLevelItemCount() == 3
    window.job_group_filter.setCurrentText("Cần chú ý")
    assert window.jobs.topLevelItemCount() == 1
    assert window.jobs.topLevelItem(0).text(0) == "beta"
    window.job_search.setText("alpha")
    assert window.jobs.topLevelItemCount() == 0
    assert "0/3" in window.job_filter_feedback.text()
    window.job_search.setText("")
    assert window.jobs.topLevelItemCount() == 1
    window.job_group_filter.setCurrentText("Tất cả")
    assert window.jobs.topLevelItemCount() == 3
    assert window.agent.connect is not None
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_copy_safe_diagnostics_command_and_keyboard_shortcuts(manager):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window, _ = manager
    assert "Ctrl+3" not in window.controller.settings()
    window.navigate(4)
    button = next(
        child
        for child in window.stack.currentWidget().findChildren(
            __import__("udb.manager_widgets", fromlist=["MotionButton"]).MotionButton
        )
        if child.accessibleName() == "Sao chép lệnh udb doctor --json"
    )
    button.click()
    assert QApplication.clipboard().text() == "udb doctor --json"
    window.navigate(5)
    QTest.keyClick(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert window.stack.currentIndex() == 2
    assert window.job_search.accessibleName() == "Tìm công việc theo thông tin"


def test_activity_timeline_uses_only_presented_metadata(manager, monkeypatch):
    window, _ = manager
    events = [
        {
            "seq": 1,
            "kind": "result",
            "tool": "computer_files",
            "status": "PASS",
            "at": 0,
            "details": {
                "action": "read",
                "content": "PRIVATE SECRET FROM FILE",
            },
        }
    ]
    monkeypatch.setattr(window.activity_feed, "poll", lambda: events)
    window._refresh_activity()
    assert window.activity_timeline.topLevelItemCount() == 1
    row = window.activity_timeline.topLevelItem(0)
    displayed = " ".join(row.text(i) for i in range(3))
    assert "Tệp trên máy" in displayed
    assert "Đã trả kết quả" in displayed
    assert "PRIVATE SECRET" not in displayed
    window._refresh_activity()
    assert window.activity_timeline.topLevelItemCount() == 1
    events[:] = []
    window._refresh_activity()
    assert window.activity_timeline.topLevelItemCount() == 0


def test_persistent_app_header_tracks_navigation_not_remote_authorization(manager):
    from PySide6.QtWidgets import QApplication

    window, _ = manager
    window.navigate(1)
    assert window.header_title.text() == "Quyền AI"
    window.navigate(2)
    assert window.header_title.text() == "Tiến trình"
    assert "ChatGPT" in window.header_connection.toolTip()
    for width, height in ((940, 640), (1220, 820)):
        window.resize(width, height)
        QApplication.processEvents()
        assert window.header_title.isVisible()
        assert window.header_connection.isVisible()
        assert window.header_connection.text().startswith("●  Tunnel:")
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_audit_export_never_contains_raw_payload_or_ids(manager, monkeypatch, tmp_path):
    import json

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    window, _ = manager
    secret = "SENSITIVE_PAYLOAD"
    event = {
        "seq": 9,
        "kind": "result",
        "status": "PASS",
        "tool": "computer_files",
        "call_id": "SECRET_CALL_ID",
        "at": 0,
        "details": {"content": secret, "action": "read"},
    }
    monkeypatch.setattr(window.activity_feed, "poll", lambda: [event])
    target = tmp_path / "owner-export.json"
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a: (str(target), "JSON")
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    window.export_activity()
    data = target.read_text(encoding="utf-8")
    records = json.loads(data)
    assert len(records) == 1
    assert set(records[0]) == {"time", "tool", "state"}
    assert records[0]["tool"].startswith("Tệp trên máy")
    assert secret not in data
    assert "SECRET_CALL_ID" not in data
    # Exclusive creation must not overwrite an existing owner file.
    target.write_text("OWNER KEEP", encoding="utf-8")
    window.export_activity()
    assert target.read_text(encoding="utf-8") == "OWNER KEEP"


def test_mcp_activity_tab_stays_available_with_no_sandbox_jobs(manager, monkeypatch):
    window, _ = manager
    assert window.jobs.topLevelItemCount() == 0
    monkeypatch.setattr(
        window.activity_feed,
        "poll",
        lambda: [
            {
                "seq": 1,
                "kind": "result",
                "tool": "host_browser",
                "status": "PASS",
                "at": 0,
                "details": {},
            }
        ],
    )
    window._refresh_activity()
    window._refresh_jobs()
    assert window.job_tabs.isVisible() is False  # Jobs page isn't active.
    window.navigate(2)
    assert window.job_tabs.isVisible()
    assert window.activity_timeline.topLevelItemCount() == 1
    assert not window.jobs_empty.isVisible()


def test_security_posture_panel_is_owner_local_and_read_only(manager, monkeypatch):
    from udb.desktop_control import pause_local

    window, _ = manager
    window.navigate(3)
    assert window.security_approval_status._status == ("0 yêu cầu", "neutral")
    assert window.security_autonomy_status._status == ("Không bật", "neutral")
    assert window.security_pause_status._status == ("Chưa tạm dừng", "neutral")
    assert window.security_observed.text().startswith("Lần kiểm tra trên máy:")

    pause_local(window.agent, True)
    try:
        window._refresh_host()
        assert window.security_pause_status._status == ("Đang tạm dừng", "owner")
        assert "nền" in window.security_pause_status.toolTip()
        assert window.desktop_resume_button.isEnabled()
    finally:
        pause_local(window.agent, False)

    monkeypatch.setattr(
        window.agent, "source_autonomy_projects", lambda: {"synthetic-project"}
    )
    window._refresh_projects()
    assert window.security_autonomy_status._status == ("1 dự án", "paused")
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_security_posture_never_keeps_successful_state_after_read_failure(
    manager, monkeypatch
):
    window, _ = manager
    assert window.security_pause_status._status[0] == "Chưa tạm dừng"

    def unavailable(*_args, **_kwargs):
        raise OSError("Synthetic status failure")

    monkeypatch.setattr("udb.host_client.status", unavailable)
    monkeypatch.setattr(window.agent, "pending_local", unavailable)
    monkeypatch.setattr(window.agent, "source_autonomy_projects", unavailable)
    window.refresh()
    for pill in (
        window.security_pause_status,
        window.security_approval_status,
        window.security_autonomy_status,
    ):
        assert pill._status == ("Chưa xác minh", "neutral")
    assert window.desktop_pause_button.isEnabled()
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_global_privilege_indicator_warns_about_unsandboxed_scope(manager, monkeypatch):
    from PySide6.QtWidgets import QApplication

    window, _ = manager
    monkeypatch.setattr("udb.computer_access.summary", lambda _agent: {"enabled": True})
    window._refresh_security()
    assert window.header_privilege._status == ("Windows: không sandbox", "paused")
    assert "không áp dụng" in window.header_privilege.toolTip()
    window.navigate(0)
    QApplication.processEvents()
    assert window.header_privilege.isVisible()
    window.navigate(5)
    QApplication.processEvents()
    assert window.header_privilege.isVisible()
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_global_privilege_indicator_fails_closed_and_distinguishes_scopes(
    manager, monkeypatch
):
    window, _ = manager
    monkeypatch.setattr(
        "udb.computer_access.summary", lambda _agent: {"enabled": False}
    )
    window._refresh_security()
    assert window.header_privilege._status == ("Quyền máy: không bật", "neutral")
    assert "Sandbox" in window.header_privilege.toolTip()

    def unreadable(_agent):
        raise OSError("PRIVATE_UNTRUSTED_PATH")

    monkeypatch.setattr("udb.computer_access.summary", unreadable)
    window.refresh()
    assert window.header_privilege._status == ("Quyền máy: chưa xác minh", "neutral")
    assert "PRIVATE_UNTRUSTED_PATH" not in window.header_privilege.toolTip()
    assert window.desktop_pause_button.isEnabled()
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_connection_onboarding_only_uses_observed_local_health(manager, monkeypatch):
    window, host = manager
    assert window.setup_agent_health._status == ("Sẵn sàng", "ready")
    assert window.setup_chatgpt_health._status == ("Chưa xác minh", "neutral")

    host["worker_ready"] = False
    window._refresh_host()
    assert window.setup_agent_health._status == ("Chưa sẵn sàng", "paused")
    host["worker_ready"] = True
    window._refresh_host()
    assert window.setup_agent_health._status == ("Sẵn sàng", "ready")

    status = dict(window.controller.status())
    status.update(ready=True, tunnel_running=True, connecting=False, tunnel_wanted=True)
    monkeypatch.setattr(window.controller, "status", lambda: status)
    window._refresh_connection(set())
    assert window.setup_tunnel_health._status == ("Sẵn sàng", "ready")
    assert window.setup_chatgpt_health._status == ("Chưa xác minh", "neutral")
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_onboarding_fail_closed_if_host_or_tunnel_status_unreadable(
    manager, monkeypatch
):
    window, _ = manager
    status = dict(window.controller.status())
    status.update(ready=True, tunnel_running=True, connecting=False, tunnel_wanted=True)
    monkeypatch.setattr(window.controller, "status", lambda: status)
    window._refresh_connection(set())
    assert window.setup_tunnel_health._status == ("Sẵn sàng", "ready")

    def unavailable(*_args, **_kwargs):
        raise OSError("untrusted status error secret")

    monkeypatch.setattr("udb.host_client.status", unavailable)
    monkeypatch.setattr(window.controller, "status", unavailable)
    window.refresh()
    assert window.setup_agent_health._status == ("Chưa xác định", "neutral")
    assert window.setup_tunnel_health._status == ("Chưa xác định", "neutral")
    assert window.setup_chatgpt_health._status == ("Chưa xác minh", "neutral")
    assert window.desktop_pause_button.isEnabled()
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_reduced_motion_is_persistent_and_does_not_change_ai_permissions(manager):
    from PySide6.QtWidgets import QApplication

    window, _ = manager
    app = QApplication.instance()
    before = window.agent.projects()
    assert not window.reduce_motion.isChecked()
    window.reduce_motion.setChecked(True)
    assert app.property("motion") is False
    assert window.controller.settings()["motion"] is False
    assert window.agent.projects() == before
    assert window.desktop_pause_button.isEnabled()
    window.reduce_motion.setChecked(False)
    assert app.property("motion") is True
    assert window.controller.settings()["motion"] is True
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_reduced_motion_save_error_restores_previous_state(manager, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    window, _ = manager
    app = QApplication.instance()
    previous = app.property("motion")
    warnings = []
    monkeypatch.setattr(
        window.controller, "save_settings", lambda *_: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window.reduce_motion.setChecked(True)
    assert not window.reduce_motion.isChecked()
    assert app.property("motion") == previous
    assert len(warnings) == 1
    assert "trước đó" in warnings[0]
    assert not (window.agent.state / "computer-access.dpapi").exists()


def test_failed_pending_refresh_hides_stale_approvals_and_recovers(
    manager, monkeypatch
):
    from PySide6.QtWidgets import QTreeWidgetItem

    window, _ = manager
    request = QTreeWidgetItem(["Stale project", "Sửa file", "100 giây"])
    window.requests.addTopLevelItem(request)
    window.pending_rows = {"old": {"id": "old"}}
    window.pending_title.setText("Old approval")
    window.pending_code.setPlainText("Old diff or script")
    window.requests.setVisible(True)
    window.pending_code.setVisible(True)
    window.approval_review.setEnabled(True)
    window.review_button.setEnabled(True)
    original = window._refresh_requests

    def unavailable():
        raise OSError("Simulated unavailable pending request database")

    monkeypatch.setattr(window, "_refresh_requests", unavailable)
    window.refresh()
    assert window.pending_rows == {}
    assert window.requests.topLevelItemCount() == 0
    assert window.pending_code.toPlainText() == ""
    assert "Chưa xác minh" in window.pending_title.text()
    assert not window.approval_review.isEnabled()
    assert not window.review_button.isEnabled()
    assert not window.media_auto.isEnabled()
    assert "Chưa xác minh" in window.nav_buttons[1].accessibleName()

    monkeypatch.setattr(window, "_refresh_requests", original)
    window.refresh()
    assert window.media_auto.isEnabled()
    assert window.requests.topLevelItemCount() == 0


def test_failed_media_autonomy_read_does_not_leave_checkbox_inert(manager, monkeypatch):
    window, _ = manager
    original = window.agent.media_autonomy

    def unavailable():
        raise OSError("Simulated temporary settings read failure")

    monkeypatch.setattr(window.agent, "media_autonomy", unavailable)
    window.refresh()
    assert not window.media_auto.signalsBlocked()
    assert not window.media_auto.isEnabled()
    monkeypatch.setattr(window.agent, "media_autonomy", original)
    window.refresh()
    assert window.media_auto.isEnabled()
    assert not window.media_auto.signalsBlocked()


@pytest.mark.parametrize(
    "method",
    ["sandbox_authorization", "source_autonomy_authorization"],
)
def test_failed_selected_project_permission_read_disables_grant_toggles(
    manager, monkeypatch, method
):
    window, _ = manager
    root = window.agent.home / "projects" / "owned-permission-project"
    root.mkdir(parents=True)
    window.agent.register_local("owner-test", str(root), True)
    window._refresh_projects()
    assert window.selected_project

    original = getattr(window.agent, method)

    def unavailable(*_args, **_kwargs):
        raise OSError("Cannot read grants")

    monkeypatch.setattr(window.agent, method, unavailable)
    window.project_selected()
    assert not window.sandbox_auto.isEnabled()
    assert not window.source_auto.isEnabled()
    assert not window.sandbox_auto.signalsBlocked()
    assert not window.source_auto.signalsBlocked()
    assert "Không xác minh được" in window.project_access.text()

    monkeypatch.setattr(window.agent, method, original)
    window.project_selected()
    assert window.sandbox_auto.isEnabled()
    assert window.source_auto.isEnabled()
    assert not window.sandbox_auto.signalsBlocked()
    assert not window.source_auto.signalsBlocked()


def test_corrupted_common_room_database_shows_local_warning(manager, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window, _ = manager
    root = window.agent.home / "corrupted-project"
    room = root / "chatgpt-workspace"
    room.mkdir(parents=True)
    database = room / "workspace.sqlite3"
    database.write_bytes(b"not a valid SQLite database")
    window.selected_project = {"id": "owned-demo"}
    monkeypatch.setattr(window.agent, "project", lambda _id: (None, root))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    window.open_common_room()

    assert len(warnings) == 1
    assert database.read_bytes() == b"not a valid SQLite database"
    assert list(room.glob("workspace*.sqlite3")) == [database]
