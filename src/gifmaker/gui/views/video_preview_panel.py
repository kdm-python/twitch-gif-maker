"""Video preview panel and playback controls."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from gifmaker.gui.themes import SELECTION_TIME_FONT_SIZE
from gifmaker.gui.views.marker_seek_slider import MarkerSeekSlider


class VideoDropWidget(QVideoWidget):
    """Video surface that accepts local-file drops without losing playback."""

    fileDropped = Signal(str)
    dragActiveChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _local_file_from_event(event) -> str | None:
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            if url.isLocalFile():
                return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:
        if self._local_file_from_event(event) is None:
            event.ignore()
            return
        self.dragActiveChanged.emit(True)
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._local_file_from_event(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.dragActiveChanged.emit(False)
        event.accept()

    def dropEvent(self, event) -> None:
        path = self._local_file_from_event(event)
        self.dragActiveChanged.emit(False)
        if path is None:
            event.ignore()
            return
        self.fileDropped.emit(path)
        event.acceptProposedAction()


class AnimationSurface(QLabel):
    """Display a scaled animation frame while letting the panel handle drops."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("border: 1px solid palette(mid);")

    def set_frame(self, image):
        self._frame = QPixmap.fromImage(image)
        self._scale_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_frame()

    def _scale_frame(self):
        if not self._frame.isNull():
            self.setPixmap(self._frame.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))


class SelectionTimeLabels(QWidget):
    """Keep timestamps beneath their markers, staggering close boundaries."""

    def __init__(self, slider: MarkerSeekSlider, parent=None) -> None:
        super().__init__(parent)
        self.slider = slider
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(100)
        self.start_label = QLabel("--:--:--.---", self)
        self.end_label = QLabel("--:--:--.---", self)
        for label, name in ((self.start_label, "Start"), (self.end_label, "End")):
            font = label.font()
            font.setPointSizeF(SELECTION_TIME_FONT_SIZE)
            label.setFont(font)
            label.setToolTip(f"Selection {name.lower()} time")
            label.setAccessibleName(f"Selection {name.lower()} time")
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Reserve two small lines so short selections never resize the player.
        self.setFixedHeight(2 * self.start_label.sizeHint().height() + 2)
        self.slider.selectionChanged.connect(self.update_positions)

    def set_times(self, start: str, end: str) -> None:
        self.start_label.setText(start)
        self.end_label.setText(end)
        self.update_positions()

    def update_positions(self, *_args) -> None:
        start, end = self.slider.selection()
        labels = (self.start_label, self.end_label)
        for label, frame in zip(labels, (start, end)):
            label.adjustSize()
            x = self.slider._frame_to_x(frame) - label.width() // 2
            label.move(max(0, min(x, self.width() - label.width())), 0)
        if self.start_label.geometry().adjusted(-3, 0, 3, 0).intersects(
            self.end_label.geometry()
        ):
            self.end_label.move(self.end_label.x(), self.start_label.height() + 2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_positions()


class VideoPreviewPanel(QGroupBox):
    """Panel containing the video preview, timeline and playback controls."""

    fileDropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Video Preview", parent)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)

        self.video_widget = VideoDropWidget(self)
        self.video_widget.setMinimumHeight(140)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("border: 1px solid palette(mid);")
        self.video_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video_widget.fileDropped.connect(self.fileDropped)
        self.video_widget.dragActiveChanged.connect(self._set_drop_highlight)

        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        self.controls_layout = QGridLayout()
        controls_layout = self.controls_layout
        controls_layout.setHorizontalSpacing(6)
        controls_layout.setVerticalSpacing(0)
        self.play_button = QPushButton("▶ Play")

        self.playback_speed_combo = QComboBox()
        self.playback_speed_combo.addItem("0.25×", 0.25)
        self.playback_speed_combo.addItem("0.5×", 0.5)
        self.playback_speed_combo.addItem("1×", 1.0)
        self.playback_speed_combo.addItem("1.5×", 1.5)
        self.playback_speed_combo.addItem("2×", 2.0)
        self.playback_speed_combo.setCurrentIndex(2)
        self.playback_speed_combo.setFixedWidth(88)
        self.playback_speed_combo.setToolTip("Video playback speed")
        self.playback_speed_combo.setAccessibleName("Video playback speed")

        self.seek_slider = MarkerSeekSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.set_total_frames(0)

        self.seek_time_label = QLabel("00:00:00 / 00:00:00")
        self.clip_selection_label = QLabel("Length: —")
        for label, sample in (
            (self.seek_time_label, "00:00:00 / 00:00:00"),
            (self.clip_selection_label, "Length: 0000.000s"),
        ):
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(sample))
        self.clip_selection_label.setToolTip("Selected source duration")
        self.clip_selection_label.setAccessibleName("Selection length")
        self.mute_button = QPushButton()
        self.mute_button.setFixedWidth(34)
        self.update_mute_button(False)

        controls_layout.addWidget(self.play_button, 0, 0)
        controls_layout.addWidget(self.playback_speed_combo, 0, 1)
        controls_layout.addWidget(self.seek_slider, 0, 2)
        controls_layout.addWidget(self.seek_time_label, 0, 3)
        controls_layout.addWidget(self.clip_selection_label, 0, 4)
        controls_layout.addWidget(self.mute_button, 0, 5)
        controls_layout.setColumnStretch(2, 1)

        self.selection_times = SelectionTimeLabels(self.seek_slider, self)
        self.start_frame_label = self.selection_times.start_label
        self.end_frame_label = self.selection_times.end_label
        controls_layout.addWidget(self.selection_times, 1, 2)

        self.animation_widget = AnimationSurface(self)
        self.source_stack = QStackedWidget(self)
        self.source_stack.addWidget(self.video_widget)
        self.source_stack.addWidget(self.animation_widget)
        self._layout.addWidget(self.source_stack)
        self._layout.addLayout(controls_layout)

    def bind_window(self, window) -> None:
        """Wire this panel to the main-window controller."""
        self.fileDropped.connect(window.open_dropped_video)
        self.media_player.mediaStatusChanged.connect(window.on_media_status_changed)
        self.media_player.errorOccurred.connect(window.on_media_error)
        self.media_player.durationChanged.connect(window.on_duration_changed)
        self.media_player.positionChanged.connect(window.on_position_changed)
        self.media_player.playbackStateChanged.connect(window._update_play_button_state)

        self.play_button.clicked.connect(window.toggle_preview_playback)
        self.playback_speed_combo.currentIndexChanged.connect(
            window.on_preview_playback_speed_changed
        )

        self.seek_slider.sliderPressed.connect(window.on_seek_slider_pressed)
        self.seek_slider.sliderMoved.connect(window.on_seek_slider_moved)
        self.seek_slider.sliderReleased.connect(window.on_seek_slider_released)
        self.seek_slider.selectionChanged.connect(window.on_scrub_selection_changed)

        self.mute_button.clicked.connect(window.toggle_mute)
        self.audio_output.mutedChanged.connect(self.update_mute_button)

    def update_mute_button(self, muted: bool) -> None:
        """Use Qt's standard speaker glyphs, with accessible text as a fallback."""
        icon = (
            QStyle.StandardPixmap.SP_MediaVolumeMuted
            if muted
            else QStyle.StandardPixmap.SP_MediaVolume
        )
        standard_icon = self.style().standardIcon(icon)
        size = QSize(16, 16)
        source = standard_icon.pixmap(size)
        tinted_icon = QPixmap(size)
        tinted_icon.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted_icon)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted_icon.rect(), self.palette().buttonText())
        painter.end()
        self.mute_button.setIcon(QIcon(tinted_icon))
        self.mute_button.setIconSize(size)
        self.mute_button.setText("")
        label = "Unmute video audio" if muted else "Mute video audio"
        self.mute_button.setToolTip(label)
        self.mute_button.setAccessibleName(label)

    @staticmethod
    def _local_file_from_event(event) -> str | None:
        return VideoDropWidget._local_file_from_event(event)

    def _set_drop_highlight(self, active: bool) -> None:
        """Show an obvious target while a local file is dragged over playback."""
        if active:
            self.video_widget.setStyleSheet(
                "border: 2px dashed palette(highlight); background: palette(alternate-base);"
            )
        else:
            self.video_widget.setStyleSheet("border: 1px solid palette(mid);")

    def dragEnterEvent(self, event) -> None:
        if self._local_file_from_event(event) is None:
            event.ignore()
            return
        self._set_drop_highlight(True)
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._local_file_from_event(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_highlight(False)
        event.accept()

    def dropEvent(self, event) -> None:
        path = self._local_file_from_event(event)
        self._set_drop_highlight(False)
        if path is None:
            event.ignore()
            return
        self.fileDropped.emit(path)
        event.acceptProposedAction()
