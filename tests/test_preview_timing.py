import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow
from gifmaker.gui.animation_preview_player import AnimationPreviewPlayer
from gifmaker.gui.views.crop_overlay_label import CropOverlayLabel


def test_cached_preview_follows_surface_resize_while_paused() -> None:
    app = QApplication.instance() or QApplication([])
    label = CropOverlayLabel()
    label.setAlignment(Qt.AlignCenter)
    original = QPixmap(800, 400)
    original.fill()
    window = SimpleNamespace(_preview_frame_cache=[original], _preview_frame_index=0)
    player = AnimationPreviewPlayer(window)
    player.bind(label)
    label.resized.connect(player.update_scaled_size)
    label.resize(200, 200)
    label.show()
    app.processEvents()
    assert label.pixmap().width() == 200
    assert label.pixmap().height() == 100
    label.resize(600, 400)
    app.processEvents()
    assert label.pixmap().width() == 600
    assert label.pixmap().height() == 300
    label.resize(100, 100)
    app.processEvents()
    assert label.pixmap().width() == 100
    assert label.pixmap().height() == 50
    assert window._preview_frame_cache[0].width() == 800
    label.close()


def test_late_timer_skips_frames_and_keeps_timeline() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    controller = window.preview_controller
    window._preview_frame_cache = [QPixmap(2, 2) for _ in range(4)]
    window._preview_frame_durations = [25] * 4
    window._preview_frame_timer = QTimer(window)
    window._preview_frame_timer.setSingleShot(True)
    window._preview_frame_timer.timeout.connect(window._on_cached_frame_timeout)
    controller.player._deadline = 10.025
    with patch("gifmaker.gui.animation_preview_player.time.monotonic", return_value=10.080):
        controller.on_cached_frame_timeout()
    assert window._preview_frame_index == 3
    assert abs(controller.player._deadline - 10.100) < 0.001
    window.close()
    app.processEvents()
