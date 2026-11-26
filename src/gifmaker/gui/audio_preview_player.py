"""Playback for encoded MP3 previews; speed is already baked into the file."""
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QStyle


class AudioPreviewPlayer:
    def __init__(self, window):
        self.window = window
        self.preview_label = None
        self.audio = QAudioOutput(window)
        self.audio.setVolume(1.0)
        self.media = QMediaPlayer(window)
        self.media.setAudioOutput(self.audio)
        self.media.setLoops(QMediaPlayer.Loops.Infinite)
        self.media.errorOccurred.connect(self._error)

    def _error(self, _error, message):
        self.window.export_status_label.setText(f"Status: Audio playback failed: {message}")
        self.window.export_controls_panel.set_preview_playing(False)

    def bind(self, label):
        self.preview_label = label

    def load(self, path):
        self.media.setSource(QUrl.fromLocalFile(str(path)))
        if self.preview_label is not None:
            self.preview_label.clear()
            self.preview_label.setPixmap(self.preview_label.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaVolume).pixmap(48, 48))
        self.set_playback_speed(self.window.preview_controller._preview_speed())
        self.play()

    def play(self):
        self.window.media_player.pause()
        self.media.play()

    def pause(self):
        self.media.pause()

    def clear(self):
        self.media.stop()
        self.media.setSource(QUrl())
        if self.preview_label is not None:
            self.preview_label.clear()

    def position_ms(self):
        return self.media.position()

    def seek(self, position_ms):
        self.pause()
        self.media.setPosition(position_ms)

    def set_playback_speed(self, speed):
        settings = self.window._last_preview_settings
        baked = settings.playback_speed if settings is not None else 1.0
        self.media.setPlaybackRate(speed / baked)

    def update_scaled_size(self):
        pass
