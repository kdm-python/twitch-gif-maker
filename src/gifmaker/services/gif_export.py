"""FFmpeg-based GIF export service."""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger


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
    if width <= 0:
        raise GifExportError("Width must be greater than 0")
    if crop is not None:
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0:
            raise GifExportError(
                "Crop dimensions must be positive with non-negative origin"
            )

    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    if crop is not None:
        cx, cy, cw, ch = crop
        vf = f"crop={cw}:{ch}:{cx}:{cy},{vf}"

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_seconds),
        "-to",
        str(end_seconds),
        "-i",
        str(source),
        "-vf",
        vf,
        str(destination),
    ]

    logger.info("Running FFmpeg GIF export: {}", " ".join(ffmpeg_cmd))

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
