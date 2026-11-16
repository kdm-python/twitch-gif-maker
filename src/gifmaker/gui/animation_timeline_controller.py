"""Connect an animation source player to a timestamp-aware marker slider."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSignalBlocker, Signal

from gifmaker.gui.views.marker_seek_slider import MarkerSeekSlider
from gifmaker.sources.animation_player import AnimationSourcePlayer
from gifmaker.sources.animation_timeline import AnimationTimeline
from gifmaker.sources.model import LoadedSource


class AnimationTimelineController(QObject):
    """Adapter for a single animation; the caller retains source ownership."""

    selectionChanged = Signal(float, float)

    def __init__(self, player: AnimationSourcePlayer, slider: MarkerSeekSlider,
                 source: LoadedSource, parent: QObject | None = None) -> None:
        super().__init__(parent)
        timeline = AnimationTimeline.from_source(source)
        # A failed load leaves existing slider connections and geometry intact.
        player.set_source(source)
        self.player = player
        self.slider = slider
        self.timeline = timeline
        self._closed = False
        with QSignalBlocker(slider):
            slider.set_animation_boundaries(timeline.boundaries_ms)
            slider.setValue(0)
        slider.valueChanged.connect(self._seek)
        slider.selectionChanged.connect(self._selection_changed)
        player.positionChanged.connect(self._position_changed)

    def _seek(self, position_ms: int) -> None:
        self.player.seek(position_ms)

    def _position_changed(self, position_ms: int) -> None:
        if not self.slider.isSliderDown():
            with QSignalBlocker(self.slider):
                self.slider.setValue(position_ms)

    def _selection_changed(self, start: int, end: int) -> None:
        start_ms, end_ms = self.timeline.selection_ms(start, end)
        self.selectionChanged.emit(start_ms / 1000, end_ms / 1000)

    def selection_seconds(self) -> tuple[float, float]:
        start, end = self.timeline.selection_ms(*self.slider.selection())
        return start / 1000, end / 1000

    def step_frame(self, delta: int) -> None:
        self.player.seek(self.timeline.step(self.player.position_ms, delta))

    def set_start_at_position(self) -> None:
        start = self.timeline.frame_index_at(self.player.position_ms)
        _, end = self.slider.selection()
        self.slider.set_selection(min(start, end - 1), end)

    def set_end_at_position(self) -> None:
        position = self.player.position_ms
        end = (self.timeline.frame_count if position >= self.timeline.duration_ms
               else self.timeline.frame_index_at(position))
        start, _ = self.slider.selection()
        self.slider.set_selection(start, max(start + 1, end))

    def close(self) -> None:
        """Disconnect before another source or the normal video timeline is used."""
        if self._closed:
            return
        self._closed = True
        self.slider.valueChanged.disconnect(self._seek)
        self.slider.selectionChanged.disconnect(self._selection_changed)
        self.player.positionChanged.disconnect(self._position_changed)
        self.player.clear()
        with QSignalBlocker(self.slider):
            self.slider.set_animation_boundaries(None)
