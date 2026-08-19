"""Centralized keyboard shortcut bindings for the GIF Maker window."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

if TYPE_CHECKING:
    from gifmaker.gui.main_window import MainWindow


class ShortcutManager:
    """Register and expose the main window's keyboard shortcuts."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self.shortcuts: dict[str, QShortcut] = {}

        # Video player
        self._register("left", Qt.Key.Key_Left, window._leftArrowPressed)
        self._register("right", Qt.Key.Key_Right, window._rightArrowPressed)
        self._register("play_pause", Qt.Key.Key_Space, window.toggle_preview_playback)
        self._register("toggle_mute", Qt.Key.Key_M, window.toggle_mute)
        # (TODO) Speed up and speed down video keys

        # Start and end frame controls
        self._register("start_set", Qt.Key.Key_C, window._startSetPressed)
        self._register("start_left", Qt.Key.Key_Z, window._startSliderLeftPressed)
        self._register("start_right", Qt.Key.Key_X, window._startSliderRightPressed)
        self._register("end_set", Qt.Key.Key_V, window._endSetPressed)
        self._register("end_left", Qt.Key.Key_B, window._endSliderLeftPressed)
        self._register("end_right", Qt.Key.Key_N, window._endSliderRightPressed)

        # GIF preview controls

    def _register(
        self,
        name: str,
        key: Qt.Key,
        callback: Callable[[], None],
    ) -> QShortcut:
        shortcut = QShortcut(QKeySequence(key), self.window)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(callback)
        self.shortcuts[name] = shortcut
        return shortcut
