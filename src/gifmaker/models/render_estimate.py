"""Pure helpers for presenting expected animation export output."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class RenderEstimate:
    """Approximate output facts derived from the active render settings."""

    frame_count: int
    duration_seconds: float
    estimated_bytes: int


def calculate_render_estimate(
    *,
    source_duration_seconds: float,
    fps: int,
    playback_speed: float,
    width: int,
    height: int,
    output_format: str,
    quality_preset: str,
) -> RenderEstimate:
    """Estimate duration, frames, and compressed file size for an animation.

    File-size estimates use conservative empirical bytes-per-pixel-per-frame
    factors. They are intentionally labelled as estimates because source motion
    and colour complexity materially affect animated GIF and WebP compression.
    """
    if source_duration_seconds <= 0 or fps <= 0 or playback_speed <= 0:
        return RenderEstimate(0, 0.0, 0)

    duration = source_duration_seconds / playback_speed
    frame_count = max(1, ceil(duration * fps))
    quality_factors = {
        "GIF": {"small": 0.15, "balanced": 0.27, "high": 0.40},
        "WebP": {"small": 0.035, "balanced": 0.060, "high": 0.095},
    }
    compression = quality_factors.get(output_format, quality_factors["GIF"])
    bytes_per_pixel_frame = compression.get(quality_preset, compression["balanced"])
    estimated_bytes = round(width * height * frame_count * bytes_per_pixel_frame)
    return RenderEstimate(frame_count, duration, estimated_bytes)


def format_file_size(byte_count: int) -> str:
    """Format a non-negative byte count for compact GUI presentation."""
    if byte_count < 1024:
        return f"{byte_count} B"
    if byte_count < 1024**2:
        return f"{byte_count / 1024:.1f} KB"
    return f"{byte_count / 1024**2:.1f} MB"
