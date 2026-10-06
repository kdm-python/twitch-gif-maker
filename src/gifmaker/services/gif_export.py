"""FFmpeg-based GIF export service."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from loguru import logger


QUALITY_PRESETS: dict[str, dict[str, str | int]] = {
    "small": {
        "label": "Small file",
        "gif_colors": 128,
        "gif_dither": "bayer:bayer_scale=3",
        "webp_quality": 50,
        "webp_preset": "picture",
    },
    "balanced": {
        "label": "Balanced",
        "gif_colors": 256,
        "gif_dither": "sierra2_4a",
        "webp_quality": 75,
        "webp_preset": "photo",
    },
    "high": {
        "label": "High quality",
        "gif_colors": 256,
        "gif_dither": "sierra2_4a",
        "webp_quality": 90,
        "webp_preset": "photo",
    },
}


def _ffmpeg_exe() -> str:
    # GIFMAKER_FFMPEG lets a dev point at a capable build (e.g. ffmpeg-full)
    return os.environ.get("GIFMAKER_FFMPEG", "ffmpeg")


class GifExportError(Exception):
    """Raised when GIF export validation or FFmpeg execution fails."""


def export_gif(
    input_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float,
    end_seconds: float,
    fps: int,
    width: int,
    height: int | None = None,
    playback_speed: float = 1.0,
    quality_preset: str = "balanced",
    crop: tuple[int, int, int, int] | None = None,
) -> None:
    """Export a palette-optimised GIF from a section of video using FFmpeg."""
    source = Path(input_path)
    destination = Path(output_path)

    if not source.exists() or not source.is_file():
        raise GifExportError(f"Input video does not exist: {source}")
    if destination.suffix.lower() != ".gif":
        raise GifExportError("Output file must use a .gif extension")
    if destination.parent and not destination.parent.exists():
        raise GifExportError(f"Output directory does not exist: {destination.parent}")
    if start_seconds < 0:
        raise GifExportError("Start time must be greater than or equal to 0")
    if end_seconds <= start_seconds:
        raise GifExportError("End time must be greater than start time")
    if fps <= 0:
        raise GifExportError("FPS must be greater than 0")
    if playback_speed <= 0:
        raise GifExportError("Playback speed must be greater than 0")
    if width <= 0:
        raise GifExportError("Width must be greater than 0")
    if height is not None and height <= 0:
        raise GifExportError("Height must be greater than 0")
    if quality_preset not in QUALITY_PRESETS:
        raise GifExportError(f"Unknown quality preset: {quality_preset}")
    if crop is not None:
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0:
            raise GifExportError(
                "Crop dimensions must be positive with non-negative origin"
            )

    target_height = height if height is not None else -1
    filters = _build_gif_filter_complex(
        fps, width, target_height, crop, playback_speed, quality_preset
    )

    ffmpeg_cmd = [
        _ffmpeg_exe(),
        "-y",
        "-ss",
        str(start_seconds),
        "-to",
        str(end_seconds),
        "-i",
        str(source),
        "-filter_complex",
        filters,
        "-loop",
        "0",
        str(destination),
    ]

    logger.info("Running FFmpeg GIF export: {}", " ".join(ffmpeg_cmd))
    logger.info("*** Full ffmpeg command: {}", " ".join(ffmpeg_cmd))

    try:
        result = subprocess.run(
            ffmpeg_cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise GifExportError(f"Failed to execute ffmpeg: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown ffmpeg error"
        raise GifExportError(f"ffmpeg export failed: {stderr}")

    logger.info("GIF export completed: {}", destination)


def _build_vf_filters(
    fps: int,
    width: int,
    height: int,
    crop: tuple[int, int, int, int] | None,
    playback_speed: float = 1.0,
) -> str:
    timing = "" if playback_speed == 1.0 else f"setpts=PTS/{playback_speed:g},"
    vf = f"{timing}fps={fps},scale={width}:{height}:flags=lanczos"
    if crop is not None:
        cx, cy, cw, ch = crop
        vf = f"crop={cw}:{ch}:{cx}:{cy},{vf}"
    return vf


def _build_gif_filter_complex(
    fps: int,
    width: int,
    height: int,
    crop: tuple[int, int, int, int] | None,
    playback_speed: float,
    quality_preset: str,
) -> str:
    """Build a palette-generation graph for high-quality animated GIF output."""
    preset = QUALITY_PRESETS[quality_preset]
    video_filters = _build_vf_filters(fps, width, height, crop, playback_speed)
    return (
        f"[0:v]{video_filters},split[gif][palette_source];"
        f"[palette_source]palettegen=max_colors={preset['gif_colors']}:stats_mode=diff[palette];"
        f"[gif][palette]paletteuse=dither={preset['gif_dither']}"
    )


def export_webp(
    input_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float,
    end_seconds: float,
    fps: int,
    width: int,
    height: int | None = None,
    playback_speed: float = 1.0,
    quality_preset: str = "balanced",
    crop: tuple[int, int, int, int] | None = None,
) -> None:
    """Export an animated WebP from a section of a video using FFmpeg."""
    source = Path(input_path)
    destination = Path(output_path)

    if not source.exists() or not source.is_file():
        raise GifExportError(f"Input video does not exist: {source}")
    if destination.suffix.lower() != ".webp":
        raise GifExportError("Output file must use a .webp extension")
    if destination.parent and not destination.parent.exists():
        raise GifExportError(f"Output directory does not exist: {destination.parent}")
    if start_seconds < 0:
        raise GifExportError("Start time must be greater than or equal to 0")
    if end_seconds <= start_seconds:
        raise GifExportError("End time must be greater than start time")
    if fps <= 0:
        raise GifExportError("FPS must be greater than 0")
    if playback_speed <= 0:
        raise GifExportError("Playback speed must be greater than 0")
    if width <= 0:
        raise GifExportError("Width must be greater than 0")
    if height is not None and height <= 0:
        raise GifExportError("Height must be greater than 0")
    if quality_preset not in QUALITY_PRESETS:
        raise GifExportError(f"Unknown quality preset: {quality_preset}")
    if crop is not None:
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0:
            raise GifExportError(
                "Crop dimensions must be positive with non-negative origin"
            )

    target_height = height if height is not None else -1
    vf = _build_vf_filters(fps, width, target_height, crop, playback_speed)
    preset = QUALITY_PRESETS[quality_preset]
    logger.debug("*** WebP export VF FILTERS *** {}", vf)

    ffmpeg_cmd = [
        _ffmpeg_exe(),
        "-y",
        "-ss",
        str(start_seconds),
        "-to",
        str(end_seconds),
        "-i",
        str(source),
        "-vf",
        vf,
        "-c:v",
        "libwebp_anim",
        "-quality",
        str(preset["webp_quality"]),
        "-preset",
        str(preset["webp_preset"]),
        "-loop",
        "0",
        "-an",
        str(destination),
    ]

    logger.info("Running FFmpeg WebP export: {}", " ".join(ffmpeg_cmd))

    try:
        result = subprocess.run(
            ffmpeg_cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise GifExportError(f"Failed to execute ffmpeg: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown ffmpeg error"
        raise GifExportError(f"ffmpeg export failed: {stderr}")

    logger.info("WebP export completed: {}", destination)
