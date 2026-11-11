"""Helpers for output preview generation, caching, and playback."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QImageReader, QMovie, QPixmap


class AnimationPreviewPlayer:
    """Own the preview animation lifecycle and its timer-based playback."""

    def __init__(self, window) -> None:
        self.window = window
        self.preview_label = None
        self._playback_speed = 1.0
        self._deadline = 0.0
        self._remaining_ms = None

    def _start_frame_timer(self, delay_ms: float) -> None:
        self._deadline = time.monotonic() + delay_ms / 1000
        self.window._preview_frame_timer.start(max(1, round(delay_ms)))

    def bind(self, preview_label) -> None:
        """Attach the label that renders the generated preview."""
        self.preview_label = preview_label

    def _rendered_speed(self) -> float:
        """Return the speed baked into the currently cached preview."""
        settings = self.window._last_preview_settings
        return settings.playback_speed if settings is not None else 1.0

    def _preview_speed(self) -> float:
        return self._playback_speed

    def _frame_delay(self, index: int) -> int:
        """Return a cached frame's delay adjusted to the selected output speed."""
        durations = self.window._preview_frame_durations
        if not durations:
            return 100
        original_delay = durations[index]
        return max(1, round(original_delay * self._rendered_speed() / self._preview_speed()))

    def set_playback_speed(self, speed: float) -> None:
        """Immediately retime the generated-animation preview without rendering."""
        if speed <= 0:
            return
        self._playback_speed = speed
        if self.window._preview_frame_cache and self.window._preview_frame_timer is not None:
            if self.window._preview_frame_timer.isActive():
                self._start_frame_timer(self._frame_delay(self.window._preview_frame_index))
            else:
                self._remaining_ms = None
            return
        movie = self.window._preview_movie
        if movie is not None:
            movie.setSpeed(round(100 * speed / self._rendered_speed()))

    def play(self) -> None:
        """Play the generated output preview."""
        if self.window._preview_frame_cache:
            if self.window._preview_frame_timer is None:
                self.window._preview_frame_timer = QTimer(self.window)
                self.window._preview_frame_timer.setSingleShot(True)
                self.window._preview_frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
                self.window._preview_frame_timer.timeout.connect(
                    self.window._on_cached_frame_timeout
                )
                idx = self.window._preview_frame_index or 0
                dur = self._frame_delay(idx)
                self._start_frame_timer(dur)
                return

            if not self.window._preview_frame_timer.isActive():
                idx = self.window._preview_frame_index or 0
                dur = self._frame_delay(idx)
                self._start_frame_timer(self._remaining_ms if self._remaining_ms is not None else dur)
                self._remaining_ms = None
            return

        movie = self.window._preview_movie
        if movie is None:
            return

        if movie.state() == QMovie.MovieState.NotRunning:
            movie.start()
            return

        movie.setPaused(False)

    def pause(self) -> None:
        """Pause the generated output preview."""
        if (
            self.window._preview_frame_cache
            and self.window._preview_frame_timer is not None
        ):
            try:
                if self.window._preview_frame_timer.isActive():
                    self._remaining_ms = max(1, (self._deadline - time.monotonic()) * 1000)
                self.window._preview_frame_timer.stop()
            except Exception:
                pass
            return

        movie = self.window._preview_movie
        if movie is None:
            return

        movie.setPaused(True)

    def clear(self) -> None:
        """Stop animation playback and clear its display."""
        try:
            self.stop_cached_preview()
        except Exception:
            pass

        movie = self.window._preview_movie
        if movie is not None:
            try:
                movie.frameChanged.disconnect(self.window._on_preview_frame_changed)
            except Exception:
                pass
            movie.stop()
            self.window._preview_movie = None

        if self.preview_label is not None:
            self.preview_label.clear()
            self.preview_label.setText("Generate preview to display animation")

    def stop_cached_preview(self) -> None:
        """Stop and clear any QTimer-based cached preview playback."""
        if self.window._preview_frame_timer is not None:
            try:
                self.window._preview_frame_timer.stop()
                self.window._preview_frame_timer.timeout.disconnect(
                    self.window._on_cached_frame_timeout
                )
            except Exception:
                pass
            self.window._preview_frame_timer = None

        self.window._preview_frame_cache = None
        self.window._preview_frame_durations = None
        self.window._preview_frame_index = 0
        self._remaining_ms = None
        self._deadline = 0.0

    def load(self, preview_path: Path) -> None:
        """Display a generated GIF or animated WebP in the preview panel."""
        movie = QMovie(str(preview_path))
        if not movie.isValid():
            raise RuntimeError("Generated preview could not be loaded")

        if self.window._preview_movie is not None:
            self.window._preview_movie.stop()

        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        try:
            movie.jumpToFrame(0)
        except Exception:
            pass

        orig_rect = movie.frameRect()
        if orig_rect.isValid() and orig_rect.width() > 0 and orig_rect.height() > 0:
            label_size = (
                self.preview_label.size() if self.preview_label is not None else None
            )
            if (
                label_size is not None
                and label_size.width() > 0
                and label_size.height() > 0
            ):
                scale_w = label_size.width() / orig_rect.width()
                scale_h = label_size.height() / orig_rect.height()
                scale = min(scale_w, scale_h)
                new_w = max(1, int(orig_rect.width() * scale))
                new_h = max(1, int(orig_rect.height() * scale))
                movie.setScaledSize(QSize(new_w, new_h))

        cached_frames: list[QPixmap] = []
        cached_durations: list[int] = []
        # QMovie.nextFrameDelay() subtracts decoding time. QImageReader returns
        # the encoded frame delay, which matters when caching animated WebP.
        reader = QImageReader(str(preview_path))
        try:
            total = movie.frameCount()
        except Exception:
            total = 0

        if total and total > 0:
            for _ in range(total):
                frame = reader.read()
                if frame.isNull():
                    break
                pix = QPixmap.fromImage(frame)
                if pix is None or pix.isNull():
                    continue

                scaled_size = movie.scaledSize()
                if (
                    scaled_size.isValid()
                    and scaled_size.width() > 0
                    and scaled_size.height() > 0
                ):
                    pix = pix.scaled(
                        scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    if self.preview_label is not None:
                        label_size = self.preview_label.size()
                        if label_size.width() > 0 and label_size.height() > 0:
                            pix = pix.scaled(
                                label_size,
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation,
                            )

                cached_frames.append(pix)
                dur = reader.nextImageDelay()
                cached_durations.append(max(1, int(dur)))

        if len(cached_frames) > 1:
            self.stop_cached_preview()
            self.window._preview_frame_cache = cached_frames
            self.window._preview_frame_durations = cached_durations
            self.window._preview_frame_index = 0
            if self.preview_label is not None:
                self.preview_label.setPixmap(self.window._preview_frame_cache[0])
            self.window._preview_frame_timer = QTimer(self.window)
            self.window._preview_frame_timer.setSingleShot(True)
            self.window._preview_frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.window._preview_frame_timer.timeout.connect(
                self.window._on_cached_frame_timeout
            )
            self._start_frame_timer(self._frame_delay(0))
            try:
                movie.stop()
            except Exception:
                pass
            self.window._preview_movie = None
            return

        try:
            if self.window._preview_movie is not None:
                self.window._preview_movie.frameChanged.disconnect(
                    self.window._on_preview_frame_changed
                )
        except Exception:
            pass

        self.stop_cached_preview()

        movie.frameChanged.connect(self.window._on_preview_frame_changed)
        if self.preview_label is not None:
            self.preview_label.setMovie(movie)
        movie.start()
        self.window._preview_movie = movie

    def update_scaled_size(self) -> None:
        """Scale the current preview movie to fit the preview label."""
        movie = self.window._preview_movie
        if movie is None or self.preview_label is None:
            return

        orig_rect = movie.frameRect()
        orig_size = orig_rect.size()
        if orig_size.width() <= 0 or orig_size.height() <= 0:
            return

        label_size = self.preview_label.size()
        if label_size.width() <= 0 or label_size.height() <= 0:
            return

        scale_w = label_size.width() / orig_size.width()
        scale_h = label_size.height() / orig_size.height()
        scale = min(scale_w, scale_h)
        new_w = max(1, int(orig_size.width() * scale))
        new_h = max(1, int(orig_size.height() * scale))
        movie.setScaledSize(QSize(new_w, new_h))

    def on_cached_frame_timeout(self) -> None:
        """Advance cached frame playback and schedule the next timeout."""
        if (
            not self.window._preview_frame_cache
            or not self.window._preview_frame_durations
        ):
            return

        now = time.monotonic()
        if not self._deadline:
            self._deadline = now
        # Skip frames when the event loop is late, preserving elapsed time.
        cycle = sum(self._frame_delay(i) for i in range(len(self.window._preview_frame_cache))) / 1000
        if cycle and now - self._deadline >= cycle:
            self._deadline += int((now - self._deadline) / cycle) * cycle
        while True:
            self.window._preview_frame_index = (self.window._preview_frame_index + 1) % len(
                self.window._preview_frame_cache
            )
            self._deadline += self._frame_delay(self.window._preview_frame_index) / 1000
            if self._deadline > now:
                break
        pix = self.window._preview_frame_cache[self.window._preview_frame_index]
        if self.preview_label is not None:
            self.preview_label.setPixmap(pix)
        if self.window._preview_frame_timer is not None:
            self.window._preview_frame_timer.start(max(1, round((self._deadline - now) * 1000)))

    def on_preview_frame_changed(self, frame: int) -> None:
        """Loop a QMovie smoothly when it reaches the end frame."""
        movie = self.window._preview_movie
        if movie is None:
            return

        try:
            total = movie.frameCount()
        except Exception:
            total = 0

        if total <= 0:
            return

        if frame >= total - 1:

            def _restart(m=movie):
                try:
                    m.jumpToFrame(0)
                    m.start()
                except Exception:
                    pass

            QTimer.singleShot(0, _restart)
