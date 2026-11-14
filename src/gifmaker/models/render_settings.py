"""Render and timing helpers used across preview/export workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputControlValues:
    """Snapshot of editable visual controls, independent of Qt widgets."""

    playback_speed: float
    fps: int
    width: int
    height: int
    quality_preset: str
    sharpness_preset: str


def resolve_visual_settings(
    start_seconds: float | None,
    end_seconds: float | None,
    controls: OutputControlValues,
    crop: tuple[int, int, int, int] | None,
    *,
    uses_quality: bool,
) -> RenderSettings:
    """Resolve an animation recipe without depending on GUI state."""
    if start_seconds is None or end_seconds is None:
        raise ValueError("Select a clip range on the timeline before export")
    if end_seconds <= start_seconds:
        raise ValueError("End time must be greater than start time")
    return RenderSettings(
        start_seconds=start_seconds, end_seconds=end_seconds,
        fps=controls.fps, width=controls.width, height=controls.height,
        playback_speed=controls.playback_speed,
        quality_preset=controls.quality_preset if uses_quality else "balanced",
        sharpness_preset=controls.sharpness_preset, crop=crop,
        format_settings=(WebPSettings(controls.quality_preset) if uses_quality else GIFSettings()),
    )


@dataclass(frozen=True)
class SharedSettings:
    """Selection and timing shared by output formats."""

    start_seconds: float
    end_seconds: float
    playback_speed: float = 1.0


@dataclass(frozen=True)
class VisualSettings:
    """Settings for formats that render video frames."""

    fps: int = 24
    width: int = 640
    height: int = 360
    sharpness_preset: str = "mild"
    crop: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class WebPSettings:
    """WebP-specific encoding options."""

    quality_preset: str = "balanced"


@dataclass(frozen=True)
class GIFSettings:
    """GIF has a fixed palette configuration in the UI."""

    @property
    def quality_preset(self) -> str:
        return "balanced"


@dataclass(frozen=True, init=False)
class RenderSettings:
    """Immutable animation recipe composed from shared and visual settings.

    The existing flat constructor and properties remain available to callers.
    """

    shared: SharedSettings
    visual: VisualSettings
    format_settings: WebPSettings | GIFSettings

    def __init__(self, start_seconds: float, end_seconds: float, fps: int = 24,
                 width: int = 640, height: int = 360, playback_speed: float = 1.0,
                 quality_preset: str = "balanced", sharpness_preset: str = "mild",
                 crop: tuple[int, int, int, int] | None = None, *,
                 format_settings: WebPSettings | GIFSettings | None = None) -> None:
        object.__setattr__(self, "shared", SharedSettings(start_seconds, end_seconds, playback_speed))
        object.__setattr__(self, "visual", VisualSettings(fps, width, height, sharpness_preset, crop))
        object.__setattr__(self, "format_settings", format_settings if format_settings is not None else WebPSettings(quality_preset))

    @property
    def start_seconds(self) -> float:
        return self.shared.start_seconds

    @property
    def end_seconds(self) -> float:
        return self.shared.end_seconds

    @property
    def playback_speed(self) -> float:
        return self.shared.playback_speed

    @property
    def fps(self) -> int:
        return self.visual.fps

    @property
    def width(self) -> int:
        return self.visual.width

    @property
    def height(self) -> int:
        return self.visual.height

    @property
    def sharpness_preset(self) -> str:
        return self.visual.sharpness_preset

    @property
    def crop(self) -> tuple[int, int, int, int] | None:
        return self.visual.crop

    @property
    def quality_preset(self) -> str:
        return self.format_settings.quality_preset

    @property
    def effective_fps(self) -> int:
        if self.playback_speed <= 0:
            raise ValueError("Playback speed must be greater than 0")
        return self.fps


@dataclass(frozen=True)
class RenderSpec:
    """The complete, immutable recipe for one render or preview artifact.

    Keeping source, format, and render settings together prevents preview and
    export code from comparing only a subset of the user's current choices.
    """

    source_path: str
    output_format: str
    settings: RenderSettings


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
