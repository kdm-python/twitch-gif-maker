"""Format-neutral rendering facade used by GUI controllers.

The lower-level GIF and WebP helpers remain public for compatibility while new
callers use this small service as the single format-selection boundary.
"""

from __future__ import annotations

from pathlib import Path

from gifmaker.models.render_settings import RenderSpec
from gifmaker.services.gif_export import GifExportError, export_gif, export_webp


class RenderService:
    """Render an animation using a resolved settings object."""

    def export(
        self,
        spec: RenderSpec,
        destination: str | Path,
    ) -> None:
        """Export the exact immutable recipe requested by the controller."""
        exporters = {"GIF": export_gif, "WebP": export_webp}
        try:
            exporter = exporters[spec.output_format]
        except KeyError as exc:
            raise GifExportError(
                f"Unsupported output format: {spec.output_format}"
            ) from exc
        exporter(
            spec.source_path,
            destination,
            start_seconds=spec.settings.start_seconds,
            end_seconds=spec.settings.end_seconds,
            fps=spec.settings.fps,
            width=spec.settings.width,
            height=spec.settings.height,
            playback_speed=spec.settings.playback_speed,
            quality_preset=spec.settings.quality_preset,
            crop=spec.settings.crop,
        )
