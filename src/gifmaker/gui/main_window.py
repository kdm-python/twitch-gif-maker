"""Main application window scaffold for the gifmaker GUI."""

import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QKeyEvent,
    QMovie,
    QPixmap,
    # QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gifmaker.gui.crop_overlay_label import CropOverlayLabel
from gifmaker.gui.marker_seek_slider import MarkerSeekSlider
from gifmaker.models.video_info import VideoInfo
from gifmaker.services.gif_export import GifExportError, export_gif, export_webp
from gifmaker.video.probe import VideoProbeError, probe_video


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
        self._previous_file_info_text: str = "No file loaded"
        self._previous_meta_info_text: str = (
            "Duration: - | Resolution: - | FPS: - | Codec: -"
        )
        self._restoring_previous_source = False
        self._preview_temp_file: Path | None = None
        self._preview_movie: QMovie | None = None
        # Cached-frame preview state (optional faster/smoother playback path)
        self._preview_frame_cache: list[QPixmap] | None = None
        self._preview_frame_durations: list[int] | None = None
        self._preview_frame_timer: QTimer | None = None
        self._preview_frame_index: int = 0

        self._last_preview_settings: dict[str, float | int | str] | None = None
        self._current_crop: tuple[int, int, int, int] | None = None
        self._current_video_info: VideoInfo | None = None

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

        self.mute_button = QPushButton("Mute")
        self.mute_button.clicked.connect(self.toggle_mute)

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.set_start_button)
        controls_layout.addWidget(self.set_end_button)
        controls_layout.addWidget(self.seek_slider, stretch=1)
        controls_layout.addWidget(self.seek_time_label)
        controls_layout.addWidget(self.mute_button)

        self.start_frame_label = QLabel("Start: --:--:--.---")
        self.start_nudge_back_button = QPushButton("−0.01")
        self.start_nudge_back_button.clicked.connect(
            lambda: self.nudge_start_frame(-self._seconds_to_frame(0.01))
        )
        marker_controls = QHBoxLayout()
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
        # Put duration/selection summary on the same row as the marker nudges
        marker_controls.addSpacing(12)
        marker_controls.addWidget(self.clip_selection_label)

        self._update_play_button_state()

        layout.addWidget(self.video_widget)
        layout.addLayout(controls_layout)
        layout.addLayout(marker_controls)
        return group

    def create_export_controls_row(self) -> QWidget:
        """Create compact, single-row precision and render settings controls."""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self.export_start_input = QLineEdit()
        self.export_start_input.setPlaceholderText("MM:SS:CC")
        self.export_start_input.setFixedWidth(92)
        self.export_start_input.editingFinished.connect(self.on_export_start_adjusted)

        self.export_end_input = QLineEdit()
        self.export_end_input.setPlaceholderText("MM:SS:CC")
        self.export_end_input.setFixedWidth(92)
        self.export_end_input.editingFinished.connect(self.on_export_end_adjusted)

        self.export_fps_input = QSpinBox()
        self.export_fps_input.setRange(1, 120)
        self.export_fps_input.setValue(24)
        self.export_fps_input.setFixedWidth(78)

        self.export_width_input = QSpinBox()
        self.export_width_input.setRange(1, 8192)
        self.export_width_input.setValue(640)
        self.export_width_input.setFixedWidth(92)

        self.generate_preview_button = QPushButton("Generate Preview")
        self.generate_preview_button.clicked.connect(self.generate_gif_preview)

        self.apply_crop_button = QPushButton("Apply Crop")
        self.apply_crop_button.clicked.connect(self.apply_crop_to_preview)

        self.reset_crop_button = QPushButton("Reset Crop")
        self.reset_crop_button.clicked.connect(self.reset_preview_crop)

        # GIF preview play/pause controls (placed here to save vertical space)
        self.gif_preview_play_button = QPushButton("Play")
        self.gif_preview_play_button.clicked.connect(self.play_gif_preview)
        self.gif_preview_pause_button = QPushButton("Pause")
        self.gif_preview_pause_button.clicked.connect(self.pause_gif_preview)

        layout.addWidget(QLabel("Start"))
        layout.addWidget(self.export_start_input)
        layout.addWidget(QLabel("End"))
        layout.addWidget(self.export_end_input)
        layout.addSpacing(8)
        layout.addWidget(QLabel("FPS"))
        layout.addWidget(self.export_fps_input)
        layout.addWidget(QLabel("Width"))
        layout.addWidget(self.export_width_input)
        layout.addSpacing(8)
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["GIF", "WebP"])
        layout.addWidget(QLabel("Format"))
        layout.addWidget(self.export_format_combo)
        layout.addSpacing(8)
        layout.addWidget(self.gif_preview_play_button)
        layout.addWidget(self.gif_preview_pause_button)
        layout.addStretch(1)
        layout.addWidget(self.generate_preview_button)
        layout.addWidget(self.apply_crop_button)
        layout.addWidget(self.reset_crop_button)

        return row

    def create_bottom_toolbar(self) -> QWidget:
        """Create a slim bottom toolbar for compact file info and exporting."""
        toolbar = QWidget(self)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        info_column = QVBoxLayout()
        info_column.setContentsMargins(0, 0, 0, 0)
        info_column.setSpacing(2)

        self.video_file_label = QLabel("No file loaded")
        self.video_meta_label = QLabel(
            "Duration: - | Resolution: - | FPS: - | Codec: -"
        )
        self.export_status_label = QLabel("Status: -")

        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.setSpacing(12)
        info_row.addWidget(self.video_meta_label)
        info_row.addWidget(self.export_status_label)
        info_row.addStretch(1)

        info_column.addWidget(self.video_file_label)
        info_column.addLayout(info_row)

        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_gif_from_selection)

        layout.addLayout(info_column, stretch=1)
        layout.addWidget(self.export_button)

        return toolbar

    def create_gif_preview_panel(self) -> QGroupBox:
        """Create the GIF preview panel shown below the video player."""
        preview_group = QGroupBox("GIF Preview")
        preview_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        preview_layout = QVBoxLayout(preview_group)

        self.gif_preview_label = CropOverlayLabel("Generate preview to display GIF")
        self.gif_preview_label.setAlignment(Qt.AlignCenter)
        # Give the GIF preview a larger minimum height to prioritize it
        self.gif_preview_label.setMinimumHeight(220)
        self.gif_preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.gif_preview_label.setStyleSheet("border: 1px solid palette(mid);")
        self.gif_preview_label.cropChanged.connect(self._on_crop_changed)
        self.gif_preview_label.cropCleared.connect(self._on_crop_cleared)
        # GIF preview area (play/pause controls are placed in the export row)
        preview_layout.addWidget(self.gif_preview_label)

        return preview_group

    def build_layout(self) -> None:
        """Assemble all panels into the window's central widget."""
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        open_button = QPushButton("Open Video File")
        open_button.clicked.connect(self.open_file_dialog)
        root_layout.addWidget(open_button)

        video_preview_group = self.create_preview_panel()
        gif_preview_group = self.create_gif_preview_panel()

        self.preview_splitter = QSplitter(Qt.Vertical)
        self.preview_splitter.setObjectName("preview_splitter")
        self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.addWidget(video_preview_group)
        self.preview_splitter.addWidget(gif_preview_group)
        # Favor the GIF preview panel vertical space
        self.preview_splitter.setSizes([260, 340])
        self.preview_splitter.setStretchFactor(0, 1)
        self.preview_splitter.setStretchFactor(1, 2)

        root_layout.addWidget(self.preview_splitter, stretch=1)
        root_layout.addWidget(self.create_export_controls_row())
        root_layout.addWidget(self.create_bottom_toolbar())

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
        """Update compact video metadata shown in the bottom toolbar."""
        self.video_file_label.setText(file_path)
        self.video_meta_label.setText(
            f"Duration: {duration:.2f}s | Resolution: {width}x{height} | FPS: {fps:.2f} | Codec: {codec}"
        )

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
        self._previous_file_info_text = self.video_file_label.text()
        self._previous_meta_info_text = self.video_meta_label.text()

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
        self.gif_preview_label.set_video_size(video_info.width, video_info.height)

    def toggle_preview_playback(self) -> None:
        """Toggle preview playback between play and pause."""
        if self.media_player.source().isEmpty():
            return

        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

        self._update_play_button_state()

    def toggle_mute(self) -> None:
        """Toggle audio output between muted and unmuted."""
        # Change button state
        if self.audio_output.isMuted():
            self.audio_output.setMuted(False)
        else:
            self.audio_output.setMuted(True)

    def _seconds_to_frame(self, seconds: float) -> int:
        """Convert seconds to a frame delta using the current preview FPS."""
        if self.current_video_fps <= 0:
            return 0
        return max(1, round(seconds * self.current_video_fps))

    def on_seek_slider_pressed(self) -> None:
        """Mark that the user is actively dragging the seek handle."""
        self._is_seek_dragging = True

    def on_seek_slider_moved(self, position: int) -> None:
        """Seek the media player while dragging and update the displayed time."""
        target_position = self._frame_to_ms(position)
        self.media_player.setPosition(target_position)
        self._update_seek_time_label(current_ms=target_position)

    def on_seek_slider_released(self) -> None:
        """Finalize the seek position when the user releases the slider handle."""
        self._is_seek_dragging = False
        target_position = self._frame_to_ms(self.seek_slider.value())
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
            self._current_video_info = self._pending_video_info
            self._current_crop = None
            self.gif_preview_label.clear_crop()
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
        self.video_file_label.setText(self._previous_file_info_text)
        self.video_meta_label.setText(self._previous_meta_info_text)

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
        self._previous_file_info_text = "No file loaded"
        self._previous_meta_info_text = (
            "Duration: - | Resolution: - | FPS: - | Codec: -"
        )

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
            if hasattr(self, "export_start_input") and hasattr(
                self, "export_end_input"
            ):
                self.export_start_input.setText("")
                self.export_end_input.setText("")
            return

        start_text = self._format_timestamp_from_frame(self.start_frame)
        end_text = self._format_timestamp_from_frame(self.end_frame)
        duration = self.clip_end_time - self.clip_start_time
        self.start_frame_label.setText(f"Start {start_text}")
        self.end_frame_label.setText(f"End {end_text}")
        self.clip_selection_label.setText(f"Duration: {duration:.3f}s")

        # Keep precision inputs synced to timeline markers for fine adjustments.
        if hasattr(self, "export_start_input") and hasattr(self, "export_end_input"):
            self.export_start_input.setText(
                self._format_ms(self._frame_to_ms(self.start_frame))
            )
            self.export_end_input.setText(
                self._format_ms(self._frame_to_ms(self.end_frame))
            )

    def on_export_start_adjusted(self) -> None:
        """Allow precise start adjustments while preserving timeline as source of truth."""
        if self.total_frames <= 0 or not self.export_start_input.text().strip():
            return

        try:
            start_seconds = self._parse_time_input(
                self.export_start_input.text().strip()
            )
        except ValueError as exc:
            self.export_status_label.setText(f"Status: {exc}")
            self.export_start_input.setText(
                self._format_ms(self._frame_to_ms(self.start_frame))
            )
            return

        start_frame = self._ms_to_frame(round(start_seconds * 1000.0))
        self.seek_slider.set_selection(start_frame, self.end_frame)

    def on_export_end_adjusted(self) -> None:
        """Allow precise end adjustments while preserving timeline as source of truth."""
        if self.total_frames <= 0 or not self.export_end_input.text().strip():
            return

        try:
            end_seconds = self._parse_time_input(self.export_end_input.text().strip())
        except ValueError as exc:
            self.export_status_label.setText(f"Status: {exc}")
            self.export_end_input.setText(
                self._format_ms(self._frame_to_ms(self.end_frame))
            )
            return

        end_frame = self._ms_to_frame(round(end_seconds * 1000.0))
        self.seek_slider.set_selection(self.start_frame, end_frame)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts for marker nudging."""
        if event.key() == Qt.Key_Left:
            self._leftArrowPressed()
        elif event.key() == Qt.Key_Right:
            self._rightArrowPressed()
        else:
            super().keyPressEvent(event)

    def _leftArrowPressed(self) -> None:
        """Nudge the start marker left by one frame."""
        # self.nudge_start_frame(-1)
        self.media_player.setPosition(
            max(0, self.media_player.position() - 1000 / self.current_video_fps)
        )

    def _rightArrowPressed(self) -> None:
        """Nudge the end marker right by one frame."""
        self.media_player.setPosition(
            self.media_player.position() + 1000 / self.current_video_fps
        )
        # self.nudge_end_frame(1)

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
        """Export a selected time segment from the current video."""
        if self.current_video_path is None:
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Export requested without a loaded video.")
            return

        fmt = self.export_format_combo.currentText()
        video_path = Path(self.current_video_path)

        if fmt == "WebP":
            default_save_name = str(video_path.with_suffix(".webp"))
            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save WebP",
                default_save_name,
                "WebP Files (*.webp)",
            )
            if not output_path:
                self.export_status_label.setText("Status: Export cancelled.")
                logger.info("WebP export cancelled by user.")
                return

            try:
                render_settings = self._resolve_render_settings()
            except ValueError as exc:
                self.export_status_label.setText(f"Status: {exc}")
                logger.error("Invalid export time input: {}", exc)
                return

            self.export_status_label.setText("Status: Exporting...")
            logger.info("Starting WebP export to '{}'", output_path)

            try:
                export_webp(
                    self.current_video_path,
                    output_path,
                    start_seconds=render_settings["start_seconds"],
                    end_seconds=render_settings["end_seconds"],
                    fps=render_settings["fps"],
                    width=render_settings["width"],
                    crop=render_settings["crop"],
                )
            except GifExportError as exc:
                self.export_status_label.setText(f"Status: Export failed: {exc}")
                logger.error("WebP export failed: {}", exc)
                return

            self.export_status_label.setText("Status: Export complete.")
            logger.info("WebP export complete: {}", output_path)
            return

        # GIF path — existing behaviour preserved exactly
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
                crop=render_settings["crop"],
            )
        except GifExportError as exc:
            self.export_status_label.setText(f"Status: Export failed: {exc}")
            logger.error("GIF export failed: {}", exc)
            return

        self.export_status_label.setText("Status: Export complete.")
        logger.info("GIF export complete: {}", output_path)

    def generate_gif_preview(self, *, force_crop: bool = False) -> None:
        """Generate a temporary GIF preview from the current settings."""
        if self.current_video_path is None:
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Preview requested without a loaded video.")
            return

        if not force_crop:
            self._current_crop = None
            self.gif_preview_label.clear_crop()

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
                crop=render_settings["crop"],
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
        # If we have a cached frame playback, start or resume the timer
        if self._preview_frame_cache:
            if self._preview_frame_timer is None:
                self._preview_frame_timer = QTimer(self)
                self._preview_frame_timer.timeout.connect(self._on_cached_frame_timeout)
                idx = self._preview_frame_index or 0
                dur = (
                    self._preview_frame_durations[idx]
                    if self._preview_frame_durations
                    else 100
                )
                self._preview_frame_timer.start(dur)
                return

            if not self._preview_frame_timer.isActive():
                idx = self._preview_frame_index or 0
                dur = (
                    self._preview_frame_durations[idx]
                    if self._preview_frame_durations
                    else 100
                )
                self._preview_frame_timer.start(dur)
            return

        if self._preview_movie is None:
            return

        if self._preview_movie.state() == QMovie.MovieState.NotRunning:
            self._preview_movie.start()
            return

        self._preview_movie.setPaused(False)

    def pause_gif_preview(self) -> None:
        """Pause the generated GIF preview."""
        # Pause cached playback if active
        if self._preview_frame_cache and self._preview_frame_timer is not None:
            try:
                self._preview_frame_timer.stop()
            except Exception:
                pass
            return

        if self._preview_movie is None:
            return

        self._preview_movie.setPaused(True)

    def _on_crop_changed(self, x: int, y: int, w: int, h: int) -> None:
        self._current_crop = (x, y, w, h)

    def _on_crop_cleared(self) -> None:
        self._current_crop = None

    def reset_preview_crop(self) -> None:
        """Clear any crop selection and return the current preview to the base clip."""
        self._current_crop = None
        self.gif_preview_label.clear_crop()
        if self.current_video_path is not None:
            self.generate_gif_preview()

    def apply_crop_to_preview(self) -> None:
        """Regenerate the preview using the current crop selection."""
        if self.current_video_path is None:
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Crop requested without a loaded video.")
            return

        if self._current_crop is None:
            self.export_status_label.setText("Status: Draw a crop selection first.")
            logger.info("Crop preview requested without an active crop selection.")
            return

        self.generate_gif_preview(force_crop=True)

    def _resolve_render_settings(
        self,
    ) -> dict[str, float | int | tuple[int, int, int, int] | None]:
        """Resolve render settings from timeline selection and compact controls."""
        if self.clip_start_time is None or self.clip_end_time is None:
            raise ValueError("Select a clip range on the timeline before export")

        start_seconds = self.clip_start_time
        end_seconds = self.clip_end_time
        logger.info(
            "Using selected clip range for render: {:.2f}s to {:.2f}s",
            start_seconds,
            end_seconds,
        )

        if end_seconds <= start_seconds:
            raise ValueError("End time must be greater than start time")

        return {
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "fps": self.export_fps_input.value(),
            "width": self.export_width_input.value(),
            "crop": self._current_crop,
        }

    def _set_preview_movie(self, gif_path: Path) -> None:
        """Display a generated GIF in the preview panel."""
        movie = QMovie(str(gif_path))
        if not movie.isValid():
            raise RuntimeError("Generated preview GIF could not be loaded")

        if self._preview_movie is not None:
            self._preview_movie.stop()

        # Cache frames and durations if possible to drive playback manually
        movie.setCacheMode(QMovie.CacheMode.CacheAll)

        # Try to compute a scaled size up-front to avoid resizing while
        # playing which can cause visible flicker.
        try:
            movie.jumpToFrame(0)
        except Exception:
            pass

        orig_rect = movie.frameRect()
        if orig_rect.isValid() and orig_rect.width() > 0 and orig_rect.height() > 0:
            label_size = self.gif_preview_label.size()
            if label_size.width() > 0 and label_size.height() > 0:
                scale_w = label_size.width() / orig_rect.width()
                scale_h = label_size.height() / orig_rect.height()
                scale = min(scale_w, scale_h)
                new_w = max(1, int(orig_rect.width() * scale))
                new_h = max(1, int(orig_rect.height() * scale))
                movie.setScaledSize(QSize(new_w, new_h))

        # Attempt to build a cached list of scaled QPixmaps and frame durations.
        cached_frames: list[QPixmap] = []
        cached_durations: list[int] = []
        try:
            total = movie.frameCount()
        except Exception:
            total = 0

        if total and total > 0:
            for i in range(total):
                try:
                    movie.jumpToFrame(i)
                except Exception:
                    break
                pix = movie.currentPixmap()
                if pix is None or pix.isNull():
                    continue

                scaled_size = movie.scaledSize()
                if (
                    scaled_size.isValid()
                    and scaled_size.width() > 0
                    and scaled_size.height() > 0
                ):
                    pix = pix.scaled(
                        scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    label_size = self.gif_preview_label.size()
                    if label_size.width() > 0 and label_size.height() > 0:
                        pix = pix.scaled(
                            label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )

                cached_frames.append(pix)
                try:
                    dur = movie.nextFrameDelay()
                except Exception:
                    dur = 100
                cached_durations.append(max(1, int(dur)))

        if len(cached_frames) > 1:
            # Use timer-driven cached playback for smooth looping
            self._stop_cached_preview()
            self._preview_frame_cache = cached_frames
            self._preview_frame_durations = cached_durations
            self._preview_frame_index = 0
            self.gif_preview_label.setPixmap(self._preview_frame_cache[0])
            self._preview_frame_timer = QTimer(self)
            self._preview_frame_timer.timeout.connect(self._on_cached_frame_timeout)
            self._preview_frame_timer.start(self._preview_frame_durations[0])
            try:
                movie.stop()
            except Exception:
                pass
            self._preview_movie = None
            return

        # Fallback to QMovie playback with a frame handler to loop seamlessly
        try:
            if self._preview_movie is not None:
                self._preview_movie.frameChanged.disconnect(
                    self._on_preview_frame_changed
                )
        except Exception:
            pass

        movie.frameChanged.connect(self._on_preview_frame_changed)
        self.gif_preview_label.setMovie(movie)
        movie.start()
        self._preview_movie = movie

    def _clear_preview_state(self, *, remove_temp_file: bool) -> None:
        """Clear preview UI state and optionally remove the temp GIF file."""
        preview_file = self._preview_temp_file
        # Stop any cached-frame playback first
        try:
            self._stop_cached_preview()
        except Exception:
            pass
        if self._preview_movie is not None:
            try:
                self._preview_movie.frameChanged.disconnect(
                    self._on_preview_frame_changed
                )
            except Exception:
                pass
            self._preview_movie.stop()
            self._preview_movie = None

        self.gif_preview_label.clear()
        self.gif_preview_label.setText("Generate preview to display GIF")

        self._preview_temp_file = None
        self._last_preview_settings = None

        if remove_temp_file and preview_file is not None:
            self._remove_file_if_exists(preview_file)

    def _stop_cached_preview(self) -> None:
        """Stop and clear any QTimer-based cached preview playback."""
        if self._preview_frame_timer is not None:
            try:
                self._preview_frame_timer.stop()
                self._preview_frame_timer.timeout.disconnect(
                    self._on_cached_frame_timeout
                )
            except Exception:
                pass
            self._preview_frame_timer = None

        self._preview_frame_cache = None
        self._preview_frame_durations = None
        self._preview_frame_index = 0

    def _on_cached_frame_timeout(self) -> None:
        """Advance cached frame playback and schedule the next timeout."""
        if not self._preview_frame_cache or not self._preview_frame_durations:
            return

        self._preview_frame_index = (self._preview_frame_index + 1) % len(
            self._preview_frame_cache
        )
        pix = self._preview_frame_cache[self._preview_frame_index]
        self.gif_preview_label.setPixmap(pix)
        if self._preview_frame_timer is not None:
            next_dur = self._preview_frame_durations[self._preview_frame_index]
            self._preview_frame_timer.start(next_dur)

    def _on_preview_frame_changed(self, frame: int) -> None:
        """Handle frame changes to implement a seamless loop for QMovie.

        Some PySide6 builds don't expose a setter for the loop count; when the
        movie reports it has reached its last frame, jump back to frame 0 on the
        next event loop tick to avoid visible flicker from stopping/starting.
        """
        movie = self._preview_movie
        if movie is None:
            return

        try:
            total = movie.frameCount()
        except Exception:
            total = 0

        if total <= 0:
            return

        # If we're at the last frame, schedule a jump to frame 0 immediately
        if frame >= total - 1:

            def _restart(m=movie):
                try:
                    m.jumpToFrame(0)
                    m.start()
                except Exception:
                    pass

            QTimer.singleShot(0, _restart)

    def _update_preview_scaled_size(self) -> None:
        """Scale the current preview movie to fit the preview label while preserving aspect ratio."""
        if self._preview_movie is None or not hasattr(self, "gif_preview_label"):
            return

        orig_rect = self._preview_movie.frameRect()
        orig_size = orig_rect.size()
        if orig_size.width() <= 0 or orig_size.height() <= 0:
            return

        label_size = self.gif_preview_label.size()
        if label_size.width() <= 0 or label_size.height() <= 0:
            return

        scale_w = label_size.width() / orig_size.width()
        scale_h = label_size.height() / orig_size.height()
        scale = min(scale_w, scale_h)
        new_w = max(1, int(orig_size.width() * scale))
        new_h = max(1, int(orig_size.height() * scale))
        self._preview_movie.setScaledSize(QSize(new_w, new_h))

    def resizeEvent(self, event) -> None:
        """Respond to window resizes by updating preview scaling."""
        super().resizeEvent(event)
        self._update_preview_scaled_size()

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
