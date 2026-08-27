"""Main application window scaffold for the gifmaker GUI."""

import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QMovie,
    QPixmap,
)
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gifmaker.gui.crop_overlay_label import CropOverlayLabel
from gifmaker.gui.export_controls_panel import ExportControlsPanel
from gifmaker.gui.preview_controller import PreviewController
from gifmaker.gui.shortcut_manager import ShortcutManager
from gifmaker.gui.video_preview_panel import VideoPreviewPanel
from gifmaker.models.render_settings import (
    RenderSettings,
    duration_to_frame_count,
    format_ms,
    format_timestamp_from_frame,
    frame_to_ms,
    ms_to_frame,
    parse_time_input,
)
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

        self.preview_controller = PreviewController(self)
        self._last_preview_settings: RenderSettings | None = None
        self._last_preview_source: str | None = None
        self._current_crop: tuple[int, int, int, int] | None = None
        self._current_video_info: VideoInfo | None = None

        # --- Keyboard Shortcuts ---

        self.shortcut_manager = ShortcutManager(self)
        self.left_shortcut = self.shortcut_manager.shortcuts["left"]
        self.right_shortcut = self.shortcut_manager.shortcuts["right"]
        self.play_button_shortcut = self.shortcut_manager.shortcuts["play_pause"]
        self.mute_shortcut = self.shortcut_manager.shortcuts["toggle_mute"]
        self.start_slider_left_shortcut = self.shortcut_manager.shortcuts["start_left"]
        self.start_slider_right_shortcut = self.shortcut_manager.shortcuts[
            "start_right"
        ]
        self.end_slider_left_shortcut = self.shortcut_manager.shortcuts["end_left"]
        self.end_slider_right_shortcut = self.shortcut_manager.shortcuts["end_right"]

        # --- Render Window ---

        self.setWindowTitle("GIF Maker")
        self.create_menu()
        self.build_layout()
        self._fit_to_available_screen()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()

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
        self.preview_panel = VideoPreviewPanel(self)
        self.video_widget = self.preview_panel.video_widget
        self.media_player = self.preview_panel.media_player
        self.audio_output = self.preview_panel.audio_output
        self.play_button = self.preview_panel.play_button
        self.preview_playback_speed_combo = self.preview_panel.playback_speed_combo
        self.set_start_button = self.preview_panel.set_start_button
        self.set_end_button = self.preview_panel.set_end_button
        self.seek_slider = self.preview_panel.seek_slider
        self.seek_time_label = self.preview_panel.seek_time_label
        self.mute_button = self.preview_panel.mute_button
        self.selection_group = self.preview_panel.selection_group
        self.start_frame_label = self.preview_panel.start_frame_label
        self.start_nudge_back_button = self.preview_panel.start_nudge_back_button
        self.start_nudge_forward_button = self.preview_panel.start_nudge_forward_button
        self.end_frame_label = self.preview_panel.end_frame_label
        self.end_nudge_back_button = self.preview_panel.end_nudge_back_button
        self.end_nudge_forward_button = self.preview_panel.end_nudge_forward_button
        self.clip_selection_label = self.preview_panel.clip_selection_label

        self.preview_panel.bind_window(self)
        self.update_clip_selection_display()
        self._update_play_button_state()
        return self.preview_panel

    def create_export_controls_row(self) -> QWidget:
        """Create compact, single-row precision and render settings controls."""
        self.export_controls_panel = ExportControlsPanel(self)
        self.export_start_input = self.export_controls_panel.export_start_input
        self.export_end_input = self.export_controls_panel.export_end_input
        self.playback_speed_combo = self.export_controls_panel.playback_speed_combo
        self.export_width_input = self.export_controls_panel.export_width_input
        self.generate_preview_button = (
            self.export_controls_panel.generate_preview_button
        )
        self.apply_crop_button = self.export_controls_panel.apply_crop_button
        self.reset_crop_button = self.export_controls_panel.reset_crop_button
        self.gif_preview_play_button = (
            self.export_controls_panel.gif_preview_play_button
        )
        self.gif_preview_pause_button = (
            self.export_controls_panel.gif_preview_pause_button
        )
        self.export_format_combo = self.export_controls_panel.export_format_combo

        self.export_controls_panel.bind_window(self)
        return self.export_controls_panel

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
        self.preview_controller.bind(self.gif_preview_label)
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

    def on_preview_playback_speed_changed(self) -> None:
        """Apply the selected preview playback rate without affecting export timing."""
        if not hasattr(self, "media_player"):
            return

        playback_speed = self.preview_playback_speed_combo.currentData()
        if playback_speed is None:
            playback_speed = 1.0

        self.media_player.setPlaybackRate(float(playback_speed))

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
            self.start_frame_label.setText("--:--:--.---")
            self.end_frame_label.setText("--:--:--.---")
            self.clip_selection_label.setText("Selection: Not selected")
            if hasattr(self, "export_start_input") and hasattr(
                self, "export_end_input"
            ):
                self.export_start_input.setText("")
                self.export_end_input.setText("")
            return

        start_text = self._format_timestamp_from_frame(self.start_frame)
        end_text = self._format_timestamp_from_frame(self.end_frame)
        duration = self.clip_end_time - self.clip_start_time
        self.start_frame_label.setText(start_text)
        self.end_frame_label.setText(end_text)
        self.clip_selection_label.setText(f"Selection: {duration:.3f}s")

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
            start_seconds = parse_time_input(self.export_start_input.text().strip())
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
            end_seconds = parse_time_input(self.export_end_input.text().strip())
        except ValueError as exc:
            self.export_status_label.setText(f"Status: {exc}")
            self.export_end_input.setText(
                self._format_ms(self._frame_to_ms(self.end_frame))
            )
            return

        end_frame = self._ms_to_frame(round(end_seconds * 1000.0))
        self.seek_slider.set_selection(self.start_frame, end_frame)

    def _leftArrowPressed(self) -> None:
        """Move playback position back by one frame."""
        frame_ms = int(1000 / self.current_video_fps)
        self.media_player.setPosition(max(0, self.media_player.position() - frame_ms))

    def _rightArrowPressed(self) -> None:
        """Move playback position forward by one frame."""
        frame_ms = int(1000 / self.current_video_fps)
        self.media_player.setPosition(self.media_player.position() + frame_ms)

    def _startSliderLeftPressed(self) -> None:
        """Nudge the start marker back by one frame."""
        self.nudge_start_frame(-1)

    def _startSetPressed(self) -> None:
        """Set the start marker to the current playback position."""
        self.set_clip_start()

    def _startSliderRightPressed(self) -> None:
        """Nudge the end marker forward by one frame."""
        self.nudge_start_frame(1)

    def _endSetPressed(self) -> None:
        """Set the end marker to the current playback position."""
        self.set_clip_end()

    def _endSliderLeftPressed(self) -> None:
        """Nudge the start marker back by one frame."""
        self.nudge_end_frame(-1)

    def _endSliderRightPressed(self) -> None:
        """Nudge the end marker forward by one frame."""
        self.nudge_end_frame(1)

    def _update_seek_time_label(self, current_ms: int | None = None) -> None:
        """Update the current/total playback time text."""
        if current_ms is None:
            current_ms = frame_to_ms(self.seek_slider.value(), self.current_video_fps)
        total_ms = frame_to_ms(max(self.total_frames - 1, 0), self.current_video_fps)
        self.seek_time_label.setText(f"{format_ms(current_ms)} / {format_ms(total_ms)}")

    def _duration_to_frame_count(self, duration_ms: int) -> int:
        """Convert media duration to total frame count."""
        return duration_to_frame_count(duration_ms, self.current_video_fps)

    def _ms_to_frame(self, milliseconds: int) -> int:
        """Convert milliseconds to nearest frame index."""
        return ms_to_frame(milliseconds, self.current_video_fps, self.total_frames)

    def _frame_to_ms(self, frame_index: int) -> int:
        """Convert frame index to milliseconds."""
        return frame_to_ms(frame_index, self.current_video_fps)

    def _format_timestamp_from_frame(self, frame_index: int) -> str:
        """Format a frame index as HH:MM:SS.mmm."""
        return format_timestamp_from_frame(frame_index, self.current_video_fps)

    def _format_ms(self, milliseconds: int) -> str:
        """Format milliseconds as MM:SS:CC or HH:MM:SS:CC."""
        return format_ms(milliseconds)

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
                    start_seconds=render_settings.start_seconds,
                    end_seconds=render_settings.end_seconds,
                    fps=render_settings.fps,
                    width=render_settings.width,
                    crop=render_settings.crop,
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

        try:
            render_settings = self._resolve_render_settings()
        except ValueError as exc:
            self.export_status_label.setText(f"Status: {exc}")
            logger.error("Invalid export time input: {}", exc)
            return

        if (
            self._preview_temp_file is not None
            and self._preview_temp_file.exists()
            and self._last_preview_settings is not None
            and self._last_preview_source == self.current_video_path
            and self._last_preview_settings == render_settings
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

        self.export_status_label.setText("Status: Exporting...")
        logger.info("Starting GIF export to '{}'", output_path)

        try:
            export_gif(
                self.current_video_path,
                output_path,
                start_seconds=render_settings.start_seconds,
                end_seconds=render_settings.end_seconds,
                fps=render_settings.fps,
                width=render_settings.width,
                playback_speed=render_settings.playback_speed,
                crop=render_settings.crop,
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
                start_seconds=render_settings.start_seconds,
                end_seconds=render_settings.end_seconds,
                fps=render_settings.fps,
                width=render_settings.width,
                playback_speed=render_settings.playback_speed,
                crop=render_settings.crop,
            )
            self._set_preview_movie(temp_file)
        except (GifExportError, RuntimeError) as exc:
            self._remove_file_if_exists(temp_file)
            self.export_status_label.setText(f"Status: Preview failed: {exc}")
            logger.error("Preview generation failed: {}", exc)
            return

        self._preview_temp_file = temp_file
        self._last_preview_settings = render_settings
        self._last_preview_source = self.current_video_path
        if previous_preview_file is not None and previous_preview_file != temp_file:
            self._remove_file_if_exists(previous_preview_file)

        self.export_status_label.setText("Status: Preview ready. Click Export to save.")
        logger.info("Preview generation complete: {}", temp_file)

    def play_gif_preview(self) -> None:
        """Play the generated GIF preview."""
        self.preview_controller.play()

    def pause_gif_preview(self) -> None:
        """Pause the generated GIF preview."""
        self.preview_controller.pause()

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

    def _resolve_render_settings(self) -> RenderSettings:
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

        playback_speed = self.playback_speed_combo.currentData()
        if playback_speed is None:
            playback_speed = 1.0

        return RenderSettings(
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            fps=24,
            width=self.export_width_input.value(),
            playback_speed=float(playback_speed),
            crop=self._current_crop,
        )

    def _set_preview_movie(self, gif_path: Path) -> None:
        """Display a generated GIF in the preview panel."""
        self.preview_controller.set_movie(gif_path)

    def _clear_preview_state(self, *, remove_temp_file: bool) -> None:
        """Clear preview UI state and optionally remove the temp GIF file."""
        self.preview_controller.clear(remove_temp_file=remove_temp_file)

    def _stop_cached_preview(self) -> None:
        """Stop and clear any QTimer-based cached preview playback."""
        self.preview_controller.stop_cached_preview()

    def _on_cached_frame_timeout(self) -> None:
        """Advance cached frame playback and schedule the next timeout."""
        self.preview_controller.on_cached_frame_timeout()

    def _on_preview_frame_changed(self, frame: int) -> None:
        """Handle frame changes to implement a seamless loop for QMovie."""
        self.preview_controller.on_preview_frame_changed(frame)

    def _update_preview_scaled_size(self) -> None:
        """Scale the current preview movie to fit the preview label while preserving aspect ratio."""
        self.preview_controller.update_scaled_size()

    def resizeEvent(self, event) -> None:
        """Respond to window resizes by updating preview scaling."""
        super().resizeEvent(event)
        self._update_preview_scaled_size()

    def _remove_file_if_exists(self, file_path: Path) -> None:
        """Best-effort removal for temporary preview artifacts."""
        self.preview_controller.remove_temp_file_if_exists(file_path)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle app close by cleaning up preview temp files."""
        self._clear_preview_state(remove_temp_file=True)
        super().closeEvent(event)
