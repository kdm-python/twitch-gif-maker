"""
Module for ffprobe video information.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gifmaker.models.video_info import VideoInfo


class VideoProbeError(Exception):
    """Raised when ffprobe fails or returns unexpected data."""


def probe_video(video_path: str | Path) -> VideoInfo:
    """Run ffprobe on a video file and return parsed metadata."""
    path = Path(video_path)

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise VideoProbeError(f"Failed to execute ffprobe: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown ffprobe error"
        raise VideoProbeError(f"ffprobe failed: {stderr}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoProbeError(f"Invalid ffprobe JSON output: {exc}") from exc

    try:
        streams = payload["streams"]
        video_stream = next(s for s in streams if s.get("codec_type") == "video")
        codec = str(video_stream["codec_name"])
        width = int(video_stream["width"])
        height = int(video_stream["height"])
        fps_raw = str(
            video_stream.get("avg_frame_rate")
            or video_stream.get("r_frame_rate")
            or "0/0"
        )
        fps = _parse_fps(fps_raw)

        duration = float(payload["format"]["duration"])
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise VideoProbeError(f"Unexpected ffprobe data format: {exc}") from exc

    if duration < 0 or width <= 0 or height <= 0 or fps <= 0 or not codec:
        raise VideoProbeError("ffprobe returned invalid video metadata values")

    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        codec=codec,
    )


def _parse_fps(rate: str) -> float:
    """Parse ffprobe frame rate values like '30000/1001' into float."""
    if "/" in rate:
        num_s, den_s = rate.split("/", 1)
        num = float(num_s)
        den = float(den_s)
        if den == 0:
            raise ValueError("frame rate denominator is zero")
        return num / den
    return float(rate)
