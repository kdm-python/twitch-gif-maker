"""Tests for the FFmpeg GIF export service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gifmaker.services.gif_export import GifExportError, export_gif, export_webp


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
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert vf_arg.startswith("crop=200:200:10:20,")
    assert ",fps=12," in vf_arg


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
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert vf_arg == "fps=12,scale=320:-1:flags=lanczos"


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
    assert cmd[:2] == ["ffmpeg", "-y"]
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
    assert vf_arg.startswith("crop=200:200:10:20,")
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
