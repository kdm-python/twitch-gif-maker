"""Helpers for GIF preview generation, caching, and playback."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QMovie, QPixmap


class PreviewController:
    """Own the preview GIF lifecycle and its timer-based playback."""

    def __init__(self, window) -> None:
        self.window = window
        self.preview_label = None

    def bind(self, preview_label) -> None:
        """Attach the label that renders the generated preview."""
        self.preview_label = preview_label

    def play(self) -> None:
        """Play the generated GIF preview."""
        if self.window._preview_frame_cache:
            if self.window._preview_frame_timer is None:
                self.window._preview_frame_timer = QTimer(self.window)
                self.window._preview_frame_timer.timeout.connect(
                    self.window._on_cached_frame_timeout
                )
                idx = self.window._preview_frame_index or 0
                dur = (
                    self.window._preview_frame_durations[idx]
                    if self.window._preview_frame_durations
                    else 100
                )
                self.window._preview_frame_timer.start(dur)
                return

            if not self.window._preview_frame_timer.isActive():
                idx = self.window._preview_frame_index or 0
                dur = (
                    self.window._preview_frame_durations[idx]
                    if self.window._preview_frame_durations
                    else 100
                )
                self.window._preview_frame_timer.start(dur)
            return

        movie = self.window._preview_movie
        if movie is None:
            return

        if movie.state() == QMovie.MovieState.NotRunning:
            movie.start()
            return

        movie.setPaused(False)

    def pause(self) -> None:
        """Pause the generated GIF preview."""
        if (
            self.window._preview_frame_cache
            and self.window._preview_frame_timer is not None
        ):
            try:
                self.window._preview_frame_timer.stop()
            except Exception:
                pass
            return

        movie = self.window._preview_movie
        if movie is None:
            return

        movie.setPaused(True)

    def clear(self, *, remove_temp_file: bool) -> None:
        """Clear preview UI state and optionally remove the temp GIF file."""
        preview_file = self.window._preview_temp_file
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
            self.preview_label.setText("Generate preview to display GIF")

        self.window._preview_temp_file = None
        self.window._last_preview_settings = None

        if remove_temp_file and preview_file is not None:
            self.remove_temp_file_if_exists(preview_file)

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

    def set_movie(self, gif_path: Path) -> None:
        """Display a generated GIF in the preview panel."""
        movie = QMovie(str(gif_path))
        if not movie.isValid():
            raise RuntimeError("Generated preview GIF could not be loaded")

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
        try:
            total = movie.frameCount()
        except Exception:
            total = 0

        if total and total > 0:
            for i in range(total):
                try:
                    movie.jumpToFrame(i)
                except Exception:
                    break
                pix = movie.currentPixmap()
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
                try:
                    dur = movie.nextFrameDelay()
                except Exception:
                    dur = 100
                cached_durations.append(max(1, int(dur)))

        if len(cached_frames) > 1:
            self.stop_cached_preview()
            self.window._preview_frame_cache = cached_frames
            self.window._preview_frame_durations = cached_durations
            self.window._preview_frame_index = 0
            if self.preview_label is not None:
                self.preview_label.setPixmap(self.window._preview_frame_cache[0])
            self.window._preview_frame_timer = QTimer(self.window)
            self.window._preview_frame_timer.timeout.connect(
                self.window._on_cached_frame_timeout
            )
            self.window._preview_frame_timer.start(
                self.window._preview_frame_durations[0]
            )
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

    def remove_temp_file_if_exists(self, file_path: Path) -> None:
        """Best-effort removal for temporary preview artifacts."""
        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove preview file '{}': {}", file_path, exc)

    def on_cached_frame_timeout(self) -> None:
        """Advance cached frame playback and schedule the next timeout."""
        if (
            not self.window._preview_frame_cache
            or not self.window._preview_frame_durations
        ):
            return

        self.window._preview_frame_index = (self.window._preview_frame_index + 1) % len(
            self.window._preview_frame_cache
        )
        pix = self.window._preview_frame_cache[self.window._preview_frame_index]
        if self.preview_label is not None:
            self.preview_label.setPixmap(pix)
        if self.window._preview_frame_timer is not None:
            next_dur = self.window._preview_frame_durations[
                self.window._preview_frame_index
            ]
            self.window._preview_frame_timer.start(next_dur)

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
