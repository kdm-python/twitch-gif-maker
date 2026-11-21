"""Exercise the modal boundary with real Qt playback and variable-delay WebP."""
import os
import shutil
import tempfile
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from gifmaker.gui.main_window import MainWindow
from gifmaker.gui.subtitle_dialog import SubtitleDialog
from gifmaker.models.render_settings import RenderSettings, RenderSpec

FIXTURE = Path(__file__).parent / "fixtures/webp_input/variable_delays.webp"


def wait_until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate()


def preview_window():
    window = MainWindow()
    settings = RenderSettings(0, .75)
    window.current_video_path = str(FIXTURE)
    window._last_preview_spec = RenderSpec(str(FIXTURE), "WebP", settings)
    window._last_preview_settings = settings
    descriptor, name = tempfile.mkstemp(prefix="gifmaker-test-preview-", suffix=".webp")
    os.close(descriptor)
    window._preview_temp_file = Path(name)
    shutil.copyfile(FIXTURE, name)
    window.preview_controller.load(Path(name))
    window.pause_gif_preview()
    window._preview_frame_index = 1
    window.preview_controller.update_scaled_size()
    window.show()
    return window


def dispose(window):
    if window.subtitle_controller.dialog is not None:
        window.subtitle_controller.dialog.close()
    window.close()


def test_handoff_timeline_shortcuts_and_exact_paused_return():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    app.processEvents()
    window.activateWindow()
    window.setFocus()
    app.processEvents()
    original_selection = window.seek_slider.selection()
    original_image = window.gif_preview_label.pixmap().toImage()
    window.preview_lock_button.setChecked(True)
    try:
        QTest.keyClick(window, Qt.Key_S)
        dialog = window.subtitle_controller.dialog
        assert dialog is not None
        assert dialog.isModal()
        assert window.render_controller._preview_suspended
        assert not window.menuBar().isEnabled()
        assert all(not s.isEnabled() for s in window.shortcut_manager.shortcuts.values())
        wait_until(app, lambda: dialog.timeline is not None)
        assert dialog.player.position_ms == 100
        assert not dialog.player.playing
        assert dialog.slider.selection() == (0, 3)
        dialog.activateWindow()
        dialog.setFocus()
        app.processEvents()
        QTest.keyClick(dialog, Qt.Key_C)
        assert dialog.slider.selection() == (1, 3)
        QTest.keyClick(dialog, Qt.Key_Z)
        assert dialog.slider.selection() == (0, 3)
        QTest.keyClick(dialog, Qt.Key_X)
        assert dialog.slider.selection() == (1, 3)
        QTest.keyClick(dialog, Qt.Key_Right)
        assert dialog.player.position_ms == 350
        QTest.keyClick(dialog, Qt.Key_V)
        assert dialog.slider.selection() == (1, 2)
        QTest.keyClick(dialog, Qt.Key_Comma)
        assert dialog.speed_combo.currentData() == .5
        QTest.keyClick(dialog, Qt.Key_Period)
        assert dialog.speed_combo.currentData() == 1.
        slider = dialog.slider
        y = slider.height() // 2
        QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(slider._frame_to_x(2), y))
        QTest.mouseMove(slider, QPoint(slider._frame_to_x(3), y))
        QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(slider._frame_to_x(3), y))
        assert slider.selection() == (1, 3)
        QTest.keyClick(dialog, Qt.Key_N)
        assert dialog.slider.selection() == (1, 3)
        QTest.keyClick(dialog, Qt.Key_B)
        assert dialog.slider.selection() == (1, 2)
        QTest.keyClick(dialog, Qt.Key_Space)
        assert dialog.player.playing
        QTest.keyClick(dialog, Qt.Key_P)
        assert not dialog.player.playing
        QTest.mouseClick(dialog.play_button, Qt.LeftButton)
        assert dialog.player.playing
        QTest.mouseClick(dialog.play_button, Qt.LeftButton)
        assert not dialog.player.playing
        source = dialog.source
        QTest.keyClick(dialog, Qt.Key_L)
        app.processEvents()
        assert window.subtitle_controller.dialog is None
        assert source.closed
        assert window.preview_controller.player.position_ms() == 100
        assert not window._preview_frame_timer.isActive()
        assert window.seek_slider.selection() == original_selection
        assert window.gif_preview_label.pixmap().toImage() == original_image
        assert window.preview_lock_button.isChecked()
        assert not window.render_controller._preview_suspended
        assert all(s.isEnabled() for s in window.shortcut_manager.shortcuts.values())
        assert window.menuBar().isEnabled()
    finally:
        dispose(window)


def test_missing_preview_and_editor_launch_failure_leave_host_usable():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    with patch.object(QMessageBox, "information") as message:
        window.open_subtitles()
        message.assert_called_once()
    window.close()
    window = preview_window()
    try:
        with patch("gifmaker.gui.subtitle_dialog.SubtitleDialog", side_effect=RuntimeError("broken")), \
                patch.object(QMessageBox, "warning") as message:
            window.open_subtitles()
            message.assert_called_once()
        assert window.subtitle_controller.dialog is None
        assert not window.render_controller._preview_suspended
        assert window.shortcut_manager.shortcuts["subtitles"].isEnabled()
        assert window.preview_controller.player.position_ms() == 100
        app.processEvents()
    finally:
        dispose(window)


def test_decode_failure_is_visible_and_close_restores_unlocked_host():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    try:
        with patch("gifmaker.gui.subtitle_dialog.load_source", side_effect=RuntimeError("decoder unavailable")):
            window.open_subtitles()
            dialog = window.subtitle_controller.dialog
            wait_until(app, lambda: "decoder unavailable" in dialog.status.text())
        assert not dialog.play_button.isEnabled()
        dialog.close()
        assert not window.render_controller.preview_locked
        assert not window.render_controller._preview_suspended
        assert window.subtitle_controller.dialog is None
    finally:
        dispose(window)


def test_close_while_loading_collects_late_source():
    app = QApplication.instance() or QApplication([])
    future = Future()
    with patch("gifmaker.gui.subtitle_dialog.ThreadPoolExecutor") as executor:
        executor.return_value.submit.return_value = future
        dialog = SubtitleDialog(FIXTURE, 100)
        # The fake worker does not run the snapshot cleanup itself.
        workspace = executor.return_value.submit.call_args.args[2]
        dialog.show()
        dialog.close()
        class Source:
            closed = False

            def close(self):
                self.closed = True

        source = Source()
        future.set_result(source)
        assert source.closed
        executor.return_value.shutdown.assert_called_once_with(wait=False)
        workspace.cleanup()
        app.processEvents()


def test_open_suspends_pending_render_and_leaves_artifact_pinned():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    try:
        render = window.render_controller
        original_preview = window._preview_temp_file
        render._preview_debounce.start(1000)
        with patch.object(render, "_cancel_preview_job") as cancel:
            window.open_subtitles()
            cancel.assert_called_once()
        assert not render._preview_debounce.isActive()
        with patch.object(render, "_start_process") as start:
            render.generate_gif_preview()
            start.assert_not_called()
        render._schedule_preview_refresh()
        assert not render._preview_debounce.isActive()
        window.subtitle_controller.dialog.close()
        assert window._preview_temp_file == original_preview
        assert not render._preview_debounce.isActive()
        app.processEvents()
    finally:
        dispose(window)


def test_cannot_open_during_source_preparation():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    try:
        window.video_session_controller._load_future = Future()
        with patch.object(QMessageBox, "information") as message:
            window.open_subtitles()
            message.assert_called_once()
        assert window.subtitle_controller.dialog is None
        assert not window.render_controller._preview_suspended
        app.processEvents()
    finally:
        dispose(window)
