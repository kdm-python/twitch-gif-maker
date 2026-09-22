"""Video loading, playback, and clip-selection coordination."""

from __future__ import annotations

from loguru import logger
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer

from gifmaker.models.render_settings import (
    duration_to_frame_count,
    format_ms,
    format_timestamp_from_frame,
    frame_to_ms,
    ms_to_frame,
    parse_time_input,
)
from gifmaker.video.probe import VideoProbeError, probe_video


class VideoSessionController:
    """Coordinate a loaded video, its player, and its selected clip range.

    Widgets intentionally remain on the window for this first extraction so the
    view layout has no behavioural knowledge.  This controller owns the
    interaction rules between those widgets and the current video session.
    """

    def __init__(self, window) -> None:
        self.window = window

    def open_file_dialog(self) -> None:
        """Ask the user for a video and probe it before changing the player."""
        from PySide6.QtWidgets import QFileDialog

        dialog = QFileDialog(self.window)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Video Files (*.mp4 *.avi *.mov)")
        if not dialog.exec() or not dialog.selectedFiles():
            logger.info("Video file selection cancelled.")
            return

        selected_path = dialog.selectedFiles()[0]
        previous_path = self.window.current_video_path
        try:
            video_info = probe_video(selected_path)
        except VideoProbeError as exc:
            logger.error("Failed to probe selected video '{}': {}", selected_path, exc)
            return

        self.window.current_video_path = selected_path
        self.load_video_preview(selected_path, video_info, previous_path)

    def load_video_preview(self, file_path, video_info, previous_video_path) -> None:
        """Prepare rollback state and load a validated source into the player."""
        window = self.window
        window._pending_video_path = file_path
        window._pending_video_info = video_info
        window._previous_video_path = previous_video_path
        window._previous_source = window.media_player.source()
        window._previous_file_info_text = window.video_file_label.text()
        window._previous_meta_info_text = window.video_meta_label.text()
        window.media_player.stop()
        window.media_player.setSource(QUrl.fromLocalFile(file_path))

    def update_video_info_from_model(self, file_path, video_info) -> None:
        """Display metadata from a successfully loaded video."""
        self.window.update_video_info(
            file_path,
            duration=video_info.duration,
            width=video_info.width,
            height=video_info.height,
            fps=video_info.fps,
            codec=video_info.codec,
        )
        self.window.gif_preview_label.set_video_size(video_info.width, video_info.height)

    def on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Commit a loaded video session or restore the prior one on failure."""
        window = self.window
        if window._restoring_previous_source:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.handle_preview_load_failure()
            return
        if status != QMediaPlayer.MediaStatus.LoadedMedia:
            return
        if window._pending_video_path is None or window._pending_video_info is None:
            return

        window.media_player.setPosition(0)
        window.media_player.pause()
        self.reset_clip_selection()
        window.render_controller.clear_preview_state(remove_temp_file=True)
        window._current_video_info = window._pending_video_info
        window._current_crop = None
        window.gif_preview_label.clear_crop()
        window.current_video_fps = max(window._pending_video_info.fps, 1.0)
        self.update_video_info_from_model(window._pending_video_path, window._pending_video_info)
        self._clear_pending_preview_state()
        self._update_play_button_state()
        logger.info("Video loaded successfully.")

    def on_media_error(self, _error: QMediaPlayer.Error, _message: str) -> None:
        """Handle player errors through the same safe rollback path."""
        self.handle_preview_load_failure()

    def handle_preview_load_failure(self) -> None:
        """Restore metadata and player source after an unsuccessful load."""
        window = self.window
        if window._pending_video_path is None:
            return
        logger.error("Failed to load video preview.")
        window.current_video_path = window._previous_video_path
        window.video_file_label.setText(window._previous_file_info_text)
        window.video_meta_label.setText(window._previous_meta_info_text)
        if window._previous_source is not None and not window._previous_source.isEmpty():
            window._restoring_previous_source = True
            window.media_player.stop()
            window.media_player.setSource(window._previous_source)
            window.media_player.pause()
            window._restoring_previous_source = False
        else:
            window.media_player.stop()
            window.media_player.setSource(QUrl())
            window.seek_slider.setRange(0, 0)
            window.seek_slider.setValue(0)
            self._update_seek_time_label(0)
        self._clear_pending_preview_state()

    def _clear_pending_preview_state(self) -> None:
        """Discard transient state used to support safe source replacement."""
        window = self.window
        window._pending_video_path = None
        window._pending_video_info = None
        window._previous_video_path = None
        window._previous_source = None
        window._previous_file_info_text = "No file loaded"
        window._previous_meta_info_text = "Duration: - | Resolution: - | FPS: - | Codec: -"

    def toggle_preview_playback(self) -> None:
        """Toggle the source player without changing its export settings."""
        player = self.window.media_player
        if player.source().isEmpty():
            return
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
        else:
            player.play()
        self._update_play_button_state()

    def toggle_mute(self) -> None:
        """Toggle source-audio mute state."""
        audio = self.window.audio_output
        audio.setMuted(not audio.isMuted())

    def on_preview_playback_speed_changed(self) -> None:
        """Apply the preview-only playback rate selected by the user."""
        speed = self.window.preview_playback_speed_combo.currentData() or 1.0
        self.window.media_player.setPlaybackRate(float(speed))

    def _set_preview_playback_speed(self, target_speed: float) -> None:
        """Select the nearest supported source-preview speed."""
        rates = [0.25, 0.5, 1.0, 1.5, 2.0]
        chosen = min(rates, key=lambda rate: abs(rate - target_speed))
        combo = self.window.preview_playback_speed_combo
        index = combo.findData(chosen)
        if index >= 0:
            combo.setCurrentIndex(index)
        self.window.media_player.setPlaybackRate(chosen)

    def speed_up_playback(self) -> None:
        """Step source-preview speed upward."""
        current = float(self.window.preview_playback_speed_combo.currentData() or 1.0)
        for rate in [0.25, 0.5, 1.0, 1.5, 2.0]:
            if rate > current:
                self._set_preview_playback_speed(rate)
                return

    def speed_down_playback(self) -> None:
        """Step source-preview speed downward."""
        current = float(self.window.preview_playback_speed_combo.currentData() or 1.0)
        for rate in reversed([0.25, 0.5, 1.0, 1.5, 2.0]):
            if rate < current:
                self._set_preview_playback_speed(rate)
                return

    def on_duration_changed(self, duration: int) -> None:
        """Initialise the frame-based timeline after media duration is known."""
        window = self.window
        window.total_frames = duration_to_frame_count(duration, window.current_video_fps)
        window.seek_slider.setRange(0, max(window.total_frames - 1, 0))
        window.seek_slider.set_total_frames(window.total_frames)
        self.reset_clip_selection()
        self._update_seek_time_label()

    def on_seek_slider_pressed(self) -> None:
        """Prevent player updates fighting an active user seek."""
        self.window._is_seek_dragging = True

    def on_seek_slider_moved(self, position: int) -> None:
        """Seek while a timeline handle is dragged."""
        target = self._frame_to_ms(position)
        self.window.media_player.setPosition(target)
        self._update_seek_time_label(target)

    def on_seek_slider_released(self) -> None:
        """Commit the timeline seek after drag completion."""
        window = self.window
        window._is_seek_dragging = False
        self.on_seek_slider_moved(window.seek_slider.value())

    def on_position_changed(self, position: int) -> None:
        """Reflect normal player movement on the timeline."""
        if not self.window._is_seek_dragging:
            self.window.seek_slider.setValue(self._ms_to_frame(position))
            self._update_seek_time_label(position)
        self._update_play_button_state()

    def reset_clip_selection(self) -> None:
        """Select the complete loaded video while preserving marker constraints."""
        window = self.window
        if window.total_frames <= 0:
            self.on_scrub_selection_changed(0, 0)
            return
        end = max(window.minimum_selection_gap_frames, window.total_frames - 1)
        window.seek_slider.set_selection(0, end, emit_signal=False)
        self.on_scrub_selection_changed(0, end)

    def set_clip_start(self) -> None:
        """Set the start marker at the current player frame."""
        if self.window.media_player.source().isEmpty():
            self.window.export_status_label.setText("Status: Load a video first.")
            return
        frame = self._ms_to_frame(self.window.media_player.position())
        self.window.seek_slider.set_selection(frame, self.window.end_frame)

    def set_clip_end(self) -> None:
        """Set the end marker at the current player frame."""
        if self.window.media_player.source().isEmpty():
            self.window.export_status_label.setText("Status: Load a video first.")
            return
        frame = self._ms_to_frame(self.window.media_player.position())
        self.window.seek_slider.set_selection(self.window.start_frame, frame)

    def nudge_start_frame(self, delta: int) -> None:
        """Move the start marker by a frame delta."""
        if self.window.total_frames > 0:
            self.window.seek_slider.nudge_start(delta)

    def nudge_end_frame(self, delta: int) -> None:
        """Move the end marker by a frame delta."""
        if self.window.total_frames > 0:
            self.window.seek_slider.nudge_end(delta)

    def on_scrub_selection_changed(self, start_frame: int, end_frame: int) -> None:
        """Persist marker positions and refresh every selection presentation."""
        window = self.window
        window.start_frame, window.end_frame = start_frame, end_frame
        if window.total_frames:
            window.clip_start_time = start_frame / window.current_video_fps
            window.clip_end_time = end_frame / window.current_video_fps
        else:
            window.clip_start_time = window.clip_end_time = None
        self.update_clip_selection_display()
        window.selection_changed.emit(start_frame, end_frame)

    def update_clip_selection_display(self) -> None:
        """Synchronise marker labels and precision inputs from frame state."""
        window = self.window
        if window.clip_start_time is None or window.clip_end_time is None or not window.total_frames:
            window.start_frame_label.setText("--:--:--.---")
            window.end_frame_label.setText("--:--:--.---")
            window.clip_selection_label.setText("Selection: Not selected")
            window.export_start_input.setText("")
            window.export_end_input.setText("")
            return
        window.start_frame_label.setText(self._format_timestamp_from_frame(window.start_frame))
        window.end_frame_label.setText(self._format_timestamp_from_frame(window.end_frame))
        window.clip_selection_label.setText(f"Selection: {window.clip_end_time - window.clip_start_time:.3f}s")
        window.export_start_input.setText(format_ms(self._frame_to_ms(window.start_frame)))
        window.export_end_input.setText(format_ms(self._frame_to_ms(window.end_frame)))

    def on_export_start_adjusted(self) -> None:
        """Map a manually entered start timestamp back to the timeline."""
        self._apply_time_input(self.window.export_start_input, is_start=True)

    def on_export_end_adjusted(self) -> None:
        """Map a manually entered end timestamp back to the timeline."""
        self._apply_time_input(self.window.export_end_input, is_start=False)

    def _apply_time_input(self, input_widget, *, is_start: bool) -> None:
        if self.window.total_frames <= 0 or not input_widget.text().strip():
            return
        try:
            frame = self._ms_to_frame(round(parse_time_input(input_widget.text().strip()) * 1000))
        except ValueError as exc:
            self.window.export_status_label.setText(f"Status: {exc}")
            frame = self.window.start_frame if is_start else self.window.end_frame
            input_widget.setText(format_ms(self._frame_to_ms(frame)))
            return
        if is_start:
            self.window.seek_slider.set_selection(frame, self.window.end_frame)
        else:
            self.window.seek_slider.set_selection(self.window.start_frame, frame)

    def _leftArrowPressed(self) -> None:
        """Seek one source frame backwards."""
        frame_ms = int(1000 / self.window.current_video_fps)
        self.window.media_player.setPosition(max(0, self.window.media_player.position() - frame_ms))

    def _rightArrowPressed(self) -> None:
        """Seek one source frame forwards."""
        frame_ms = int(1000 / self.window.current_video_fps)
        self.window.media_player.setPosition(self.window.media_player.position() + frame_ms)

    def _startSliderLeftPressed(self) -> None: self.nudge_start_frame(-1)
    def _startSetPressed(self) -> None: self.set_clip_start()
    def _startSliderRightPressed(self) -> None: self.nudge_start_frame(1)
    def _endSetPressed(self) -> None: self.set_clip_end()
    def _endSliderLeftPressed(self) -> None: self.nudge_end_frame(-1)
    def _endSliderRightPressed(self) -> None: self.nudge_end_frame(1)
    def _seconds_to_frame(self, seconds: float) -> int: return max(1, round(seconds * self.window.current_video_fps))
    def _ms_to_frame(self, milliseconds: int) -> int: return ms_to_frame(milliseconds, self.window.current_video_fps, self.window.total_frames)
    def _frame_to_ms(self, frame: int) -> int: return frame_to_ms(frame, self.window.current_video_fps)
    def _format_timestamp_from_frame(self, frame: int) -> str: return format_timestamp_from_frame(frame, self.window.current_video_fps)

    def _update_seek_time_label(self, current_ms: int | None = None) -> None:
        current = self._frame_to_ms(self.window.seek_slider.value()) if current_ms is None else current_ms
        total = self._frame_to_ms(max(self.window.total_frames - 1, 0))
        self.window.seek_time_label.setText(f"{format_ms(current)} / {format_ms(total)}")

    def _update_play_button_state(self, _state=None) -> None:
        playing = self.window.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.window.play_button.setText("⏸ Pause" if playing else "▶ Play")
