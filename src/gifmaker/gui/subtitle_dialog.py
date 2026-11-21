"""Focused animation workspace; caption editing is added in a later stage."""
from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from loguru import logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gifmaker.gui.animation_timeline_controller import AnimationTimelineController
from gifmaker.gui.views.marker_seek_slider import MarkerSeekSlider
from gifmaker.gui.views.video_preview_panel import AnimationSurface, SelectionTimeLabels
from gifmaker.models.render_settings import format_ms
from gifmaker.sources.animation_player import AnimationSourcePlayer
from gifmaker.sources.loader import load_source


def _prepare_snapshot(path: Path, workspace: TemporaryDirectory):
    try:
        return load_source(path)
    finally:
        workspace.cleanup()


def _discard_result(future):
    try:
        future.result().close()
    except Exception as exc:  # noqa: BLE001 - failed worker results still need to be collected
        logger.debug("Closed subtitle workspace discarded failed preparation: {}", exc)


class SubtitleDialog(QDialog):
    """Own an independent player and prepared source, never main-window state."""

    def __init__(self, path: Path, position_ms: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Subtitles")
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(850, 550)
        self._initial_position = position_ms
        self.source = None
        self.timeline = None
        self._closed = False
        self.player = AnimationSourcePlayer(self)
        layout = QVBoxLayout(self)
        self.surface = AnimationSurface(self)
        layout.addWidget(self.surface, 1)
        self.status = QLabel("Loading animation…")
        layout.addWidget(self.status)
        self.slider = MarkerSeekSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        layout.addWidget(self.slider)
        self.selection_times = SelectionTimeLabels(self.slider, self)
        layout.addWidget(self.selection_times)
        row = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.setEnabled(False)
        self.play_button.setAutoDefault(False)
        self.play_button.clicked.connect(self.toggle_playback)
        row.addWidget(self.play_button)
        self.speed_combo = QComboBox()
        for rate in (.25, .5, 1., 1.5, 2.):
            self.speed_combo.addItem(f"{rate:g}×", rate)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.setAccessibleName("Subtitle preview playback speed")
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.set_playback_rate(self.speed_combo.currentData())
        )
        row.addWidget(self.speed_combo)
        self.position_label = QLabel()
        row.addWidget(self.position_label)
        row.addStretch()
        close_button = QPushButton("Return (L)")
        close_button.setAutoDefault(False)
        close_button.clicked.connect(self.accept)
        row.addWidget(close_button)
        layout.addLayout(row)
        help_label = QLabel("←/→ Step frame · C/Z/X Start · V/B/N End · Space/P Play/pause")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.player.frameChanged.connect(self.surface.set_frame)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playingChanged.connect(
            lambda playing: self.play_button.setText("⏸ Pause" if playing else "▶ Play")
        )
        self.player.errorOccurred.connect(self._error)
        bindings = {
            "Left": lambda: self.timeline.step_frame(-1),
            "Right": lambda: self.timeline.step_frame(1),
            "C": lambda: self.timeline.set_start_at_position(),
            "V": lambda: self.timeline.set_end_at_position(),
            "Z": lambda: self.slider.nudge_start(-1),
            "X": lambda: self.slider.nudge_start(1),
            "B": lambda: self.slider.nudge_end(-1),
            "N": lambda: self.slider.nudge_end(1),
            "Space": self.toggle_playback,
            "P": self.toggle_playback,
            ",": lambda: self._step_speed(-1),
            ".": lambda: self._step_speed(1),
        }
        self.shortcuts = []
        for key, callback in bindings.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setAutoRepeat(key not in ("Space", "P"))
            shortcut.activated.connect(lambda action=callback: action() if self.timeline else None)
            self.shortcuts.append(shortcut)
        shortcut = QShortcut(QKeySequence("L"), self)
        shortcut.setAutoRepeat(False)
        shortcut.activated.connect(self.accept)
        self.shortcuts.append(shortcut)

        # Pin the encoded input before yielding to the event loop. Decoding and
        # PNG preparation run outside the GUI thread and survive an early close.
        workspace = TemporaryDirectory(prefix="gifmaker-subtitle-input-")
        try:
            snapshot = Path(workspace.name) / "input.webp"
            shutil.copyfile(path, snapshot)
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subtitle-loader")
            self._future = self._executor.submit(_prepare_snapshot, snapshot, workspace)
        except Exception:
            workspace.cleanup()
            raise
        self._poll = QTimer(self)
        self._poll.setInterval(30)
        self._poll.timeout.connect(self._check_loaded)
        self._poll.start()
        self.finished.connect(self._cleanup)

    def _check_loaded(self):
        if not self._future.done():
            return
        self._poll.stop()
        try:
            self.source = self._future.result()
            self.timeline = AnimationTimelineController(self.player, self.slider, self.source, self)
            self.timeline.selectionChanged.connect(self._selection_changed)
            self.player.seek(self._initial_position)
            self.slider.setEnabled(True)
            self.play_button.setEnabled(True)
            self._selection_changed(*self.timeline.selection_seconds())
        except Exception as exc:  # noqa: BLE001 - surface asynchronous preparation failures
            self._error(str(exc))

    def _position_changed(self, position):
        self.position_label.setText(f"{format_ms(position)} / {format_ms(self.player.duration_ms)}")

    def _selection_changed(self, start, end):
        self.selection_times.set_times(format_ms(round(start * 1000)), format_ms(round(end * 1000)))
        self.status.setText(f"Text visibility range: {start:.3f}s–{end:.3f}s (end excluded)")

    def toggle_playback(self):
        if self.player.playing:
            self.player.pause()
        else:
            self.player.play()

    def _step_speed(self, delta):
        self.speed_combo.setCurrentIndex(
            max(0, min(self.speed_combo.count() - 1, self.speed_combo.currentIndex() + delta))
        )

    def _error(self, message):
        logger.error("Subtitle playback failed: {}", message)
        self.player.pause()
        self.status.setText(f"Could not prepare subtitles: {message}")
        self.slider.setEnabled(False)
        self.play_button.setEnabled(False)
        for shortcut in self.shortcuts[:-1]:
            shortcut.setEnabled(False)

    def _cleanup(self, *_args):
        if self._closed:
            return
        self._closed = True
        self._poll.stop()
        if self.timeline is not None:
            self.timeline.close()
        else:
            self.player.clear()
        if self.source is not None:
            self.source.close()
        else:
            self._future.add_done_callback(_discard_result)
        self._executor.shutdown(wait=False)
