"""
Centralized keyboard shortcut bindings for the GIF Maker window.

Keyboard mappings:

- Video player
    - Left arrow: Move video playback backward by 1 frame
    - Right arrow: Move video playback forward by 1 frame
    - Space: Toggle video playback
    - m: Toggle mute
    - Comma: Decrease playback speed
    - Period: Increase playback speed
- Start and end frame controls
    - c: Set the start frame to the current video frame
    - z: Move the start frame backward by 1 frame
    - x: Move the start frame forward by 1 frame
    - v: Set the end frame to the current video frame
    - b: Move the end frame backward by 1 frame
    - n: Move the end frame forward by 1 frame
- File management
    - Shift+O: Open a video file
    - Shift+E: Export the GIF
- GIF preview controls
    - g: Generate a GIF preview
    - a: Apply the current crop to the GIF preview
    - r: Reset the crop on the GIF preview


"""

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
        self._register("left", Qt.Key.Key_Left, window._shortcut_left)
        self._register("right", Qt.Key.Key_Right, window._shortcut_right)
        self._register("play_pause", Qt.Key.Key_Space, window._shortcut_play_pause)
        self._register("toggle_mute", Qt.Key.Key_M, window._shortcut_toggle_mute)
        self._register("speed_down", Qt.Key.Key_Comma, window._shortcut_speed_down)
        self._register("speed_up", Qt.Key.Key_Period, window._shortcut_speed_up)

        # Start and end frame controls
        self._register("start_set", Qt.Key.Key_C, window._shortcut_start_set)
        self._register("start_left", Qt.Key.Key_Z, window._shortcut_start_left)
        self._register("start_right", Qt.Key.Key_X, window._shortcut_start_right)
        self._register("end_set", Qt.Key.Key_V, window._shortcut_end_set)
        self._register("end_left", Qt.Key.Key_B, window._shortcut_end_left)
        self._register("end_right", Qt.Key.Key_N, window._shortcut_end_right)

        # File management
        self._register(
            "open_file",
            QKeySequence(Qt.CTRL | Qt.Key.Key_O),
            window._shortcut_open_file,
        )
        self._register(
            "export_file",
            QKeySequence(Qt.CTRL | Qt.Key.Key_E),
            window._shortcut_export_file,
        )

        # GIF preview controls
        self._register("apply_crop", Qt.Key.Key_A, window._shortcut_apply_crop)
        self._register("reset_crop", Qt.Key.Key_R, window._shortcut_reset_crop)

    def _register(
        self,
        name: str,
        key: QKeySequence | Qt.Key,
        callback: Callable[[], None],
    ) -> QShortcut:
        sequence = QKeySequence(key)
        shortcut = QShortcut(sequence, self.window)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(callback)
        self.shortcuts[name] = shortcut
        return shortcut
