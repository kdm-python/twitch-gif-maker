"""Render and timing helpers used across preview/export workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderSettings:
    """Resolved render configuration for export and preview generation."""

    start_seconds: float
    end_seconds: float
    fps: int
    width: int
    crop: tuple[int, int, int, int] | None = None


def parse_time_input(value: str) -> float:
    """Parse seconds, MM:SS:CC, HH:MM:SS:CC, or legacy HH:MM:SS.xx."""
    if ":" not in value:
        seconds = float(value)
        if seconds < 0:
            raise ValueError("Time values must be non-negative")
        return seconds

    parts = value.split(":")
    if len(parts) == 2:
        minutes = int(parts[0])
        seconds = float(parts[1])

        if minutes < 0 or seconds < 0:
            raise ValueError("Time values must be non-negative")
        if seconds >= 60:
            raise ValueError("Seconds must be less than 60")

        return (minutes * 60) + seconds

    if len(parts) == 3:
        if "." in parts[2]:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])

            if hours < 0 or minutes < 0 or seconds < 0:
                raise ValueError("Time values must be non-negative")
            if minutes >= 60 or seconds >= 60:
                raise ValueError("Minutes and seconds must be less than 60")

            return (hours * 3600) + (minutes * 60) + seconds

        minutes = int(parts[0])
        seconds = int(parts[1])
        centiseconds = int(parts[2])

        if minutes < 0 or seconds < 0 or centiseconds < 0:
            raise ValueError("Time values must be non-negative")
        if seconds >= 60:
            raise ValueError("Seconds must be less than 60")
        if centiseconds >= 100:
            raise ValueError("Centiseconds must be less than 100")

        return (minutes * 60) + seconds + (centiseconds / 100)

    if len(parts) == 4:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        centiseconds = int(parts[3])

        if hours < 0 or minutes < 0 or seconds < 0 or centiseconds < 0:
            raise ValueError("Time values must be non-negative")
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Minutes and seconds must be less than 60")
        if centiseconds >= 100:
            raise ValueError("Centiseconds must be less than 100")

        return (hours * 3600) + (minutes * 60) + seconds + (centiseconds / 100)

    raise ValueError("Time must be seconds, MM:SS:CC, HH:MM:SS:CC, or HH:MM:SS.xx")


def format_ms(milliseconds: int) -> str:
    """Format milliseconds as MM:SS:CC or HH:MM:SS:CC."""
    total_centiseconds = round(max(milliseconds, 0) / 10)

    hours = total_centiseconds // 360_000
    remaining_after_hours = total_centiseconds % 360_000
    minutes = remaining_after_hours // 6_000
    remaining_after_minutes = remaining_after_hours % 6_000
    seconds = remaining_after_minutes // 100
    centiseconds = remaining_after_minutes % 100

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{centiseconds:02d}"
    return f"{minutes:02d}:{seconds:02d}:{centiseconds:02d}"


def format_timestamp_from_frame(frame_index: int, fps: float) -> str:
    """Format a frame index as HH:MM:SS.mmm."""
    total_ms = round((frame_index / fps) * 1000.0) if fps > 0 else 0
    total_seconds, milliseconds = divmod(max(total_ms, 0), 1000)
    hours, remaining = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def duration_to_frame_count(duration_ms: int, fps: float) -> int:
    """Convert a media duration to total frame count."""
    if duration_ms <= 0 or fps <= 0:
        return 0
    duration_seconds = duration_ms / 1000.0
    return max(1, round(duration_seconds * fps))


def ms_to_frame(milliseconds: int, fps: float, total_frames: int) -> int:
    """Convert milliseconds to nearest frame index."""
    if total_frames <= 0 or fps <= 0:
        return 0
    frame = round((milliseconds / 1000.0) * fps)
    return max(0, min(frame, total_frames - 1))


def frame_to_ms(frame_index: int, fps: float) -> int:
    """Convert frame index to milliseconds."""
    if fps <= 0:
        return 0
    return round((frame_index / fps) * 1000.0)
