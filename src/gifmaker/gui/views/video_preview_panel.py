"""Video preview panel and playback controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from gifmaker.gui.views.marker_seek_slider import MarkerSeekSlider


class VideoPreviewPanel(QGroupBox):
    """Panel containing the video preview and its playback controls.

    Selection controls are exposed as ``selection_group`` but are placed by the
    main window beneath the shared preview area.  Keeping them out of this
    panel lets the video canvas use the height it needs.
    """

    def __init__(self, parent=None) -> None:
        super().__init__("Video Preview", parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setMinimumHeight(140)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("border: 1px solid palette(mid);")
        self.video_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        controls_layout = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")

        self.playback_speed_combo = QComboBox()
        self.playback_speed_combo.addItem("0.25×", 0.25)
        self.playback_speed_combo.addItem("0.5×", 0.5)
        self.playback_speed_combo.addItem("1×", 1.0)
        self.playback_speed_combo.addItem("1.5×", 1.5)
        self.playback_speed_combo.addItem("2×", 2.0)
        self.playback_speed_combo.setCurrentIndex(2)
        self.playback_speed_combo.setFixedWidth(88)

        self.seek_slider = MarkerSeekSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.set_total_frames(0)

        self.seek_time_label = QLabel("00:00:00 / 00:00:00")
        self.mute_button = QPushButton("Mute")

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(QLabel("Playback Speed"))
        controls_layout.addWidget(self.playback_speed_combo)
        controls_layout.addWidget(self.seek_slider, stretch=1)
        controls_layout.addWidget(self.seek_time_label)
        controls_layout.addWidget(self.mute_button)

        self.start_label = QLabel("Start")
        self.start_frame_label = QLabel("--:--:--.---")
        self.start_nudge_back_button = QPushButton("−0.01")
        self.start_nudge_forward_button = QPushButton("+.01")
        self.set_start_button = QPushButton("Set Start")

        self.end_label = QLabel("End")
        self.end_frame_label = QLabel("--:--:--.---")
        self.end_nudge_back_button = QPushButton("−0.01")
        self.end_nudge_forward_button = QPushButton("+.01")
        self.set_end_button = QPushButton("Set End")

        self.selection_group = QGroupBox("Selection")
        self.selection_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.selection_group.setMaximumHeight(64)
        selection_layout = QHBoxLayout(self.selection_group)
        selection_layout.setContentsMargins(8, 4, 8, 4)
        selection_layout.setSpacing(6)

        self.clip_selection_label = QLabel("Selection: Not selected")
        self.clip_selection_label.setStyleSheet("font-size: 10px;")

        selection_layout.addWidget(self.start_label)
        selection_layout.addWidget(self.start_frame_label)
        selection_layout.addWidget(self.start_nudge_back_button)
        selection_layout.addWidget(self.start_nudge_forward_button)
        selection_layout.addWidget(self.set_start_button)
        selection_layout.addSpacing(10)
        selection_layout.addWidget(self.end_label)
        selection_layout.addWidget(self.end_frame_label)
        selection_layout.addWidget(self.end_nudge_back_button)
        selection_layout.addWidget(self.end_nudge_forward_button)
        selection_layout.addWidget(self.set_end_button)
        selection_layout.addStretch(1)
        selection_layout.addWidget(self.clip_selection_label)

        selection_button_height = max(
            self.play_button.sizeHint().height(), self.mute_button.sizeHint().height()
        )
        for button in (
            self.start_nudge_back_button,
            self.start_nudge_forward_button,
            self.end_nudge_back_button,
            self.end_nudge_forward_button,
            self.set_start_button,
            self.set_end_button,
        ):
            button.setFixedHeight(selection_button_height)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self._layout.addWidget(self.video_widget)
        self._layout.addLayout(controls_layout)

    def bind_window(self, window) -> None:
        """Wire this panel to the main-window controller."""
        self.media_player.mediaStatusChanged.connect(window.on_media_status_changed)
        self.media_player.errorOccurred.connect(window.on_media_error)
        self.media_player.durationChanged.connect(window.on_duration_changed)
        self.media_player.positionChanged.connect(window.on_position_changed)
        self.media_player.playbackStateChanged.connect(window._update_play_button_state)

        self.play_button.clicked.connect(window.toggle_preview_playback)
        self.playback_speed_combo.currentIndexChanged.connect(
            window.on_preview_playback_speed_changed
        )
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
