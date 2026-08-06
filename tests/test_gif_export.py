"""Tests for the FFmpeg GIF export service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from gifmaker.services.gif_export import GifExportError, export_gif


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
    assert cmd[:2] == ["ffmpeg", "-y"]
    assert "-ss" in cmd
    assert "-to" in cmd
    assert str(input_video) in cmd
    assert str(output_gif) == cmd[-1]
    assert "fps=24,scale=640:-1:flags=lanczos" in cmd


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
