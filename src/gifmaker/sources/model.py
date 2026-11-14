"""Source metadata and ownership of prepared animation frames."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self


@dataclass(frozen=True, slots=True)
class SourceFrame:
    path: Path
    start_ms: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class SourceInfo:
    duration_seconds: float
    width: int
    height: int
    codec: str
    average_fps: float


class LoadedSource:
    """Prepared source and its temporary files, valid until closed.

    MP4 has a direct media path. For WebP, frames are ordered composited PNGs;
    their timestamps define playback and future rendering, not a constant FPS.
    """

    def __init__(self, original_path: Path, info: SourceInfo, *,
                 media_path: Path | None = None, frames: tuple[SourceFrame, ...] = (),
                 temporary_directory: TemporaryDirectory | None = None) -> None:
        self.original_path = original_path
        self.info = info
        self.media_path = media_path
        self.frames = frames
        self._starts = tuple(frame.start_ms for frame in frames)
        self._temporary_directory = temporary_directory
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def frame_at(self, timestamp_ms: int) -> SourceFrame:
        """Find the active frame; at the duration endpoint display the last."""
        if self._closed:
            raise ValueError("Source is closed")
        if not self.frames:
            raise ValueError("Source has no prepared animation frames")
        if timestamp_ms < 0 or timestamp_ms > self.frames[-1].start_ms + self.frames[-1].duration_ms:
            raise ValueError("Timestamp is outside the source")
        return self.frames[min(bisect_right(self._starts, timestamp_ms) - 1, len(self.frames) - 1)]

    def close(self) -> None:
        """Release temporary files; safe to call more than once."""
        if not self._closed:
            self._closed = True
            if self._temporary_directory is not None:
                self._temporary_directory.cleanup()
                self._temporary_directory = None

    def __enter__(self) -> Self:
        if self._closed:
            raise ValueError("Source is closed")
        return self

    def __exit__(self, *_args) -> None:
        self.close()
