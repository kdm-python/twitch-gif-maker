"""Check timing against real constant- and variable-rate source videos."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication

from gifmaker.services.gif_export import build_gif_command, build_webp_command
from gifmaker.video.probe import probe_video
from tests.test_preview_formats import webp_ffmpeg


@pytest.fixture(scope="module")
def ffmpeg():
    executable = webp_ffmpeg()
    if not executable or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg with libwebp_anim and ffprobe required")
    return executable


@pytest.mark.parametrize("rate", ["24", "25", "30000/1001", "60", "vfr"])
@pytest.mark.parametrize("kind", ["gif", "webp"])
def test_render_duration_and_cadence_for_source_rates(
    tmp_path, monkeypatch, ffmpeg, rate, kind
):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source.mp4"
    input_rate = "30" if rate == "vfr" else rate
    command = [
        ffmpeg,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=128x72:rate={input_rate}:duration=3",
    ]
    if rate == "vfr":
        command += ["-vf", "select='not(mod(n,3))+not(mod(n,5))'", "-fps_mode", "vfr"]
    command += ["-c:v", "mpeg4", "-q:v", "2", str(source)]
    subprocess.run(command, check=True, capture_output=True)
    info = probe_video(source)
    assert info.fps > 0
    if rate == "vfr":
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame=best_effort_timestamp_time",
                "-of",
                "json",
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        timestamps = [
            float(frame["best_effort_timestamp_time"])
            for frame in json.loads(result.stdout)["frames"]
        ]
        assert len({round(b - a, 3) for a, b in zip(timestamps, timestamps[1:])}) > 1
    if rate != "vfr":
        expected_rate = 30000 / 1001 if rate == "30000/1001" else float(rate)
        assert info.fps == pytest.approx(expected_rate, rel=0.002)
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    target = tmp_path / f"output.{kind}"
    builder = build_gif_command if kind == "gif" else build_webp_command
    subprocess.run(
        builder(
            source,
            target,
            start_seconds=0.5,
            end_seconds=2.5,
            fps=30,
            width=128,
            height=72,
        ),
        check=True,
        capture_output=True,
    )
    reader = QImageReader(str(target))
    durations = []
    images = []
    for _ in range(reader.imageCount()):
        image = reader.read()
        assert not image.isNull()
        durations.append(reader.nextImageDelay())
        images.append(bytes(image.constBits()))
    assert len(images) >= 20
    assert len(set(images)) >= 15
    assert sum(durations) == pytest.approx(2000, abs=100)
    assert app is not None


@pytest.mark.parametrize("speed", [0.5, 1.0, 2.0])
@pytest.mark.parametrize("kind", ["gif", "webp"])
def test_render_speed_preserves_requested_duration(
    tmp_path, monkeypatch, ffmpeg, speed, kind
):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=30:duration=3",
            "-c:v",
            "mpeg4",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    target = tmp_path / f"output.{kind}"
    builder = build_gif_command if kind == "gif" else build_webp_command
    subprocess.run(
        builder(
            source,
            target,
            start_seconds=0.5,
            end_seconds=2.5,
            fps=30,
            width=128,
            height=72,
            playback_speed=speed,
        ),
        check=True,
        capture_output=True,
    )
    reader = QImageReader(str(target))
    delays = []
    for _ in range(reader.imageCount()):
        assert not reader.read().isNull()
        delays.append(reader.nextImageDelay())
    assert sum(delays) == pytest.approx(2000 / speed, abs=100)
    assert app is not None


@pytest.mark.parametrize("kind", ["gif", "webp"])
def test_selection_respects_start_and_end_boundaries(
    tmp_path, monkeypatch, ffmpeg, kind
):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "colours.mp4"
    command = [ffmpeg, "-v", "error", "-y"]
    for colour in ("red", "green", "blue"):
        command += ["-f", "lavfi", "-i", f"color={colour}:s=64x64:r=30:d=1"]
    command += [
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "mpeg4",
        str(source),
    ]
    subprocess.run(command, check=True, capture_output=True)
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    target = tmp_path / f"selection.{kind}"
    builder = build_gif_command if kind == "gif" else build_webp_command
    subprocess.run(
        builder(
            source,
            target,
            start_seconds=1.1,
            end_seconds=1.9,
            fps=30,
            width=64,
            height=64,
        ),
        check=True,
        capture_output=True,
    )
    reader = QImageReader(str(target))
    for _ in range(reader.imageCount()):
        image = reader.read()
        assert not image.isNull()
        pixel = image.pixelColor(32, 32)
        assert pixel.green() > pixel.red() + 40
        assert pixel.green() > pixel.blue() + 40
    assert app is not None


@pytest.mark.parametrize("fps", [24, 30, 40, 60])
def test_webp_output_rate_does_not_change_duration(tmp_path, monkeypatch, ffmpeg, fps):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=30:duration=2",
            "-c:v",
            "mpeg4",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("GIFMAKER_FFMPEG", ffmpeg)
    output = tmp_path / "output.webp"
    subprocess.run(
        build_webp_command(
            source,
            output,
            start_seconds=0,
            end_seconds=2,
            fps=fps,
            width=128,
            height=72,
        ),
        check=True,
        capture_output=True,
    )
    reader = QImageReader(str(output))
    delays = []
    frames = []
    for _ in range(reader.imageCount()):
        image = reader.read()
        assert not image.isNull()
        frames.append(bytes(image.constBits()))
        delays.append(reader.nextImageDelay())
    assert sum(delays) == pytest.approx(2000, abs=70)
    assert len(set(frames)) <= 61
    assert len(set(frames)) >= 35
    assert app is not None
