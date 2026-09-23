"""Top-level composition root for the GIF Maker desktop application.

The window deliberately contains layout composition and durable Qt-owned state.
Interaction rules live in the video-session and render controllers; reusable
widgets live in :mod:`gifmaker.gui.views`.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QMovie, QPixmap
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gifmaker.controllers.render_controller import RenderController
from gifmaker.controllers.video_session_controller import VideoSessionController
from gifmaker.gui.preview_controller import PreviewController
from gifmaker.gui.shortcut_manager import ShortcutManager
from gifmaker.gui.views.crop_overlay_label import CropOverlayLabel
from gifmaker.gui.views.export_controls_panel import ExportControlsPanel
from gifmaker.gui.views.video_preview_panel import VideoPreviewPanel
from gifmaker.models.render_settings import RenderSettings
from gifmaker.models.video_info import VideoInfo


class MainWindow(QMainWindow):
    """Compose the application views and delegate interactions to controllers."""

    selection_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._initialise_session_state()
        self.preview_controller = PreviewController(self)
        self.video_session_controller = VideoSessionController(self)
        self.render_controller = RenderController(self)

        self.setWindowTitle("GIF Maker")
        self.create_menu()
        self.build_layout()
        self.shortcut_manager = ShortcutManager(self)
        self._fit_to_available_screen()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        logger.info("Main window initialised.")

    def _initialise_session_state(self) -> None:
        """Create all non-widget state shared by controllers and preview playback."""
        self.current_video_path: str | None = None
        self.clip_start_time: float | None = None
        self.clip_end_time: float | None = None
        self.start_frame = self.end_frame = self.total_frames = 0
        self.current_video_fps = 24.0
        self.minimum_selection_gap_frames = 2
        self._is_seek_dragging = False
        self._pending_video_path: str | None = None
        self._pending_video_info: VideoInfo | None = None
        self._previous_video_path: str | None = None
        self._previous_source: QUrl | None = None
        self._previous_file_info_text = "No file loaded"
        self._previous_meta_info_text = "Duration: - | Resolution: - | FPS: - | Codec: -"
        self._restoring_previous_source = False
        self._current_crop: tuple[int, int, int, int] | None = None
        self._current_video_info: VideoInfo | None = None
        self._preview_temp_file: Path | None = None
        self._preview_movie: QMovie | None = None
        self._preview_frame_cache: list[QPixmap] | None = None
        self._preview_frame_durations: list[int] | None = None
        self._preview_frame_timer: QTimer | None = None
        self._preview_frame_index = 0
        self._last_preview_settings: RenderSettings | None = None
        self._last_preview_source: str | None = None

    def __getattr__(self, name: str):
        """Expose controller callbacks to Qt views without duplicating forwarding code."""
        for controller_name in ("video_session_controller", "render_controller"):
            controller = self.__dict__.get(controller_name)
            if controller is not None and hasattr(controller, name):
                return getattr(controller, name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def create_menu(self) -> None:
        """Create the current placeholder menu structure."""
        menu_bar = self.menuBar()
        for name in ("File", "Edit", "View", "Help"):
            menu_bar.addMenu(name)

    def build_layout(self) -> None:
        """Assemble views while keeping their visual hierarchy unchanged."""
        central = QWidget(self)
        layout = QVBoxLayout(central)
        open_button = QPushButton("Open Video File")
        open_button.clicked.connect(self.open_file_dialog)
        layout.addWidget(open_button)

        self.preview_panel = VideoPreviewPanel(self)
        self._expose_video_preview_widgets()
        self.preview_panel.bind_window(self)

        gif_preview = self.create_gif_preview_panel()
        self.export_controls_panel = ExportControlsPanel(self)
        self._expose_export_widgets()
        self.export_controls_panel.bind_window(self)

        self.preview_splitter = QSplitter(Qt.Vertical)
        self.preview_splitter.setObjectName("preview_splitter")
        self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.addWidget(self.preview_panel)
        self.preview_splitter.addWidget(gif_preview)
        self.preview_splitter.setSizes([500, 400])
        self.preview_splitter.setStretchFactor(0, 1)
        self.preview_splitter.setStretchFactor(1, 1)

        layout.addWidget(self.preview_splitter, stretch=1)
        layout.addWidget(self.export_controls_panel)
        layout.addWidget(self.create_bottom_toolbar())
        self.setCentralWidget(central)
        self.video_session_controller.update_clip_selection_display()

    def _expose_video_preview_widgets(self) -> None:
        """Keep established widget attributes available to controllers and integrations."""
        panel = self.preview_panel
        for name in (
            "video_widget", "media_player", "audio_output", "play_button",
            "playback_speed_combo", "set_start_button", "set_end_button",
            "seek_slider", "seek_time_label", "mute_button", "selection_group",
            "start_frame_label", "start_nudge_back_button", "start_nudge_forward_button",
            "end_frame_label", "end_nudge_back_button", "end_nudge_forward_button",
            "clip_selection_label",
        ):
            setattr(self, name, getattr(panel, name))
        self.preview_playback_speed_combo = panel.playback_speed_combo

    def _expose_export_widgets(self) -> None:
        """Keep established control attributes available during the transition."""
        panel = self.export_controls_panel
        for name in (
            "export_start_input", "export_end_input", "output_speed_slider",
            "output_speed_value_label", "output_fps_combo",
            "export_width_input", "generate_preview_button", "apply_crop_button",
            "reset_crop_button", "gif_preview_play_button", "gif_preview_pause_button",
            "export_format_combo",
        ):
            setattr(self, name, getattr(panel, name))

    def create_gif_preview_panel(self) -> QGroupBox:
        """Create the crop-enabled generated-animation preview view."""
        group = QGroupBox("GIF Preview")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(group)
        self.gif_preview_label = CropOverlayLabel("Generate preview to display GIF")
        self.gif_preview_label.setAlignment(Qt.AlignCenter)
        self.gif_preview_label.setMinimumHeight(180)
        self.gif_preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.gif_preview_label.setStyleSheet("border: 1px solid palette(mid);")
        self.gif_preview_label.cropChanged.connect(self._on_crop_changed)
        self.gif_preview_label.cropCleared.connect(self._on_crop_cleared)
        self.preview_controller.bind(self.gif_preview_label)
        layout.addWidget(self.gif_preview_label)
        return group

    def create_bottom_toolbar(self) -> QWidget:
        """Create the unchanged file-metadata and primary-export footer."""
        toolbar = QWidget(self)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        self.video_file_label = QLabel("No file loaded")
        self.video_meta_label = QLabel("Duration: - | Resolution: - | FPS: - | Codec: -")
        self.export_status_label = QLabel("Status: -")
        row = QHBoxLayout()
        row.addWidget(self.video_meta_label)
        row.addWidget(self.export_status_label)
        row.addStretch(1)
        info.addWidget(self.video_file_label)
        info.addLayout(row)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_gif_from_selection)
        layout.addLayout(info, stretch=1)
        layout.addWidget(self.export_button)
        return toolbar

    def update_video_info(self, file_path: str, *, duration: float, width: int, height: int, fps: float, codec: str) -> None:
        """Update the compact source-file metadata displayed in the footer."""
        self.video_file_label.setText(file_path)
        self.video_meta_label.setText(
            f"Duration: {duration:.2f}s | Resolution: {width}x{height} | FPS: {fps:.2f} | Codec: {codec}"
        )

    def resizeEvent(self, event) -> None:
        """Resize generated-preview content while views manage their own layout."""
        super().resizeEvent(event)
        self.preview_controller.update_scaled_size()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Release temporary preview assets when the application closes."""
        self.render_controller.clear_preview_state(remove_temp_file=True)
        super().closeEvent(event)

    # PreviewController callback adapters.  Keeping these stable lets the
    # preview lifecycle remain independent of the window's layout code.
    def _on_cached_frame_timeout(self) -> None:
        """Advance a cached preview frame after its delay expires."""
        self.preview_controller.on_cached_frame_timeout()

    def _on_preview_frame_changed(self, frame: int) -> None:
        """Forward QMovie frame changes to the preview loop controller."""
        self.preview_controller.on_preview_frame_changed(frame)

    def _fit_to_available_screen(self) -> None:
        """Keep initial and maximum window bounds inside the active display."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1050, 760)
            self.setMinimumSize(760, 540)
            return
        available = screen.availableGeometry()
        self.setMinimumSize(760, 540)
        self.setMaximumSize(available.width(), available.height())
        self.resize(min(1050, available.width()), min(760, available.height()))

    # Shortcut adapters retain the existing ShortcutManager API.
    def _shortcut_left(self) -> None: self._leftArrowPressed()
    def _shortcut_right(self) -> None: self._rightArrowPressed()
    def _shortcut_play_pause(self) -> None: self.toggle_preview_playback()
    def _shortcut_toggle_mute(self) -> None: self.toggle_mute()
    def _shortcut_speed_down(self) -> None: self.speed_down_playback()
    def _shortcut_speed_up(self) -> None: self.speed_up_playback()
    def _shortcut_start_set(self) -> None: self._startSetPressed()
    def _shortcut_start_left(self) -> None: self._startSliderLeftPressed()
    def _shortcut_start_right(self) -> None: self._startSliderRightPressed()
    def _shortcut_end_set(self) -> None: self._endSetPressed()
    def _shortcut_end_left(self) -> None: self._endSliderLeftPressed()
    def _shortcut_end_right(self) -> None: self._endSliderRightPressed()
    def _shortcut_open_file(self) -> None: self.open_file_dialog()
    def _shortcut_export_file(self) -> None: self.export_gif_from_selection()
    def _shortcut_apply_crop(self) -> None: self.apply_crop_to_preview()
    def _shortcut_reset_crop(self) -> None: self.reset_preview_crop()
