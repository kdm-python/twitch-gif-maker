"""Timestamp-based playback of a prepared animation source."""
from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage

from gifmaker.sources.model import LoadedSource


class AnimationSourcePlayer(QObject):
    """Play one prepared cycle. The caller owns the source and its lifetime.

    Positions are integer milliseconds. Playback stops at the end of the cycle;
    play at the endpoint restarts at zero. Source preparation and rendering are
    deliberately separate from this player.
    """

    positionChanged = Signal(int)
    durationChanged = Signal(int)
    frameChanged = Signal(QImage)
    playingChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(self, parent: QObject | None = None, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self._clock = clock
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._source: LoadedSource | None = None
        self._position_ms = 0
        self._anchor_ms = 0
        self._anchor_time = 0.0
        self._rate = 1.0
        self._playing = False
        self._frame_index: int | None = None

    @property
    def duration_ms(self) -> int:
        if self._source is None:
            return 0
        frame = self._source.frames[-1]
        return frame.start_ms + frame.duration_ms

    @property
    def position_ms(self) -> int:
        if self._playing:
            return min(self.duration_ms, self._anchor_ms + int((self._clock() - self._anchor_time) * 1000 * self._rate))
        return self._position_ms

    @property
    def playing(self) -> bool:
        return self._playing

    def set_source(self, source: LoadedSource) -> None:
        """Adopt a live frame source without taking ownership of it."""
        if source.closed or not source.frames:
            raise ValueError("A live prepared animation source is required")
        image = QImage(str(source.frames[0].path))
        if image.isNull():
            raise ValueError("The first source frame cannot be read")
        self.stop()
        self._source = source
        self._position_ms = 0
        self._frame_index = 0
        self.durationChanged.emit(self.duration_ms)
        self.positionChanged.emit(0)
        self.frameChanged.emit(image)

    def clear(self) -> None:
        """Release the reference without closing the caller-owned source."""
        self.stop()
        self._source = None
        self._position_ms = 0
        self._frame_index = None
        self.durationChanged.emit(0)
        self.positionChanged.emit(0)

    def play(self) -> None:
        if self._source is None or self._playing:
            return
        if self._source.closed:
            self.errorOccurred.emit("Source is closed")
            return
        if self._position_ms >= self.duration_ms:
            self.seek(0)
            if self._position_ms != 0:
                return
        self._anchor_ms = self._position_ms
        self._anchor_time = self._clock()
        self._playing = True
        self.playingChanged.emit(True)
        self._schedule()

    def pause(self) -> None:
        if not self._playing:
            return
        self._update(self.position_ms)
        self._set_stopped()

    def stop(self) -> None:
        """Stop at the current position; use seek(0) to rewind."""
        self.pause()

    def seek(self, position_ms: int) -> None:
        if self._source is None:
            return
        position = max(0, min(int(position_ms), self.duration_ms))
        self._update(position)
        if self._playing:
            self._anchor_ms = self._position_ms
            self._anchor_time = self._clock()
            if position == self.duration_ms:
                self._set_stopped()
            else:
                self._schedule()

    def set_playback_rate(self, rate: float) -> None:
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Playback rate must be positive and finite")
        if self._playing:
            self._update(self.position_ms)
            self._anchor_ms = self._position_ms
            self._anchor_time = self._clock()
        self._rate = rate
        if self._playing:
            self._schedule()

    def _set_stopped(self) -> None:
        self._timer.stop()
        if self._playing:
            self._playing = False
            self.playingChanged.emit(False)

    def _update(self, position: int) -> None:
        source = self._source
        if source is None:
            return
        if source.closed:
            self._set_stopped()
            self.errorOccurred.emit("Source is closed")
            return
        frame = source.frame_at(position)
        index = frame.start_ms
        if index != self._frame_index:
            image = QImage(str(frame.path))
            if image.isNull():
                self._set_stopped()
                self.errorOccurred.emit("Source frame could not be read")
                return
            self._frame_index = index
            self.frameChanged.emit(image)
        if position != self._position_ms:
            self._position_ms = position
            self.positionChanged.emit(position)

    def _schedule(self) -> None:
        # Frequent position updates keep a future seek slider responsive; the
        # monotonic anchor avoids accumulating timer drift or dropped frames.
        self._timer.start(16)

    def _tick(self) -> None:
        if not self._playing:
            return
        self._update(self.position_ms)
        if self._playing and self._position_ms >= self.duration_ms:
            self._set_stopped()
        elif self._playing:
            self._schedule()
