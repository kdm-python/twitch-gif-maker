"""Video preview panel and playback controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from gifmaker.gui.marker_seek_slider import MarkerSeekSlider


class VideoPreviewPanel(QGroupBox):
    """Panel containing the video preview, seek bar, and selection controls."""

    def __init__(self, parent=None) -> None:
        super().__init__("Video Preview", parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._layout = QVBoxLayout(self)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setMinimumHeight(160)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("border: 1px solid palette(mid);")
        self.video_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.set_start_button = QPushButton("Set Start")
        self.set_end_button = QPushButton("Set End")

        self.seek_slider = MarkerSeekSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.set_total_frames(0)

        self.seek_time_label = QLabel("00:00:00 / 00:00:00")
        self.mute_button = QPushButton("Mute")

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.set_start_button)
        controls_layout.addWidget(self.set_end_button)
        controls_layout.addWidget(self.seek_slider, stretch=1)
        controls_layout.addWidget(self.seek_time_label)
        controls_layout.addWidget(self.mute_button)

        self.start_frame_label = QLabel("Start: --:--:--.---")
        self.start_nudge_back_button = QPushButton("−0.01")
        self.start_nudge_forward_button = QPushButton("+0.01")

        self.end_frame_label = QLabel("End: --:--:--.---")
        self.end_nudge_back_button = QPushButton("−0.01")
        self.end_nudge_forward_button = QPushButton("+0.01")

        marker_controls = QHBoxLayout()
        marker_controls.addWidget(self.start_frame_label)
        marker_controls.addWidget(self.start_nudge_back_button)
        marker_controls.addWidget(self.start_nudge_forward_button)
        marker_controls.addSpacing(12)
        marker_controls.addWidget(self.end_frame_label)
        marker_controls.addWidget(self.end_nudge_back_button)
        marker_controls.addWidget(self.end_nudge_forward_button)
        marker_controls.addStretch(1)

        self.clip_selection_label = QLabel()
        marker_controls.addSpacing(12)
        marker_controls.addWidget(self.clip_selection_label)

        self._layout.addWidget(self.video_widget)
        self._layout.addLayout(controls_layout)
        self._layout.addLayout(marker_controls)

    def bind_window(self, window) -> None:
        """Wire this panel to the main-window controller."""
        self.media_player.mediaStatusChanged.connect(window.on_media_status_changed)
        self.media_player.errorOccurred.connect(window.on_media_error)
        self.media_player.durationChanged.connect(window.on_duration_changed)
        self.media_player.positionChanged.connect(window.on_position_changed)
        self.media_player.playbackStateChanged.connect(window._update_play_button_state)

        self.play_button.clicked.connect(window.toggle_preview_playback)
        self.set_start_button.clicked.connect(window.set_clip_start)
        self.set_end_button.clicked.connect(window.set_clip_end)

        self.seek_slider.sliderPressed.connect(window.on_seek_slider_pressed)
        self.seek_slider.sliderMoved.connect(window.on_seek_slider_moved)
        self.seek_slider.sliderReleased.connect(window.on_seek_slider_released)
        self.seek_slider.selectionChanged.connect(window.on_scrub_selection_changed)

        self.start_nudge_back_button.clicked.connect(
            lambda: window.nudge_start_frame(-window._seconds_to_frame(0.01))
        )
        self.start_nudge_forward_button.clicked.connect(
            lambda: window.nudge_start_frame(window._seconds_to_frame(0.01))
        )
        self.end_nudge_back_button.clicked.connect(
            lambda: window.nudge_end_frame(-window._seconds_to_frame(0.01))
        )
        self.end_nudge_forward_button.clicked.connect(
            lambda: window.nudge_end_frame(window._seconds_to_frame(0.01))
        )

        self.mute_button.clicked.connect(window.toggle_mute)
