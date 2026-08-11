import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QSplitter

from gifmaker.gui.main_window import MainWindow


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
