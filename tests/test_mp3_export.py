"""Exercise MP3 rendering, preview reuse, audio controls and source restrictions."""
import json
import os
import shutil
import subprocess
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow
from gifmaker.models.render_settings import AudioSettings, RenderSettings, RenderSpec
from gifmaker.services.audio_export import build_mp3_command
from gifmaker.services.gif_export import GifExportError, format_ffmpeg_error
from gifmaker.services.render_service import RenderService


@pytest.mark.parametrize("speed", [0.25, 1.0, 3.0])
def test_mp3_real_render_and_preview(tmp_path, speed):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "tone.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=16x16:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest", str(source)], check=True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.current_video_path = str(source)
        window.clip_start_time, window.clip_end_time = 0.5, 1.5
        window.export_format_combo.setCurrentText("MP3")
        window.output_speed_slider.setValue(round(speed * 100))
        window.export_controls_panel.audio_volume.setValue(80)
        window.export_controls_panel.audio_fade.setChecked(True)
        spec = window.render_controller._resolve_render_spec()
        assert not spec.subtitles.captions
        assert spec.settings.format_settings == AudioSettings(80, True)
        window.generate_gif_preview()
        deadline = time.monotonic() + 15
        while window.render_controller._preview_job is not None and time.monotonic() < deadline:
            QTest.qWait(20)
        assert window._last_preview_spec == spec, window.export_status_label.text()
        preview = window._preview_temp_file
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(preview)], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        assert [s["codec_name"] for s in info["streams"]] == ["mp3"]
        assert float(info["format"]["duration"]) == pytest.approx(1 / speed, abs=0.1)
        player = window.preview_controller.player
        assert player.media.playbackRate() == pytest.approx(1)
        assert not window.gif_preview_label.pixmap().isNull()
        assert "frames" not in window.output_summary_label.text()
        output = tmp_path / "saved.mp3"
        window.render_controller._copy_preview(output)
        assert output.read_bytes() == preview.read_bytes()
        window.preview_controller.pause()
        window.preview_controller.play()
        window.export_format_combo.setCurrentText("WebP")
        assert not window.export_controls_panel.audio_volume.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_audio_controls_and_format_restrictions():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.export_format_combo.setCurrentText("MP3")
        panel = window.export_controls_panel
        assert not panel.audio_volume.isHidden()
        assert panel.output_fps_combo.isHidden()
        assert panel.export_width_input.isHidden()
        window.video_session_controller._set_animation_format(True)
        index = window.export_format_combo.findText("MP3")
        assert window.export_format_combo.currentText() == "WebP"
        assert not window.export_format_combo.model().item(index).isEnabled()
        window.video_session_controller._set_animation_format(False)
        assert window.export_format_combo.currentText() == "MP3"
        assert window.export_format_combo.model().item(index).isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_audio_validation_and_missing_audio(tmp_path):
    source = tmp_path / "silent.mp4"
    source.touch()
    spec = RenderSpec(str(source), "MP3", RenderSettings(0, 1, format_settings=AudioSettings()))
    with pytest.raises(GifExportError):
        build_mp3_command(spec, source)
    assert "no audio track" in format_ffmpeg_error("Stream map '0:a:0' matches no streams")
    if not shutil.which("ffmpeg"):
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=16x16:d=1", str(source)], check=True)
    with pytest.raises(GifExportError):
        RenderService().export(spec, tmp_path / "out.mp3")
