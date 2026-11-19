"""Selection readouts follow marker geometry without changing the timeline."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow
from gifmaker.gui.themes import apply_theme


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_timestamps_follow_markers_without_clipping_or_overlapping(theme):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    previous_theme = window.current_theme
    apply_theme(app, theme)
    window.setMaximumSize(1600, 1200)
    window.total_frames = 3001
    window.current_video_fps = 100
    slider = window.seek_slider
    slider.setRange(0, 3000)
    slider.set_total_frames(3001)
    window.show()
    times = window.preview_panel.selection_times
    try:
        for width, height in ((1050, 760), (760, 540), (1050, 1000)):
            window.resize(width, height)
            app.processEvents()
            for start, end in ((0, 3000), (900, 2100), (1500, 1502), (0, 2), (2998, 3000)):
                slider.set_selection(start, end)
                app.processEvents()
                assert times.x() == slider.x()
                assert times.width() == slider.width()
                assert times.y() >= slider.geometry().bottom()
                for label, frame in ((times.start_label, start), (times.end_label, end)):
                    expected_x = slider._frame_to_x(frame) - label.width() // 2
                    expected_x = max(0, min(expected_x, times.width() - label.width()))
                    assert label.x() == expected_x
                    assert times.rect().contains(label.geometry())
                assert not times.start_label.geometry().intersects(times.end_label.geometry())
                assert not window.seek_time_label.geometry().intersects(
                    window.clip_selection_label.geometry()
                )
                assert window.preview_panel.rect().contains(window.mute_button.geometry())

        # A taller window keeps the default balance and allows manual resizing.
        source, output = window.preview_splitter.sizes()
        assert 0.49 < output / (source + output) < 0.51
        window.preview_splitter.setSizes([600, 400])
        assert window.preview_splitter.sizes()[0] > window.preview_splitter.sizes()[1]
    finally:
        window.close()
        apply_theme(app, previous_theme)


def test_marker_dragging_and_keyboard_nudges_refresh_inline_readouts():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.total_frames = 3001
    window.current_video_fps = 100
    slider = window.seek_slider
    slider.setRange(0, 3000)
    slider.set_total_frames(3001)
    window.show()
    app.processEvents()
    try:
        slider.set_selection(1000, 2000)
        assert window.start_frame_label.text() == "00:00:10.000"
        assert window.end_frame_label.text() == "00:00:20.000"
        assert window.clip_selection_label.text() == "Length: 10.000s"
        y = slider.height() // 2
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider._frame_to_x(1000), y))
        QTest.mouseMove(slider, QPoint(slider._frame_to_x(500), y))
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider._frame_to_x(500), y))
        assert window.start_frame < 1000
        assert window.start_frame_label.text() == window._format_timestamp_from_frame(window.start_frame)
        start = window.start_frame
        window._shortcut_start_right()
        assert window.start_frame == start + 1
        assert window.start_frame_label.text() == window._format_timestamp_from_frame(start + 1)
        assert window.clip_selection_label.text() == f"Length: {(2000 - start - 1) / 100:.3f}s"

        # Playback time and selection length remain separate from output speed.
        window.output_speed_slider.setValue(200)
        assert window.clip_selection_label.text() == f"Length: {(2000 - start - 1) / 100:.3f}s"
        window.total_frames = 0
        window.video_session_controller.update_clip_selection_display()
        assert window.start_frame_label.text() == "--:--:--.---"
        assert window.end_frame_label.text() == "--:--:--.---"
        assert window.clip_selection_label.text() == "Length: —"
    finally:
        window.close()
