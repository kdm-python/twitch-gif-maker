"""Format-neutral rendering facade used by GUI controllers.

The lower-level GIF and WebP helpers remain public for compatibility while new
callers use this small service as the single format-selection boundary.
"""

from __future__ import annotations

from pathlib import Path

from gifmaker.models.render_settings import RenderSettings
from gifmaker.services.gif_export import GifExportError, export_gif, export_webp


class RenderService:
    """Render an animation using a resolved settings object."""

    def export(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        output_format: str,
        settings: RenderSettings,
    ) -> None:
        """Export ``source`` in the requested supported animation format."""
        exporters = {"GIF": export_gif, "WebP": export_webp}
        try:
            exporter = exporters[output_format]
        except KeyError as exc:
            raise GifExportError(f"Unsupported output format: {output_format}") from exc
        exporter(
            source,
            destination,
            start_seconds=settings.start_seconds,
            end_seconds=settings.end_seconds,
            fps=settings.fps,
            width=settings.width,
            playback_speed=settings.playback_speed,
            crop=settings.crop,
        )
