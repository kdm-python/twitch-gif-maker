"""FFmpeg-based GIF export service."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from loguru import logger


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
    playback_speed: float = 1.0,
    crop: tuple[int, int, int, int] | None = None,
) -> None:
    """Export a GIF from a section of a video using FFmpeg."""
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
    if crop is not None:
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0:
            raise GifExportError(
                "Crop dimensions must be positive with non-negative origin"
            )

    effective_fps = _effective_output_fps(fps, playback_speed)
    vf = _build_vf_filters(effective_fps, width, crop)

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
        "-quality",
        "90",
        "-preset",
        "photo",
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


def _effective_output_fps(base_fps: int, playback_speed: float) -> int:
    """Compute the effective GIF frame rate from the base GIF FPS and playback speed."""
    if base_fps <= 0:
        raise GifExportError("FPS must be greater than 0")
    if playback_speed <= 0:
        raise GifExportError("Playback speed must be greater than 0")
    return max(1, round(base_fps * playback_speed))


def _build_vf_filters(
    fps: int,
    width: int,
    crop: tuple[int, int, int, int] | None,
) -> str:
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    if crop is not None:
        cx, cy, cw, ch = crop
        vf = f"crop={cw}:{ch}:{cx}:{cy},{vf}"
    return vf


def export_webp(
    input_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float,
    end_seconds: float,
    fps: int,
    width: int,
    playback_speed: float = 1.0,
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
    if crop is not None:
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0:
            raise GifExportError(
                "Crop dimensions must be positive with non-negative origin"
            )

    effective_fps = _effective_output_fps(fps, playback_speed)
    vf = _build_vf_filters(effective_fps, width, crop)
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
        "90",
        "-preset",
        "photo",
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
