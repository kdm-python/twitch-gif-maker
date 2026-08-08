import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGroupBox, QSplitter

from gifmaker.gui.main_window import MainWindow


def test_main_window_uses_splitter_for_resizable_preview_sections() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    central_layout = window.centralWidget().layout()
    resizable_container = central_layout.itemAt(2).widget()

    assert isinstance(resizable_container, QSplitter)
    assert resizable_container.count() == 3
    assert isinstance(resizable_container.widget(0), QGroupBox)
    assert isinstance(resizable_container.widget(1), QGroupBox)
    assert isinstance(resizable_container.widget(2), QGroupBox)

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
