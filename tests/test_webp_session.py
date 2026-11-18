import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox

from gifmaker.gui.main_window import MainWindow
from gifmaker.models.video_info import VideoInfo

FIXTURE = Path(__file__).parent / "fixtures/webp_input/variable_delays.webp"


def wait_for(app, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def test_animation_loading_selection_and_return_to_video():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    controller = window.video_session_controller
    window.export_format_combo.setCurrentText("GIF")
    window.open_dropped_video(str(FIXTURE))
    wait_for(app, lambda: controller._animation_source is not None)
    source = controller._animation_source
    assert window.current_video_path == str(FIXTURE.resolve())
    assert (window.clip_start_time, window.clip_end_time) == (0, 0.75)
    assert window.export_format_combo.currentText() == "WebP"
    assert not window.export_format_combo.model().item(window.export_format_combo.findText("GIF")).isEnabled()
    assert window.generate_preview_button.isEnabled()
    controller._rightArrowPressed()
    assert controller._animation_player.position_ms == 100
    controller.set_clip_start()
    assert window.clip_start_time == 0.1
    controller._rightArrowPressed()
    assert controller._animation_player.position_ms == 350
    window.seek_slider.set_selection(2, 3)
    assert (window.clip_start_time, window.clip_end_time) == (0.35, 0.75)
    window._pending_video_path = "next.mp4"
    window._pending_video_info = VideoInfo(2, 16, 16, 24, "h264")
    controller.on_media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)
    assert source.closed
    assert window.export_format_combo.currentText() == "GIF"
    assert window.export_format_combo.model().item(window.export_format_combo.findText("GIF")).isEnabled()
    assert window.generate_preview_button.isEnabled()
    window.close()


def test_failed_animation_load_keeps_current_source(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    controller = window.video_session_controller
    window.open_dropped_video(str(FIXTURE))
    wait_for(app, lambda: controller._animation_source is not None)
    source = controller._animation_source
    bad = tmp_path / "bad.webp"
    bad.write_bytes(b"invalid")
    with patch.object(QMessageBox, "warning") as warning:
        window.open_video_path(str(bad))
        wait_for(app, lambda: warning.called)
    assert controller._animation_source is source
    assert not source.closed
    window.close()
    assert source.closed


def test_luddy_loads_through_the_session():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    controller = window.video_session_controller
    fixture = Path(__file__).parent / "fixtures/luddy.webp"
    if not fixture.exists():
        window.close()
        return
    window.open_video_path(str(fixture))
    wait_for(app, lambda: controller._animation_source is not None)
    player = controller._animation_player
    assert player.duration_ms > 0
    player.seek(player.duration_ms)
    assert player.position_ms == player.duration_ms
    window.close()


def test_cli_webp_uses_the_shared_source_opening_path():
    from unittest.mock import MagicMock

    from gifmaker.main import main

    app = MagicMock()
    app.exec.return_value = 0
    window = MagicMock()
    with (
        patch("PySide6.QtWidgets.QApplication.instance", return_value=app),
        patch("gifmaker.gui.main_window.MainWindow", return_value=window),
        patch("gifmaker.main.probe_video") as probe,
    ):
        assert main(["--file", str(FIXTURE)]) == 0
    window.video_session_controller.open_video_path.assert_called_once_with(str(FIXTURE.resolve()))
    probe.assert_not_called()
