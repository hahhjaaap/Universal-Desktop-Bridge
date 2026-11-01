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
