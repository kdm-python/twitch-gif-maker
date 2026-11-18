"""Video loading, playback, and clip-selection coordination."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from loguru import logger
from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QInputDialog, QMessageBox

from gifmaker.gui.animation_timeline_controller import AnimationTimelineController
from gifmaker.models.render_settings import (
    duration_to_frame_count,
    format_ms,
    format_timestamp_from_frame,
    frame_to_ms,
    ms_to_frame,
)
from gifmaker.models.video_info import VideoInfo
from gifmaker.services.clip_downloader import ClipDownloadError, validate_clip_url
from gifmaker.sources.animation_player import AnimationSourcePlayer
from gifmaker.sources.loader import load_source
from gifmaker.video.probe import VideoProbeError, probe_video


class LoadSignals(QObject):
    completed = Signal(int, object, object)


class VideoSessionController:
    """Coordinate a loaded video, its player, and its selected clip range.

    Widgets intentionally remain on the window for this first extraction so the
    view layout has no behavioural knowledge.  This controller owns the
    interaction rules between those widgets and the current video session.
    """

    def __init__(self, window) -> None:
        self.window = window
        self._clip_temp_dir = None
        self._clip_process = None
        self._clip_counter = 0
        self._animation_source = None
        self._animation_timeline = None
        self._animation_player = None
        self._previous_format = None
        self._load_generation = 0
        self._closing = False
        self._load_lock = Lock()
        self._pending_sources = set()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="source-loader")
        self._load_signals = LoadSignals(window)
        self._load_signals.completed.connect(self._animation_loaded)

    def open_clip_dialog(self) -> None:
        if self._clip_process is not None:
            return
        url, accepted = QInputDialog.getText(self.window, "Open Twitch Clip", "Twitch clip URL:")
        if not accepted:
            return
        try:
            url = validate_clip_url(url)
        except ClipDownloadError as exc:
            QMessageBox.warning(self.window, "Invalid clip link", str(exc))
            return
        if self._clip_temp_dir is None:
            self._clip_temp_dir = TemporaryDirectory(prefix="gifmaker-clips-")
        self._clip_counter += 1
        target = Path(self._clip_temp_dir.name) / str(self._clip_counter)
        process = QProcess(self.window)
        self._clip_process = process
        self.window.clip_button.setEnabled(False)
        self.window.clip_button.setText("Downloading clip…")
        process.finished.connect(lambda code, status: self._clip_download_finished(process, target, code, status))
        process.errorOccurred.connect(lambda error: self._clip_process_error(process, error))
        process.start(sys.executable, ["-m", "gifmaker.services.clip_downloader", url, str(target)])

    def _clip_process_error(self, process, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._clip_process is process:
            self._finish_clip_process(process)
            QMessageBox.warning(self.window, "Could not download clip", process.errorString())

    def _clip_download_finished(self, process, target, code, status) -> None:
        if self._clip_process is not process:
            return
        error = bytes(process.readAllStandardError()).decode(errors="replace").strip()
        self._finish_clip_process(process)
        if code != 0 or status != QProcess.ExitStatus.NormalExit:
            QMessageBox.warning(self.window, "Could not download clip", error or "The clip download failed.")
            return
        self.open_video_path(str(target / "clip.mp4"))

    def _finish_clip_process(self, process) -> None:
        self._clip_process = None
        self.window.clip_button.setEnabled(True)
        self.window.clip_button.setText("Open Twitch Clip")
        process.deleteLater()

    def cleanup_clip_downloads(self) -> None:
        with self._load_lock:
            self._closing = True
            for source in self._pending_sources:
                source.close()
            self._pending_sources.clear()
        self._load_generation += 1
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._release_animation()
        if self._clip_process is not None:
            process = self._clip_process
            self._clip_process = None
            process.kill()
            process.waitForFinished(3000)
        if self._clip_temp_dir is not None:
            self._clip_temp_dir.cleanup()
            self._clip_temp_dir = None

    def open_file_dialog(self) -> None:
        """Ask the user for a video and probe it before changing the player."""
        from PySide6.QtWidgets import QFileDialog

        dialog = QFileDialog(self.window)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Video and animation files (*.mp4 *.webp)")
        if not dialog.exec() or not dialog.selectedFiles():
            logger.info("Video file selection cancelled.")
            return

        self.open_video_path(dialog.selectedFiles()[0])

    def open_dropped_video(self, file_path: str) -> None:
        """Handle a local file dropped onto the playback surface."""
        self.open_video_path(file_path)

    def open_video_path(self, file_path: str) -> None:
        """Validate and load a path from either the picker or drag-and-drop."""
        from pathlib import Path

        source = Path(file_path)
        self._load_generation += 1
        if source.suffix.lower() not in (".mp4", ".webp"):
            QMessageBox.warning(
                self.window,
                "Unsupported video",
                f"Only MP4 and animated WebP files can be opened.\n\n{source.name}",
            )
            return
        if not source.exists() or not source.is_file():
            QMessageBox.warning(
                self.window,
                "Video not found",
                f"The selected file could not be found.\n\n{source}",
            )
            return

        selected_path = str(source)
        if source.suffix.lower() == ".webp":
            generation = self._load_generation
            self.window.export_status_label.setText("Status: Loading animation...")
            future = self._executor.submit(load_source, selected_path)
            future.add_done_callback(lambda result: self._load_finished(generation, result))
            return
        previous_path = self.window.current_video_path
        try:
            video_info = probe_video(selected_path)
        except VideoProbeError as exc:
            logger.error("Failed to probe selected video '{}': {}", selected_path, exc)
            QMessageBox.warning(
                self.window,
                "Could not open video",
                f"The MP4 file could not be read.\n\n{exc}",
            )
            return

        self.window.current_video_path = selected_path
        self.load_video_preview(selected_path, video_info, previous_path)

    def _load_finished(self, generation, future) -> None:
        try:
            source, error = future.result(), None
        except Exception as exc:  # noqa: BLE001 - report unexpected worker failures in the UI
            source, error = None, exc
        with self._load_lock:
            if self._closing:
                if source is not None:
                    source.close()
                return
            if source is not None:
                self._pending_sources.add(source)
            self._load_signals.completed.emit(generation, source, error)

    def _animation_loaded(self, generation, source, error) -> None:
        with self._load_lock:
            self._pending_sources.discard(source)
        if self._closing or generation != self._load_generation:
            if source is not None:
                source.close()
            return
        if error is not None:
            logger.error("Animation loading failed: {}", error)
            self.window.export_status_label.setText("Status: Could not load animation.")
            QMessageBox.warning(self.window, "Could not open animation", str(error))
            return
        self._activate_animation(source)

    def _activate_animation(self, source) -> None:
        window = self.window
        player = AnimationSourcePlayer(window)
        player.frameChanged.connect(window.preview_panel.animation_widget.set_frame)
        player.positionChanged.connect(self._animation_position_changed)
        player.playingChanged.connect(self._update_play_button_state)
        player.errorOccurred.connect(self._animation_error)
        try:
            player.set_source(source)
        except (OSError, ValueError, RuntimeError) as exc:
            source.close()
            self._animation_error(str(exc))
            return
        window.render_controller.clear_preview_state(remove_temp_file=True)
        self._release_animation()
        window.media_player.stop()
        self._clear_pending_preview_state()
        self._animation_source = source
        self._animation_player = player
        self._animation_timeline = AnimationTimelineController(player, window.seek_slider, source, window)
        self._animation_timeline.selectionChanged.connect(self._animation_selection_changed)
        info = source.info
        window.current_video_path = str(source.original_path)
        window._current_video_info = VideoInfo(info.duration_seconds, info.width, info.height, info.average_fps, info.codec)
        window.current_video_fps = max(info.average_fps, 1.0)
        window.total_frames = len(source.frames)
        window._current_crop = None
        window.gif_preview_label.clear_crop()
        self.update_video_info_from_model(window.current_video_path, window._current_video_info)
        window.preview_panel.source_stack.setCurrentWidget(window.preview_panel.animation_widget)
        self._set_animation_format(True)
        player.set_playback_rate(float(window.preview_playback_speed_combo.currentData() or 1.0))
        self._animation_selection_changed(*self._animation_timeline.selection_seconds())
        self._animation_position_changed(0)
        window.render_controller.on_crop_dimensions_changed()
        window.export_status_label.setText("Status: Animation loaded.")

    def _release_animation(self) -> None:
        if self._animation_timeline is not None:
            self._animation_timeline.close()
            self._animation_timeline.deleteLater()
            self._animation_timeline = None
        if self._animation_player is not None:
            self._animation_player.deleteLater()
            self._animation_player = None
        if self._animation_source is not None:
            self._animation_source.close()
            self._animation_source = None

    def _set_animation_format(self, active: bool) -> None:
        window = self.window
        combo = window.export_format_combo
        gif_index = combo.findText("GIF")
        if active:
            if self._previous_format is None:
                self._previous_format = combo.currentText()
            combo.setCurrentText("WebP")
        item = combo.model().item(gif_index)
        if item is not None:
            item.setEnabled(not active)
        if not active and self._previous_format is not None:
            combo.setCurrentText(self._previous_format)
            self._previous_format = None

    def _animation_error(self, message: str) -> None:
        logger.error("Animation playback failed: {}", message)
        self.window.export_status_label.setText(f"Status: Animation error: {message}")

    def _animation_position_changed(self, position: int) -> None:
        if self._animation_player is not None:
            self.window.seek_time_label.setText(f"{format_ms(position)} / {format_ms(self._animation_player.duration_ms)}")

    def _animation_selection_changed(self, start: float, end: float) -> None:
        window = self.window
        window.clip_start_time, window.clip_end_time = start, end
        window.start_frame, window.end_frame = window.seek_slider.selection()
        self.update_clip_selection_display()
        window.selection_changed.emit(window.start_frame, window.end_frame)

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

        if self._animation_source is not None:
            self._release_animation()
            window.preview_panel.source_stack.setCurrentWidget(window.video_widget)
            self._set_animation_format(False)
            window.current_video_fps = max(window._pending_video_info.fps, 1.0)
            self.on_duration_changed(window.media_player.duration())
        window.media_player.setPosition(0)
        window.media_player.pause()
        self.reset_clip_selection()
        window.render_controller.clear_preview_state(remove_temp_file=True)
        window._current_video_info = window._pending_video_info
        window._current_crop = None
        window.gif_preview_label.clear_crop()
        window.current_video_fps = max(window._pending_video_info.fps, 1.0)
        self.update_video_info_from_model(window._pending_video_path, window._pending_video_info)
        window.render_controller.on_crop_dimensions_changed()
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
            if self._animation_source is None:
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
        if self._animation_player is not None:
            if self._animation_player.playing:
                self._animation_player.pause()
            else:
                self._animation_player.play()
            return
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
        if self._animation_player is not None:
            self._animation_player.set_playback_rate(float(speed))

    def _set_preview_playback_speed(self, target_speed: float) -> None:
        """Select the nearest supported source-preview speed."""
        rates = [0.25, 0.5, 1.0, 1.5, 2.0]
        chosen = min(rates, key=lambda rate: abs(rate - target_speed))
        combo = self.window.preview_playback_speed_combo
        index = combo.findData(chosen)
        if index >= 0:
            combo.setCurrentIndex(index)
        self.window.media_player.setPlaybackRate(chosen)
        if self._animation_player is not None:
            self._animation_player.set_playback_rate(chosen)

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
        if self._animation_source is not None:
            return
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
        if self._animation_player is not None:
            self._animation_player.seek(position)
            return
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
        if self._animation_source is not None:
            return
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
        if self._animation_timeline is not None:
            self._animation_timeline.set_start_at_position()
            return
        if self.window.media_player.source().isEmpty():
            self.window.export_status_label.setText("Status: Load a video first.")
            return
        frame = self._ms_to_frame(self.window.media_player.position())
        self.window.seek_slider.set_selection(frame, self.window.end_frame)

    def set_clip_end(self) -> None:
        """Set the end marker at the current player frame."""
        if self._animation_timeline is not None:
            self._animation_timeline.set_end_at_position()
            return
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
        if self._animation_timeline is not None:
            return
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
            return
        if self._animation_timeline is not None:
            window.start_frame_label.setText(format_ms(round(window.clip_start_time * 1000)))
            window.end_frame_label.setText(format_ms(round(window.clip_end_time * 1000)))
        else:
            window.start_frame_label.setText(self._format_timestamp_from_frame(window.start_frame))
            window.end_frame_label.setText(self._format_timestamp_from_frame(window.end_frame))
        window.clip_selection_label.setText(
            f"Selection: {window.clip_end_time - window.clip_start_time:.3f}s"
        )
    def _leftArrowPressed(self) -> None:
        """Seek one source frame backwards."""
        if self._animation_timeline is not None:
            self._animation_timeline.step_frame(-1)
            return
        frame_ms = int(1000 / self.window.current_video_fps)
        self.window.media_player.setPosition(max(0, self.window.media_player.position() - frame_ms))

    def _rightArrowPressed(self) -> None:
        """Seek one source frame forwards."""
        if self._animation_timeline is not None:
            self._animation_timeline.step_frame(1)
            return
        frame_ms = int(1000 / self.window.current_video_fps)
        self.window.media_player.setPosition(self.window.media_player.position() + frame_ms)

    def _startSliderLeftPressed(self) -> None: self.nudge_start_frame(-1)
    def _startSetPressed(self) -> None: self.set_clip_start()
    def _startSliderRightPressed(self) -> None: self.nudge_start_frame(1)
    def _endSetPressed(self) -> None: self.set_clip_end()
    def _endSliderLeftPressed(self) -> None: self.nudge_end_frame(-1)
    def _endSliderRightPressed(self) -> None: self.nudge_end_frame(1)
    def _seconds_to_frame(self, seconds: float) -> int:
        if self._animation_timeline is not None:
            return 1
        return max(1, round(seconds * self.window.current_video_fps))
    def _ms_to_frame(self, milliseconds: int) -> int: return ms_to_frame(milliseconds, self.window.current_video_fps, self.window.total_frames)
    def _frame_to_ms(self, frame: int) -> int: return frame_to_ms(frame, self.window.current_video_fps)
    def _format_timestamp_from_frame(self, frame: int) -> str: return format_timestamp_from_frame(frame, self.window.current_video_fps)

    def _update_seek_time_label(self, current_ms: int | None = None) -> None:
        current = self._frame_to_ms(self.window.seek_slider.value()) if current_ms is None else current_ms
        total = self._frame_to_ms(max(self.window.total_frames - 1, 0))
        self.window.seek_time_label.setText(f"{format_ms(current)} / {format_ms(total)}")

    def _update_play_button_state(self, _state=None) -> None:
        playing = (self._animation_player.playing if self._animation_player is not None else
                   self.window.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.window.play_button.setText("⏸ Pause" if playing else "▶ Play")
