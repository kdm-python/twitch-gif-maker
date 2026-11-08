import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QMessageBox, QSplitter, QTextBrowser

from gifmaker.gui.main_window import MainWindow
from gifmaker.gui.shortcut_manager import ShortcutManager
from gifmaker.controllers.render_controller import _RenderProcessJob
from gifmaker.models.render_settings import RenderSettings, RenderSpec, format_ms, parse_time_input


def test_main_window_uses_splitter_for_resizable_preview_sections() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    central_layout = window.centralWidget().layout()
    resizable_container = window.preview_splitter

    assert isinstance(resizable_container, QSplitter)
    assert resizable_container.count() == 3
    assert isinstance(resizable_container.widget(0), QGroupBox)
    assert isinstance(resizable_container.widget(1), QGroupBox)
    assert isinstance(resizable_container.widget(2), QGroupBox)

    app.quit()


def test_main_window_allows_tighter_horizontal_minimum() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.minimumWidth() <= 760
    assert window.minimumHeight() >= 500

    app.quit()


def test_main_window_gives_more_space_to_preview_panels() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.preview_panel.video_widget.minimumHeight() <= 140
    assert window.preview_panel.acceptDrops()
    assert window.preview_panel.video_widget.acceptDrops()
    assert window.gif_preview_label.minimumHeight() <= 180

    sizes = window.preview_splitter.sizes()
    assert sizes[0] >= 200
    assert sizes[1] >= 40
    assert sizes[2] >= 180

    app.quit()


def test_dropped_non_mp4_shows_an_explanatory_dialog(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    unsupported = tmp_path / "clip.mov"
    unsupported.write_bytes(b"video")

    with patch.object(QMessageBox, "warning") as warning:
        window.open_dropped_video(str(unsupported))

    warning.assert_called_once()
    assert warning.call_args.args[1] == "Unsupported video"
    assert "Only MP4 videos" in warning.call_args.args[2]
    app.quit()


def test_dropped_mp4_uses_the_existing_video_loading_path(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = tmp_path / "clip.MP4"
    source.write_bytes(b"video")
    video_info = object()

    with patch("gifmaker.controllers.video_session_controller.probe_video", return_value=video_info), patch.object(
        window.video_session_controller, "load_video_preview"
    ) as load_preview:
        window.open_dropped_video(str(source))

    assert window.current_video_path == str(source)
    load_preview.assert_called_once_with(str(source), video_info, None)
    app.quit()


def test_export_controls_panel_compacts_action_buttons_below_inputs() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.export_controls_panel

    assert hasattr(panel, "primary_row")
    assert hasattr(panel, "button_row")
    assert panel.primary_row is not None
    assert panel.button_row is not None

    panel._apply_layout_mode(700)
    assert panel._compact_mode is True

    panel._apply_layout_mode(1100)
    assert panel._compact_mode is False

    app.quit()


def test_seek_slider_moves_media_player_to_frame_position_in_milliseconds() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_fps = 2.0
    window.total_frames = 10
    window.seek_slider.setRange(0, 9)
    window.seek_slider.set_total_frames(10)
    window.seek_slider.setValue(4)

    with patch.object(window.media_player, "setPosition") as set_position:
        window.on_seek_slider_pressed()
        window.on_seek_slider_moved(4)
        window.on_seek_slider_released()

    assert set_position.call_args_list[-1].args[0] == 2000

    app.quit()


def test_export_format_combo_defaults_to_webp_with_gif_available() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    combo = window.export_format_combo
    assert isinstance(combo, QComboBox)
    assert combo.count() == 2
    assert combo.itemText(0) == "WebP"
    assert combo.itemText(1) == "GIF"
    assert combo.currentText() == "WebP"

    app.quit()


def test_reset_preview_crop_clears_box_and_window_state() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._current_crop = (10, 20, 30, 40)
    window.gif_preview_label._crop_label_rect = (
        window.gif_preview_label._crop_label_rect
        or window.gif_preview_label._crop_label_rect
    )
    window.gif_preview_label._crop_label_rect = (
        window.gif_preview_label._crop_label_rect
    )
    window.gif_preview_label._crop_mode = "moving"

    window.reset_preview_crop()

    assert window._current_crop is None
    assert window.gif_preview_label._crop_label_rect is None
    assert window.gif_preview_label._crop_mode == "idle"

    app.quit()


def test_reset_preview_crop_restores_source_aspect_for_preview_and_export(
    tmp_path: Path,
) -> None:
    """Reset must not reuse square/tall output dimensions from an applied crop."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    window.current_video_path = str(source)
    window.clip_start_time = 0.0
    window.clip_end_time = 1.0
    window._current_video_info = type("Video", (), {"width": 1920, "height": 1080})()
    window._current_crop = (100, 100, 800, 800)
    window.export_width_input.setValue(640)
    window.export_height_input.setValue(640)
    window.gif_preview_label.set_video_size(1920, 1080)
    window.gif_preview_label.set_coordinate_space(window._current_crop)

    with patch.object(window.render_controller.render_service, "build_command") as build_mock, patch.object(
        window.render_controller, "_start_process"
    ):
        window.reset_preview_crop()

    assert window._current_crop is None
    assert window.gif_preview_label._coordinate_space == (0, 0, 1920, 1080)
    assert window.export_width_input.value() == 640
    assert window.export_height_input.value() == 360
    assert build_mock.call_args.args[0].settings.crop is None
    assert build_mock.call_args.args[0].settings.height == 360
    app.quit()


def test_shortcut_manager_registers_expected_key_bindings() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    manager = ShortcutManager(window)

    assert manager.shortcuts["left"].key() == QKeySequence(Qt.Key.Key_Left)
    assert manager.shortcuts["right"].key() == QKeySequence(Qt.Key.Key_Right)
    assert manager.shortcuts["play_pause"].key() == QKeySequence(Qt.Key.Key_Space)
    assert manager.shortcuts["toggle_mute"].key() == QKeySequence(Qt.Key.Key_M)
    assert manager.shortcuts["speed_down"].key() == QKeySequence(Qt.Key.Key_Comma)
    assert manager.shortcuts["speed_up"].key() == QKeySequence(Qt.Key.Key_Period)
    assert manager.shortcuts["start_set"].key() == QKeySequence(Qt.Key.Key_C)
    assert manager.shortcuts["start_left"].key() == QKeySequence(Qt.Key.Key_Z)
    assert manager.shortcuts["start_right"].key() == QKeySequence(Qt.Key.Key_X)
    assert manager.shortcuts["end_set"].key() == QKeySequence(Qt.Key.Key_V)
    assert manager.shortcuts["end_left"].key() == QKeySequence(Qt.Key.Key_B)
    assert manager.shortcuts["end_right"].key() == QKeySequence(Qt.Key.Key_N)
    assert manager.shortcuts["open_file"].key() == QKeySequence("Shift+O")
    assert manager.shortcuts["export_file"].key() == QKeySequence("Shift+E")
    assert manager.shortcuts["apply_crop"].key() == QKeySequence(Qt.Key.Key_A)
    assert manager.shortcuts["reset_crop"].key() == QKeySequence(Qt.Key.Key_R)
    assert manager.shortcuts["output_speed_down"].key() == QKeySequence(Qt.Key.Key_BracketLeft)
    assert manager.shortcuts["output_speed_up"].key() == QKeySequence(Qt.Key.Key_BracketRight)
    assert manager.shortcuts["output_speed_down"].autoRepeat()

    app.quit()


def test_bracket_shortcuts_step_output_speed_slider() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.output_speed_slider.setValue(100)

    window._shortcut_output_speed_down()
    assert window.output_speed_slider.value() == 95

    window._shortcut_output_speed_up()
    assert window.output_speed_slider.value() == 100
    app.quit()


def test_file_menu_contains_shortcuts_action_and_opens_reference_dialog() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert [action.text() for action in window.file_menu.actions()] == [
        "Shortcuts",
        "Documentation",
        "",
        "Theme",
    ]
    assert [action.text() for action in window.theme_menu.actions()] == [
        "Light",
        "Dark",
    ]
    assert window.theme_actions[window.current_theme].isChecked()
    window.shortcuts_action.trigger()
    dialog = window.shortcuts_dialog
    assert dialog.windowTitle() == "Keyboard Shortcuts"
    assert [group.title() for group in dialog.findChildren(QGroupBox)] == [
        "Video player",
        "Start and end frame controls",
        "File management",
        "Output preview controls",
        "Work mode",
    ]
    dialog.close()
    app.quit()


def test_documentation_menu_renders_readme_in_scrollable_dialog() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.documentation_action.trigger()
    dialog = window.documentation_dialog
    browser = dialog.findChild(QTextBrowser, "documentation_browser")

    assert dialog.windowTitle() == "Documentation"
    assert dialog.isVisible()
    assert browser.isReadOnly()
    assert "Preview workflow" in browser.toPlainText()
    assert "<h1" in browser.toHtml()
    assert browser.verticalScrollBar() is not None
    dialog.close()
    app.quit()


def test_documentation_reports_unavailable_readme() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    with patch("gifmaker.gui.main_window.load_documentation", side_effect=OSError("unavailable")):
        dialog = window.show_documentation_dialog()
    assert "Unable to load documentation: unavailable" in dialog.findChild(
        QTextBrowser, "documentation_browser"
    ).toPlainText()
    dialog.close()
    app.quit()


def test_documentation_uses_installed_distribution_description(tmp_path: Path) -> None:
    from email.message import Message

    from gifmaker.gui.main_window import load_documentation

    distribution = Message()
    distribution.set_payload("# Installed guide\n\nPreview workflow")
    with patch("gifmaker.gui.main_window.__file__", str(tmp_path / "site" / "gifmaker" / "gui" / "main_window.py")), patch(
        "gifmaker.gui.main_window.metadata", return_value=distribution
    ):
        assert "Installed guide" in load_documentation()


def test_theme_menu_applies_dark_and_restores_saved_choice_on_next_window() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window.theme_actions["dark"].trigger()
    assert window.current_theme == "dark"
    assert window.theme_actions["dark"].isChecked()
    assert "#17191f" in app.styleSheet()

    reopened_window = MainWindow()
    assert reopened_window.current_theme == "dark"
    assert reopened_window.theme_actions["dark"].isChecked()

    reopened_window.theme_actions["light"].trigger()
    assert reopened_window.current_theme == "light"
    assert reopened_window.theme_actions["light"].isChecked()
    assert app.styleSheet() == ""
    settings = QSettings("T10Nat", "GIF Maker")
    assert settings.value(MainWindow._THEME_SETTING_KEY) == "light"
    app.quit()


def test_render_settings_helpers_parse_and_format_time() -> None:
    assert parse_time_input("1:02:03") == 62.03
    assert parse_time_input("00:05:00") == 5.0
    assert parse_time_input("00:00:05") == 0.05
    assert format_ms(12345) == "00:12:34"

    settings = RenderSettings(
        start_seconds=1.5,
        end_seconds=3.0,
        fps=24,
        width=320,
        playback_speed=1.5,
        crop=(10, 20, 30, 40),
    )
    assert settings.start_seconds == 1.5
    assert settings.end_seconds == 3.0
    assert settings.width == 320
    assert settings.playback_speed == 1.5
    assert settings.effective_fps == 24


def test_main_window_has_player_playback_speed_control_and_selection_group() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert hasattr(window, "playback_speed_combo")
    assert hasattr(window.preview_panel, "playback_speed_combo")
    assert window.preview_panel.playback_speed_combo.itemText(0) == "0.25×"
    assert window.preview_panel.playback_speed_combo.itemText(1) == "0.5×"
    assert window.preview_panel.playback_speed_combo.itemText(2) == "1×"
    assert window.preview_panel.playback_speed_combo.itemText(3) == "1.5×"
    assert window.preview_panel.playback_speed_combo.itemText(4) == "2×"
    assert window.preview_panel.selection_group.title() == "Selection"
    assert window.preview_panel.selection_group.maximumHeight() <= 64
    assert window.preview_panel.selection_group.parentWidget() is window.preview_splitter
    assert window.clip_selection_label.text() == "Selection: Not selected"
    assert window.mute_button.text() == ""
    assert window.mute_button.toolTip() == "Mute video audio"
    assert window.open_button.text() == "Open Video File"
    assert window.output_speed_slider.minimum() == 25
    assert window.output_speed_slider.maximum() == 300
    assert window.output_speed_slider.value() == 100
    assert window.output_fps_combo.currentData() == 24
    assert window.aspect_ratio_lock.isChecked()
    assert window.export_format_combo.currentText() == "WebP"
    assert window.quality_preset_combo.currentData() == "high"
    assert window.sharpness_combo.currentData() == "mild"
    assert not window.quality_preset_combo.isHidden()

    app.quit()


def test_render_status_shows_activity_indicator_for_preview_generation() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window.export_status_label.setText("Status: Generating preview...")
    assert window.render_activity_indicator._timer.isActive()

    window.export_status_label.setText("Status: Preview ready. Click Export to save.")
    assert not window.render_activity_indicator._timer.isActive()
    app.quit()


def test_quality_control_is_webp_only_and_gif_uses_its_fixed_palette() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = "input.mp4"
    window.clip_start_time = 0.0
    window.clip_end_time = 1.0
    assert window.render_controller._resolve_render_settings().quality_preset == "high"
    assert not window.quality_preset_combo.isHidden()

    window.export_format_combo.setCurrentText("GIF")
    assert window.quality_preset_combo.isHidden()
    assert window.render_controller._resolve_render_settings().quality_preset == "balanced"
    app.quit()


def test_export_controls_keep_preview_playback_on_the_primary_row() -> None:
    """The duplicate time inputs are replaced by the GIF preview controls."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    panel = window.export_controls_panel

    assert not hasattr(panel, "export_start_input")
    assert not hasattr(panel, "export_end_input")
    assert panel.primary_layout.indexOf(panel.gif_preview_play_button) >= 0
    assert panel.primary_layout.indexOf(panel.gif_preview_pause_button) >= 0
    assert panel.secondary_layout.indexOf(panel.gif_preview_play_button) == -1
    assert panel.secondary_layout.indexOf(panel.gif_preview_pause_button) == -1

    app.quit()


def test_output_dimensions_remain_linked_to_the_source_aspect_ratio() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._current_video_info = type("Video", (), {"width": 1920, "height": 1080})()

    window.export_width_input.setValue(800)
    assert window.export_height_input.value() == 450

    window.export_height_input.setValue(900)
    assert window.export_width_input.value() == 1600

    window.use_original_size()
    assert window.export_width_input.value() == 1920
    assert window.export_height_input.value() == 1080
    app.quit()


def test_output_settings_resolve_and_retime_the_generated_preview() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.clip_start_time = 1.0
    window.clip_end_time = 3.0
    window.output_speed_slider.setValue(150)
    window.output_fps_combo.setCurrentIndex(window.output_fps_combo.findData(30))

    settings = window.render_controller._resolve_render_settings()

    assert window.output_speed_value_label.text() == "1.5×"
    assert settings.playback_speed == 1.5
    assert settings.fps == 30

    window._preview_frame_durations = [120]
    window._last_preview_settings = RenderSettings(
        start_seconds=1.0, end_seconds=3.0, playback_speed=1.0
    )
    assert window.preview_controller._frame_delay(0) == 80

    app.quit()


def test_generate_preview_keeps_the_active_crop(tmp_path: Path) -> None:
    """Refreshing a preview must never be a hidden reset-crop action."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    window.current_video_path = str(source)
    window.clip_start_time = 0.0
    window.clip_end_time = 1.0
    window._current_crop = (10, 20, 100, 80)

    with patch.object(window.render_controller.render_service, "build_command") as build_mock, patch.object(
        window.render_controller, "_start_process"
    ):
        window.render_controller.generate_gif_preview()

    assert window._current_crop == (10, 20, 100, 80)
    assert build_mock.call_args.args[0].settings.crop == (10, 20, 100, 80)
    app.quit()


def test_preview_cache_never_matches_a_different_export_format(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = str(tmp_path / "input.mp4")
    preview = tmp_path / "preview.gif"
    preview.write_bytes(b"preview")
    settings = RenderSettings(start_seconds=0.0, end_seconds=1.0)
    window._preview_temp_file = preview
    window._last_preview_spec = RenderSpec(source, "GIF", settings)

    assert not window.render_controller._preview_matches(
        RenderSpec(source, "WebP", settings)
    )
    app.quit()


def test_stale_preview_process_result_is_discarded(tmp_path: Path) -> None:
    """An older FFmpeg job must never replace a newer settings revision."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    preview = tmp_path / "stale.gif"
    preview.write_bytes(b"stale")
    source = str(tmp_path / "input.mp4")
    spec = RenderSpec(source, "GIF", RenderSettings(start_seconds=0.0, end_seconds=1.0))
    job = _RenderProcessJob(QProcess(window), spec, preview, revision=1)
    window._render_revision = 2
    window.render_controller._preview_job = job

    window.render_controller._on_preview_finished(job, 0, None)

    assert window.render_controller._preview_job is None
    assert not preview.exists()
    assert window._last_preview_spec is None
    app.quit()


def test_render_change_debounces_a_refresh_when_a_preview_exists(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = str(tmp_path / "input.mp4")
    window.current_video_path = source
    window.clip_start_time = 0.0
    window.clip_end_time = 1.0
    window._last_preview_spec = RenderSpec(
        source, "GIF", RenderSettings(start_seconds=0.0, end_seconds=1.0)
    )

    with patch.object(window.render_controller, "_schedule_preview_refresh") as schedule:
        window.render_controller.on_render_setting_changed()

    schedule.assert_called_once_with()
    app.quit()


def test_locked_preview_defers_edits_and_unlock_renders_latest_settings(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    controller = window.render_controller
    window._last_preview_spec = controller._resolve_render_spec()
    window._last_preview_settings = window._last_preview_spec.settings
    window.preview_lock_button.click()

    with patch.object(controller, "_schedule_preview_refresh") as schedule, patch.object(
        controller, "generate_gif_preview"
    ) as generate:
        window.output_speed_slider.setValue(150)
        assert controller.preview_locked
        assert window.preview_controller._preview_speed() == 1.0
        assert "out of date" in window.export_status_label.text()
        schedule.assert_not_called()
        generate.assert_not_called()
        window.preview_lock_button.click()
        generate.assert_called_once_with()
        assert not controller.preview_locked
    app.quit()


def test_locked_generate_and_crop_actions_do_not_unlock(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    controller = window.render_controller
    window.preview_lock_button.click()
    window._current_crop = (0, 0, 20, 20)
    with patch.object(controller, "generate_gif_preview") as generate:
        controller.apply_crop_to_preview()
        controller.reset_preview_crop()
        generate.assert_not_called()
    with patch.object(controller.render_service, "build_command"), patch.object(controller, "_start_process"):
        controller.generate_gif_preview()
    assert controller.preview_locked
    assert window.preview_lock_button.isChecked()
    app.quit()


def test_preview_lock_cancels_pending_refresh_and_shortcut_does_not_repeat(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    controller = window.render_controller
    controller._preview_debounce.start(10000)
    window.preview_lock_button.click()
    assert not controller._preview_debounce.isActive()
    shortcut = window.shortcut_manager.shortcuts["toggle_preview_lock"]
    assert shortcut.key() == QKeySequence(Qt.Key.Key_L)
    assert not shortcut.autoRepeat()
    with patch.object(controller, "generate_gif_preview") as generate:
        shortcut.activated.emit()
        generate.assert_called_once_with()
    app.quit()


def test_unlock_without_first_preview_or_pending_changes_does_not_render(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    with patch.object(window.render_controller, "generate_gif_preview") as generate:
        window.preview_lock_button.click()
        window.preview_lock_button.click()
        generate.assert_not_called()
        window._last_preview_spec = window.render_controller._resolve_render_spec()
        window.preview_lock_button.click()
        window.preview_lock_button.click()
        generate.assert_not_called()
    app.quit()


def test_edit_during_first_locked_render_is_applied_on_unlock(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    controller = window.render_controller
    window.preview_lock_button.click()
    destination = tmp_path / "pending.gif"
    destination.write_bytes(b"partial")
    controller._preview_job = _RenderProcessJob(
        QProcess(window), controller._resolve_render_spec(output_format="GIF"), destination
    )
    window.output_speed_slider.setValue(150)
    assert controller._preview_job is None
    assert not destination.exists()
    with patch.object(controller, "generate_gif_preview") as generate:
        window.preview_lock_button.click()
        generate.assert_called_once_with()
    app.quit()


def test_main_window_keeps_preview_controller_callback_adapters() -> None:
    """Cached-frame preview playback must retain its Qt timer callbacks."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    with patch.object(window.preview_controller, "on_cached_frame_timeout") as cached:
        window._on_cached_frame_timeout()
        cached.assert_called_once_with()

    with patch.object(window.preview_controller, "on_preview_frame_changed") as changed:
        window._on_preview_frame_changed(3)
        changed.assert_called_once_with(3)

    app.quit()
