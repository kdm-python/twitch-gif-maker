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
from gifmaker.services.gif_export import build_gif_command, build_webp_command, format_ffmpeg_error


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
    assert "Preview " in window.output_summary_label.text()
    assert f"{preview.stat().st_size:,} bytes" in window.output_summary_label.toolTip()
    window.pause_gif_preview()
    paused_frame = window._preview_frame_index
    QTest.qWait(100)
    assert window._preview_frame_index == paused_frame
    window.play_gif_preview()
    QTest.qWait(100)
    assert window._preview_frame_index != paused_frame
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


@pytest.mark.parametrize("output_format", ["WebP", "GIF"])
def test_stale_locked_preview_exports_current_settings(tmp_path, monkeypatch, output_format):
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
    window.render_controller.generate_gif_preview()
    deadline = time.monotonic() + 30
    while window.render_controller._preview_job is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert window._last_preview_spec is not None, window.export_status_label.text()
    preview = window._preview_temp_file
    window.preview_lock_button.click()
    window.export_width_input.setValue(120)
    assert "Estimated ~" in window.output_summary_label.text()
    destination = tmp_path / ("output.webp" if output_format == "WebP" else "output.gif")
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName",
               return_value=(str(destination), "")):
        window.render_controller.export_gif_from_selection()
    deadline = time.monotonic() + 30
    while window.render_controller._export_job is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert destination.exists(), window.export_status_label.text()
    assert destination.read_bytes() != preview.read_bytes()
    from PySide6.QtGui import QImageReader
    assert QImageReader(str(destination)).size().width() == 120
    assert window.preview_lock_button.isChecked()
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


def test_summary_only_measures_an_existing_matching_preview(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_video_path = str(tmp_path / "input.mp4")
    window.clip_start_time, window.clip_end_time = 0.0, 1.0
    controller = window.render_controller
    preview = tmp_path / "preview.webp"
    preview.write_bytes(b"x" * 2048)
    window._preview_temp_file = preview
    window._last_preview_spec = controller._resolve_render_spec()
    controller.update_output_summary()
    assert "Preview 2.0 KB" in window.output_summary_label.text()
    assert "2,048 bytes" in window.output_summary_label.toolTip()
    window.preview_lock_button.click()
    original_width = window.export_width_input.value()
    window.export_width_input.setValue(original_width + 10)
    assert "Estimated ~" in window.output_summary_label.text()
    window.export_width_input.setValue(original_width)
    assert "Preview 2.0 KB" in window.output_summary_label.text()
    preview.unlink()
    controller.update_output_summary()
    assert "Estimated ~" in window.output_summary_label.text()
    window.close()
    app.processEvents()


def test_webp_quality_presets_produce_distinct_real_encodes(tmp_path, monkeypatch):
    ffmpeg = webp_ffmpeg()
    if ffmpeg is None:
        pytest.skip("FFmpeg with libwebp_anim is required")
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    source = Path(__file__).parent / "fixtures" / "small_floor_landscape.mp4"
    sizes = []
    for preset in ("small", "balanced", "high"):
        output = tmp_path / f"{preset}.webp"
        subprocess.run(build_webp_command(source, output, start_seconds=1, end_seconds=2,
                                          fps=24, width=320, height=180,
                                          quality_preset=preset),
                       check=True, capture_output=True)
        sizes.append(output.stat().st_size)
    assert sizes[0] < sizes[1] < sizes[2]


@pytest.mark.parametrize("kind", ["gif", "webp"])
def test_real_sharpness_and_crop_change_decoded_image(tmp_path, monkeypatch, kind):
    from PySide6.QtGui import QImageReader

    ffmpeg = webp_ffmpeg()
    if ffmpeg is None:
        pytest.skip("FFmpeg with libwebp_anim is required")
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    app = QApplication.instance() or QApplication([])
    source = Path(__file__).parent / "fixtures" / "small_floor_landscape.mp4"
    frames = []
    for name, sharpness, crop in (("off", "off", None),
                                   ("sharp", "strong", None),
                                   ("crop", "off", (100, 100, 800, 450))):
        output = tmp_path / f"{name}.{kind}"
        builder = build_webp_command if kind == "webp" else build_gif_command
        subprocess.run(builder(source, output, start_seconds=1, end_seconds=2,
                                          fps=24, width=160, height=90,
                                          quality_preset="balanced",
                                          sharpness_preset=sharpness, crop=crop),
                       check=True, capture_output=True)
        image = QImageReader(str(output)).read()
        assert not image.isNull()
        assert (image.width(), image.height()) == (160, 90)
        frames.append(bytes(image.constBits()))
    assert len(set(frames)) == 3
    assert app is not None
