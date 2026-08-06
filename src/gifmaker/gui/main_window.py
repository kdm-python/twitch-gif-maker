"""Main application window scaffold for the gifmaker GUI."""

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
from gifmaker.video.probe import VideoProbeError, probe_video


class MainWindow(QMainWindow):
    """Primary window scaffold for video/GIF import and export workflows."""

    def __init__(self) -> None:
        super().__init__()
        self.current_video_path: str | None = None
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

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.on_seek_slider_moved)

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.seek_slider, stretch=1)

        layout.addWidget(self.video_widget)
        layout.addLayout(controls_layout)
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

        start_input = QLineEdit()
        start_input.setPlaceholderText("e.g. 00:00:00")

        end_input = QLineEdit()
        end_input.setPlaceholderText("e.g. 00:00:05")

        fps_input = QSpinBox()
        fps_input.setRange(1, 120)
        fps_input.setValue(24)

        width_input = QSpinBox()
        width_input.setRange(1, 8192)
        width_input.setValue(640)

        form_layout.addRow("Start", start_input)
        form_layout.addRow("End", end_input)
        form_layout.addRow("FPS", fps_input)
        form_layout.addRow("Width", width_input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(QPushButton("Export GIF"))

        root_layout.addLayout(form_layout)
        root_layout.addLayout(button_row)

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

    def on_seek_slider_moved(self, position: int) -> None:
        """Seek to a new position from the preview controls."""
        self.media_player.setPosition(position)

    def on_duration_changed(self, duration: int) -> None:
        """Sync the seek range with loaded media duration."""
        self.seek_slider.setRange(0, max(duration, 0))

    def on_position_changed(self, position: int) -> None:
        """Sync the seek slider with the current playback position."""
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)

    def on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Handle media load lifecycle events for preview updates."""
        if self._restoring_previous_source:
            return

        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            if self._pending_video_path is None or self._pending_video_info is None:
                return

            self.media_player.setPosition(0)
            self.media_player.pause()
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

        self._clear_pending_preview_state()

    def _clear_pending_preview_state(self) -> None:
        """Clear temporary state used while loading a new preview."""
        self._pending_video_path = None
        self._pending_video_info = None
        self._previous_video_path = None
        self._previous_source = None
        self._previous_info_texts = {}
