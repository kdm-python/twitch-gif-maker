import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
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


def test_main_window_allows_tighter_horizontal_minimum() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.minimumWidth() <= 760
    assert window.minimumHeight() >= 500

    app.quit()


def test_main_window_gives_more_space_to_preview_panels() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.preview_panel.video_widget.minimumHeight() <= 140
    assert window.gif_preview_label.minimumHeight() <= 180

    sizes = window.preview_splitter.sizes()
    assert sizes[0] >= 200
    assert sizes[1] >= 180

    app.quit()


def test_export_controls_panel_compacts_action_buttons_below_inputs() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.export_controls_panel

    assert hasattr(panel, "primary_row")
    assert hasattr(panel, "button_row")
    assert panel.primary_row is not None
    assert panel.button_row is not None

    window.show()
    window.resize(700, 120)
    app.processEvents()
    assert panel._compact_mode is True

    window.resize(1100, 120)
    app.processEvents()
    assert panel._compact_mode is False

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

    assert manager.shortcuts["left"].key() == QKeySequence(Qt.Key.Key_Left)
    assert manager.shortcuts["right"].key() == QKeySequence(Qt.Key.Key_Right)
    assert manager.shortcuts["play_pause"].key() == QKeySequence(Qt.Key.Key_Space)
    assert manager.shortcuts["toggle_mute"].key() == QKeySequence(Qt.Key.Key_M)
    assert manager.shortcuts["speed_down"].key() == QKeySequence(Qt.Key.Key_Comma)
    assert manager.shortcuts["speed_up"].key() == QKeySequence(Qt.Key.Key_Period)
    assert manager.shortcuts["start_set"].key() == QKeySequence(Qt.Key.Key_C)
    assert manager.shortcuts["start_left"].key() == QKeySequence(Qt.Key.Key_Z)
    assert manager.shortcuts["start_right"].key() == QKeySequence(Qt.Key.Key_X)
    assert manager.shortcuts["end_set"].key() == QKeySequence(Qt.Key.Key_V)
    assert manager.shortcuts["end_left"].key() == QKeySequence(Qt.Key.Key_B)
    assert manager.shortcuts["end_right"].key() == QKeySequence(Qt.Key.Key_N)
    assert manager.shortcuts["open_file"].key() == QKeySequence("Ctrl+O")
    assert manager.shortcuts["export_file"].key() == QKeySequence("Ctrl+E")
    assert manager.shortcuts["apply_crop"].key() == QKeySequence(Qt.Key.Key_A)
    assert manager.shortcuts["reset_crop"].key() == QKeySequence(Qt.Key.Key_R)

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


def test_main_window_has_player_playback_speed_control_and_selection_group() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert hasattr(window, "playback_speed_combo")
    assert hasattr(window.preview_panel, "playback_speed_combo")
    assert window.preview_panel.playback_speed_combo.itemText(0) == "0.25×"
    assert window.preview_panel.playback_speed_combo.itemText(1) == "0.5×"
    assert window.preview_panel.playback_speed_combo.itemText(2) == "1×"
    assert window.preview_panel.playback_speed_combo.itemText(3) == "1.5×"
    assert window.preview_panel.playback_speed_combo.itemText(4) == "2×"
    assert window.preview_panel.selection_group.title() == "Selection"
    assert window.preview_panel.selection_group.maximumHeight() <= 110
    assert not hasattr(window, "export_fps_input")

    app.quit()
