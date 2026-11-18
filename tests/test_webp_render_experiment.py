"""Real-encode experiments for a possible WebP input render bridge."""
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes.util import find_library
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QImageReader
from PySide6.QtWidgets import QApplication

from gifmaker.sources import load_source
from gifmaker.sources.animation_player import AnimationSourcePlayer
from scripts.webp_reference_decoder import load_reference_webp
from scripts.webp_render_experiment import (
    RenderCancelled,
    build_experiment_command,
    ensure_animated,
    prepare_sampled_frames,
    run_cancellable,
)
from tests.test_preview_formats import webp_ffmpeg

FIXTURES = Path(__file__).parent / "fixtures"


def test_encoder_errors_and_cancellation_are_reported():
    cancel = threading.Event()
    with pytest.raises(FileNotFoundError):
        run_cancellable(["missing-gifmaker-ffmpeg-executable"], cancel)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_cancellable([sys.executable, "-c", "import sys; sys.stderr.write('failure'); sys.exit(7)"], cancel)
    assert failure.value.returncode == 7
    assert b"failure" in failure.value.stderr
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(RenderCancelled):
            run_cancellable([sys.executable, "-c", "import time; time.sleep(30)"], cancel)
    finally:
        timer.cancel()
        timer.join()
    assert time.monotonic() - started < 5


def test_cancelled_render_context_removes_intermediates(tmp_path):
    cancel = threading.Event()
    cancel.set()
    temp_path = None
    with pytest.raises(RenderCancelled), tempfile.TemporaryDirectory(dir=tmp_path) as temp:
        temp_path = Path(temp)
        (temp_path / "partial.webp").write_bytes(b"partial")
        run_cancellable([sys.executable, "-c", "pass"], cancel)
    assert temp_path is not None and not temp_path.exists()


@pytest.fixture(scope="module")
def ffmpeg():
    result = webp_ffmpeg()
    if not result:
        pytest.skip("FFmpeg with libwebp_anim is required")
    return result


def read_frames(path):
    reader = QImageReader(str(path))
    result = []
    elapsed = 0
    while True:
        frame = reader.read()
        if frame.isNull():
            break
        delay = reader.nextImageDelay()
        assert delay > 0
        result.append((elapsed, delay, frame))
        elapsed += delay
    assert result
    return result, elapsed


def frame_at(frames, timestamp):
    return next(frame for start, delay, frame in frames if start <= timestamp < start + delay)


def render(source, tmp_path, ffmpeg, *, start, end, fps=20, speed=1.0,
           crop=None, width=16, height=16, lossless=True):
    sequence = tmp_path / "sequence"
    count = prepare_sampled_frames(source, sequence, start_ms=start, end_ms=end, fps=fps, speed=speed)
    destination = tmp_path / "render.webp"
    command = build_experiment_command(ffmpeg, sequence, destination, fps=fps, width=width,
                                       height=height, frame_count=count, crop=crop, lossless=lossless)
    subprocess.run(command, check=True, capture_output=True, text=True)
    ensure_animated(destination, duration_ms=round(count * 1000 / fps))
    return read_frames(destination), count


@pytest.mark.parametrize(("start", "end", "speed", "fps", "expected"), [
    (0, 750, 1.0, 20, [(0, "#ff0000"), (100, "#00ff00"), (350, "#0000ff"), (700, "#0000ff")]),
    (100, 750, 1.0, 20, [(0, "#00ff00"), (250, "#0000ff"), (600, "#0000ff")]),
    (50, 500, 1.0, 20, [(0, "#ff0000"), (50, "#00ff00"), (300, "#0000ff"), (400, "#0000ff")]),
    (0, 750, 2.0, 20, [(0, "#ff0000"), (50, "#00ff00"), (200, "#0000ff"), (350, "#0000ff")]),
    (0, 750, 1.0, 10, [(0, "#ff0000"), (100, "#00ff00"), (400, "#0000ff"), (700, "#0000ff")]),
])
def test_timing_trim_speed_and_fps(tmp_path, ffmpeg, start, end, speed, fps, expected):
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        (frames, duration), count = render(source, tmp_path, ffmpeg, start=start, end=end, fps=fps, speed=speed)
        assert duration == pytest.approx(count * 1000 / fps, abs=2)
        assert abs(duration - (end - start) / speed) <= 1000 / fps + 2
        for time, color in expected:
            assert frame_at(frames, time).pixelColor(0, 0).name() == color


def test_single_unchanging_frame_keeps_animation_duration(tmp_path, ffmpeg):
    if not shutil.which("webpmux"):
        pytest.skip("webpmux is required to repair a still animation")
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        (frames, duration), _ = render(source, tmp_path, ffmpeg, start=350, end=750)
        assert duration == 400
        assert frame_at(frames, 350).pixelColor(0, 0).name() == "#0000ff"


@pytest.mark.parametrize(("fps", "length"), [(60, 1), (30, 34), (20, 400)])
def test_unchanging_transparent_frames_keep_short_duration_and_alpha(tmp_path, ffmpeg, fps, length):
    if not shutil.which("webpmux"):
        pytest.skip("webpmux is required to repair a still animation")
    with load_source(FIXTURES / "webp_input/transparent.webp") as source:
        (frames, duration), count = render(source, tmp_path, ffmpeg, start=350, end=350 + length,
                                           fps=fps)
        assert duration == round(count * 1000 / fps)
        for _, _, image in frames:
            assert image.pixelColor(0, 0).alpha() == 0
            assert image.pixelColor(9, 5).alpha() == 255


@pytest.mark.parametrize("lossless", [True, False])
def test_crop_and_transparency(tmp_path, ffmpeg, lossless):
    with load_source(FIXTURES / "webp_input/transparent.webp") as source:
        (frames, duration), _ = render(source, tmp_path, ffmpeg, start=0, end=750,
                                       crop=(4, 4, 8, 8), width=8, height=8, lossless=lossless)
        assert duration == 750
        for time, x, expected in [(0, 1, 0), (100, 1, 255), (350, 5, 255)]:
            frame = frame_at(frames, time)
            assert (frame.width(), frame.height()) == (8, 8)
            assert frame.pixelColor(x, 1).alpha() == expected


def test_mux_can_restore_single_frame_animation_duration(tmp_path, ffmpeg):
    mux = shutil.which("webpmux")
    if not mux:
        pytest.skip("webpmux is needed for this optional mux experiment")
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        sequence = tmp_path / "sequence"
        count = prepare_sampled_frames(source, sequence, start_ms=350, end_ms=750, fps=20, speed=1)
        still = tmp_path / "still.webp"
        cmd = build_experiment_command(ffmpeg, sequence, still, fps=20, width=16, height=16, frame_count=count)
        subprocess.run(cmd, check=True, capture_output=True)
        animated = tmp_path / "animated.webp"
        subprocess.run([mux, "-frame", str(still), "+200+0+0+1-b", "-frame", str(still),
                        "+200+0+0+1-b", "-loop", "0", "-o", str(animated)],
                       check=True, capture_output=True)
        frames, duration = read_frames(animated)
        assert duration == 400
        assert frame_at(frames, 350).pixelColor(0, 0).name() == "#0000ff"


@pytest.mark.parametrize("fps", [12, 15, 24, 30, 60])
@pytest.mark.parametrize("speed", [0.25, 1.0, 3.0])
def test_supported_rates_keep_expected_duration(tmp_path, ffmpeg, fps, speed):
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        (frames, duration), count = render(source, tmp_path, ffmpeg, start=0, end=750,
                                           fps=fps, speed=speed)
        assert duration == pytest.approx(count * 1000 / fps, abs=3)
        assert abs(duration - 750 / speed) <= 1000 / fps + 3
        assert frame_at(frames, 0).pixelColor(0, 0).name() == "#ff0000"


def test_missing_mux_fails_without_overwriting_still(tmp_path, ffmpeg):
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        sequence = tmp_path / "sequence"
        count = prepare_sampled_frames(source, sequence, start_ms=350, end_ms=750, fps=20, speed=1)
        destination = tmp_path / "still.webp"
        subprocess.run(build_experiment_command(ffmpeg, sequence, destination, fps=20, width=16,
                                               height=16, frame_count=count), check=True)
        before = destination.read_bytes()
        with pytest.raises(FileNotFoundError, match="webpmux"):
            ensure_animated(destination, duration_ms=400, mux="missing-gifmaker-webpmux")
        assert destination.read_bytes() == before
        false_tool = shutil.which("false")
        if false_tool:
            with pytest.raises(subprocess.CalledProcessError):
                ensure_animated(destination, duration_ms=400, mux=false_tool)
            assert destination.read_bytes() == before


def test_invalid_encoder_reports_ffmpeg_failure(tmp_path, ffmpeg):
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        sequence = tmp_path / "sequence"
        count = prepare_sampled_frames(source, sequence, start_ms=0, end_ms=750, fps=20, speed=1)
        command = build_experiment_command(ffmpeg, sequence, tmp_path / "bad.webp",
                                           fps=20, width=16, height=16, frame_count=count)
        command[command.index("libwebp_anim")] = "missing_gifmaker_encoder"
        with pytest.raises(subprocess.CalledProcessError) as exc:
            run_cancellable(command, threading.Event())
        assert b"missing_gifmaker_encoder" in exc.value.stderr


def test_player_and_render_use_same_source_frames(tmp_path, ffmpeg):
    app = QApplication.instance() or QApplication([])
    with load_source(FIXTURES / "webp_input/variable_delays.webp") as source:
        (frames, _), _ = render(source, tmp_path, ffmpeg, start=50, end=500)
        player = AnimationSourcePlayer()
        shown = []
        player.frameChanged.connect(lambda image: shown.append(image.pixelColor(0, 0).name()))
        player.set_source(source)
        for output_time in (0, 50, 100, 300, 400):
            player.seek(output_time + 50)
            assert shown[-1] == frame_at(frames, output_time).pixelColor(0, 0).name()
        player.clear()
    app.processEvents()


@pytest.fixture
def partial_source(tmp_path):
    cwebp, mux = shutil.which("cwebp"), shutil.which("webpmux")
    if not cwebp or not mux:
        pytest.skip("cwebp and webpmux are required for partial-frame fixture")
    bitstreams = []
    for index, color in enumerate((QColor(255, 0, 0), QColor(0, 0, 255), QColor(0, 255, 0, 128))):
        size = 16 if index == 0 else 4
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(color)
        png, webp = tmp_path / f"p{index}.png", tmp_path / f"p{index}.webp"
        assert image.save(str(png), "PNG")
        subprocess.run([cwebp, "-quiet", "-lossless", "-exact", str(png), "-o", str(webp)], check=True)
        bitstreams.append(webp)
    source_path = tmp_path / "partial.webp"
    subprocess.run([mux, "-frame", str(bitstreams[0]), "+100+0+0+0-b",
                    "-frame", str(bitstreams[1]), "+150+4+4+1+b",
                    "-frame", str(bitstreams[2]), "+200+4+4+0+b",
                    "-loop", "0", "-bgcolor", "0,0,0,0", "-o", str(source_path)],
                   check=True, capture_output=True)
    return source_path


@pytest.mark.skipif(not find_library("webpdemux"), reason="libwebpdemux is unavailable")
def test_partial_frame_blend_dispose_and_alpha(tmp_path, ffmpeg, partial_source):
    with load_reference_webp(partial_source) as source:
        first = QImage(str(source.frames[0].path))
        second = QImage(str(source.frames[1].path))
        third = QImage(str(source.frames[2].path))
        assert first.pixelColor(5, 5).name() == "#ff0000"
        assert second.pixelColor(5, 5).name() == "#0000ff"
        assert second.pixelColor(1, 1).name() == "#ff0000"
        assert third.pixelColor(5, 5).alpha() == 128
        assert third.pixelColor(1, 1).name() == "#ff0000"
        (frames, duration), _ = render(source, tmp_path, ffmpeg, start=0, end=450)
        assert duration == 450
        for time, reference in ((0, first), (100, second), (250, third)):
            actual = frame_at(frames, time)
            for x, y in ((1, 1), (4, 4), (7, 7), (8, 8)):
                assert actual.pixelColor(x, y).getRgb() == reference.pixelColor(x, y).getRgb()


def test_source_decodes_partial_frame_disposal(partial_source):
    with load_source(partial_source) as source:
        assert QImage(str(source.frames[2].path)).pixelColor(5, 5).alpha() == 128


@pytest.mark.parametrize("backend", ["qt", "libwebp"])
def test_luddy_trim_real_encode(tmp_path, ffmpeg, backend):
    path = FIXTURES / "luddy.webp"
    if not path.is_file():
        pytest.skip("Optional real-world luddy.webp is not present")
    if backend == "libwebp" and not find_library("webpdemux"):
        pytest.skip("libwebpdemux is unavailable")
    loader = load_source if backend == "qt" else load_reference_webp
    with loader(path) as source:
        (frames, duration), count = render(source, tmp_path, ffmpeg, start=1000, end=2000,
                                           fps=30, width=200, height=216, lossless=False)
        assert count == 30
        assert duration == pytest.approx(1000, abs=35)
        assert (frames[0][2].width(), frames[0][2].height()) == (200, 216)
        assert len(frames) > 1
        for offset in (0, 500, 950):
            expected = QImageReader(str(source.frame_at(1000 + offset).path)).read().scaled(200, 216)
            actual = frame_at(frames, offset)
            diffs = []
            for y in range(5, 216, 15):
                for x in range(5, 200, 15):
                    a, b = expected.pixelColor(x, y), actual.pixelColor(x, y)
                    diffs.extend(abs(x - y) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3], strict=True))
            assert sum(diffs) / len(diffs) < 25


@pytest.mark.skipif(not find_library("webpdemux"), reason="libwebpdemux is unavailable")
def test_luddy_qt_and_libwebp_decoders_agree_at_sampled_times():
    path = FIXTURES / "luddy.webp"
    if not path.is_file():
        pytest.skip("Optional real-world luddy.webp is not present")
    qt_frames, duration = read_frames(path)
    with load_reference_webp(path) as reference:
        assert duration == round(reference.info.duration_seconds * 1000)
        for time_ms in (0, 1000, 2500, 5000):
            qt_image = frame_at(qt_frames, time_ms)
            ref_image = QImage(str(reference.frame_at(time_ms).path))
            assert qt_image == ref_image
