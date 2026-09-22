"""Render-preview and export coordination for the main window."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger
from PySide6.QtWidgets import QFileDialog

from gifmaker.models.render_settings import RenderSettings
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
        speed = window.playback_speed_combo.currentData() or 1.0
        return RenderSettings(
            start_seconds=window.clip_start_time,
            end_seconds=window.clip_end_time,
            fps=24,
            width=window.export_width_input.value(),
            playback_speed=float(speed),
            crop=window._current_crop,
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
            settings = self._resolve_render_settings()
        except ValueError as exc:
            window.export_status_label.setText(f"Status: {exc}")
            return

        if fmt == "GIF" and self._preview_matches(settings):
            self._copy_preview(Path(output_path))
            return
        self._export_source(Path(output_path), fmt, settings)

    def _preview_matches(self, settings: RenderSettings) -> bool:
        """Return whether the saved preview is the requested GIF output."""
        window = self.window
        return bool(
            window._preview_temp_file
            and window._preview_temp_file.exists()
            and window._last_preview_source == window.current_video_path
            and window._last_preview_settings == settings
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

    def _export_source(self, destination: Path, fmt: str, settings: RenderSettings) -> None:
        """Invoke the matching exporter and report its terminal state."""
        window = self.window
        window.export_status_label.setText("Status: Exporting...")
        try:
            self.render_service.export(
                window.current_video_path,
                destination,
                output_format=fmt,
                settings=settings,
            )
        except GifExportError as exc:
            logger.error("{} export failed: {}", fmt, exc)
            window.export_status_label.setText(f"Status: Export failed: {exc}")
            return
        window.export_status_label.setText("Status: Export complete.")
        logger.info("{} export completed: {}", fmt, destination)

    def generate_gif_preview(self, *, force_crop: bool = False) -> None:
        """Render a temporary GIF preview for the current selection and crop."""
        window = self.window
        if window.current_video_path is None:
            window.export_status_label.setText("Status: Load a video first.")
            return
        if not force_crop:
            window._current_crop = None
            window.gif_preview_label.clear_crop()
        try:
            settings = self._resolve_render_settings()
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
                start_seconds=settings.start_seconds,
                end_seconds=settings.end_seconds,
                fps=settings.fps,
                width=settings.width,
                playback_speed=settings.playback_speed,
                crop=settings.crop,
            )
            window.preview_controller.set_movie(temporary_file)
        except (GifExportError, RuntimeError) as exc:
            self.remove_temp_file_if_exists(temporary_file)
            logger.error("Preview generation failed: {}", exc)
            window.export_status_label.setText(f"Status: Preview failed: {exc}")
            return
        window._preview_temp_file = temporary_file
        window._last_preview_settings = settings
        window._last_preview_source = window.current_video_path
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
            self.generate_gif_preview(force_crop=True)

    def reset_preview_crop(self) -> None:
        """Clear the crop selection and regenerate the uncropped preview."""
        self.window._current_crop = None
        self.window.gif_preview_label.clear_crop()
        if self.window.current_video_path is not None:
            self.generate_gif_preview()

    def _on_crop_changed(self, x: int, y: int, width: int, height: int) -> None:
        """Store crop geometry emitted by the crop overlay view."""
        self.window._current_crop = (x, y, width, height)

    def _on_crop_cleared(self) -> None:
        """Clear stored crop geometry when the overlay clears itself."""
        self.window._current_crop = None

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
