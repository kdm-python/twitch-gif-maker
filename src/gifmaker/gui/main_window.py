"""Main application window scaffold for the gifmaker GUI."""

import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QMovie, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from gifmaker.models.video_info import VideoInfo
from gifmaker.services.gif_export import GifExportError, export_gif
from gifmaker.video.probe import VideoProbeError, probe_video


class MarkerSeekSlider(QSlider):
    """Seek slider with draggable start/end frame markers and shaded selection."""

    selectionChanged = Signal(int, int)

    def __init__(
        self, orientation: Qt.Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(orientation, parent)
        self._total_frames = 0
        self._start_frame = 0
        self._end_frame = 0
        self._min_gap_frames = 2
        self._dragging_marker: str | None = None
        self._marker_hit_radius = 8

    def set_total_frames(self, total_frames: int) -> None:
        """Set total frame count and ensure marker bounds remain valid."""
        self._total_frames = max(total_frames, 0)
        if self._total_frames <= 0:
            self._start_frame = 0
            self._end_frame = 0
            self.update()
            return

        self.set_selection(self._start_frame, self._end_frame, emit_signal=False)

    def set_selection(
        self, start_frame: int, end_frame: int, *, emit_signal: bool = True
    ) -> None:
        """Set marker selection while enforcing ordering and minimum gap."""
        if self._total_frames <= 0:
            return

        max_frame = self._total_frames - 1
        min_end = min(max_frame, self._min_gap_frames)
        clamped_start = max(
            0, min(start_frame, max(0, max_frame - self._min_gap_frames))
        )
        clamped_end = max(min_end, min(end_frame, max_frame))

        if clamped_end - clamped_start < self._min_gap_frames:
            if self._dragging_marker == "start":
                clamped_start = max(0, clamped_end - self._min_gap_frames)
            else:
                clamped_end = min(max_frame, clamped_start + self._min_gap_frames)

        if clamped_end - clamped_start < self._min_gap_frames:
            clamped_start = 0
            clamped_end = min(max_frame, max(self._min_gap_frames, 0))

        changed = clamped_start != self._start_frame or clamped_end != self._end_frame
        self._start_frame = clamped_start
        self._end_frame = clamped_end
        self.update()

        if changed and emit_signal:
            self.selectionChanged.emit(self._start_frame, self._end_frame)

    def selection(self) -> tuple[int, int]:
        """Return current start/end frame selection."""
        return self._start_frame, self._end_frame

    def nudge_start(self, delta: int) -> None:
        """Move start marker by delta frames with clamped bounds."""
        self._dragging_marker = "start"
        self.set_selection(self._start_frame + delta, self._end_frame)
        self._dragging_marker = None

    def nudge_end(self, delta: int) -> None:
        """Move end marker by delta frames with clamped bounds."""
        self._dragging_marker = "end"
        self.set_selection(self._start_frame, self._end_frame + delta)
        self._dragging_marker = None

    def _groove_rect(self) -> tuple[int, int, int]:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.CC_Slider,
            option,
            QStyle.SC_SliderGroove,
            self,
        )
        left = groove.left()
        right = groove.right()
        width = max(1, right - left)
        return left, right, width

    def _frame_to_x(self, frame: int) -> int:
        if self._total_frames <= 1:
            left, _, _ = self._groove_rect()
            return left

        left, _, width = self._groove_rect()
        ratio = frame / (self._total_frames - 1)
        return left + round(ratio * width)

    def _x_to_frame(self, x_pos: int) -> int:
        if self._total_frames <= 1:
            return 0

        left, right, width = self._groove_rect()
        clamped_x = max(left, min(x_pos, right))
        ratio = (clamped_x - left) / width
        return round(ratio * (self._total_frames - 1))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._total_frames <= 0:
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.CC_Slider,
            option,
            QStyle.SC_SliderGroove,
            self,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        start_x = self._frame_to_x(self._start_frame)
        end_x = self._frame_to_x(self._end_frame)

        if end_x > start_x:
            selection_color = self.palette().highlight().color()
            selection_color.setAlpha(90)
            painter.fillRect(
                start_x, groove.top(), end_x - start_x, groove.height(), selection_color
            )

        marker_color = self.palette().highlight().color()
        painter.setPen(marker_color)
        painter.drawLine(start_x, groove.top() - 4, start_x, groove.bottom() + 4)
        painter.drawLine(end_x, groove.top() - 4, end_x, groove.bottom() + 4)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton or self._total_frames <= 0:
            super().mousePressEvent(event)
            return

        press_x = event.position().toPoint().x()
        start_x = self._frame_to_x(self._start_frame)
        end_x = self._frame_to_x(self._end_frame)
        start_dist = abs(press_x - start_x)
        end_dist = abs(press_x - end_x)

        if min(start_dist, end_dist) <= self._marker_hit_radius:
            self._dragging_marker = "start" if start_dist <= end_dist else "end"
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging_marker is None:
            super().mouseMoveEvent(event)
            return

        frame = self._x_to_frame(event.position().toPoint().x())
        if self._dragging_marker == "start":
            self.set_selection(frame, self._end_frame)
        else:
            self.set_selection(self._start_frame, frame)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging_marker is None:
            super().mouseReleaseEvent(event)
            return

        self._dragging_marker = None
        event.accept()


class MainWindow(QMainWindow):
    """Primary window scaffold for video/GIF import and export workflows."""

    selection_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.current_video_path: str | None = None
        self.clip_start_time: float | None = None
        self.clip_end_time: float | None = None
        self.start_frame: int = 0
        self.end_frame: int = 0
        self.total_frames: int = 0
        self.current_video_fps: float = 24.0
        self.minimum_selection_gap_frames: int = 2
        self._is_seek_dragging = False
        self._pending_video_path: str | None = None
        self._pending_video_info: VideoInfo | None = None
        self._previous_video_path: str | None = None
        self._previous_source: QUrl | None = None
        self._previous_info_texts: dict[str, str] = {}
        self._restoring_previous_source = False
        self._preview_temp_file: Path | None = None
        self._preview_movie: QMovie | None = None
        self._last_preview_settings: dict[str, float | int | str] | None = None

        self.setWindowTitle("GIF Maker")

        self.create_menu()
        self.build_layout()
        self._fit_to_available_screen()
        logger.info("Main window initialized.")

    def create_menu(self) -> None:
        """Create the top-level menu structure."""
        menu_bar = self.menuBar()
        menu_bar.addMenu("File")
        menu_bar.addMenu("Edit")
        menu_bar.addMenu("View")
        menu_bar.addMenu("Help")

    def create_preview_panel(self) -> QGroupBox:
        """Create the expandable preview section."""
        group = QGroupBox("Video Preview")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(group)

        self.video_widget = QVideoWidget(group)
        self.video_widget.setMinimumHeight(160)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("border: 1px solid palette(mid);")

        self.media_player = QMediaPlayer(group)
        self.audio_output = QAudioOutput(group)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.media_player.errorOccurred.connect(self.on_media_error)
        self.media_player.durationChanged.connect(self.on_duration_changed)
        self.media_player.positionChanged.connect(self.on_position_changed)
        self.media_player.playbackStateChanged.connect(self._update_play_button_state)

        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_preview_playback)

        self.set_start_button = QPushButton("Set Start")
        self.set_start_button.clicked.connect(self.set_clip_start)

        self.set_end_button = QPushButton("Set End")
        self.set_end_button.clicked.connect(self.set_clip_end)

        self.seek_slider = MarkerSeekSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.set_total_frames(0)
        self.seek_slider.sliderPressed.connect(self.on_seek_slider_pressed)
        self.seek_slider.sliderMoved.connect(self.on_seek_slider_moved)
        self.seek_slider.sliderReleased.connect(self.on_seek_slider_released)
        self.seek_slider.selectionChanged.connect(self.on_scrub_selection_changed)

        self.seek_time_label = QLabel("00:00:00 / 00:00:00")

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.set_start_button)
        controls_layout.addWidget(self.set_end_button)
        controls_layout.addWidget(self.seek_slider, stretch=1)
        controls_layout.addWidget(self.seek_time_label)

        marker_controls = QHBoxLayout()

        self.start_frame_label = QLabel("Start: --:--:--.---")
        self.start_nudge_back_button = QPushButton("−0.01")
        self.start_nudge_back_button.clicked.connect(
            lambda: self.nudge_start_frame(-self._seconds_to_frame(0.01))
        )
        self.start_nudge_forward_button = QPushButton("+0.01")
        self.start_nudge_forward_button.clicked.connect(
            lambda: self.nudge_start_frame(self._seconds_to_frame(0.01))
        )

        self.end_frame_label = QLabel("End: --:--:--.---")
        self.end_nudge_back_button = QPushButton("−0.01")
        self.end_nudge_back_button.clicked.connect(
            lambda: self.nudge_end_frame(-self._seconds_to_frame(0.01))
        )
        self.end_nudge_forward_button = QPushButton("+0.01")
        self.end_nudge_forward_button.clicked.connect(
            lambda: self.nudge_end_frame(self._seconds_to_frame(0.01))
        )

        marker_controls.addWidget(self.start_frame_label)
        marker_controls.addWidget(self.start_nudge_back_button)
        marker_controls.addWidget(self.start_nudge_forward_button)
        marker_controls.addSpacing(12)
        marker_controls.addWidget(self.end_frame_label)
        marker_controls.addWidget(self.end_nudge_back_button)
        marker_controls.addWidget(self.end_nudge_forward_button)
        marker_controls.addStretch(1)

        self.clip_selection_label = QLabel()
        self.update_clip_selection_display()

        self._update_play_button_state()

        layout.addWidget(self.video_widget)
        layout.addLayout(controls_layout)
        layout.addLayout(marker_controls)
        layout.addWidget(self.clip_selection_label)
        return group

    def create_export_panel(self) -> QGroupBox:
        """Create export settings with placeholder controls."""
        group = QGroupBox("Export")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        group.setMinimumHeight(190)

        root_layout = QVBoxLayout(group)
        form_layout = QFormLayout()

        self.export_start_input = QLineEdit()
        self.export_start_input.setPlaceholderText("e.g. 00:00:00")

        self.export_end_input = QLineEdit()
        self.export_end_input.setPlaceholderText("e.g. 00:05:00")

        self.export_fps_input = QSpinBox()
        self.export_fps_input.setRange(1, 120)
        self.export_fps_input.setValue(24)

        self.export_width_input = QSpinBox()
        self.export_width_input.setRange(1, 8192)
        self.export_width_input.setValue(640)

        form_layout.addRow("Start", self.export_start_input)
        form_layout.addRow("End", self.export_end_input)
        form_layout.addRow("FPS", self.export_fps_input)
        form_layout.addRow("Width", self.export_width_input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.generate_preview_button = QPushButton("Generate Preview")
        self.generate_preview_button.clicked.connect(self.generate_gif_preview)

        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_gif_from_selection)

        button_row.addWidget(self.generate_preview_button)
        button_row.addWidget(self.export_button)

        self.export_status_label = QLabel("Status: -")

        root_layout.addLayout(form_layout)
        root_layout.addLayout(button_row)
        root_layout.addWidget(self.export_status_label)

        return group

    def create_gif_preview_panel(self) -> QGroupBox:
        """Create the GIF preview panel shown below the video player."""
        preview_group = QGroupBox("GIF Preview")
        preview_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        preview_layout = QVBoxLayout(preview_group)

        self.gif_preview_label = QLabel("Generate preview to display GIF")
        self.gif_preview_label.setAlignment(Qt.AlignCenter)
        self.gif_preview_label.setMinimumHeight(120)
        self.gif_preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.gif_preview_label.setStyleSheet("border: 1px solid palette(mid);")

        preview_controls = QHBoxLayout()
        self.gif_preview_play_button = QPushButton("Play")
        self.gif_preview_play_button.clicked.connect(self.play_gif_preview)
        self.gif_preview_pause_button = QPushButton("Pause")
        self.gif_preview_pause_button.clicked.connect(self.pause_gif_preview)

        preview_controls.addStretch(1)
        preview_controls.addWidget(self.gif_preview_play_button)
        preview_controls.addWidget(self.gif_preview_pause_button)

        preview_layout.addWidget(self.gif_preview_label)
        preview_layout.addLayout(preview_controls)

        return preview_group

    def build_layout(self) -> None:
        """Assemble all panels into the window's central widget."""
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        open_button = QPushButton("Open Video File")
        open_button.clicked.connect(self.open_file_dialog)
        root_layout.addWidget(open_button)

        video_info_group = self.create_video_info_panel()
        root_layout.addWidget(video_info_group)

        video_preview_group = self.create_preview_panel()
        gif_preview_group = self.create_gif_preview_panel()
        export_group = self.create_export_panel()

        self.preview_splitter = QSplitter(Qt.Vertical)
        self.preview_splitter.setObjectName("preview_splitter")
        self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.addWidget(video_preview_group)
        self.preview_splitter.addWidget(gif_preview_group)
        self.preview_splitter.addWidget(export_group)
        self.preview_splitter.setSizes([260, 180, 210])
        self.preview_splitter.setStretchFactor(0, 1)
        self.preview_splitter.setStretchFactor(1, 1)
        self.preview_splitter.setStretchFactor(2, 0)

        root_layout.addWidget(self.preview_splitter, stretch=1)

        self.setCentralWidget(central)

    def _fit_to_available_screen(self) -> None:
        """Keep initial and maximum window size inside available screen bounds."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1100, 760)
            return

        available = screen.availableGeometry()
        target_width = min(1100, available.width())
        target_height = min(760, available.height())

        self.setMaximumSize(available.width(), available.height())
        self.resize(target_width, target_height)

    def create_video_info_panel(self) -> QGroupBox:
        """Create a panel to display video metadata."""
        group = QGroupBox("Video Information")
        layout = QFormLayout(group)

        self.video_info_labels: dict[str, QLabel] = {
            "File": QLabel("-"),
            "Duration": QLabel("-"),
            "Resolution": QLabel("-"),
            "FPS": QLabel("-"),
            "Codec": QLabel("-"),
        }

        for label, widget in self.video_info_labels.items():
            layout.addRow(label, widget)

        return group

    def update_video_info(
        self,
        file_path: str,
        *,
        duration: float,
        width: int,
        height: int,
        fps: float,
        codec: str,
    ) -> None:
        """Update the video information panel with probed metadata."""
        self.video_info_labels["File"].setText(file_path)
        self.video_info_labels["Duration"].setText(f"{duration:.2f} s")
        self.video_info_labels["Resolution"].setText(f"{width}x{height}")
        self.video_info_labels["FPS"].setText(f"{fps:.2f}")
        self.video_info_labels["Codec"].setText(codec)

    def open_file_dialog(self) -> None:
        """Open a file dialog to select a video file."""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        file_dialog.setNameFilter("Video Files (*.mp4 *.avi *.mov)")
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                previous_path = self.current_video_path
                selected_path = selected_files[0]
                self.current_video_path = selected_path
                logger.info("Selected file: {}", self.current_video_path)

                try:
                    video_info = probe_video(selected_path)
                except VideoProbeError as exc:
                    self.current_video_path = previous_path
                    logger.error(
                        "Failed to probe selected video '{}': {}",
                        selected_path,
                        exc,
                    )
                    return

                self.load_video_preview(selected_path, video_info, previous_path)
            else:
                logger.info("No file selected.")
        else:
            logger.info("File dialog cancelled.")

    def load_video_preview(
        self,
        file_path: str,
        video_info: VideoInfo,
        previous_video_path: str | None,
    ) -> None:
        """Load the selected video into the preview area."""
        logger.info("Loading video preview...")
        self._pending_video_path = file_path
        self._pending_video_info = video_info
        self._previous_video_path = previous_video_path
        self._previous_source = self.media_player.source()
        self._previous_info_texts = {
            key: label.text() for key, label in self.video_info_labels.items()
        }

        self.media_player.stop()
        self.media_player.setSource(QUrl.fromLocalFile(file_path))

    def update_video_info_from_model(
        self, file_path: str, video_info: VideoInfo
    ) -> None:
        """Update the panel from a VideoInfo model instance."""
        self.update_video_info(
            file_path,
            duration=video_info.duration,
            width=video_info.width,
            height=video_info.height,
            fps=video_info.fps,
            codec=video_info.codec,
        )

    def toggle_preview_playback(self) -> None:
        """Toggle preview playback between play and pause."""
        if self.media_player.source().isEmpty():
            return

        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

        self._update_play_button_state()

    def _seconds_to_frame(self, seconds: float) -> int:
        """Convert seconds to a frame delta using the current preview FPS."""
        if self.current_video_fps <= 0:
            return 0
        return max(1, int(round(seconds * self.current_video_fps)))

    def on_seek_slider_pressed(self) -> None:
        """Mark that the user is actively dragging the seek handle."""
        self._is_seek_dragging = True

    def on_seek_slider_moved(self, position: int) -> None:
        """Update the displayed time while dragging without seeking yet."""
        self._update_seek_time_label(current_ms=position)

    def on_seek_slider_released(self) -> None:
        """Seek once when the user releases the slider handle."""
        self._is_seek_dragging = False
        target_position = self.seek_slider.value()
        self.media_player.setPosition(target_position)
        self._update_seek_time_label(current_ms=target_position)

    def on_duration_changed(self, duration: int) -> None:
        """Sync the seek range with loaded media duration."""
        self.total_frames = self._duration_to_frame_count(duration)
        seek_max = max(self.total_frames - 1, 0)
        self.seek_slider.setRange(0, seek_max)
        self.seek_slider.set_total_frames(self.total_frames)

        if self.total_frames > 0:
            default_end = max(self.minimum_selection_gap_frames, self.total_frames - 1)
            self.seek_slider.set_selection(0, default_end, emit_signal=False)
            self.on_scrub_selection_changed(0, default_end)
        else:
            self.on_scrub_selection_changed(0, 0)

        self._update_seek_time_label()

    def on_position_changed(self, position: int) -> None:
        """Sync the seek slider with the current playback position."""
        if not self._is_seek_dragging:
            self.seek_slider.setValue(self._ms_to_frame(position))
            self._update_seek_time_label(current_ms=position)
        self._update_play_button_state()

    def on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Handle media load lifecycle events for preview updates."""
        if self._restoring_previous_source:
            return

        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            if self._pending_video_path is None or self._pending_video_info is None:
                return

            self.media_player.setPosition(0)
            self.media_player.pause()
            self.reset_clip_selection()
            self._clear_preview_state(remove_temp_file=True)
            self.current_video_fps = max(self._pending_video_info.fps, 1.0)
            self.update_video_info_from_model(
                self._pending_video_path,
                self._pending_video_info,
            )
            logger.info("Video loaded successfully.")
            self._clear_pending_preview_state()
            self._update_play_button_state()

        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.handle_preview_load_failure()

    def on_media_error(
        self,
        _error: QMediaPlayer.Error,
        _error_message: str,
    ) -> None:
        """Handle media player load errors safely."""
        self.handle_preview_load_failure()

    def handle_preview_load_failure(self) -> None:
        """Restore previous preview state after a failed load attempt."""
        if self._pending_video_path is None:
            return

        logger.error("Failed to load preview.")
        self.current_video_path = self._previous_video_path

        if self._previous_info_texts:
            for key, value in self._previous_info_texts.items():
                self.video_info_labels[key].setText(value)

        if self._previous_source is not None and not self._previous_source.isEmpty():
            self._restoring_previous_source = True
            self.media_player.stop()
            self.media_player.setSource(self._previous_source)
            self.media_player.pause()
            self._restoring_previous_source = False
        else:
            self.media_player.stop()
            self.media_player.setSource(QUrl())
            self.seek_slider.setValue(0)
            self.seek_slider.setRange(0, 0)
            self._update_seek_time_label(current_ms=0)

        self._clear_pending_preview_state()

    def _clear_pending_preview_state(self) -> None:
        """Clear temporary state used while loading a new preview."""
        self._pending_video_path = None
        self._pending_video_info = None
        self._previous_video_path = None
        self._previous_source = None
        self._previous_info_texts = {}

    def reset_clip_selection(self) -> None:
        """Reset the currently selected clip range."""
        if self.total_frames <= 0:
            self.start_frame = 0
            self.end_frame = 0
            self.clip_start_time = None
            self.clip_end_time = None
            self.update_clip_selection_display()
            return

        default_end = max(self.minimum_selection_gap_frames, self.total_frames - 1)
        self.seek_slider.set_selection(0, default_end, emit_signal=False)
        self.on_scrub_selection_changed(0, default_end)

    def set_clip_start(self) -> None:
        """Store the current preview position as clip start."""
        if self.media_player.source().isEmpty():
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Cannot set clip start without a loaded video.")
            return

        current_frame = self._ms_to_frame(self.media_player.position())
        self.seek_slider.set_selection(current_frame, self.end_frame)
        logger.info("Clip start set at frame {}", current_frame)

    def set_clip_end(self) -> None:
        """Store the current preview position as clip end."""
        if self.media_player.source().isEmpty():
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Cannot set clip end without a loaded video.")
            return

        current_frame = self._ms_to_frame(self.media_player.position())
        self.seek_slider.set_selection(self.start_frame, current_frame)
        logger.info("Clip end set at frame {}", current_frame)

    def nudge_start_frame(self, delta: int) -> None:
        """Nudge the start marker by one frame in either direction."""
        if self.total_frames <= 0:
            return
        self.seek_slider.nudge_start(delta)

    def nudge_end_frame(self, delta: int) -> None:
        """Nudge the end marker by one frame in either direction."""
        if self.total_frames <= 0:
            return
        self.seek_slider.nudge_end(delta)

    def _update_play_button_state(self, _state=None) -> None:
        """Keep the play button text aligned with playback state."""
        if self.media_player.source().isEmpty():
            self.play_button.setText("▶ Play")
            return

        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("⏸ Pause")
        else:
            self.play_button.setText("▶ Play")

    def on_scrub_selection_changed(self, start_frame: int, end_frame: int) -> None:
        """Sync frame model, labels, and selection signal from slider markers."""
        self.start_frame = start_frame
        self.end_frame = end_frame

        if self.total_frames > 0:
            self.clip_start_time = self.start_frame / self.current_video_fps
            self.clip_end_time = self.end_frame / self.current_video_fps
        else:
            self.clip_start_time = None
            self.clip_end_time = None

        self.update_clip_selection_display()
        self.selection_changed.emit(self.start_frame, self.end_frame)

    def update_clip_selection_display(self) -> None:
        """Refresh the clip selection summary shown in the preview panel."""
        if (
            self.total_frames <= 0
            or self.clip_start_time is None
            or self.clip_end_time is None
        ):
            self.start_frame_label.setText("Start: --:--:--.---")
            self.end_frame_label.setText("End: --:--:--.---")
            self.clip_selection_label.setText("Selection:\nNot selected")
            return

        start_text = self._format_timestamp_from_frame(self.start_frame)
        end_text = self._format_timestamp_from_frame(self.end_frame)
        duration = self.clip_end_time - self.clip_start_time
        self.start_frame_label.setText(f"Start {start_text}")
        self.end_frame_label.setText(f"End {end_text}")
        self.clip_selection_label.setText(f"Duration: {duration:.3f}s")

    def _update_seek_time_label(self, current_ms: int | None = None) -> None:
        """Update the current/total playback time text."""
        if current_ms is None:
            current_ms = self._frame_to_ms(self.seek_slider.value())
        total_ms = self._frame_to_ms(max(self.total_frames - 1, 0))
        self.seek_time_label.setText(
            f"{self._format_ms(current_ms)} / {self._format_ms(total_ms)}"
        )

    def _duration_to_frame_count(self, duration_ms: int) -> int:
        """Convert media duration to total frame count."""
        if duration_ms <= 0 or self.current_video_fps <= 0:
            return 0
        duration_seconds = duration_ms / 1000.0
        return max(1, round(duration_seconds * self.current_video_fps))

    def _ms_to_frame(self, milliseconds: int) -> int:
        """Convert milliseconds to nearest frame index."""
        if self.total_frames <= 0 or self.current_video_fps <= 0:
            return 0
        frame = round((milliseconds / 1000.0) * self.current_video_fps)
        return max(0, min(frame, self.total_frames - 1))

    def _frame_to_ms(self, frame_index: int) -> int:
        """Convert frame index to milliseconds."""
        if self.current_video_fps <= 0:
            return 0
        return round((frame_index / self.current_video_fps) * 1000.0)

    def _format_timestamp_from_frame(self, frame_index: int) -> str:
        """Format a frame index as HH:MM:SS.mmm."""
        total_ms = self._frame_to_ms(frame_index)
        total_seconds, milliseconds = divmod(max(total_ms, 0), 1000)
        hours, remaining = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remaining, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _format_ms(self, milliseconds: int) -> str:
        """Format milliseconds as MM:SS:CC or HH:MM:SS:CC."""
        total_centiseconds = round(max(milliseconds, 0) / 10)

        hours = total_centiseconds // 360_000
        remaining_after_hours = total_centiseconds % 360_000
        minutes = remaining_after_hours // 6_000
        remaining_after_minutes = remaining_after_hours % 6_000
        seconds = remaining_after_minutes // 100
        centiseconds = remaining_after_minutes % 100

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{centiseconds:02d}"
        return f"{minutes:02d}:{seconds:02d}:{centiseconds:02d}"

    def export_gif_from_selection(self) -> None:
        """Export a selected time segment from the current video to GIF."""
        if self.current_video_path is None:
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Export requested without a loaded video.")
            return

        default_save_name = "output.gif"
        video_path = Path(self.current_video_path)
        default_save_name = str(video_path.with_suffix(".gif"))

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GIF",
            default_save_name,
            "GIF Files (*.gif)",
        )
        if not output_path:
            self.export_status_label.setText("Status: Export cancelled.")
            logger.info("GIF export cancelled by user.")
            return

        if (
            self._preview_temp_file is not None
            and self._preview_temp_file.exists()
            and self._last_preview_settings is not None
        ):
            self.export_status_label.setText("Status: Exporting preview...")
            logger.info(
                "Exporting from last generated preview '{}' to '{}'",
                self._preview_temp_file,
                output_path,
            )
            try:
                shutil.copyfile(self._preview_temp_file, output_path)
            except OSError as exc:
                self.export_status_label.setText(f"Status: Export failed: {exc}")
                logger.error("Failed to export from preview file: {}", exc)
                return

            self.export_status_label.setText("Status: Export complete.")
            logger.info("GIF export complete: {}", output_path)
            return

        try:
            render_settings = self._resolve_render_settings()
        except ValueError as exc:
            self.export_status_label.setText(f"Status: {exc}")
            logger.error("Invalid export time input: {}", exc)
            return

        self.export_status_label.setText("Status: Exporting...")
        logger.info("Starting GIF export to '{}'", output_path)

        try:
            export_gif(
                self.current_video_path,
                output_path,
                start_seconds=render_settings["start_seconds"],
                end_seconds=render_settings["end_seconds"],
                fps=render_settings["fps"],
                width=render_settings["width"],
            )
        except GifExportError as exc:
            self.export_status_label.setText(f"Status: Export failed: {exc}")
            logger.error("GIF export failed: {}", exc)
            return

        self.export_status_label.setText("Status: Export complete.")
        logger.info("GIF export complete: {}", output_path)

    def generate_gif_preview(self) -> None:
        """Generate a temporary GIF preview from the current settings."""
        if self.current_video_path is None:
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Preview requested without a loaded video.")
            return

        try:
            render_settings = self._resolve_render_settings()
        except ValueError as exc:
            self.export_status_label.setText(f"Status: {exc}")
            logger.error("Invalid preview time input: {}", exc)
            return

        fd, temp_name = tempfile.mkstemp(
            prefix="gifmaker-preview-",
            suffix=".gif",
        )
        os.close(fd)
        temp_file = Path(temp_name)
        previous_preview_file = self._preview_temp_file

        self.export_status_label.setText("Status: Generating preview...")
        logger.info("Generating preview GIF: {}", temp_file)

        try:
            export_gif(
                self.current_video_path,
                temp_file,
                start_seconds=render_settings["start_seconds"],
                end_seconds=render_settings["end_seconds"],
                fps=render_settings["fps"],
                width=render_settings["width"],
            )
            self._set_preview_movie(temp_file)
        except (GifExportError, RuntimeError) as exc:
            self._remove_file_if_exists(temp_file)
            self.export_status_label.setText(f"Status: Preview failed: {exc}")
            logger.error("Preview generation failed: {}", exc)
            return

        self._preview_temp_file = temp_file
        self._last_preview_settings = {
            "source_path": self.current_video_path,
            **render_settings,
        }
        if previous_preview_file is not None and previous_preview_file != temp_file:
            self._remove_file_if_exists(previous_preview_file)

        self.export_status_label.setText("Status: Preview ready. Click Export to save.")
        logger.info("Preview generation complete: {}", temp_file)

    def play_gif_preview(self) -> None:
        """Play the generated GIF preview."""
        if self._preview_movie is None:
            return

        if self._preview_movie.state() == QMovie.MovieState.NotRunning:
            self._preview_movie.start()
            return

        self._preview_movie.setPaused(False)

    def pause_gif_preview(self) -> None:
        """Pause the generated GIF preview."""
        if self._preview_movie is None:
            return

        self._preview_movie.setPaused(True)

    def _resolve_render_settings(self) -> dict[str, float | int]:
        """Resolve start/end/fps/width from clip selection or export controls."""
        if self.clip_start_time is not None and self.clip_end_time is not None:
            start_seconds = self.clip_start_time
            end_seconds = self.clip_end_time
            logger.info(
                "Using selected clip range for render: {:.2f}s to {:.2f}s",
                start_seconds,
                end_seconds,
            )
        else:
            start_seconds = self._parse_time_input(
                self.export_start_input.text().strip() or "0"
            )
            end_text = self.export_end_input.text().strip()
            if not end_text:
                duration_ms = self.media_player.duration()
                if duration_ms <= 0:
                    raise ValueError("End time is required before export")
                end_seconds = duration_ms / 1000.0
            else:
                end_seconds = self._parse_time_input(end_text)

        if end_seconds <= start_seconds:
            raise ValueError("End time must be greater than start time")

        return {
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "fps": self.export_fps_input.value(),
            "width": self.export_width_input.value(),
        }

    def _set_preview_movie(self, gif_path: Path) -> None:
        """Display a generated GIF in the preview panel."""
        movie = QMovie(str(gif_path))
        if not movie.isValid():
            raise RuntimeError("Generated preview GIF could not be loaded")

        if self._preview_movie is not None:
            self._preview_movie.stop()

        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self.gif_preview_label.setMovie(movie)
        movie.start()
        self._preview_movie = movie

    def _clear_preview_state(self, *, remove_temp_file: bool) -> None:
        """Clear preview UI state and optionally remove the temp GIF file."""
        preview_file = self._preview_temp_file
        if self._preview_movie is not None:
            self._preview_movie.stop()
            self._preview_movie = None

        self.gif_preview_label.clear()
        self.gif_preview_label.setText("Generate preview to display GIF")

        self._preview_temp_file = None
        self._last_preview_settings = None

        if remove_temp_file and preview_file is not None:
            self._remove_file_if_exists(preview_file)

    def _remove_file_if_exists(self, file_path: Path) -> None:
        """Best-effort removal for temporary preview artifacts."""
        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove preview file '{}': {}", file_path, exc)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle app close by cleaning up preview temp files."""
        self._clear_preview_state(remove_temp_file=True)
        super().closeEvent(event)

    def _parse_time_input(self, value: str) -> float:
        """Parse seconds, MM:SS:CC, HH:MM:SS:CC, or legacy HH:MM:SS.xx."""
        if ":" not in value:
            seconds = float(value)
            if seconds < 0:
                raise ValueError("Time values must be non-negative")
            return seconds

        parts = value.split(":")
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])

            if minutes < 0 or seconds < 0:
                raise ValueError("Time values must be non-negative")
            if seconds >= 60:
                raise ValueError("Seconds must be less than 60")

            return (minutes * 60) + seconds

        if len(parts) == 3:
            if "." in parts[2]:
                # Backward-compatible parse for existing HH:MM:SS.xx entries.
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])

                if hours < 0 or minutes < 0 or seconds < 0:
                    raise ValueError("Time values must be non-negative")
                if minutes >= 60 or seconds >= 60:
                    raise ValueError("Minutes and seconds must be less than 60")

                return (hours * 3600) + (minutes * 60) + seconds

            minutes = int(parts[0])
            seconds = int(parts[1])
            centiseconds = int(parts[2])

            if minutes < 0 or seconds < 0 or centiseconds < 0:
                raise ValueError("Time values must be non-negative")
            if seconds >= 60:
                raise ValueError("Seconds must be less than 60")
            if centiseconds >= 100:
                raise ValueError("Centiseconds must be less than 100")

            return (minutes * 60) + seconds + (centiseconds / 100)

        if len(parts) == 4:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            centiseconds = int(parts[3])

            if hours < 0 or minutes < 0 or seconds < 0 or centiseconds < 0:
                raise ValueError("Time values must be non-negative")
            if minutes >= 60 or seconds >= 60:
                raise ValueError("Minutes and seconds must be less than 60")
            if centiseconds >= 100:
                raise ValueError("Centiseconds must be less than 100")

            return (hours * 3600) + (minutes * 60) + seconds + (centiseconds / 100)

        raise ValueError("Time must be seconds, MM:SS:CC, HH:MM:SS:CC, or HH:MM:SS.xx")
