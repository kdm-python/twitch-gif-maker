"""Top-level composition root for the GIF Maker desktop application.

The window deliberately contains layout composition and durable Qt-owned state.
Interaction rules live in the video-session and render controllers; reusable
widgets live in :mod:`gifmaker.gui.views`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractSlider,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gifmaker.controllers.render_controller import RenderController
from gifmaker.controllers.video_session_controller import VideoSessionController
from gifmaker.gui.preview_controller import PreviewController
from gifmaker.gui.shortcut_manager import SHORTCUT_HELP, ShortcutManager
from gifmaker.gui.themes import THEMES, apply_theme
from gifmaker.gui.views.activity_indicator import ActivityIndicator
from gifmaker.gui.views.crop_overlay_label import CropOverlayLabel
from gifmaker.gui.views.export_controls_panel import ExportControlsPanel
from gifmaker.gui.views.video_preview_panel import VideoPreviewPanel
from gifmaker.models.render_settings import RenderSettings, RenderSpec
from gifmaker.models.video_info import VideoInfo


class RenderStatusLabel(QLabel):
    """Status text that automatically shows activity for active render jobs."""

    def __init__(self, activity_indicator: ActivityIndicator, parent=None) -> None:
        super().__init__(parent)
        self._activity_indicator = activity_indicator

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._activity_indicator.set_running(
            text.startswith("Status: Generating preview")
            or text.startswith("Status: Exporting")
        )
        super().setText(text)


def load_documentation() -> str:
    """Read the source README, or its packaged copy in distribution metadata."""
    project_root = Path(__file__).resolve().parents[3]
    readme = project_root / "README.md"
    if (project_root / "pyproject.toml").is_file() and readme.is_file():
        return readme.read_text(encoding="utf-8")
    try:
        description = metadata("gifmaker").get_payload()
    except PackageNotFoundError as exc:
        raise OSError("The application documentation could not be found.") from exc
    if not isinstance(description, str) or not description.strip():
        raise OSError("The application documentation is empty or unavailable.")
    return description


class MainWindow(QMainWindow):
    """Compose the application views and delegate interactions to controllers."""

    selection_changed = Signal(int, int)
    _THEME_SETTING_KEY = "appearance/theme"

    def __init__(self) -> None:
        super().__init__()
        self._initialise_session_state()
        self.preview_controller = PreviewController(self)
        self.video_session_controller = VideoSessionController(self)
        self.render_controller = RenderController(self)

        self.setWindowTitle("GIF Maker")
        self._theme_settings = QSettings("T10Nat", "GIF Maker")
        saved_theme = self._theme_settings.value(self._THEME_SETTING_KEY, "light")
        self.current_theme = saved_theme if saved_theme in THEMES else "light"
        application = QGuiApplication.instance()
        if application is not None:
            apply_theme(application, self.current_theme)
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
        self._previous_meta_info_text = (
            "Duration: - | Resolution: - | FPS: - | Codec: -"
        )
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
        self._last_preview_spec: RenderSpec | None = None
        self._render_revision = 0

    def __getattr__(self, name: str):
        """Expose controller callbacks to Qt views without duplicating forwarding code."""
        for controller_name in ("video_session_controller", "render_controller"):
            controller = self.__dict__.get(controller_name)
            if controller is not None and hasattr(controller, name):
                return getattr(controller, name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def create_menu(self) -> None:
        """Create the application menu bar.

        Add later File-menu options by creating another ``QAction`` here and
        passing it to ``self.file_menu.addAction(...)``.
        """
        self.file_menu = self.menuBar().addMenu("File")
        self.shortcuts_action = QAction("Shortcuts", self)
        self.shortcuts_action.triggered.connect(self.show_shortcuts_dialog)
        self.file_menu.addAction(self.shortcuts_action)
        self.documentation_action = QAction("Documentation", self)
        self.documentation_action.triggered.connect(self.show_documentation_dialog)
        self.file_menu.addAction(self.documentation_action)
        self.file_menu.addSeparator()

        self.theme_menu = self.file_menu.addMenu("Theme")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for name, theme in THEMES.items():
            action = QAction(theme.label, self, checkable=True)
            action.triggered.connect(
                lambda checked, theme_name=name: checked
                and self.set_theme(theme_name)
            )
            self.theme_action_group.addAction(action)
            self.theme_menu.addAction(action)
            self.theme_actions[name] = action
        self.theme_actions[self.current_theme].setChecked(True)

    def set_theme(self, theme_name: str) -> None:
        """Apply one of the registered themes and update the File-menu state."""
        application = QGuiApplication.instance()
        if application is None:
            return
        self.current_theme = apply_theme(application, theme_name)
        self.theme_actions[self.current_theme].setChecked(True)
        self._theme_settings.setValue(self._THEME_SETTING_KEY, self.current_theme)
        self._theme_settings.sync()
        if hasattr(self, "preview_panel"):
            self.preview_panel.update_mute_button(self.audio_output.isMuted())
        if hasattr(self, "preview_lock_button"):
            self._update_preview_lock_button(self.preview_lock_button.isChecked())

    def show_shortcuts_dialog(self) -> QDialog:
        """Open the grouped keyboard-shortcut reference window."""
        dialog = QDialog(self)
        dialog.setObjectName("shortcuts_dialog")
        dialog.setWindowTitle("Keyboard Shortcuts")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        for group_name, shortcuts in SHORTCUT_HELP:
            group = QGroupBox(group_name, dialog)
            grid = QGridLayout(group)
            grid.setColumnStretch(1, 1)
            for row, (key, description) in enumerate(shortcuts):
                key_label = QLabel(key, group)
                key_label.setStyleSheet("font-weight: 600;")
                grid.addWidget(key_label, row, 0)
                grid.addWidget(QLabel(description, group), row, 1)
            layout.addWidget(group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)
        self.shortcuts_dialog = dialog
        dialog.open()
        return dialog

    def show_documentation_dialog(self) -> QDialog:
        """Display the README as scrollable Markdown, including in installs."""
        dialog = QDialog(self)
        dialog.setObjectName("documentation_dialog")
        dialog.setWindowTitle("Documentation")
        dialog.resize(800, 650)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setObjectName("documentation_browser")
        browser.setOpenExternalLinks(True)
        try:
            browser.setMarkdown(load_documentation())
        except (OSError, UnicodeError) as exc:
            browser.setPlainText(f"Unable to load documentation: {exc}")
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)
        self.documentation_dialog = dialog
        dialog.open()
        return dialog

    def build_layout(self) -> None:
        """Assemble a preview-first workspace with secondary controls below it."""
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

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
        # Keep the existing Selection box intact, but place it between the two
        # preview surfaces so it reads as the bridge between source and output.
        self.preview_splitter.addWidget(self.preview_panel.selection_group)
        self.preview_splitter.addWidget(gif_preview)
        self.preview_splitter.setSizes([500, 64, 400])
        self.preview_splitter.setStretchFactor(0, 1)
        self.preview_splitter.setStretchFactor(1, 0)
        self.preview_splitter.setStretchFactor(2, 1)

        # Keep the video and GIF canvases as the stretchable regions around the
        # compact selection strip.
        layout.addWidget(self.preview_splitter, stretch=1)
        layout.addWidget(self.export_controls_panel)
        layout.addWidget(self.create_bottom_toolbar())
        self.setCentralWidget(central)
        self.selection_changed.connect(self.render_controller.on_render_setting_changed)
        self.video_session_controller.update_clip_selection_display()
        self.render_controller.update_output_summary()

    def _expose_video_preview_widgets(self) -> None:
        """Keep established widget attributes available to controllers and integrations."""
        panel = self.preview_panel
        for name in (
            "video_widget",
            "media_player",
            "audio_output",
            "play_button",
            "playback_speed_combo",
            "set_start_button",
            "set_end_button",
            "seek_slider",
            "seek_time_label",
            "mute_button",
            "selection_group",
            "start_frame_label",
            "start_nudge_back_button",
            "start_nudge_forward_button",
            "end_frame_label",
            "end_nudge_back_button",
            "end_nudge_forward_button",
            "clip_selection_label",
        ):
            setattr(self, name, getattr(panel, name))
        self.preview_playback_speed_combo = panel.playback_speed_combo

    def _expose_export_widgets(self) -> None:
        """Keep established control attributes available during the transition."""
        panel = self.export_controls_panel
        for name in (
            "output_speed_slider",
            "output_speed_value_label",
            "output_fps_combo",
            "export_width_input",
            "export_height_input",
            "aspect_ratio_lock",
            "original_size_button",
            "quality_preset_combo",
            "generate_preview_button",
            "apply_crop_button",
            "sharpness_combo",
            "reset_crop_button",
            "gif_preview_play_button",
            "gif_preview_pause_button",
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
        self.gif_preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.gif_preview_label.setStyleSheet("border: 1px solid palette(mid);")
        self.gif_preview_label.cropChanged.connect(self._on_crop_changed)
        self.gif_preview_label.cropCleared.connect(self._on_crop_cleared)
        self.preview_controller.bind(self.gif_preview_label)
        layout.addWidget(self.gif_preview_label)
        return group

    def create_bottom_toolbar(self) -> QWidget:
        """Create the file-metadata footer and its primary file actions."""
        toolbar = QWidget(self)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        self.video_file_label = QLabel("No file loaded")
        self.video_meta_label = QLabel(
            "Duration: - | Resolution: - | FPS: - | Codec: -"
        )
        self.render_status_frame = QFrame(toolbar)
        self.render_status_frame.setObjectName("render_status_frame")
        self.render_status_frame.setStyleSheet(
            "QFrame#render_status_frame {"
            " background: palette(alternate-base);"
            " border: 1px solid palette(mid);"
            " border-radius: 6px;"
            "}"
        )
        status_layout = QHBoxLayout(self.render_status_frame)
        status_layout.setContentsMargins(7, 2, 7, 2)
        status_layout.setSpacing(5)
        self.render_activity_indicator = ActivityIndicator(self.render_status_frame)
        self.export_status_label = RenderStatusLabel(
            self.render_activity_indicator, self.render_status_frame
        )
        self.export_status_label.setText("Status: -")
        status_layout.addWidget(self.render_activity_indicator)
        status_layout.addWidget(self.export_status_label)
        self.output_summary_label = QLabel("Output: Select a clip range")
        row = QHBoxLayout()
        row.addWidget(self.video_meta_label)
        row.addWidget(self.render_status_frame)
        row.addWidget(self.output_summary_label)
        row.addStretch(1)
        info.addWidget(self.video_file_label)
        info.addLayout(row)
        self.open_button = QPushButton("Open Video File")
        self.open_button.clicked.connect(self.open_file_dialog)
        self.clip_button = QPushButton("Open Twitch Clip")
        self.clip_button.clicked.connect(self.open_clip_dialog)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_gif_from_selection)
        self.preview_lock_button = QPushButton()
        self.preview_lock_button.setCheckable(True)
        self.preview_lock_button.setFixedWidth(34)
        self.preview_lock_button.toggled.connect(self._set_preview_locked)
        self._update_preview_lock_button(False)
        layout.addWidget(self.preview_lock_button)
        layout.addLayout(info, stretch=1)
        layout.addWidget(self.open_button)
        layout.addWidget(self.clip_button)
        layout.addWidget(self.export_button)
        return toolbar

    def _set_preview_locked(self, locked: bool) -> None:
        self._update_preview_lock_button(locked)
        self.render_controller.set_preview_locked(locked)

    def _update_preview_lock_button(self, locked: bool) -> None:
        """Draw a closed or open padlock using the active theme's colours."""
        size = QSize(20, 20)
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = (
            self.palette().highlight().color()
            if locked
            else self.palette().buttonText().color()
        )
        painter.setPen(QPen(colour, 1.8))
        shackle = QPainterPath()
        if locked:
            shackle.moveTo(6, 9)
            shackle.lineTo(6, 6)
            shackle.cubicTo(6, 1, 14, 1, 14, 6)
            shackle.lineTo(14, 9)
        else:
            shackle.moveTo(6, 9)
            shackle.lineTo(6, 6)
            shackle.cubicTo(6, 1, 14, 1, 14, 6)
        painter.drawPath(shackle)
        painter.drawRoundedRect(QRectF(4, 9, 12, 9), 2, 2)
        painter.drawPoint(10, 13)
        painter.end()
        self.preview_lock_button.setIcon(QIcon(pixmap))
        self.preview_lock_button.setIconSize(size)
        label = (
            "Preview locked — click to enable live updates (L)"
            if locked
            else "Live preview — click to lock updates (L)"
        )
        self.preview_lock_button.setToolTip(label)
        self.preview_lock_button.setAccessibleName(label)

    def update_video_info(
        self,
        file_path: str,
        *,
        duration: float,
        width: int,
        height: int,
        fps: float,
        codec: str,
    ) -> None:
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
        self.render_controller.cancel_active_renders()
        self.render_controller.clear_preview_state(remove_temp_file=True)
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self.video_session_controller.cleanup_clip_downloads()
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
    def _shortcut_left(self) -> None:
        self._leftArrowPressed()

    def _shortcut_right(self) -> None:
        self._rightArrowPressed()

    def _shortcut_play_pause(self) -> None:
        self.toggle_preview_playback()

    def _shortcut_toggle_mute(self) -> None:
        self.toggle_mute()

    def _shortcut_speed_down(self) -> None:
        self.speed_down_playback()

    def _shortcut_speed_up(self) -> None:
        self.speed_up_playback()

    def _shortcut_start_set(self) -> None:
        self._startSetPressed()

    def _shortcut_start_left(self) -> None:
        self._startSliderLeftPressed()

    def _shortcut_start_right(self) -> None:
        self._startSliderRightPressed()

    def _shortcut_end_set(self) -> None:
        self._endSetPressed()

    def _shortcut_end_left(self) -> None:
        self._endSliderLeftPressed()

    def _shortcut_end_right(self) -> None:
        self._endSliderRightPressed()

    def _shortcut_open_clip(self) -> None:
        self.open_clip_dialog()

    def _shortcut_open_file(self) -> None:
        self.open_file_dialog()

    # GIF preview controls

    def _shortcut_generate_gif_preview(self) -> None:
        self.generate_gif_preview()

    def _shortcut_export_file(self) -> None:
        self.export_gif_from_selection()

    def _shortcut_apply_crop(self) -> None:
        self.apply_crop_to_preview()

    def _shortcut_reset_crop(self) -> None:
        self.reset_preview_crop()

    def _shortcut_output_speed_down(self) -> None:
        self.output_speed_slider.triggerAction(
            QAbstractSlider.SliderAction.SliderSingleStepSub
        )

    def _shortcut_output_speed_up(self) -> None:
        self.output_speed_slider.triggerAction(
            QAbstractSlider.SliderAction.SliderSingleStepAdd
        )
