"""Presentation-only theme tokens for the native UDB Qt manager.

No access policy, MCP control or credential state is derived from UI colors.
Qt is imported only when applying a theme, allowing pure token validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    panel: str
    raised: str
    field: str
    line: str
    text: str
    muted: str
    accent: str
    accent_text: str
    hover: str
    selected: str
    focus: str
    warning: str
    danger: str
    success_bg: str
    warning_bg: str
    owner_bg: str
    hero: str
    hero_line: str
    disabled_bg: str
    disabled_text: str


DARK = Theme(
    name="dark",
    bg="#0B1220",
    panel="#111C30",
    raised="#1B2A42",
    field="#0F192B",
    line="#31415A",
    text="#F2F6FC",
    muted="#B7C4D9",
    accent="#86B5FF",
    accent_text="#0B1D3B",
    hover="#253958",
    selected="#294466",
    focus="#86B5FF",
    warning="#F5C874",
    danger="#FFB1B1",
    success_bg="#1B3B33",
    warning_bg="#3B3020",
    owner_bg="#193249",
    hero="#122743",
    hero_line="#28476A",
    disabled_bg="#202D40",
    disabled_text="#8190A5",
)

LIGHT = Theme(
    name="light",
    bg="#F5F7FB",
    panel="#FFFFFF",
    raised="#EAF0F8",
    field="#FFFFFF",
    line="#CCD6E5",
    text="#17233A",
    muted="#50627D",
    accent="#175CD3",
    accent_text="#FFFFFF",
    hover="#DEEAFB",
    selected="#DFEAFB",
    focus="#175CD3",
    warning="#855100",
    danger="#A6273E",
    success_bg="#E7F6EE",
    warning_bg="#FFF1DA",
    owner_bg="#E6F3FF",
    hero="#E8F1FF",
    hero_line="#CADCF4",
    disabled_bg="#E9EEF6",
    disabled_text="#697891",
)


def normalize_preference(preference: object) -> str:
    """Unknown or corrupted local settings cannot inject arbitrary CSS."""
    return preference if type(preference) is str and preference in {
        "system", "light", "dark"
    } else "system"


def pick_theme(preference: object, system_dark: bool = False) -> Theme:
    choice = normalize_preference(preference)
    return DARK if choice == "dark" or (choice == "system" and system_dark) else LIGHT


def _linear(rgb: int) -> float:
    c = rgb / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG relative luminance ratio, used as a regression check."""
    def lum(hex_color: str) -> float:
        channels = [_linear(int(hex_color[i:i + 2], 16)) for i in (1, 3, 5)]
        return sum(a * b for a, b in zip(channels, (0.2126, 0.7152, 0.0722)))

    top, bottom = sorted((lum(foreground), lum(background)), reverse=True)
    return (top + 0.05) / (bottom + 0.05)


_QSS = Template("""
QWidget { color:$text; font-family:"Segoe UI"; font-size:14px; }
QMainWindow, QDialog { background:$bg; }
QWidget#Root, QWidget#Page, QWidget#PageHeader, QStackedWidget { background:$bg; }
QFrame#Sidebar { background:$panel; border-right:1px solid $line; }
QFrame#Panel { background:$panel; border:1px solid $line; border-radius:14px; }
QFrame#Hero { background:$hero; border:1px solid $hero_line; border-radius:14px; }
QFrame#Footer { background:$bg; border-top:1px solid $line; }
QLabel { background:transparent; border:0; }
QLabel#H1 { font-size:26px; font-weight:600; }
QLabel#H2 { font-size:18px; font-weight:600; }
QLabel#EmptyTitle { font-size:20px; font-weight:600; }
QLabel#EmptyIcon { color:$accent; font-size:32px; }
QLabel#Subtitle, QLabel#Muted { color:$muted; font-size:14px; }
QLabel#Brand { font-size:27px; font-weight:600; }
QLabel#Eyebrow { color:$muted; font-size:12px; letter-spacing:1px; }
QLabel#Fine { color:$muted; font-size:13px; }
QLabel#Warning { color:$warning; font-size:12px; }
QLabel#Badge { color:$accent; background:$raised; border-radius:8px; padding:3px 8px; }
QLineEdit, QPlainTextEdit, QListWidget, QTreeWidget, QComboBox {
  background:$field; color:$text; border:1px solid $line; border-radius:8px;
  selection-background-color:$selected; selection-color:$text;
}
QLineEdit, QComboBox { padding:9px 11px; min-height:20px; }
QLineEdit#ProjectPath { background:transparent; border:0; padding:0; color:$muted; font-size:12px; }
QLineEdit:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus,
QComboBox:focus, QCheckBox:focus { border:2px solid $focus; }
QComboBox::drop-down { border:0; width:24px; }
QComboBox QAbstractItemView { background:$panel; color:$text; selection-background-color:$selected; }
QPlainTextEdit { padding:12px; font-family:"Cascadia Code",Consolas,monospace; font-size:13px; }
QTreeWidget { border:0; outline:0; background:transparent; alternate-background-color:$panel; }
QTreeWidget::item { padding:10px 8px; border-bottom:1px solid $line; }
QTreeWidget::item:selected, QListWidget::item:selected { background:$selected; color:$text; }
QTreeWidget::item:hover { background:$hover; }
QHeaderView::section { background:$bg; color:$muted; border:0; border-bottom:1px solid $line; padding:10px 7px; font-size:12px; }
QListWidget::item { padding:10px; }
QScrollArea { background:transparent; border:0; }
QScrollBar:vertical { background:$bg; width:10px; margin:0; }
QScrollBar::handle:vertical { background:$line; min-height:28px; border-radius:5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:$bg; height:10px; margin:0; }
QScrollBar::handle:horizontal { background:$line; min-width:28px; border-radius:5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QTabWidget::pane { border:1px solid $line; border-radius:8px; }
QTabBar::tab { background:$panel; color:$muted; padding:10px 16px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:$text; border-bottom:2px solid $accent; }
QCheckBox { spacing:10px; padding:7px 0; }
QCheckBox::indicator { width:17px; height:17px; background:$field; border:1px solid $line; border-radius:4px; }
QCheckBox::indicator:checked { background:$accent; border:4px solid $selected; }
QToolButton { color:$muted; background:transparent; border:0; padding:8px 0; text-align:left; }
QToolButton:hover { color:$text; }
QToolButton:focus { border:2px solid $focus; border-radius:6px; }
QToolTip { background:$raised; color:$text; border:1px solid $line; padding:7px; }
QMessageBox { background:$bg; }
QMessageBox QPushButton, QInputDialog QPushButton {
 background:$raised; color:$text; border:1px solid $line;
 border-radius:7px; padding:8px 18px; min-width:75px;
}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover { background:$hover; }
QMessageBox QPushButton:focus, QInputDialog QPushButton:focus { border:2px solid $focus; }
QSplitter::handle { background:transparent; width:1px; }
""")


def stylesheet(theme: Theme) -> str:
    return _QSS.substitute(vars(theme))


def current_theme(app=None) -> Theme:
    if app is None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
    return LIGHT if app and app.property("udb_theme") == "light" else DARK


def apply_theme(app, preference: object = "system") -> Theme:
    """Apply presentation preferences only; this never touches UDB grants."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QGuiApplication, QPalette

    dark_system = False
    try:
        dark_system = (
            QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
    except (AttributeError, RuntimeError):
        pass
    theme = pick_theme(preference, dark_system)
    app.setProperty("udb_theme_preference", normalize_preference(preference))
    app.setProperty("udb_theme", theme.name)
    p = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, theme.bg),
        (QPalette.ColorRole.Base, theme.field),
        (QPalette.ColorRole.AlternateBase, theme.panel),
        (QPalette.ColorRole.Text, theme.text),
        (QPalette.ColorRole.WindowText, theme.text),
        (QPalette.ColorRole.Button, theme.panel),
        (QPalette.ColorRole.ButtonText, theme.text),
        (QPalette.ColorRole.Highlight, theme.selected),
        (QPalette.ColorRole.HighlightedText, theme.text),
        (QPalette.ColorRole.PlaceholderText, theme.muted),
    ):
        p.setColor(role, QColor(color))
    app.setPalette(p)
    app.setStyleSheet(stylesheet(theme))
    # Custom painted buttons, badges and status components use the same palette.
    for widget in app.allWidgets():
        refresh = getattr(widget, "refresh_theme", None)
        if callable(refresh):
            refresh()
        else:
            widget.update()
    return theme
