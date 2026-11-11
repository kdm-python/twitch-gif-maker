"""Explicit registry of output renderers and their file extensions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gifmaker.models.render_settings import RenderSpec
from gifmaker.services.gif_export import (
    GifExportError,
    build_gif_command,
    build_webp_command,
)


@dataclass(frozen=True)
class OutputFormat:
    name: str
    suffix: str
    build_command: Callable[[RenderSpec, str | Path], list[str]]
    control_groups: frozenset[str] = frozenset()


def _animation_command(builder, spec: RenderSpec, destination: str | Path) -> list[str]:
    settings = spec.settings
    return builder(
        spec.source_path, destination,
        start_seconds=settings.start_seconds, end_seconds=settings.end_seconds,
        fps=settings.fps, width=settings.width, height=settings.height,
        playback_speed=settings.playback_speed, quality_preset=settings.quality_preset,
        sharpness_preset=settings.sharpness_preset, crop=settings.crop,
    )


def _gif(spec: RenderSpec, destination: str | Path) -> list[str]:
    return _animation_command(build_gif_command, spec, destination)


def _webp(spec: RenderSpec, destination: str | Path) -> list[str]:
    return _animation_command(build_webp_command, spec, destination)


_VISUAL_GROUPS = frozenset({"fps", "size", "sharpness", "crop"})

_FORMATS = {
    item.name: item for item in (
        OutputFormat("WebP", ".webp", _webp, _VISUAL_GROUPS | {"quality"}),
        OutputFormat("GIF", ".gif", _gif, _VISUAL_GROUPS),
    )
}


def get_output_format(name: str) -> OutputFormat:
    try:
        return _FORMATS[name]
    except KeyError as exc:
        raise GifExportError(f"Unsupported output format: {name}") from exc
