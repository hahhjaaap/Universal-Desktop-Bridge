"""Regression tests for UDB GUI presentation; no remote grants or credentials."""

from __future__ import annotations

from types import SimpleNamespace

from udb.desktop import DesktopController
from udb.ui_theme import (
    DARK,
    LIGHT,
    contrast_ratio,
    normalize_preference,
    pick_theme,
    stylesheet,
)


def test_theme_preferences_are_strictly_allowlisted():
    assert normalize_preference("dark") == "dark"
    assert normalize_preference("light") == "light"
    assert normalize_preference("system") == "system"
    for bad in (None, "<img onerror=1>", {}, 0, b"dark", "night", "light;*"):
        assert normalize_preference(bad) == "system"
        assert pick_theme(bad, system_dark=False) == LIGHT
    assert pick_theme("system", system_dark=True) == DARK
    assert pick_theme("dark", system_dark=False) == DARK


def test_text_and_semantic_indicators_meet_minimum_contrast():
    for theme in (DARK, LIGHT):
        for foreground, background in (
            (theme.text, theme.bg),
            (theme.text, theme.panel),
            (theme.muted, theme.bg),
            (theme.muted, theme.panel),
            (theme.accent, theme.panel),
            (theme.accent, theme.success_bg),
            (theme.warning, theme.warning_bg),
            (theme.accent_text, theme.accent),
        ):
            assert contrast_ratio(foreground, background) >= 4.5, (
                theme.name,
                foreground,
                background,
            )


def test_stylesheets_use_only_token_values():
    assert "QComboBox" in stylesheet(LIGHT)
    assert LIGHT.accent in stylesheet(LIGHT)
    assert DARK.accent in stylesheet(DARK)
    assert "$" not in stylesheet(DARK)
    assert "onerror" not in stylesheet(LIGHT)


def test_setting_persistence_rejects_untrusted_theme_values(tmp_path):
    controller = SimpleNamespace(agent=SimpleNamespace(state=tmp_path))
    DesktopController.save_settings(
        controller,
        {"motion": True, "autoconnect": False, "theme": "light", "token": "SECRET"},
    )
    assert DesktopController.settings(controller) == {
        "motion": True,
        "autoconnect": False,
        "theme": "light",
    }
    DesktopController.save_settings(
        controller, {"motion": False, "autoconnect": True, "theme": "bad-css"}
    )
    assert DesktopController.settings(controller)["theme"] == "system"
    assert "SECRET" not in (tmp_path / "gui.json").read_text(encoding="utf-8")


def test_live_qt_theme_switch_updates_palette_and_badges():
    import pytest

    pytest.importorskip("PySide6")
    from udb.manager import make_app
    from udb.manager_widgets import MotionButton, StatusPill
    from udb.ui_theme import apply_theme, current_theme

    app = make_app()
    badge = StatusPill("Đang chờ", "paused")
    button = MotionButton("Tạm dừng", "pause", "danger")
    try:
        for choice in ("light", "dark"):
            theme = apply_theme(app, choice)
            assert current_theme().name == choice
            assert theme.name == choice
            assert theme.warning.lower() in badge.styleSheet().lower()
            assert badge.accessibleName() == "Đang chờ"
            assert button.accessibleName() == "Tạm dừng"
            assert theme.panel in app.styleSheet()
    finally:
        badge.close()
        button.close()
        apply_theme(app, "dark")


def test_system_color_event_never_overrides_forced_theme():
    import pytest

    pytest.importorskip("PySide6")
    from udb.manager import make_app
    from udb.ui_theme import apply_theme, current_theme

    app = make_app()
    apply_theme(app, "dark")
    callback = getattr(app, "_udb_color_scheme_callback", None)
    if callback is not None:
        callback()
    assert current_theme().name == "dark"
    apply_theme(app, "system")
    if callback is not None:
        callback()
    assert app.property("udb_theme_preference") == "system"
    apply_theme(app, "dark")
