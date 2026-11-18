"""End-to-end WebP source previews and exports."""
import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gifmaker.gui.main_window import MainWindow
from gifmaker.sources import load_source
from tests.test_preview_formats import webp_ffmpeg
from tests.test_webp_render_experiment import frame_at, read_frames
from tests.test_webp_session import FIXTURE, wait_for

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def finish_job(controller, name):
    deadline = time.monotonic() + 30
    while getattr(controller, name) is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert getattr(controller, name) is None


@pytest.fixture
def window(monkeypatch):
    ffmpeg = webp_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg with libwebp_anim is required")
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    app = QApplication.instance() or QApplication([])
    instance = MainWindow()
    instance.open_video_path(str(FIXTURE))
    wait_for(app, lambda: instance.video_session_controller._animation_source is not None)
    instance.export_width_input.setValue(16)
    instance.export_height_input.setValue(16)
    instance.output_fps_combo.setCurrentIndex(instance.output_fps_combo.findData(30))
    yield instance
    instance.close()
    app.processEvents()


def test_preview_export_and_source_protection(window, tmp_path):
    controller = window.render_controller
    controller.generate_gif_preview()
    finish_job(controller, "_preview_job")
    assert window._last_preview_spec is not None, window.export_status_label.text()
    preview = window._preview_temp_file
    frames, duration = read_frames(preview)
    assert duration == pytest.approx(767, abs=2)
    for position, channel in ((0, 0), (100, 1), (400, 2), (700, 2)):
        color = frame_at(frames, position).pixelColor(0, 0).getRgb()
        assert color[channel] > 240 and all(color[i] < 15 for i in range(3) if i != channel)
    destination = tmp_path / "edited.webp"
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
        controller.export_gif_from_selection()
    assert destination.read_bytes() == preview.read_bytes()
    before = FIXTURE.read_bytes()
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(FIXTURE), "")):
        controller.export_gif_from_selection()
    assert "different from the original" in window.export_status_label.text()
    assert FIXTURE.read_bytes() == before
    alias = tmp_path / "alias.webp"
    os.link(FIXTURE, alias)
    with pytest.raises(ValueError, match="different from the original"):
        controller._check_destination(alias, window._last_preview_spec)


def test_single_frame_trim_and_uncached_export(window, tmp_path):
    if not shutil.which("webpmux"):
        pytest.skip("webpmux is required for unchanged selections")
    controller = window.render_controller
    window.seek_slider.set_selection(2, 3)
    window.output_speed_slider.setValue(200)
    destination = tmp_path / "trim.webp"
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
        controller.export_gif_from_selection()
    finish_job(controller, "_export_job")
    assert destination.exists(), window.export_status_label.text()
    frames, duration = read_frames(destination)
    assert duration == 200
    assert frame_at(frames, 150).pixelColor(0, 0).blue() > 240
    with load_source(destination) as reopened:
        assert reopened.info.duration_seconds == pytest.approx(0.2)


def test_failed_encoder_preserves_destination(window, tmp_path, monkeypatch):
    monkeypatch.setenv("GIFMAKER_FFMPEG", "/missing/gifmaker-ffmpeg")
    target = tmp_path / "existing.webp"
    target.write_bytes(b"existing")
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        window.export_gif_from_selection()
    finish_job(window.render_controller, "_export_job")
    assert target.read_bytes() == b"existing"
    assert "failed" in window.export_status_label.text().lower()


def test_missing_mux_reports_failure_without_replacing_output(window, tmp_path, monkeypatch):
    monkeypatch.setenv("GIFMAKER_WEBPMUX", "/missing/gifmaker-webpmux")
    window.seek_slider.set_selection(2, 3)
    target = tmp_path / "existing.webp"
    target.write_bytes(b"existing")
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        window.export_gif_from_selection()
    finish_job(window.render_controller, "_export_job")
    assert target.read_bytes() == b"existing"
    assert "webpmux" in window.export_status_label.text()


def test_export_continues_after_loading_another_source(window, tmp_path):
    controller = window.render_controller
    destination = tmp_path / "from-first-source.webp"
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
        controller.export_gif_from_selection()
    original = window.video_session_controller._animation_source
    second = load_source(Path(__file__).parent / "fixtures/webp_input/transparent.webp")
    window.video_session_controller._activate_animation(second)
    assert original.closed
    finish_job(controller, "_export_job")
    assert destination.exists(), window.export_status_label.text()
    frames, _ = read_frames(destination)
    assert frame_at(frames, 0).pixelColor(0, 0).red() > 240


def test_transparent_crop_and_resize(window):
    controller = window.render_controller
    source = load_source(Path(__file__).parent / "fixtures/webp_input/transparent.webp")
    window.video_session_controller._activate_animation(source)
    window._current_crop = (4, 0, 8, 8)
    window.aspect_ratio_lock.setChecked(False)
    window.export_width_input.setValue(8)
    window.export_height_input.setValue(8)
    controller.generate_gif_preview()
    finish_job(controller, "_preview_job")
    assert window._preview_temp_file is not None, window.export_status_label.text()
    frames, _ = read_frames(window._preview_temp_file)
    first = frame_at(frames, 0)
    assert (first.width(), first.height()) == (8, 8)
    assert first.pixelColor(7, 1).alpha() == 0


def test_cancel_stops_encoder_and_removes_workspace(window, tmp_path, monkeypatch):
    encoder = tmp_path / "slow-encoder"
    pid_file = tmp_path / "encoder.pid"
    encoder.write_text(
        f"#!/usr/bin/env python3\nimport os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(30)\n"
    )
    encoder.chmod(0o755)
    monkeypatch.setenv("GIFMAKER_FFMPEG", str(encoder))
    controller = window.render_controller
    controller.generate_gif_preview()
    job = controller._preview_job
    directory = Path(job.workspace.name)
    app = QApplication.instance()
    wait_for(app, pid_file.exists)
    pid = int(pid_file.read_text())
    controller._cancel_preview_job()
    assert not directory.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not job.destination.exists()


def test_luddy_render_can_be_reopened(window, tmp_path):
    fixture = Path(__file__).parent / "fixtures/luddy.webp"
    if not fixture.exists():
        pytest.skip("Optional luddy.webp is not present")
    source = load_source(fixture)
    window.video_session_controller._activate_animation(source)
    window.seek_slider.set_selection(10, 40)
    window.aspect_ratio_lock.setChecked(False)
    window.export_width_input.setValue(200)
    window.export_height_input.setValue(216)
    controller = window.render_controller
    controller.generate_gif_preview()
    finish_job(controller, "_preview_job")
    assert window._preview_temp_file is not None, window.export_status_label.text()
    destination = tmp_path / "luddy-edited.webp"
    with patch("gifmaker.controllers.render_controller.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
        controller.export_gif_from_selection()
    with load_source(destination) as reopened:
        assert (reopened.info.width, reopened.info.height) == (200, 216)
        assert len(reopened.frames) > 1
