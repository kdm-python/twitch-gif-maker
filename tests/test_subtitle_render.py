"""Real caption encoding through both supported source-render paths."""
import os
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow
from gifmaker.gui.subtitle_dialog import _prepare_snapshot
from gifmaker.models.render_settings import RenderSettings, RenderSpec
from gifmaker.models.subtitles import Caption, SubtitleDocument
from gifmaker.services.render_service import RenderService
from gifmaker.services.subtitle_compositor import compose_subtitles
from gifmaker.services.subtitle_render import prepare_job as prepare_mp4_job
from gifmaker.services.webp_render import prepare_job
from gifmaker.sources import load_source
from tests.test_preview_formats import webp_ffmpeg


def wait_for_job(app, predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate()

FIXTURE = Path(__file__).parent / "fixtures/webp_input/variable_delays.webp"


@pytest.fixture
def encoder(monkeypatch):
    binary = webp_ffmpeg()
    if not binary or not shutil.which("webpmux"):
        pytest.skip("WebP encoder and webpmux required")
    monkeypatch.setenv("GIFMAKER_FFMPEG", binary)
    return binary


def spec_for(path):
    settings = RenderSettings(.1, .75, fps=20, width=160, height=120,
                              playback_speed=2, sharpness_preset="off", quality_preset="high")
    caption = Caption(200, 500, "Hello", y=.8, size=.25, bold=True)
    return RenderSpec(str(path), "WebP", settings, SubtitleDocument((caption,)))


def test_webp_captioned_pixels_timing_clean_backing_and_alpha(encoder):
    app = QApplication.instance() or QApplication([])
    with load_source(FIXTURE) as source:
        spec = spec_for(FIXTURE)
        workspace, command = prepare_job(source, spec)
        with workspace:
            subprocess.run(command, check=True, capture_output=True, text=True)
            directory = Path(workspace.name)
            # The exact PNGs submitted to the encoder use the modal compositor.
            for index in range(7):
                clean = QImage(str(directory / "visual" / f"frame-{index:08d}.png"))
                actual = QImage(str(directory / "captioned" / f"frame-{index:08d}.png"))
                expected = compose_subtitles(clean, spec.subtitles, 100 + index * 100)
                assert actual.convertToFormat(expected.format()) == expected
            with load_source(directory / "result.webp") as output, load_source(directory / "clean.webp") as clean:
                assert output.info.duration_seconds == pytest.approx(.35, abs=.002)
                for time, caption_visible in ((0, False), (50, True), (150, True), (200, False)):
                    image = QImage(str(output.frame_at(time).path))
                    base = QImage(str(clean.frame_at(time).path))
                    has_white = any(image.pixelColor(x, y).red() > 230 and image.pixelColor(x, y).green() > 230
                                    and image.pixelColor(x, y).blue() > 230 for x in range(20, 140) for y in range(60, 100))
                    assert has_white == caption_visible
                    assert not any(base.pixelColor(x, y).name() == "#ffffff" for x in range(20, 140) for y in range(60, 100))
                aligned = _prepare_snapshot(directory / "clean.webp", TemporaryDirectory(), directory / "result.webp")
                with aligned:
                    assert [(f.start_ms, f.duration_ms) for f in aligned.frames] == [(f.start_ms, f.duration_ms) for f in output.frames]
                    assert all(frame.path.is_file() for frame in aligned.frames)
                    assert aligned.info.duration_seconds == output.info.duration_seconds
    transparent = FIXTURE.with_name("transparent.webp")
    with load_source(transparent) as source:
        workspace, command = prepare_job(source, replace(spec_for(transparent), settings=RenderSettings(0, .75, fps=20, width=80, height=80, crop=(4, 0, 8, 16), sharpness_preset="off")))
        with workspace:
            subprocess.run(command, check=True, capture_output=True, text=True)
            with load_source(Path(workspace.name) / "result.webp") as output:
                for frame in output.frames:
                    image = QImage(str(frame.path))
                    assert (image.width(), image.height()) == (80, 80)
                    assert image.pixelColor(79, 79).alpha() == 0
    app.processEvents()


def test_mp4_captions_render_to_webp_and_gif(encoder, tmp_path):
    app = QApplication.instance() or QApplication([])
    video = tmp_path / "source.mp4"
    subprocess.run([encoder, "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=160x120:r=20:d=1",
                    "-c:v", "mpeg4", str(video)], check=True)
    for format in ("WebP", "GIF"):
        spec = replace(spec_for(video), output_format=format)
        workspace, command = prepare_mp4_job(spec)
        with workspace:
            subprocess.run(command, check=True, capture_output=True, text=True)
            directory = Path(workspace.name)
            assert (directory / f"result.{format.lower()}").is_file()
            assert (directory / "clean.webp").is_file()
            frames = sorted((directory / "captioned").glob("frame-*.png"))
            assert len(frames) > 1
            assert QImage(str(frames[0])).pixelColor(0, 0).blue() > 240
            # Unchanged pixels stay blue; text only exists inside its interval.
            clean = QImage(str(directory / "visual/frame-00000000.png"))
            assert QImage(str(frames[0])).convertToFormat(clean.format()) == clean
    exported = tmp_path / "service.webp"
    RenderService().export(spec_for(video), exported)
    assert exported.is_file()
    with pytest.raises(ValueError, match="prepared job"):
        RenderService().build_command(spec_for(video), exported)
    # A hard link with an output suffix must never replace the original media.
    hard_link = tmp_path / "original-alias.webp"
    os.link(video, hard_link)
    with pytest.raises(ValueError, match="original source"):
        RenderService().export(spec_for(video), hard_link)
    app.processEvents()


def test_modal_apply_export_reopen_clear_and_failure_recovery(encoder, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        window.video_session_controller._activate_animation(load_source(FIXTURE))
        window.export_width_input.setValue(160)
        window.sharpness_combo.setCurrentIndex(window.sharpness_combo.findData("off"))
        window.generate_gif_preview()
        wait_for_job(app, lambda: window.render_controller._preview_job is None)
        assert window._last_preview_spec is not None, window.export_status_label.text()
        window.pause_gif_preview()
        window.preview_controller.seek(150)
        original_position = window.preview_controller.position_ms()
        window.preview_lock_button.setChecked(True)

        def edit(text):
            window.open_subtitles()
            dialog = window.subtitle_controller.dialog
            wait_for_job(app, lambda: dialog.ready)
            dialog._set_text(text)
            dialog.close()
            wait_for_job(app, lambda: window.render_controller._preview_job is None)

        edit("First")
        assert window._last_preview_spec.subtitles.captions[0].text == "First", window.export_status_label.text()
        assert window.preview_controller.position_ms() == original_position
        assert not window._preview_frame_timer.isActive()
        assert window.preview_lock_button.isChecked()
        clean_path = window._preview_clean_file
        assert clean_path.is_file()
        with load_source(clean_path) as source:
            clean_pixels = QImage(str(source.frame_at(original_position).path)).copy()
        with load_source(window._preview_temp_file) as encoded:
            for index, cached in enumerate(window._preview_frame_cache):
                time_ms = sum(window._preview_frame_durations[:index])
                image = QImage(str(encoded.frame_at(time_ms).path))
                assert cached.toImage().convertToFormat(image.format()) == image
        window.open_subtitles()
        dialog = window.subtitle_controller.dialog
        wait_for_job(app, lambda: dialog.ready)
        assert dialog.surface.image == clean_pixels
        assert dialog.document.captions[0].text == "First"
        dialog._set_text("Second")
        dialog.close()
        wait_for_job(app, lambda: window.render_controller._preview_job is None)
        assert window._last_preview_spec.subtitles.captions[0].text == "Second"
        assert not clean_path.exists()

        destination = tmp_path / "captions.webp"
        recipe = window.render_controller._resolve_render_spec()
        assert window.render_controller._preview_matches(recipe)
        with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(destination), "")), \
                patch.object(window.render_controller, "_export_source") as render:
            window.export_gif_from_selection()
            render.assert_not_called()
        assert destination.read_bytes() == window._preview_temp_file.read_bytes()

        # A worker failure retains both the last good result and clean backing.
        previous = window._preview_temp_file
        previous_spec = window._last_preview_spec
        monkeypatch.setenv("GIFMAKER_FFMPEG", "missing-subtitle-encoder")
        edit("Retry me")
        assert window._preview_temp_file == previous and previous.exists()
        assert window._last_preview_spec == previous_spec
        assert window._preview_clean_file.is_file()
        assert "failed" in window.export_status_label.text().lower()
        monkeypatch.setenv("GIFMAKER_FFMPEG", encoder)
        window.generate_gif_preview()
        wait_for_job(app, lambda: window.render_controller._preview_job is None)
        assert window._last_preview_spec.subtitles.captions[0].text == "Retry me"

        # Export a changed recipe instead of copying a now-stale preview.
        settings = replace(window._last_preview_spec.settings.shared, playback_speed=2.)
        fresh = replace(window._last_preview_spec, settings=RenderSettings(
            settings.start_seconds, settings.end_seconds, fps=24, width=160, height=160,
            playback_speed=2., sharpness_preset="off"))
        new_export = tmp_path / "retimed.WEBP"
        window.render_controller._export_source(new_export, fresh)
        wait_for_job(app, lambda: window.render_controller._export_job is None)
        with load_source(new_export) as output:
            assert output.info.duration_seconds == pytest.approx(.375, abs=.045)
        edit("")
        assert not window._last_preview_spec.subtitles.captions
        assert window._preview_clean_file is None
    finally:
        window.close()
        app.processEvents()
