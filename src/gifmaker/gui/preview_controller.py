"""Coordinate preview playback and the lifetime of preview artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from loguru import logger

from gifmaker.gui.animation_preview_player import AnimationPreviewPlayer


class PreviewPlayer(Protocol):
    """Playback operations required by the output preview."""

    def bind(self, preview_label) -> None: ...
    def load(self, preview_path: Path) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def clear(self) -> None: ...
    def set_playback_speed(self, speed: float) -> None: ...
    def update_scaled_size(self) -> None: ...


class PreviewController:
    """Keep playback separate from the rendered artifact's lifecycle."""

    def __init__(self, window, player: PreviewPlayer | None = None) -> None:
        self.window = window
        self.player = player if player is not None else AnimationPreviewPlayer(window)
        self._playback_speed = 1.0

    def bind(self, preview_label) -> None:
        self.player.bind(preview_label)

    def load(self, preview_path: Path) -> None:
        self.player.load(preview_path)

    def play(self) -> None:
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def set_playback_speed(self, speed: float) -> None:
        if speed > 0:
            self._playback_speed = speed
        self.player.set_playback_speed(speed)

    def update_scaled_size(self) -> None:
        self.player.update_scaled_size()

    def clear(self, *, remove_temp_file: bool) -> None:
        preview_file = self.window._preview_temp_file
        self.player.clear()
        self.window._preview_temp_file = None
        self.window._last_preview_settings = None
        self.window._last_preview_source = None
        self.window._last_preview_spec = None
        if remove_temp_file and preview_file is not None:
            self.remove_temp_file_if_exists(preview_file)

    @staticmethod
    def remove_temp_file_if_exists(file_path: Path) -> None:
        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove preview file '{}': {}", file_path, exc)

    # Compatibility adapters used by the current animation preview callbacks.
    def on_cached_frame_timeout(self) -> None:
        self.player.on_cached_frame_timeout()

    def on_preview_frame_changed(self, frame: int) -> None:
        self.player.on_preview_frame_changed(frame)

    def _preview_speed(self) -> float:
        return self._playback_speed

    def _frame_delay(self, index: int) -> int:
        return self.player._frame_delay(index)
