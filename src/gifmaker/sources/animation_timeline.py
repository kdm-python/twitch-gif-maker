"""Frame-boundary timeline for variable-delay animation sources."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise

from gifmaker.sources.model import LoadedSource


@dataclass(frozen=True, slots=True)
class AnimationTimeline:
    """Frame starts followed by the exclusive end of a single cycle."""

    boundaries_ms: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.boundaries_ms) < 2 or self.boundaries_ms[0] != 0:
            raise ValueError("Timeline must start at zero and contain a frame")
        if any(a >= b for a, b in pairwise(self.boundaries_ms)):
            raise ValueError("Timeline boundaries must increase")

    @classmethod
    def from_source(cls, source: LoadedSource) -> AnimationTimeline:
        if source.closed or not source.frames:
            raise ValueError("A live animation source is required")
        frames = source.frames
        if any(frame.duration_ms <= 0 or frame.start_ms + frame.duration_ms != following.start_ms
               for frame, following in pairwise(frames)) or frames[-1].duration_ms <= 0:
            raise ValueError("Animation frames must have contiguous positive durations")
        return cls(tuple(frame.start_ms for frame in frames) +
                   (frames[-1].start_ms + frames[-1].duration_ms,))

    @property
    def frame_count(self) -> int:
        return len(self.boundaries_ms) - 1

    @property
    def duration_ms(self) -> int:
        return self.boundaries_ms[-1]

    def frame_index_at(self, position_ms: int) -> int:
        position = max(0, min(position_ms, self.duration_ms))
        return min(self.frame_count - 1, bisect_right(self.boundaries_ms, position) - 1)

    def step(self, position_ms: int, delta: int) -> int:
        index = max(0, min(self.frame_count - 1, self.frame_index_at(position_ms) + delta))
        return self.boundaries_ms[index]

    def selection_ms(self, start: int, end: int) -> tuple[int, int]:
        """Convert marker boundary indices to a nonempty half-open interval."""
        if not 0 <= start < end <= self.frame_count:
            raise ValueError("Invalid animation selection boundaries")
        return self.boundaries_ms[start], self.boundaries_ms[end]
