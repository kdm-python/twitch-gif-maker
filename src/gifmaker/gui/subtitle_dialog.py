"""Modal caption editing over an independently prepared animation."""
from __future__ import annotations

import shutil
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from loguru import logger
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gifmaker.gui.animation_timeline_controller import AnimationTimelineController
from gifmaker.gui.views.marker_seek_slider import MarkerSeekSlider
from gifmaker.gui.views.subtitle_surface import SubtitleSurface
from gifmaker.gui.views.video_preview_panel import SelectionTimeLabels
from gifmaker.models.render_settings import format_ms
from gifmaker.models.subtitles import Caption, SubtitleDocument, SubtitleTiming
from gifmaker.sources.animation_player import AnimationSourcePlayer
from gifmaker.sources.loader import load_source

FONT_CHOICES = (
    "American Typewriter", "Arial", "Chalkboard", "Comic Sans MS", "Copperplate",
    "Courier New", "DejaVu Sans", "Helvetica", "Herculanum", "Impact", "Marker Felt",
    "Noteworthy", "Old English Text MT", "Papyrus", "Times New Roman", "Verdana",
)

COLOUR_CHOICES = (
    ("White", "#ffffff"),
    ("Black", "#000000"),
    ("Grey", "#808080"),
    ("Gold", "#ffd700"),
    ("Silver", "#c0c0c0"),
    ("Blue", "#1e90ff"),
    ("Crimson", "#dc143c"),
    ("Lime", "#32cd32"),
    ("Purple", "#a855f7"),
    ("Yellow", "#ffff00"),
)


def _prepare_snapshot(path: Path, workspace: TemporaryDirectory, timeline_path: Path | None = None):
    source = None
    try:
        source = load_source(path)
        if timeline_path is not None:
            # Encoders may merge identical clean frames. Preserve the displayed
            # result's timing boundaries while substituting uncaptioned pixels.
            with load_source(timeline_path) as displayed:
                source.align_timing(displayed)
        return source
    except BaseException:
        if source is not None:
            source.close()
        raise
    finally:
        workspace.cleanup()


def _discard_result(future):
    try:
        future.result().close()
    except Exception as exc:  # noqa: BLE001 - failed worker results still need to be collected
        logger.debug("Closed subtitle workspace discarded failed preparation: {}", exc)


class SubtitleDialog(QDialog):
    """Own an independent player and prepared source, never main-window state."""

    def __init__(self, path: Path, position_ms: int, parent=None, *,
                 document: SubtitleDocument | None = None, timing: SubtitleTiming | None = None,
                 timeline_path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Subtitles")
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(850, 550)
        self._initial_position = position_ms
        self.source = None
        self.timeline = None
        self._closed = False
        self._has_error = False
        self.ready = False
        self.document = document or SubtitleDocument()
        self.timing = timing
        self.player = AnimationSourcePlayer(self)
        layout = QVBoxLayout(self)
        self.surface = SubtitleSurface(self)
        layout.addWidget(self.surface, 1)
        self._build_text_controls(layout)
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
        help_label = QLabel("←/→ Step frame · C/Z/X Start · V/B/N End · Space/P Play/pause · "
                            "F Font · W Colour · [/] Size +/- · E Bold · R Italic")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addWidget(QLabel("Close or press L to apply captions to the preview and export."))
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
            "F": lambda: self._cycle_combo(self.font_combo),
            "W": lambda: self._cycle_combo(self.color_combo),
            "[": lambda: self._step_font_size(1),
            "]": lambda: self._step_font_size(-1),
            "E": self.bold_button.toggle,
            "R": self.italic_button.toggle,
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
        self.surface.interactionStarted.connect(self.player.pause)
        self.surface.textEdited.connect(self._set_text)
        self.surface.positionEdited.connect(lambda x, y: self._edit_caption(x=x, y=y))

        # Pin the encoded input before yielding to the event loop. Decoding and
        # PNG preparation run outside the GUI thread and survive an early close.
        workspace = TemporaryDirectory(prefix="gifmaker-subtitle-input-")
        try:
            snapshot = Path(workspace.name) / "input.webp"
            shutil.copyfile(path, snapshot)
            timeline_snapshot = None
            if timeline_path is not None:
                timeline_snapshot = Path(workspace.name) / "timeline.webp"
                shutil.copyfile(timeline_path, timeline_snapshot)
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subtitle-loader")
            self._future = self._executor.submit(_prepare_snapshot, snapshot, workspace, timeline_snapshot)
        except Exception:
            workspace.cleanup()
            raise
        self._poll = QTimer(self)
        self._poll.setInterval(30)
        self._poll.timeout.connect(self._check_loaded)
        self._poll.start()
        self.finished.connect(self._cleanup)
        QApplication.instance().focusChanged.connect(self._focus_changed)
        QApplication.instance().installEventFilter(self)

    def _check_loaded(self):
        if not self._future.done():
            return
        self._poll.stop()
        try:
            self.source = self._future.result()
            if self.timing is None:
                self.timing = SubtitleTiming(0, self.source.info.duration_seconds * 1000)
            if not self.document.captions:
                family = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
                self.document = SubtitleDocument((Caption(self.timing.start_ms, self.timing.end_ms,
                                                         font_family=family),))
            self.timeline = AnimationTimelineController(self.player, self.slider, self.source, self)
            self.timeline.selectionChanged.connect(self._selection_changed)
            self._restore_caption_range()
            self._sync_text_controls()
            self.player.seek(self._initial_position)
            self.slider.setEnabled(True)
            self.play_button.setEnabled(True)
            self.text_controls.setEnabled(True)
            self.ready = True
            self._update_surface()
            self._focus_changed(None, QApplication.focusWidget())
        except Exception as exc:  # noqa: BLE001 - surface asynchronous preparation failures
            self._error(str(exc))

    def _position_changed(self, position):
        self.position_label.setText(f"{format_ms(position)} / {format_ms(self.player.duration_ms)}")
        self._update_surface()

    def _selection_changed(self, start, end):
        if self.timing and self.document.captions:
            source_start, source_end = self.timing.source_time(start * 1000), self.timing.source_time(end * 1000)
            if source_start < source_end:
                self._edit_caption(start_ms=source_start, end_ms=source_end)
        self._range_labels(start, end)

    def _range_labels(self, start, end):
        self.selection_times.set_times(format_ms(round(start * 1000)), format_ms(round(end * 1000)))
        self.status.setText(f"Text visibility range: {start:.3f}s–{end:.3f}s (end excluded)")

    def _restore_caption_range(self):
        caption = self.document.captions[0]
        boundaries = self.timeline.timeline.boundaries_ms
        start = max(0, min(len(boundaries) - 2, bisect_right(boundaries, self.timing.output_time(caption.start_ms)) - 1))
        end = max(start + 1, min(len(boundaries) - 1, bisect_left(boundaries, self.timing.output_time(caption.end_ms))))
        with QSignalBlocker(self.slider):
            self.slider.set_selection(start, end)
        self._range_labels(*self.timeline.selection_seconds())
        if caption.end_ms <= self.timing.start_ms or caption.start_ms >= self.timing.end_ms:
            self.status.setText("Caption is outside this clip. Adjust its markers to assign a new range.")
        elif caption.start_ms < self.timing.start_ms or caption.end_ms > self.timing.end_ms:
            self.status.setText(self.status.text() + " · Caption is partially trimmed; original timing retained.")
        elif (boundaries[start] != self.timing.output_time(caption.start_ms)
              or boundaries[end] != self.timing.output_time(caption.end_ms)):
            actual_start = self.timing.output_time(caption.start_ms) / 1000
            actual_end = self.timing.output_time(caption.end_ms) / 1000
            self.status.setText(f"Caption timing: {actual_start:.3f}s–{actual_end:.3f}s · Markers snapped to current frames.")

    def _build_text_controls(self, layout):
        self.text_controls = QWidget(self)
        controls = QVBoxLayout(self.text_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Your text here")
        self.text_input.setAccessibleName("Caption text")
        self.text_input.setToolTip("Type your caption, then press Enter or click outside the field to use playback shortcuts.")
        self.text_input.textEdited.connect(self._set_text)
        self.text_input.returnPressed.connect(self.setFocus)
        controls.addWidget(self.text_input)
        style = QHBoxLayout()
        self.font_combo = QComboBox()
        available = set(QFontDatabase.families())
        default = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
        for family in sorted(set(FONT_CHOICES) | {default}, key=str.casefold):
            if family in available or family == default:
                self.font_combo.addItem(family)
        self.font_combo.setAccessibleName("Caption font")
        self.font_combo.currentTextChanged.connect(lambda family: self._edit_caption(font_family=family))
        style.addWidget(QLabel("Font"))
        style.addWidget(self.font_combo)
        self.color_combo = QComboBox()
        for name, color in COLOUR_CHOICES:
            self.color_combo.addItem(name, color)
        self.color_combo.setAccessibleName("Caption colour")
        self.color_combo.currentIndexChanged.connect(lambda: self._edit_caption(color=self.color_combo.currentData()))
        style.addWidget(self.color_combo)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(2, 30)
        self.size_spin.setSingleStep(.5)
        self.size_spin.setSuffix("%")
        self.size_spin.setAccessibleName("Caption size as percentage of image height")
        self.size_spin.valueChanged.connect(lambda value: self._edit_caption(size=value / 100))
        style.addWidget(QLabel("Size"))
        style.addWidget(self.size_spin)
        for name in ("bold", "italic"):
            button = QPushButton(name.title())
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.toggled.connect(lambda checked, attribute=name: self._edit_caption(**{attribute: checked}))
            setattr(self, f"{name}_button", button)
            style.addWidget(button)
        centre = QPushButton("Bottom centre")
        centre.setAutoDefault(False)
        centre.clicked.connect(lambda: self._edit_caption(x=.5, y=.9))
        style.addWidget(centre)
        controls.addLayout(style)
        self.text_controls.setEnabled(False)
        layout.addWidget(self.text_controls)

    def _sync_text_controls(self):
        caption = self.document.captions[0]
        widgets = [self.text_input, self.font_combo, self.color_combo, self.size_spin,
                   self.bold_button, self.italic_button]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        self.text_input.setText(caption.text)
        if self.font_combo.findText(caption.font_family) < 0:
            self.font_combo.addItem(caption.font_family)
        self.font_combo.setCurrentText(caption.font_family)
        self.color_combo.setCurrentIndex(self.color_combo.findData(caption.color))
        self.size_spin.setValue(caption.size * 100)
        self.bold_button.setChecked(caption.bold)
        self.italic_button.setChecked(caption.italic)
        del blockers

    def _set_text(self, text):
        self._edit_caption(text=text)
        if self.text_input.text() != text:
            self.text_input.setText(text)

    def _edit_caption(self, **changes):
        if not self.document.captions:
            return
        self.document = replace(self.document, captions=(replace(self.document.captions[0], **changes),)
                                + self.document.captions[1:])
        self._update_surface()

    def _update_surface(self):
        if self.timeline is not None and self.timing is not None and not self._closed:
            timeline = self.timeline.timeline
            frame_start = timeline.boundaries_ms[timeline.frame_index_at(self.player.position_ms)]
            self.surface.set_document(self.document, self.timing.source_time(frame_start))

    def _focus_changed(self, _old, current):
        if self._closed:
            return
        typing = isinstance(current, (QLineEdit, QDoubleSpinBox))
        if typing and (current is self.surface.editor or self.text_controls.isAncestorOf(current)):
            self.player.pause()
        for shortcut in self.shortcuts[:-1]:
            shortcut.setEnabled(self.ready and not self._has_error and not typing)
        self.shortcuts[-1].setEnabled(not typing)

    def _input_owner(self, widget):
        if widget in (self.text_input, self.surface.editor):
            return widget
        if widget is self.size_spin or (widget is not None and self.size_spin.isAncestorOf(widget)):
            return self.size_spin
        return None

    def eventFilter(self, watched, event):
        if not self._closed:
            owner = self._input_owner(QApplication.focusWidget())
            if (owner is not None and event.type() == QEvent.MouseButtonPress
                    and isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))
                    and watched is not owner and not owner.isAncestorOf(watched)):
                if owner is self.size_spin:
                    self.size_spin.interpretText()
                owner.clearFocus()
                self.surface._finish_editing()
                self.setFocus(Qt.MouseFocusReason)
            elif (owner is self.size_spin and event.type() == QEvent.KeyPress
                  and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
                self.size_spin.interpretText()
                self.setFocus()
                return True
        return super().eventFilter(watched, event)

    def toggle_playback(self):
        if self.player.playing:
            self.player.pause()
        else:
            self.player.play()

    def _step_speed(self, delta):
        self.speed_combo.setCurrentIndex(
            max(0, min(self.speed_combo.count() - 1, self.speed_combo.currentIndex() + delta))
        )

    @staticmethod
    def _cycle_combo(combo):
        if combo.count():
            combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())

    def _step_font_size(self, direction):
        self.size_spin.setValue(self.size_spin.value() + direction * self.size_spin.singleStep())

    def _error(self, message):
        self._has_error = True
        logger.error("Subtitle playback failed: {}", message)
        self.player.pause()
        self.status.setText(f"Could not prepare subtitles: {message}")
        self.slider.setEnabled(False)
        self.play_button.setEnabled(False)
        self.text_controls.setEnabled(False)
        for shortcut in self.shortcuts[:-1]:
            shortcut.setEnabled(False)

    def _cleanup(self, *_args):
        if self._closed:
            return
        self._closed = True
        QApplication.instance().removeEventFilter(self)
        QApplication.instance().focusChanged.disconnect(self._focus_changed)
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
