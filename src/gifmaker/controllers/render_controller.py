"""Render-preview and export coordination for the main window."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger
from PySide6.QtWidgets import QFileDialog

from gifmaker.models.render_settings import RenderSettings, RenderSpec
from gifmaker.models.render_estimate import calculate_render_estimate, format_file_size
from gifmaker.services.gif_export import GifExportError, export_gif
from gifmaker.services.render_service import RenderService


class RenderController:
    """Build render settings and manage temporary previews and saved exports."""

    def __init__(self, window) -> None:
        self.window = window
        self.render_service = RenderService()

    def _resolve_render_settings(self) -> RenderSettings:
        """Resolve the current timeline and controls into immutable settings."""
        window = self.window
        if window.clip_start_time is None or window.clip_end_time is None:
            raise ValueError("Select a clip range on the timeline before export")
        if window.clip_end_time <= window.clip_start_time:
            raise ValueError("End time must be greater than start time")
        speed = window.output_speed_slider.value() / 100
        fps = window.output_fps_combo.currentData() or 24
        return RenderSettings(
            start_seconds=window.clip_start_time,
            end_seconds=window.clip_end_time,
            fps=int(fps),
            width=window.export_width_input.value(),
            height=window.export_height_input.value(),
            playback_speed=float(speed),
            quality_preset=str(window.quality_preset_combo.currentData()),
            crop=window._current_crop,
        )

    def _resolve_render_spec(self, *, output_format: str | None = None) -> RenderSpec:
        """Capture all inputs needed to produce one deterministic artifact."""
        window = self.window
        if window.current_video_path is None:
            raise ValueError("Load a video first.")
        return RenderSpec(
            source_path=window.current_video_path,
            output_format=output_format or window.export_format_combo.currentText(),
            settings=self._resolve_render_settings(),
        )

    def on_output_speed_changed(self, value: int) -> None:
        """Update output-speed feedback and apply it to the live GIF preview."""
        speed = value / 100
        self.window.output_speed_value_label.setText(f"{speed:g}×")
        self.window.preview_controller.set_playback_speed(speed)
        self.on_render_setting_changed()

    def on_render_setting_changed(self, _value=None) -> None:
        """Record a changed render input and mark an older preview as stale."""
        self.window._render_revision += 1
        self.update_output_summary()
        self._show_preview_stale_state()

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
            current = self._resolve_render_spec(output_format="GIF")
        except ValueError:
            return
        if current != window._last_preview_spec:
            window.export_status_label.setText(
                "Status: Preview out of date. Export will render current settings."
            )

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
        """Show live output dimensions, duration, frames, and estimated size."""
        window = self.window
        if window.clip_start_time is None or window.clip_end_time is None:
            window.output_summary_label.setText("Output: Select a clip range")
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
        )
        window.output_summary_label.setText(
            f"Output: {settings.width}×{settings.height} · {estimate.frame_count} frames · "
            f"{estimate.duration_seconds:.2f}s · ~{format_file_size(estimate.estimated_bytes)}"
        )

    def export_gif_from_selection(self) -> None:
        """Prompt for a target file and export the current selection."""
        window = self.window
        if window.current_video_path is None:
            window.export_status_label.setText("Status: Load a video first.")
            return
        fmt = window.export_format_combo.currentText()
        suffix = ".webp" if fmt == "WebP" else ".gif"
        output_path, _ = QFileDialog.getSaveFileName(
            window,
            f"Save {fmt}",
            str(Path(window.current_video_path).with_suffix(suffix)),
            f"{fmt} Files (*{suffix})",
        )
        if not output_path:
            window.export_status_label.setText("Status: Export cancelled.")
            return
        try:
            spec = self._resolve_render_spec()
        except ValueError as exc:
            window.export_status_label.setText(f"Status: {exc}")
            return

        if self._preview_matches(spec):
            self._copy_preview(Path(output_path))
            return
        self._export_source(Path(output_path), spec)

    def _preview_matches(self, spec: RenderSpec) -> bool:
        """Return whether the saved preview is the requested GIF output."""
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
            shutil.copyfile(window._preview_temp_file, destination)
        except OSError as exc:
            logger.error("Failed to save preview export: {}", exc)
            window.export_status_label.setText(f"Status: Export failed: {exc}")
            return
        window.export_status_label.setText("Status: Export complete.")

    def _export_source(self, destination: Path, spec: RenderSpec) -> None:
        """Invoke the matching exporter and report its terminal state."""
        window = self.window
        window.export_status_label.setText("Status: Exporting...")
        try:
            self.render_service.export(
                spec,
                destination,
            )
        except GifExportError as exc:
            logger.error("{} export failed: {}", spec.output_format, exc)
            window.export_status_label.setText(f"Status: Export failed: {exc}")
            return
        window.export_status_label.setText("Status: Export complete.")
        logger.info("{} export completed: {}", spec.output_format, destination)

    def generate_gif_preview(self) -> None:
        """Render a temporary GIF preview for the current selection and crop."""
        window = self.window
        if window.current_video_path is None:
            window.export_status_label.setText("Status: Load a video first.")
            return
        try:
            # The current preview implementation is GIF-only.  Pinning its
            # format in the spec prevents a WebP export from ever copying it.
            spec = self._resolve_render_spec(output_format="GIF")
        except ValueError as exc:
            window.export_status_label.setText(f"Status: {exc}")
            return

        descriptor, temporary_name = tempfile.mkstemp(prefix="gifmaker-preview-", suffix=".gif")
        os.close(descriptor)
        temporary_file = Path(temporary_name)
        previous_file = window._preview_temp_file
        window.export_status_label.setText("Status: Generating preview...")
        try:
            export_gif(
                window.current_video_path,
                temporary_file,
                start_seconds=spec.settings.start_seconds,
                end_seconds=spec.settings.end_seconds,
                fps=spec.settings.fps,
                width=spec.settings.width,
                height=spec.settings.height,
                playback_speed=spec.settings.playback_speed,
                quality_preset=spec.settings.quality_preset,
                crop=spec.settings.crop,
            )
            window.preview_controller.set_movie(temporary_file)
        except (GifExportError, RuntimeError) as exc:
            self.remove_temp_file_if_exists(temporary_file)
            logger.error("Preview generation failed: {}", exc)
            window.export_status_label.setText(f"Status: Preview failed: {exc}")
            return
        window._preview_temp_file = temporary_file
        window._last_preview_settings = spec.settings
        window._last_preview_source = spec.source_path
        window._last_preview_spec = spec
        window.gif_preview_label.set_coordinate_space(spec.settings.crop)
        if previous_file and previous_file != temporary_file:
            self.remove_temp_file_if_exists(previous_file)
        window.export_status_label.setText("Status: Preview ready. Click Export to save.")

    def apply_crop_to_preview(self) -> None:
        """Render a preview using the crop that is currently drawn."""
        if self.window.current_video_path is None:
            self.window.export_status_label.setText("Status: Load a video first.")
        elif self.window._current_crop is None:
            self.window.export_status_label.setText("Status: Draw a crop selection first.")
        else:
            self.generate_gif_preview()

    def reset_preview_crop(self) -> None:
        """Clear the crop selection and regenerate the uncropped preview."""
        self.window._current_crop = None
        self.window.gif_preview_label.clear_crop()
        if self.window.current_video_path is not None:
            self.generate_gif_preview()

    def _on_crop_changed(self, x: int, y: int, width: int, height: int) -> None:
        """Store crop geometry emitted by the crop overlay view."""
        self.window._current_crop = (x, y, width, height)
        self.on_crop_dimensions_changed()

    def _on_crop_cleared(self) -> None:
        """Clear stored crop geometry when the overlay clears itself."""
        self.window._current_crop = None
        self.on_crop_dimensions_changed()

    def play_gif_preview(self) -> None:
        """Start the currently generated preview."""
        self.window.preview_controller.play()

    def pause_gif_preview(self) -> None:
        """Pause the currently generated preview."""
        self.window.preview_controller.pause()

    def clear_preview_state(self, *, remove_temp_file: bool) -> None:
        """Dispose of preview playback and optionally delete its temporary file."""
        self.window.preview_controller.clear(remove_temp_file=remove_temp_file)

    def remove_temp_file_if_exists(self, file_path: Path) -> None:
        """Delegate temporary-file cleanup to the preview lifecycle helper."""
        self.window.preview_controller.remove_temp_file_if_exists(file_path)
