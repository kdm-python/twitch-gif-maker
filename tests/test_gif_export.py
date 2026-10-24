"""Tests for the FFmpeg GIF export service."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from gifmaker.services.gif_export import (
    GifExportError,
    build_gif_command,
    build_webp_command,
    export_gif,
    export_webp,
)


def test_export_gif_builds_ffmpeg_command(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_gif(
            input_video,
            output_gif,
            start_seconds=1.5,
            end_seconds=3.0,
            fps=24,
            width=640,
        )

    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd[1] == "-y"
    assert cmd[0].endswith("ffmpeg")
    assert "-ss" in cmd
    assert "-to" in cmd
    assert str(input_video) in cmd
    assert str(output_gif) == cmd[-1]
    filter_graph = cmd[cmd.index("-filter_complex") + 1]
    assert "fps=24,scale=640:-1:flags=lanczos" in filter_graph
    assert "palettegen=max_colors=256" in filter_graph
    assert "format=rgb24,split" in filter_graph
    assert "stats_mode=single:reserve_transparent=0" in filter_graph
    assert "paletteuse=dither=sierra2_4a:new=1" in filter_graph


def test_export_gif_uses_timestamp_adjustment_for_playback_speed(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_gif(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=24,
            playback_speed=2.0,
            width=320,
        )

    cmd = run_mock.call_args.args[0]
    filter_graph = cmd[cmd.index("-filter_complex") + 1]
    assert "setpts=PTS/2" in filter_graph
    assert "fps=24" in filter_graph


def test_export_gif_raises_for_invalid_time_range(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    try:
        export_gif(
            input_video,
            output_gif,
            start_seconds=5.0,
            end_seconds=5.0,
            fps=24,
            width=640,
        )
    except GifExportError as exc:
        assert str(exc) == "End time must be greater than start time"
    else:
        assert False, "Expected GifExportError for invalid time range"


def test_export_gif_raises_when_ffmpeg_fails(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 1
        run_mock.return_value.stderr = "ffmpeg failure"

        try:
            export_gif(
                input_video,
                output_gif,
                start_seconds=0.0,
                end_seconds=2.0,
                fps=12,
                width=320,
            )
        except GifExportError as exc:
            assert str(exc) == "ffmpeg export failed: ffmpeg failure"
        else:
            assert False, "Expected GifExportError when ffmpeg fails"


def test_export_gif_with_crop_prepends_crop_filter(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_gif(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
            crop=(10, 20, 200, 200),
        )

    cmd = run_mock.call_args.args[0]
    filter_graph = cmd[cmd.index("-filter_complex") + 1]
    assert filter_graph.startswith("[0:v]crop=200:200:10:20:exact=1,")
    assert ",fps=12," in filter_graph


def test_export_gif_without_crop_omits_crop_filter(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_gif(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
        )

    cmd = run_mock.call_args.args[0]
    filter_graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:v]fps=12,scale=320:-1:flags=lanczos," in filter_graph
    assert "crop=" not in filter_graph


def test_export_gif_quality_preset_changes_palette_settings(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        export_gif(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
            height=180,
            quality_preset="small",
        )

    filter_graph = run_mock.call_args.args[0][
        run_mock.call_args.args[0].index("-filter_complex") + 1
    ]
    assert "scale=320:180:flags=lanczos" in filter_graph
    assert "palettegen=max_colors=128" in filter_graph
    assert "paletteuse=dither=bayer:bayer_scale=3" in filter_graph


def test_export_gif_applies_selected_luma_sharpening(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        export_gif(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=24,
            width=320,
            sharpness_preset="strong",
        )

    filter_graph = run_mock.call_args.args[0][
        run_mock.call_args.args[0].index("-filter_complex") + 1
    ]
    assert "scale=320:-1:flags=lanczos,unsharp=5:5:0.8" in filter_graph


def test_export_gif_raises_for_invalid_crop(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    try:
        export_gif(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
            crop=(0, 0, -1, 100),
        )
    except GifExportError as exc:
        assert "Crop" in str(exc)
    else:
        assert False, "Expected GifExportError for invalid crop dimensions"


# ---------------------------------------------------------------------------
# export_webp tests
# ---------------------------------------------------------------------------


def test_export_webp_builds_ffmpeg_command(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_webp(
            input_video,
            output_webp,
            start_seconds=1.5,
            end_seconds=3.0,
            fps=24,
            width=640,
        )

    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd[1] == "-y"
    assert cmd[0].endswith("ffmpeg")
    assert "-ss" in cmd
    assert "-to" in cmd
    assert str(input_video) in cmd
    assert str(output_webp) == cmd[-1]
    assert "fps=24,scale=640:-1:flags=lanczos" in cmd
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libwebp_anim"
    assert "-loop" in cmd
    assert cmd[cmd.index("-loop") + 1] == "0"
    assert "-an" in cmd


@pytest.mark.parametrize(
    ("preset", "quality"),
    [("small", "50"), ("balanced", "90"), ("high", "100")],
)
def test_webp_quality_presets_preserve_default_detail(
    tmp_path: Path, preset: str, quality: str
) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake video")

    command = build_webp_command(
        source, tmp_path / "output.webp", start_seconds=0, end_seconds=1,
        fps=24, width=640, quality_preset=preset,
    )

    assert command[command.index("-quality") + 1] == quality


def test_export_webp_uses_timestamp_adjustment_for_playback_speed(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        export_webp(
            input_video,
            output_webp,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=30,
            playback_speed=0.5,
            width=320,
        )

    cmd = run_mock.call_args.args[0]
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert "setpts=PTS/0.5" in vf_arg
    assert "fps=30" in vf_arg


def test_export_webp_raises_for_wrong_extension(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_gif = tmp_path / "output.gif"

    try:
        export_webp(
            input_video,
            output_gif,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
        )
    except GifExportError as exc:
        assert ".webp" in str(exc)
    else:
        assert False, "Expected GifExportError for wrong output extension"


def test_export_webp_raises_for_invalid_time_range(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    try:
        export_webp(
            input_video,
            output_webp,
            start_seconds=5.0,
            end_seconds=5.0,
            fps=24,
            width=640,
        )
    except GifExportError as exc:
        assert str(exc) == "End time must be greater than start time"
    else:
        assert False, "Expected GifExportError for invalid time range"


def test_export_webp_raises_when_ffmpeg_fails(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 1
        run_mock.return_value.stderr = "ffmpeg failure"

        try:
            export_webp(
                input_video,
                output_webp,
                start_seconds=0.0,
                end_seconds=2.0,
                fps=12,
                width=320,
            )
        except GifExportError as exc:
            assert str(exc) == "ffmpeg export failed: ffmpeg failure"
        else:
            assert False, "Expected GifExportError when ffmpeg fails"


def test_export_webp_with_crop_prepends_crop_filter(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_webp(
            input_video,
            output_webp,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
            crop=(10, 20, 200, 200),
        )

    cmd = run_mock.call_args.args[0]
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert vf_arg.startswith("crop=200:200:10:20:exact=1,")
    assert ",fps=12," in vf_arg


def test_export_webp_without_crop_omits_crop_filter(tmp_path: Path) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_webp(
            input_video,
            output_webp,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
        )

    cmd = run_mock.call_args.args[0]
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert vf_arg == "fps=12,scale=320:-1:flags=lanczos"


def test_ffmpeg_exe_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_video = tmp_path / "input.mp4"
    input_video.write_text("fake video")
    output_webp = tmp_path / "output.webp"

    monkeypatch.setenv("GIFMAKER_FFMPEG", "/custom/bin/ffmpeg")

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""

        export_webp(
            input_video,
            output_webp,
            start_seconds=0.0,
            end_seconds=2.0,
            fps=12,
            width=320,
        )

    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "/custom/bin/ffmpeg"


@pytest.mark.parametrize(
    ("builder", "exporter", "suffix"),
    [
        (build_gif_command, export_gif, ".gif"),
        (build_webp_command, export_webp, ".webp"),
    ],
)
def test_sync_export_uses_the_async_command_builder(
    tmp_path: Path, builder, exporter, suffix: str
) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake video")
    destination = tmp_path / f"output{suffix}"
    settings = dict(
        start_seconds=0.5, end_seconds=2.5, fps=15, width=320,
        height=180, playback_speed=1.25, sharpness_preset="mild",
        crop=(10, 20, 400, 225),
    )

    with patch("gifmaker.services.gif_export.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        exporter(source, destination, **settings)

    assert run_mock.call_args.args[0] == builder(source, destination, **settings)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is required for the render smoke test",
)
def test_cropped_gif_renders_with_per_frame_palette(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "small_floor_landscape.mp4"
    destination = tmp_path / "cropped.gif"

    export_gif(
        source, destination, start_seconds=1.0, end_seconds=1.4,
        fps=12, width=240, height=240, crop=(601, 181, 701, 701),
    )

    assert destination.stat().st_size > 0
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,nb_read_frames", "-of", "csv=p=0",
            str(destination),
        ],
        check=True, capture_output=True, text=True,
    )
    width, height, frame_count = map(int, result.stdout.strip().split(","))
    assert (width, height) == (240, 240)
    assert frame_count >= 4
