"""Main application window scaffold for the gifmaker GUI."""

from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt, QUrl
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
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gifmaker.models.video_info import VideoInfo
from gifmaker.services.gif_export import GifExportError, export_gif
from gifmaker.video.probe import VideoProbeError, probe_video


class MainWindow(QMainWindow):
    """Primary window scaffold for video/GIF import and export workflows."""

    def __init__(self) -> None:
        super().__init__()
        self.current_video_path: str | None = None
        self.clip_start_time: float | None = None
        self.clip_end_time: float | None = None
        self._is_seek_dragging = False
        self._pending_video_path: str | None = None
        self._pending_video_info: VideoInfo | None = None
        self._previous_video_path: str | None = None
        self._previous_source: QUrl | None = None
        self._previous_info_texts: dict[str, str] = {}
        self._restoring_previous_source = False

        self.setWindowTitle("GIF Maker")
        self.resize(1100, 760)

        self.create_menu()
        self.build_layout()
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
        layout = QVBoxLayout(group)

        self.video_widget = QVideoWidget(group)
        self.video_widget.setMinimumHeight(260)
        self.video_widget.setStyleSheet("border: 1px solid palette(mid);")

        self.media_player = QMediaPlayer(group)
        self.audio_output = QAudioOutput(group)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.media_player.errorOccurred.connect(self.on_media_error)
        self.media_player.durationChanged.connect(self.on_duration_changed)
        self.media_player.positionChanged.connect(self.on_position_changed)

        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.play_preview)

        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_preview)

        self.set_start_button = QPushButton("Set Start")
        self.set_start_button.clicked.connect(self.set_clip_start)

        self.set_end_button = QPushButton("Set End")
        self.set_end_button.clicked.connect(self.set_clip_end)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self.on_seek_slider_pressed)
        self.seek_slider.sliderMoved.connect(self.on_seek_slider_moved)
        self.seek_slider.sliderReleased.connect(self.on_seek_slider_released)

        self.seek_time_label = QLabel("00:00:00 / 00:00:00")

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.set_start_button)
        controls_layout.addWidget(self.set_end_button)
        controls_layout.addWidget(self.seek_slider, stretch=1)
        controls_layout.addWidget(self.seek_time_label)

        self.clip_selection_label = QLabel()
        self.update_clip_selection_display()

        layout.addWidget(self.video_widget)
        layout.addLayout(controls_layout)
        layout.addWidget(self.clip_selection_label)
        return group

    def create_timeline_panel(self) -> QGroupBox:
        """Create a fixed-height timeline placeholder section."""
        group = QGroupBox("Timeline")
        group.setFixedHeight(170)

        layout = QVBoxLayout(group)
        timeline_placeholder = QLabel("Timeline placeholder")
        timeline_placeholder.setAlignment(Qt.AlignCenter)
        timeline_placeholder.setStyleSheet("border: 1px dashed palette(mid);")

        layout.addWidget(timeline_placeholder)
        return group

    def create_export_panel(self) -> QGroupBox:
        """Create export settings with placeholder controls."""
        group = QGroupBox("Export")

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
        self.export_button = QPushButton("Export GIF")
        self.export_button.clicked.connect(self.export_gif_from_selection)
        button_row.addWidget(self.export_button)

        self.export_status_label = QLabel("Status: -")

        root_layout.addLayout(form_layout)
        root_layout.addLayout(button_row)
        root_layout.addWidget(self.export_status_label)

        return group

    def build_layout(self) -> None:
        """Assemble all panels into the window's central widget."""
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        open_button = QPushButton("Open Video File")
        open_button.clicked.connect(self.open_file_dialog)
        root_layout.addWidget(open_button)

        video_info_group = self.create_video_info_panel()
        root_layout.addWidget(video_info_group)

        preview_group = self.create_preview_panel()
        timeline_group = self.create_timeline_panel()
        export_group = self.create_export_panel()

        root_layout.addWidget(preview_group, stretch=1)
        root_layout.addWidget(timeline_group)
        root_layout.addWidget(export_group)

        self.setCentralWidget(central)

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

    def play_preview(self) -> None:
        """Start preview playback."""
        if self.media_player.source().isEmpty():
            return
        self.media_player.play()
        logger.info("Playback started.")

    def pause_preview(self) -> None:
        """Pause preview playback."""
        if self.media_player.source().isEmpty():
            return
        self.media_player.pause()
        logger.info("Playback paused.")

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
        self.seek_slider.setRange(0, max(duration, 0))
        self._update_seek_time_label()

    def on_position_changed(self, position: int) -> None:
        """Sync the seek slider with the current playback position."""
        if not self._is_seek_dragging:
            self.seek_slider.setValue(position)
            self._update_seek_time_label(current_ms=position)

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
            self.update_video_info_from_model(
                self._pending_video_path,
                self._pending_video_info,
            )
            logger.info("Video loaded successfully.")
            self._clear_pending_preview_state()

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
        self.clip_start_time = None
        self.clip_end_time = None
        self.update_clip_selection_display()

    def set_clip_start(self) -> None:
        """Store the current preview position as clip start."""
        if self.media_player.source().isEmpty():
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Cannot set clip start without a loaded video.")
            return

        self.clip_start_time = self.media_player.position() / 1000.0
        logger.info("Clip start set at {:.2f}s", self.clip_start_time)
        self.update_clip_selection_display()

    def set_clip_end(self) -> None:
        """Store the current preview position as clip end."""
        if self.media_player.source().isEmpty():
            self.export_status_label.setText("Status: Load a video first.")
            logger.error("Cannot set clip end without a loaded video.")
            return

        new_end_time = self.media_player.position() / 1000.0
        if self.clip_start_time is not None and new_end_time < self.clip_start_time:
            self.export_status_label.setText(
                "Status: End time must be after selected start time."
            )
            logger.error(
                "Rejected clip end {:.2f}s before clip start {:.2f}s",
                new_end_time,
                self.clip_start_time,
            )
            return

        self.clip_end_time = new_end_time
        logger.info("Clip end set at {:.2f}s", self.clip_end_time)
        self.update_clip_selection_display()

    def update_clip_selection_display(self) -> None:
        """Refresh the clip selection summary shown in the preview panel."""
        if self.clip_start_time is None or self.clip_end_time is None:
            self.clip_selection_label.setText("Selection:\nNot selected")
            return

        start_text = self._format_ms(round(self.clip_start_time * 1000))
        end_text = self._format_ms(round(self.clip_end_time * 1000))
        duration = self.clip_end_time - self.clip_start_time
        self.clip_selection_label.setText(
            f"Selection:\n{start_text} -> {end_text}\nDuration:\n{duration:.2f}s"
        )

    def _update_seek_time_label(self, current_ms: int | None = None) -> None:
        """Update the current/total playback time text."""
        if current_ms is None:
            current_ms = self.media_player.position()
        total_ms = max(self.media_player.duration(), 0)
        self.seek_time_label.setText(
            f"{self._format_ms(current_ms)} / {self._format_ms(total_ms)}"
        )

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

        if self.clip_start_time is not None and self.clip_end_time is not None:
            start_seconds = self.clip_start_time
            end_seconds = self.clip_end_time
            logger.info(
                "Using selected clip range for export: {:.2f}s to {:.2f}s",
                start_seconds,
                end_seconds,
            )
        else:
            try:
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
            except ValueError as exc:
                self.export_status_label.setText(f"Status: {exc}")
                logger.error("Invalid export time input: {}", exc)
                return

        default_save_name = "output.gif"
        if self.current_video_path is not None:
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

        fps = self.export_fps_input.value()
        width = self.export_width_input.value()

        self.export_status_label.setText("Status: Exporting...")
        logger.info("Starting GIF export to '{}'", output_path)

        try:
            export_gif(
                self.current_video_path,
                output_path,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                fps=fps,
                width=width,
            )
        except GifExportError as exc:
            self.export_status_label.setText(f"Status: Export failed: {exc}")
            logger.error("GIF export failed: {}", exc)
            return

        self.export_status_label.setText("Status: Export complete.")
        logger.info("GIF export complete: {}", output_path)

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
