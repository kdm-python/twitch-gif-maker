"""Exercise actual rendered previews and their export identity."""

import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow
from gifmaker.services.gif_export import format_ffmpeg_error


def webp_ffmpeg() -> str | None:
    candidates = [os.environ.get("GIFMAKER_FFMPEG"), shutil.which("ffmpeg"),
                  "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"]
    for executable in candidates:
        if not executable or not Path(executable).is_file():
            continue
        result = subprocess.run([executable, "-hide_banner", "-encoders"],
                                capture_output=True, text=True, check=False)
        if "libwebp_anim" in result.stdout:
            return executable
    return None


@pytest.mark.parametrize("output_format", ["WebP", "GIF"])
def test_preview_matches_export_and_plays_real_animation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_format: str
) -> None:
    ffmpeg = webp_ffmpeg()
    if ffmpeg is None:
        pytest.skip("FFmpeg with libwebp_anim is required")
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source = Path(__file__).parent / "fixtures" / "small_floor_landscape.mp4"
    window.current_video_path = str(source.resolve())
    window.clip_start_time, window.clip_end_time = 1.0, 2.0
    window.export_format_combo.setCurrentText(output_format)
    window.export_width_input.setValue(160)
    window.export_height_input.setValue(90)
    window.output_fps_combo.setCurrentIndex(window.output_fps_combo.findData(30))
    window.quality_preset_combo.setCurrentIndex(window.quality_preset_combo.findData("small"))
    window.render_controller.generate_gif_preview()
    deadline = time.monotonic() + 30
    while window.render_controller._preview_job is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert window.render_controller._preview_job is None
    assert window._last_preview_spec is not None, window.export_status_label.text()
    spec = window._last_preview_spec
    preview = window._preview_temp_file
    assert spec.output_format == output_format
    assert preview.suffix == (".webp" if output_format == "WebP" else ".gif")
    assert spec.settings.quality_preset == ("small" if output_format == "WebP" else "balanced")
    assert len(window._preview_frame_cache) > 1
    assert 900 <= sum(window._preview_frame_durations) <= 1100
    assert window._preview_frame_timer.isActive()
    destination = tmp_path / f"output{preview.suffix}"
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName",
               return_value=(str(destination), "")), patch.object(
        window.render_controller, "_export_source"
    ) as render:
        window.render_controller.export_gif_from_selection()
    render.assert_not_called()
    assert destination.read_bytes() == preview.read_bytes()
    window.close()
    app.processEvents()


def test_locked_format_and_quality_changes_refresh_on_unlock(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    controller = window.render_controller
    window._last_preview_spec = controller._resolve_render_spec()
    window.preview_lock_button.click()
    window.quality_preset_combo.setCurrentIndex(window.quality_preset_combo.findData("small"))
    assert "out of date" in window.export_status_label.text()
    with patch.object(controller, "generate_gif_preview") as generate:
        window.preview_lock_button.click()
        generate.assert_called_once()
    window.preview_lock_button.click()
    window.export_format_combo.setCurrentText("GIF")
    with patch.object(controller, "generate_gif_preview") as generate:
        window.preview_lock_button.click()
        generate.assert_called_once()
    window.close()
    app.processEvents()


def test_missing_webp_encoder_provides_setup_guidance() -> None:
    message = format_ffmpeg_error("Unknown encoder 'libwebp_anim'\nEncoder not found")
    assert "GIFMAKER_FFMPEG" in message
    assert "Documentation" in message
    assert format_ffmpeg_error("invalid crop") == "invalid crop"
