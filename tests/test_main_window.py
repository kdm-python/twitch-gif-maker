import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QSplitter

from gifmaker.gui.main_window import MainWindow
from gifmaker.gui.shortcut_manager import ShortcutManager
from gifmaker.models.render_settings import RenderSettings, format_ms, parse_time_input


def test_main_window_uses_splitter_for_resizable_preview_sections() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    central_layout = window.centralWidget().layout()
    resizable_container = central_layout.itemAt(1).widget()

    assert isinstance(resizable_container, QSplitter)
    assert resizable_container.count() == 2
    assert isinstance(resizable_container.widget(0), QGroupBox)
    assert isinstance(resizable_container.widget(1), QGroupBox)

    app.quit()


def test_seek_slider_moves_media_player_to_frame_position_in_milliseconds() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_fps = 2.0
    window.total_frames = 10
    window.seek_slider.setRange(0, 9)
    window.seek_slider.set_total_frames(10)
    window.seek_slider.setValue(4)

    with patch.object(window.media_player, "setPosition") as set_position:
        window.on_seek_slider_pressed()
        window.on_seek_slider_moved(4)
        window.on_seek_slider_released()

    assert set_position.call_args_list[-1].args[0] == 2000

    app.quit()


def test_export_format_combo_has_gif_and_webp_options() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    combo = window.export_format_combo
    assert isinstance(combo, QComboBox)
    assert combo.count() == 2
    assert combo.itemText(0) == "GIF"
    assert combo.itemText(1) == "WebP"
    assert combo.currentText() == "GIF"

    app.quit()


def test_reset_preview_crop_clears_box_and_window_state() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._current_crop = (10, 20, 30, 40)
    window.gif_preview_label._crop_label_rect = (
        window.gif_preview_label._crop_label_rect
        or window.gif_preview_label._crop_label_rect
    )
    window.gif_preview_label._crop_label_rect = (
        window.gif_preview_label._crop_label_rect
    )
    window.gif_preview_label._crop_mode = "moving"

    window.reset_preview_crop()

    assert window._current_crop is None
    assert window.gif_preview_label._crop_label_rect is None
    assert window.gif_preview_label._crop_mode == "idle"

    app.quit()


def test_shortcut_manager_registers_expected_key_bindings() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    manager = ShortcutManager(window)

    assert manager.shortcuts["left"].key() == Qt.Key.Key_Left
    assert manager.shortcuts["right"].key() == Qt.Key.Key_Right
    assert manager.shortcuts["play_pause"].key() == Qt.Key.Key_Space
    assert manager.shortcuts["toggle_mute"].key() == Qt.Key.Key_M
    assert manager.shortcuts["start_left"].key() == Qt.Key.Key_Z
    assert manager.shortcuts["start_right"].key() == Qt.Key.Key_X
    assert manager.shortcuts["end_left"].key() == Qt.Key.Key_B
    assert manager.shortcuts["end_right"].key() == Qt.Key.Key_N

    app.quit()


def test_render_settings_helpers_parse_and_format_time() -> None:
    assert parse_time_input("1:02:03") == 62.03
    assert parse_time_input("00:05:00") == 5.0
    assert parse_time_input("00:00:05") == 0.05
    assert format_ms(12345) == "00:12:34"

    settings = RenderSettings(
        start_seconds=1.5,
        end_seconds=3.0,
        fps=24,
        width=320,
        playback_speed=1.5,
        crop=(10, 20, 30, 40),
    )
    assert settings.start_seconds == 1.5
    assert settings.end_seconds == 3.0
    assert settings.width == 320
    assert settings.playback_speed == 1.5
    assert settings.effective_fps == 36


def test_main_window_has_playback_speed_control_and_not_fps_input() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert hasattr(window, "playback_speed_combo")
    assert not hasattr(window, "export_fps_input")

    app.quit()
