from dataclasses import dataclass


@dataclass(slots=True)
class VideoInfo:
    """Metadata for a single video stream."""

    duration: float  # seconds
    width: int
    height: int
    fps: float
    codec: str
