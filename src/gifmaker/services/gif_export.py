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
        # The original WebP export used 90. Dropping the default to 75 made
        # block artifacts visible in otherwise smooth video backgrounds.
        "webp_quality": 90,
        "webp_preset": "photo",
    },
    "high": {
        "label": "High quality",
        "gif_colors": 256,
        "gif_dither": "sierra2_4a",
        "webp_quality": 100,
        "webp_preset": "photo",
    },
}

SHARPNESS_PRESETS: dict[str, str] = {
    "off": "",
    # Apply a restrained luma-only sharpening pass after scaling.  This avoids
    # adding coloured halos, which GIF's limited palette would amplify.
    "mild": "unsharp=5:5:0.45",
    "strong": "unsharp=5:5:0.8",
}


def _ffmpeg_exe() -> str:
    # GIFMAKER_FFMPEG lets a dev point at a capable build (e.g. ffmpeg-full)
    return os.environ.get("GIFMAKER_FFMPEG", "ffmpeg")


class GifExportError(Exception):
    """Raised when GIF export validation or FFmpeg execution fails."""


def _validate_render_request(
    input_path: str | Path,
    output_path: str | Path,
    *,
    extension: str,
    start_seconds: float,
    end_seconds: float,
    fps: int,
    width: int,
    height: int | None,
    playback_speed: float,
    quality_preset: str,
    sharpness_preset: str,
    crop: tuple[int, int, int, int] | None,
) -> tuple[Path, Path]:
    """Validate the shared render inputs for synchronous and async exports."""
    source = Path(input_path)
    destination = Path(output_path)
    if not source.is_file():
        raise GifExportError(f"Input video does not exist: {source}")
    if destination.suffix.lower() != extension:
        raise GifExportError(f"Output file must use a {extension} extension")
    if not destination.parent.is_dir():
        raise GifExportError(f"Output directory does not exist: {destination.parent}")
    if start_seconds < 0:
        raise GifExportError("Start time must be greater than or equal to 0")
    if end_seconds <= start_seconds:
        raise GifExportError("End time must be greater than start time")
    if fps <= 0 or width <= 0 or (height is not None and height <= 0):
        raise GifExportError("Render dimensions and FPS must be greater than 0")
    if playback_speed <= 0:
        raise GifExportError("Playback speed must be greater than 0")
    if quality_preset not in QUALITY_PRESETS:
        raise GifExportError(f"Unknown quality preset: {quality_preset}")
    if sharpness_preset not in SHARPNESS_PRESETS:
        raise GifExportError(f"Unknown sharpness preset: {sharpness_preset}")
    if crop is not None and (crop[0] < 0 or crop[1] < 0 or crop[2] <= 0 or crop[3] <= 0):
        raise GifExportError("Crop dimensions must be positive with non-negative origin")
    return source, destination


def build_gif_command(
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
    sharpness_preset: str = "off",
    crop: tuple[int, int, int, int] | None = None,
) -> list[str]:
    """Build and validate the FFmpeg command used for a GIF render."""
    source, destination = _validate_render_request(
        input_path, output_path, extension=".gif", start_seconds=start_seconds,
        end_seconds=end_seconds, fps=fps, width=width, height=height,
        playback_speed=playback_speed, quality_preset=quality_preset,
        sharpness_preset=sharpness_preset, crop=crop,
    )

    target_height = height if height is not None else -1
    filters = _build_gif_filter_complex(
        fps, width, target_height, crop, playback_speed, quality_preset, sharpness_preset
    )
    return [
        _ffmpeg_exe(), "-y", "-ss", str(start_seconds), "-to", str(end_seconds),
        "-i", str(source), "-filter_complex", filters, "-loop", "0", str(destination),
    ]


def build_webp_command(
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
    sharpness_preset: str = "off",
    crop: tuple[int, int, int, int] | None = None,
) -> list[str]:
    """Build and validate the FFmpeg command used for an animated WebP render."""
    source, destination = _validate_render_request(
        input_path, output_path, extension=".webp", start_seconds=start_seconds,
        end_seconds=end_seconds, fps=fps, width=width, height=height,
        playback_speed=playback_speed, quality_preset=quality_preset,
        sharpness_preset=sharpness_preset, crop=crop,
    )

    target_height = height if height is not None else -1
    vf = _build_vf_filters(
        fps, width, target_height, crop, playback_speed, sharpness_preset
    )
    preset = QUALITY_PRESETS[quality_preset]
    return [
        _ffmpeg_exe(), "-y", "-ss", str(start_seconds), "-to", str(end_seconds),
        "-i", str(source), "-vf", vf, "-c:v", "libwebp_anim", "-quality",
        str(preset["webp_quality"]), "-preset", str(preset["webp_preset"]),
        "-loop", "0", "-an", str(destination),
    ]


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
    sharpness_preset: str = "off",
    crop: tuple[int, int, int, int] | None = None,
) -> None:
    """Export a GIF using the same command as the asynchronous render path."""
    command = build_gif_command(
        input_path, output_path, start_seconds=start_seconds,
        end_seconds=end_seconds, fps=fps, width=width, height=height,
        playback_speed=playback_speed, quality_preset=quality_preset,
        sharpness_preset=sharpness_preset, crop=crop,
    )
    _run_export(command)


def _build_vf_filters(
    fps: int,
    width: int,
    height: int,
    crop: tuple[int, int, int, int] | None,
    playback_speed: float = 1.0,
    sharpness_preset: str = "off",
) -> str:
    timing = "" if playback_speed == 1.0 else f"setpts=PTS/{playback_speed:g},"
    vf = f"{timing}fps={fps},scale={width}:{height}:flags=lanczos"
    sharpness_filter = SHARPNESS_PRESETS[sharpness_preset]
    if sharpness_filter:
        vf = f"{vf},{sharpness_filter}"
    if crop is not None:
        cx, cy, cw, ch = crop
        # MP4 is commonly 4:2:0; without exact=1 FFmpeg rounds odd crop
        # coordinates and dimensions to chroma-subsampling boundaries.
        vf = f"crop={cw}:{ch}:{cx}:{cy}:exact=1,{vf}"
    return vf


def _build_gif_filter_complex(
    fps: int,
    width: int,
    height: int,
    crop: tuple[int, int, int, int] | None,
    playback_speed: float,
    quality_preset: str,
    sharpness_preset: str,
) -> str:
    """Build a palette-generation graph for high-quality animated GIF output."""
    preset = QUALITY_PRESETS[quality_preset]
    video_filters = _build_vf_filters(
        fps, width, height, crop, playback_speed, sharpness_preset
    )
    # A clip-wide palette can give moving colours priority over detailed still
    # areas, especially after cropping. Build a fresh opaque palette for each
    # frame so each frame gets the full colour budget. The source and palette
    # must be in the same RGB colour space before they split.
    return (
        f"[0:v]{video_filters},format=rgb24,split[gif][palette_source];"
        f"[palette_source]palettegen=max_colors={preset['gif_colors']}:"
        "stats_mode=single:reserve_transparent=0[palette];"
        f"[gif][palette]paletteuse=dither={preset['gif_dither']}:new=1"
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
    sharpness_preset: str = "off",
    crop: tuple[int, int, int, int] | None = None,
) -> None:
    """Export a WebP using the same command as the asynchronous render path."""
    command = build_webp_command(
        input_path, output_path, start_seconds=start_seconds,
        end_seconds=end_seconds, fps=fps, width=width, height=height,
        playback_speed=playback_speed, quality_preset=quality_preset,
        sharpness_preset=sharpness_preset, crop=crop,
    )
    _run_export(command)


def _run_export(command: list[str]) -> None:
    logger.info("Running FFmpeg export: {}", " ".join(command))
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise GifExportError(f"Failed to execute ffmpeg: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown ffmpeg error"
        raise GifExportError(f"ffmpeg export failed: {stderr}")
    logger.info("Export completed: {}", command[-1])
