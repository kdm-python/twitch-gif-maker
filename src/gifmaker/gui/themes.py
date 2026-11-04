"""Application themes and the small API used to apply them.

To add a theme, define a :class:`Theme` below and add it to ``THEMES``.  The
palette supplies Qt's semantic colours (including custom widgets using
``palette(highlight)``); the stylesheet is for the higher-level visual finish.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    """A named Qt palette plus optional application-wide stylesheet."""

    label: str
    palette: QPalette | None
    stylesheet: str = ""


def _dark_palette() -> QPalette:
    """Build a cool, high-contrast palette for the dark interface."""
    palette = QPalette()
    colours = {
        QPalette.ColorRole.Window: "#17191f",
        QPalette.ColorRole.WindowText: "#e8eaf0",
        QPalette.ColorRole.Base: "#101217",
        QPalette.ColorRole.AlternateBase: "#20242d",
        QPalette.ColorRole.ToolTipBase: "#20242d",
        QPalette.ColorRole.ToolTipText: "#f5f7fb",
        QPalette.ColorRole.Text: "#e8eaf0",
        QPalette.ColorRole.Button: "#252a34",
        QPalette.ColorRole.ButtonText: "#e8eaf0",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: "#6d8cff",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#8ca4ff",
        QPalette.ColorRole.Mid: "#3b4352",
        QPalette.ColorRole.PlaceholderText: "#9098a8",
    }
    for role, colour in colours.items():
        palette.setColor(QPalette.ColorGroup.All, role, QColor(colour))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#737b89")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#737b89")
    )
    return palette


DARK_STYLESHEET = """
QMainWindow, QDialog {
    background: #17191f;
}
QGroupBox {
    border: 1px solid #343b49;
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #c8d2ff;
}
QPushButton, QComboBox, QSpinBox {
    background: #252a34;
    border: 1px solid #3b4352;
    border-radius: 6px;
    min-height: 24px;
    padding: 2px 8px;
}
QPushButton:hover, QComboBox:hover, QSpinBox:hover {
    border-color: #6d8cff;
    background: #2c3340;
}
QPushButton:pressed {
    background: #343d4d;
}
QPushButton:disabled, QComboBox:disabled, QSpinBox:disabled {
    background: #1c2028;
    border-color: #2b303a;
}
QComboBox::drop-down {
    border: 0;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #20242d;
    border: 1px solid #3b4352;
    selection-background-color: #526cc9;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #343b49;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #6d8cff;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #c8d2ff;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #596274;
    border-radius: 4px;
    background: #20242d;
}
QCheckBox::indicator:checked {
    background: #6d8cff;
    border-color: #8ca4ff;
}
QMenuBar {
    background: #20242d;
    border-bottom: 1px solid #343b49;
}
QMenuBar::item {
    padding: 6px 10px;
    background: transparent;
}
QMenuBar::item:selected, QMenu::item:selected {
    background: #39466e;
}
QMenu {
    background: #20242d;
    border: 1px solid #3b4352;
    padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 12px;
    border-radius: 4px;
}
QToolTip {
    color: #f5f7fb;
    background: #20242d;
    border: 1px solid #596274;
}
"""


THEMES: dict[str, Theme] = {
    # The existing, native-looking grey interface intentionally has no custom
    # stylesheet.  Keeping it explicit makes it a proper selectable theme.
    "light": Theme("Light", None),
    "dark": Theme("Dark", _dark_palette(), DARK_STYLESHEET),
}


def apply_theme(application: QApplication, theme_name: str) -> str:
    """Apply ``theme_name`` and return it; unknown names fall back to light."""
    name = theme_name if theme_name in THEMES else "light"
    theme = THEMES[name]
    application.setStyleSheet("")
    # Restore the active Qt style's standard palette for the original native
    # light-grey look, rather than retaining dark colours after a switch.
    application.setPalette(theme.palette or application.style().standardPalette())
    application.setStyleSheet(theme.stylesheet)
    return name
