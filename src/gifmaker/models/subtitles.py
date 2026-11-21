"""Editable, immutable subtitle data, independent of Qt and window state."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Caption:
    start_ms: float
    end_ms: float
    text: str = ""
    x: float = .5  # Horizontal centre, relative to the final output canvas.
    y: float = .9  # Bottom of the text, relative to the final output canvas.
    font_family: str = "Sans Serif"
    size: float = .065  # Relative to canvas height; independent of display scale.
    color: str = "#ffffff"
    bold: bool = False
    italic: bool = False

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.start_ms, self.end_ms, self.x, self.y, self.size)):
            raise ValueError("Caption coordinates must be finite")
        if not 0 <= self.start_ms < self.end_ms:
            raise ValueError("Caption must have a nonempty source-time interval")
        if not 0 <= self.x <= 1 or not 0 <= self.y <= 1 or not 0 < self.size <= 1:
            raise ValueError("Caption position and size must be relative to the canvas")

    def visible_at(self, source_ms: float) -> bool:
        return self.start_ms <= source_ms < self.end_ms


@dataclass(frozen=True)
class SubtitleDocument:
    captions: tuple[Caption, ...] = ()


@dataclass(frozen=True)
class SubtitleTiming:
    """Map the encoded output timeline to the recipe that produced it."""

    start_ms: float
    end_ms: float
    speed: float = 1.

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.start_ms, self.end_ms, self.speed)):
            raise ValueError("Subtitle timing must be finite")
        if not 0 <= self.start_ms < self.end_ms or self.speed <= 0:
            raise ValueError("Invalid subtitle timing")

    def source_time(self, output_ms: float) -> float:
        return min(self.end_ms, max(self.start_ms, self.start_ms + output_ms * self.speed))

    def output_time(self, source_ms: float) -> float:
        return (source_ms - self.start_ms) / self.speed
