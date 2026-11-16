"""Variable-delay timeline behaviour using deterministic WebP fixtures."""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gifmaker.gui.animation_timeline_controller import AnimationTimelineController
from gifmaker.gui.views.marker_seek_slider import MarkerSeekSlider
from gifmaker.sources import load_source
from gifmaker.sources.animation_player import AnimationSourcePlayer
from gifmaker.sources.animation_timeline import AnimationTimeline

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FIXTURE = Path(__file__).parent / "fixtures/webp_input/variable_delays.webp"


def test_frame_positions_steps_and_exclusive_selection():
    with load_source(FIXTURE) as source:
        timeline = AnimationTimeline.from_source(source)
        assert timeline.boundaries_ms == (0, 100, 350, 750)
        assert [timeline.frame_index_at(t) for t in (0, 99, 100, 349, 350, 750)] == [0, 0, 1, 1, 2, 2]
        assert timeline.selection_ms(0, 3) == (0, 750)
        assert timeline.selection_ms(1, 3) == (100, 750)
        assert timeline.selection_ms(2, 3) == (350, 750)
        assert timeline.step(149, 1) == 350
        assert timeline.step(750, -1) == 100
        assert timeline.step(0, -1) == 0
        assert timeline.step(750, 1) == 350
        with pytest.raises(ValueError):
            timeline.selection_ms(2, 2)


def test_invalid_boundaries_and_closed_source():
    with pytest.raises(ValueError):
        AnimationTimeline((0, 100, 100))
    source = load_source(FIXTURE)
    source.close()
    with pytest.raises(ValueError):
        AnimationTimeline.from_source(source)


def test_slider_marker_geometry_and_player_integration():
    app = QApplication.instance() or QApplication([])
    with load_source(FIXTURE) as source:
        player = AnimationSourcePlayer()
        slider = MarkerSeekSlider(Qt.Horizontal)
        slider.resize(800, 28)
        controller = AnimationTimelineController(player, slider, source)
        selections = []
        controller.selectionChanged.connect(lambda start, end: selections.append((start, end)))
        assert slider.maximum() == 750
        assert slider.selection() == (0, 3)
        assert controller.selection_seconds() == (0, 0.75)
        left, _, width = slider._groove_rect()
        assert abs(slider._frame_to_x(1) - (left + width * 100 / 750)) <= 1
        assert slider._x_to_frame(slider._frame_to_x(2)) == 2
        slider.set_selection(1, 3)
        assert selections[-1] == (0.1, 0.75)
        slider.set_selection(2, 3)
        assert controller.selection_seconds() == (0.35, 0.75)
        slider.setValue(100)
        assert player.position_ms == 100
        controller.step_frame(1)
        assert player.position_ms == slider.value() == 350
        player.seek(750)
        assert slider.value() == 750
        controller.set_end_at_position()
        assert controller.selection_seconds() == (0.35, 0.75)
        player.seek(0)
        controller.set_start_at_position()
        player.seek(100)
        controller.set_end_at_position()
        assert controller.selection_seconds() == (0, 0.1)
        slider.nudge_end(1)
        assert controller.selection_seconds() == (0, 0.35)
        controller.close()
        controller.close()
        assert slider.maximum() == 0
        assert not source.closed
    app.processEvents()
