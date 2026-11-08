import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow


def test_late_timer_skips_frames_and_keeps_timeline() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    controller = window.preview_controller
    window._preview_frame_cache = [QPixmap(2, 2) for _ in range(4)]
    window._preview_frame_durations = [25] * 4
    window._preview_frame_timer = QTimer(window)
    window._preview_frame_timer.setSingleShot(True)
    window._preview_frame_timer.timeout.connect(window._on_cached_frame_timeout)
    controller._deadline = 10.025
    with patch("gifmaker.gui.preview_controller.time.monotonic", return_value=10.080):
        controller.on_cached_frame_timeout()
    assert window._preview_frame_index == 3
    assert abs(controller._deadline - 10.100) < 0.001
    window.close()
    app.processEvents()
