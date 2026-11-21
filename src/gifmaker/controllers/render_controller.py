"""Render-preview and export coordination for the main window."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QFileDialog

from gifmaker.models.render_estimate import calculate_render_estimate, format_file_size
from gifmaker.models.render_settings import (
    RenderSettings,
    RenderSpec,
    resolve_visual_settings,
)
from gifmaker.services.gif_export import format_ffmpeg_error
from gifmaker.services.output_formats import get_output_format
from gifmaker.services.render_service import RenderService
from gifmaker.services.webp_render import prepare_job


@dataclass
class _RenderProcessJob:
    """A single in-flight FFmpeg process and the immutable recipe it serves."""

    process: QProcess
    spec: RenderSpec
    destination: Path
    revision: int | None = None
    workspace: tempfile.TemporaryDirectory | None = None


class RenderController:
    """Build render settings and manage temporary previews and saved exports."""

    def __init__(self, window) -> None:
        self.window = window
        self.render_service = RenderService()
        self._preview_job: _RenderProcessJob | None = None
        self.preview_locked = False
        self._preview_suspended = False
        self._refresh_after_unlock = False
        self._export_job: _RenderProcessJob | None = None
        self._preview_debounce = QTimer(window)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.timeout.connect(self._generate_debounced_preview)

    def _resolve_render_settings(
        self, *, output_format: str | None = None
    ) -> RenderSettings:
        """Resolve the current timeline and controls into immutable settings."""
        window = self.window
        selected_format = output_format or window.export_format_combo.currentText()
        return resolve_visual_settings(
            window.clip_start_time, window.clip_end_time,
            window.export_controls_panel.control_values(), window._current_crop,
            uses_quality="quality" in get_output_format(selected_format).control_groups,
        )

    def _resolve_render_spec(self, *, output_format: str | None = None) -> RenderSpec:
        """Capture all inputs needed to produce one deterministic artifact."""
        window = self.window
        if window.current_video_path is None:
            raise ValueError("Load a video first.")
        return RenderSpec(
            source_path=window.current_video_path,
            output_format=output_format or window.export_format_combo.currentText(),
            settings=self._resolve_render_settings(output_format=output_format),
        )

    def on_output_format_changed(self, _value=None) -> None:
        """Apply format-specific controls before creating a new render revision."""
        self.window.export_controls_panel.set_output_format(
            self.window.export_format_combo.currentText()
        )
        self.on_render_setting_changed()

    def on_output_speed_changed(self, value: int) -> None:
        """Update output-speed feedback and apply it to the live preview."""
        speed = value / 100
        self.window.output_speed_value_label.setText(f"{speed:g}×")
        if not self.preview_locked:
            self.window.preview_controller.set_playback_speed(speed)
        self.on_render_setting_changed()

    def on_render_setting_changed(self, _value=None) -> None:
        """Record a changed render input and mark an older preview as stale."""
        should_refresh_preview = bool(
            self.window._last_preview_spec is not None or self._preview_job is not None
        )
        if self.preview_locked and self._preview_job is not None:
            self._refresh_after_unlock = True
        self.window._render_revision += 1
        self._cancel_stale_preview_job()
        self.update_output_summary()
        if should_refresh_preview and not self.preview_locked:
            self._schedule_preview_refresh()
        else:
            self._show_preview_stale_state()

    def suspend_preview(self) -> None:
        """Pin the displayed artifact without changing the user's lock setting."""
        self._preview_suspended = True
        self._preview_debounce.stop()
        self._cancel_preview_job()
        self.window.export_status_label.setText("Status: Subtitle workspace open.")

    def resume_preview(self) -> None:
        """Restore normal updates; keep the pinned frame until the next edit."""
        self._preview_suspended = False
        self.window.export_status_label.setText("Status: Preview ready. Click Export to save.")
        self._show_preview_stale_state()

    def set_preview_locked(self, locked: bool) -> None:
        """Switch between automatic and explicitly requested preview updates."""
        if locked == self.preview_locked:
            return
        self.preview_locked = locked
        if locked:
            self._refresh_after_unlock = bool(self._preview_job or self._preview_debounce.isActive())
            self._preview_debounce.stop()
            self._cancel_preview_job()
            self.window.export_status_label.setText("Status: Preview locked.")
            self._show_preview_stale_state()
            return

        had_pending = self._refresh_after_unlock
        self._refresh_after_unlock = False
        if self.window._last_preview_spec is None and not had_pending:
            return
        try:
            current = self._resolve_render_spec()
        except ValueError:
            return
        if current != self.window._last_preview_spec:
            self.generate_gif_preview()
        else:
            self.window.preview_controller.set_playback_speed(current.settings.playback_speed)
            self.window.export_status_label.setText("Status: Preview ready. Click Export to save.")

    def on_width_changed(self, width: int) -> None:
        """Keep output height proportional when aspect locking is enabled."""
        if self.window.aspect_ratio_lock.isChecked():
            self._set_linked_dimension(width=width)
        self.on_render_setting_changed()

    def on_height_changed(self, height: int) -> None:
        """Keep output width proportional when aspect locking is enabled."""
        if self.window.aspect_ratio_lock.isChecked():
            self._set_linked_dimension(height=height)
        self.on_render_setting_changed()

    def on_crop_dimensions_changed(self) -> None:
        """Recalculate the linked size after a crop changes the source aspect."""
        if self.window.aspect_ratio_lock.isChecked():
            self._set_linked_dimension(width=self.window.export_width_input.value())
        self.on_render_setting_changed()

    def _show_preview_stale_state(self) -> None:
        """Make it explicit when the displayed artifact is no longer current."""
        window = self.window
        if window._last_preview_spec is None:
            return
        try:
            current = self._resolve_render_spec()
        except ValueError:
            return
        if current != window._last_preview_spec:
            window.export_status_label.setText(
                "Status: Preview out of date. Export will render current settings."
            )

    def _schedule_preview_refresh(self) -> None:
        """Coalesce rapid control changes into one current-revision preview job."""
        if self._preview_suspended or self.window.current_video_path is None:
            return
        self.window.export_status_label.setText("Status: Updating preview...")
        self._preview_debounce.start(200)

    def _generate_debounced_preview(self) -> None:
        """Render only after a brief pause in setting changes."""
        self.generate_gif_preview()

    def use_original_size(self) -> None:
        """Set output dimensions to the current crop or source-video dimensions."""
        dimensions = self._render_source_dimensions()
        if dimensions is None:
            return
        width, height = dimensions
        self._set_output_dimensions(width, height)

    def _render_source_dimensions(self) -> tuple[int, int] | None:
        """Return dimensions that determine the active export aspect ratio."""
        if self.window._current_crop is not None:
            _, _, width, height = self.window._current_crop
            return width, height
        info = self.window._current_video_info
        if info is None:
            return None
        return info.width, info.height

    def _set_linked_dimension(
        self, *, width: int | None = None, height: int | None = None
    ) -> None:
        """Set the opposite dimension from the current source/crop ratio."""
        dimensions = self._render_source_dimensions()
        if dimensions is None:
            return
        source_width, source_height = dimensions
        if width is not None:
            self._set_output_dimensions(width, max(1, round(width * source_height / source_width)), width_changed=True)
        elif height is not None:
            self._set_output_dimensions(max(1, round(height * source_width / source_height)), height, height_changed=True)

    def _set_output_dimensions(
        self, width: int, height: int, *, width_changed: bool = False, height_changed: bool = False
    ) -> None:
        """Update output dimensions without recursively emitting value signals."""
        from PySide6.QtCore import QSignalBlocker

        window = self.window
        with QSignalBlocker(window.export_width_input), QSignalBlocker(window.export_height_input):
            if not width_changed:
                window.export_width_input.setValue(width)
            if not height_changed:
                window.export_height_input.setValue(height)
        self.on_render_setting_changed()

    def update_output_summary(self, *_args) -> None:
        """Show current output facts and a measured or approximate file size."""
        window = self.window
        if window.clip_start_time is None or window.clip_end_time is None:
            window.output_summary_label.setText("Output: Select a clip range")
            window.output_summary_label.setToolTip("")
            return
        settings = self._resolve_render_settings()
        estimate = calculate_render_estimate(
            source_duration_seconds=settings.end_seconds - settings.start_seconds,
            fps=settings.fps,
            playback_speed=settings.playback_speed,
            width=settings.width,
            height=settings.height,
            output_format=window.export_format_combo.currentText(),
            quality_preset=settings.quality_preset,
            sharpness_preset=settings.sharpness_preset,
        )
        size_text = f"Estimated ~{format_file_size(estimate.estimated_bytes)}"
        tooltip = ("Rough estimate: actual size depends on the video content. "
                   "Generate a preview for the measured file size.")
        try:
            spec = self._resolve_render_spec()
            if self._preview_matches(spec):
                size = window._preview_temp_file.stat().st_size
                size_text = f"Preview {format_file_size(size)}"
                tooltip = f"Matching preview: {size:,} bytes. Export will reuse this file."
        except (OSError, ValueError):
            pass
        window.output_summary_label.setText(
            f"Output: {settings.width}×{settings.height} · {estimate.frame_count} frames · "
            f"{estimate.duration_seconds:.2f}s · {size_text}"
        )
        window.output_summary_label.setToolTip(tooltip)

    def export_gif_from_selection(self) -> None:
        """Prompt for a target file and export the current selection."""
        window = self.window
        if window.current_video_path is None:
            window.export_status_label.setText("Status: Load a video first.")
            return
        fmt = window.export_format_combo.currentText()
        suffix = get_output_format(fmt).suffix
        source = Path(window.current_video_path)
        default_name = (source.with_name(f"{source.stem}-edited{suffix}")
                        if window.video_session_controller._animation_source is not None
                        else source.with_suffix(suffix))
        output_path, _ = QFileDialog.getSaveFileName(
            window,
            f"Save {fmt}",
            str(default_name),
            f"{fmt} Files (*{suffix})",
        )
        if not output_path:
            window.export_status_label.setText("Status: Export cancelled.")
            return
        try:
            spec = self._resolve_render_spec()
            self._check_destination(Path(output_path), spec)
        except (OSError, ValueError, RuntimeError) as exc:
            window.export_status_label.setText(f"Status: {exc}")
            return

        if self._preview_matches(spec):
            self._copy_preview(Path(output_path))
            return
        self._export_source(Path(output_path), spec)

    def _preview_matches(self, spec: RenderSpec) -> bool:
        """Return whether the saved preview is exactly the requested output."""
        window = self.window
        return bool(
            window._preview_temp_file
            and window._preview_temp_file.exists()
            and window._last_preview_spec == spec
        )

    def _copy_preview(self, destination: Path) -> None:
        """Save an identical preview without needlessly re-rendering it."""
        window = self.window
        window.export_status_label.setText("Status: Exporting preview...")
        try:
            self._check_destination(destination, window._last_preview_spec)
            if window.video_session_controller._animation_source is not None:
                self._atomic_copy(window._preview_temp_file, destination)
            else:
                shutil.copyfile(window._preview_temp_file, destination)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.error("Failed to save preview export: {}", exc)
            window.export_status_label.setText(f"Status: Export failed: {exc}")
            return
        window.export_status_label.setText("Status: Export complete.")

    def _export_source(self, destination: Path, spec: RenderSpec) -> None:
        """Start a non-blocking export for the captured settings snapshot."""
        window = self.window
        if self._export_job is not None:
            window.export_status_label.setText("Status: Export already in progress.")
            return
        workspace = None
        try:
            self._check_destination(destination, spec)
            source = window.video_session_controller._animation_source
            if source is not None:
                workspace, command = prepare_job(source, spec)
            else:
                command = self.render_service.build_command(spec, destination)
        except Exception as exc:  # noqa: BLE001 - report preparation failures without closing the application
            logger.error("Export preparation failed: {}", exc)
            window.export_status_label.setText(f"Status: Export failed: {exc}")
            return
        window.export_status_label.setText("Status: Exporting...")
        self._export_job = self._start_process(
            command,
            spec,
            destination,
            workspace=workspace,
            on_finished=self._on_export_finished,
        )

    def generate_gif_preview(self) -> None:
        """Render a temporary preview in the selected output format."""
        if self._preview_suspended:
            return
        window = self.window
        self._preview_debounce.stop()
        if window.current_video_path is None:
            window.export_status_label.setText("Status: Load a video first.")
            return
        try:
            spec = self._resolve_render_spec()
        except ValueError as exc:
            window.export_status_label.setText(f"Status: {exc}")
            return

        suffix = get_output_format(spec.output_format).suffix
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix="gifmaker-preview-", suffix=suffix)
            os.close(descriptor)
        except OSError as exc:
            logger.error("Could not create preview file: {}", exc)
            window.export_status_label.setText(f"Status: Preview failed: {exc}")
            return
        temporary_file = Path(temporary_name)
        self._cancel_preview_job()
        window.export_status_label.setText("Status: Generating preview...")
        workspace = None
        try:
            source = window.video_session_controller._animation_source
            if source is not None:
                workspace, command = prepare_job(source, spec)
            else:
                command = self.render_service.build_command(spec, temporary_file)
        except Exception as exc:  # noqa: BLE001 - report preparation failures without closing the application
            self.remove_temp_file_if_exists(temporary_file)
            logger.error("Preview generation failed: {}", exc)
            window.export_status_label.setText(f"Status: Preview failed: {exc}")
            return
        self._preview_job = self._start_process(
            command,
            spec,
            temporary_file,
            workspace=workspace,
            revision=window._render_revision,
            on_finished=self._on_preview_finished,
        )

    def _start_process(
        self,
        command: list[str],
        spec: RenderSpec,
        destination: Path,
        *,
        on_finished,
        revision: int | None = None,
        workspace: tempfile.TemporaryDirectory | None = None,
    ) -> _RenderProcessJob:
        """Launch FFmpeg without blocking Qt's event loop."""
        process = QProcess(self.window)
        job = _RenderProcessJob(process, spec, destination, revision, workspace)
        process.finished.connect(
            lambda exit_code, exit_status, active_job=job: on_finished(
                active_job, exit_code, exit_status
            )
        )
        process.errorOccurred.connect(
            lambda _error, active_job=job: self._on_process_error(active_job)
        )
        process.setProgram(command[0])
        process.setArguments(command[1:])
        logger.info("Starting FFmpeg {} render: {}", spec.output_format, " ".join(command))
        process.start()
        return job

    def _on_process_error(self, job: _RenderProcessJob) -> None:
        """Surface failures to launch FFmpeg and clean up a failed preview."""
        logger.error("Render process error: {}", job.process.errorString())
        if job is self._preview_job:
            self._preview_job = None
            self.remove_temp_file_if_exists(job.destination)
            self.window.export_status_label.setText(
                f"Status: Preview failed: {job.process.errorString()}"
            )
        elif job is self._export_job:
            self._export_job = None
            self.window.export_status_label.setText(
                f"Status: Export failed: {job.process.errorString()}"
            )
        if job.process.state() == QProcess.ProcessState.NotRunning:
            self._cleanup_workspace(job)

    def _on_preview_finished(self, job: _RenderProcessJob, exit_code: int, _status) -> None:
        """Adopt only the latest successful preview job."""
        if _status == QProcess.ExitStatus.CrashExit:
            exit_code = exit_code or 1
        is_current_job = job is self._preview_job
        if is_current_job:
            self._preview_job = None
        is_current_revision = job.revision == self.window._render_revision
        if is_current_job and is_current_revision and exit_code == 0 and job.workspace is not None:
            try:
                self._atomic_copy(Path(job.workspace.name) / "result.webp", job.destination)
            except (OSError, ValueError) as exc:
                logger.error("Preview finalization failed: {}", exc)
                self.window.export_status_label.setText(f"Status: Preview failed: {exc}")
                self.remove_temp_file_if_exists(job.destination)
                self._cleanup_workspace(job)
                return
        self._cleanup_workspace(job)
        if not is_current_job or not is_current_revision or exit_code != 0:
            self.remove_temp_file_if_exists(job.destination)
            if is_current_job and exit_code != 0:
                message = bytes(job.process.readAllStandardError()).decode(errors="replace").strip()
                message = format_ffmpeg_error(message)
                logger.error("Preview render failed: {}", message)
                self.window.export_status_label.setText(
                    f"Status: Preview failed: {message or 'ffmpeg exited unsuccessfully'}"
                )
            return
        previous_settings = self.window._last_preview_settings
        previous_speed = self.window.preview_controller._preview_speed()
        self.window._last_preview_settings = job.spec.settings
        self.window.preview_controller.set_playback_speed(job.spec.settings.playback_speed)
        try:
            self.window.preview_controller.load(job.destination)
        except RuntimeError as exc:
            self.window._last_preview_settings = previous_settings
            self.window.preview_controller.set_playback_speed(previous_speed)
            self.remove_temp_file_if_exists(job.destination)
            self.window.export_status_label.setText(f"Status: Preview failed: {exc}")
            return

        self.window.export_controls_panel.set_preview_playing(True, enabled=True)

        window = self.window
        previous_file = window._preview_temp_file
        window._preview_temp_file = job.destination
        window._last_preview_settings = job.spec.settings
        window._last_preview_source = job.spec.source_path
        window._last_preview_spec = job.spec
        window.gif_preview_label.set_coordinate_space(job.spec.settings.crop)
        if previous_file and previous_file != job.destination:
            self.remove_temp_file_if_exists(previous_file)
        self.update_output_summary()
        window.export_status_label.setText("Status: Preview ready. Click Export to save.")

    def _on_export_finished(self, job: _RenderProcessJob, exit_code: int, _status) -> None:
        """Complete an export without coupling it to later UI changes."""
        if _status == QProcess.ExitStatus.CrashExit:
            exit_code = exit_code or 1
        if job is not self._export_job:
            self._cleanup_workspace(job)
            return
        self._export_job = None
        if exit_code == 0 and job.workspace is not None:
            try:
                self._check_destination(job.destination, job.spec)
                self._atomic_copy(Path(job.workspace.name) / "result.webp", job.destination)
            except (OSError, ValueError) as exc:
                logger.error("Export finalization failed: {}", exc)
                self.window.export_status_label.setText(f"Status: Export failed: {exc}")
                self._cleanup_workspace(job)
                return
        self._cleanup_workspace(job)
        if exit_code == 0:
            self.window.export_status_label.setText("Status: Export complete.")
            logger.info("{} export completed: {}", job.spec.output_format, job.destination)
            return
        message = bytes(job.process.readAllStandardError()).decode(errors="replace").strip()
        message = format_ffmpeg_error(message)
        logger.error("Export render failed: {}", message)
        self.window.export_status_label.setText(
            f"Status: Export failed: {message or 'ffmpeg exited unsuccessfully'}"
        )

    def _cancel_stale_preview_job(self) -> None:
        """Stop an in-flight preview as soon as its input revision changes."""
        if self._preview_job is not None:
            self._cancel_preview_job()

    def _cancel_preview_job(self) -> None:
        """Cancel an in-flight preview; its finish callback performs cleanup."""
        job = self._preview_job
        if job is None:
            return
        self._preview_job = None
        if job.process.state() != QProcess.ProcessState.NotRunning:
            self._stop_job(job)
        else:
            self.remove_temp_file_if_exists(job.destination)
            self._cleanup_workspace(job)

    def _check_destination(self, destination: Path, spec: RenderSpec) -> None:
        suffix = get_output_format(spec.output_format).suffix
        if destination.suffix.lower() != suffix:
            raise ValueError(f"Output file must use a {suffix} extension.")
        if not destination.parent.is_dir():
            raise ValueError("Output directory does not exist.")
        sources = [Path(spec.source_path)]
        if self.window.current_video_path:
            sources.append(Path(self.window.current_video_path))
        for source in sources:
            if destination.resolve() == source.resolve() or (
                destination.exists() and source.exists() and os.path.samefile(destination, source)
            ):
                raise ValueError("Choose an output file different from the original source.")

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".gifmaker-", suffix=destination.suffix,
                                            dir=destination.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _cleanup_workspace(job: _RenderProcessJob) -> None:
        if job.workspace is not None:
            job.workspace.cleanup()
            job.workspace = None

    def _stop_job(self, job: _RenderProcessJob) -> None:
        if job.workspace is None:
            job.process.kill()
            return
        job.process.terminate()
        if not job.process.waitForFinished(3000):
            job.process.kill()
            job.process.waitForFinished(3000)
        self._cleanup_workspace(job)

    def apply_crop_to_preview(self) -> None:
        """Render a preview using the crop that is currently drawn."""
        if self.window.current_video_path is None:
            self.window.export_status_label.setText("Status: Load a video first.")
        elif self.window._current_crop is None:
            self.window.export_status_label.setText("Status: Draw a crop selection first.")
        elif not self.preview_locked:
            self.generate_gif_preview()
        else:
            self._show_preview_stale_state()

    def reset_preview_crop(self) -> None:
        """Restore the full source aspect ratio and regenerate its preview.

        An applied crop clears the overlay after rendering, so calling only
        ``clear_crop`` here may not emit ``cropCleared``.  Reset the coordinate
        space and linked output dimensions explicitly to avoid rendering a full
        frame at the former crop's aspect ratio.
        """
        window = self.window
        window._current_crop = None
        if not self.preview_locked:
            window.gif_preview_label.set_coordinate_space(None)
        else:
            window.gif_preview_label.clear_crop()
        self.on_crop_dimensions_changed()
        if window.current_video_path is not None and not self.preview_locked:
            self.generate_gif_preview()

    def _on_crop_changed(self, x: int, y: int, width: int, height: int) -> None:
        """Store crop geometry emitted by the crop overlay view."""
        self.window._current_crop = (x, y, width, height)
        self.on_crop_dimensions_changed()

    def _on_crop_cleared(self) -> None:
        """Clear stored crop geometry when the overlay clears itself."""
        self.window._current_crop = None
        self.on_crop_dimensions_changed()

    def set_gif_preview_playing(self, playing: bool) -> None:
        """Play or pause the generated preview from its single toggle control."""
        if self.window._last_preview_spec is None:
            self.window.export_controls_panel.set_preview_playing(False, enabled=False)
            return
        self.window.export_controls_panel.set_preview_playing(playing, enabled=True)
        if playing:
            self.window.preview_controller.play()
        else:
            self.window.preview_controller.pause()

    def toggle_gif_preview_playback(self) -> None:
        """Toggle generated-preview playback while keeping its button in sync."""
        button = self.window.gif_preview_play_pause_button
        if button.isEnabled():
            self.set_gif_preview_playing(not button.isChecked())

    def play_gif_preview(self) -> None:
        """Compatibility adapter for callers that explicitly start the preview."""
        self.set_gif_preview_playing(True)

    def pause_gif_preview(self) -> None:
        """Compatibility adapter for callers that explicitly pause the preview."""
        self.set_gif_preview_playing(False)

    def clear_preview_state(self, *, remove_temp_file: bool) -> None:
        """Dispose of preview playback and optionally delete its temporary file."""
        self._preview_debounce.stop()
        self._refresh_after_unlock = False
        self._cancel_preview_job()
        self.window.preview_controller.clear(remove_temp_file=remove_temp_file)
        self.window.export_controls_panel.set_preview_playing(False, enabled=False)
        self.update_output_summary()

    def cancel_active_renders(self) -> None:
        """Stop running FFmpeg processes during application shutdown."""
        self._preview_debounce.stop()
        self._cancel_preview_job()
        if self._export_job is not None:
            job = self._export_job
            self._export_job = None
            if job.process.state() != QProcess.ProcessState.NotRunning:
                self._stop_job(job)
            else:
                self._cleanup_workspace(job)

    def remove_temp_file_if_exists(self, file_path: Path) -> None:
        """Delegate temporary-file cleanup to the preview lifecycle helper."""
        self.window.preview_controller.remove_temp_file_if_exists(file_path)
