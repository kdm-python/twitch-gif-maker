"""Lossless visual preparation followed by shared caption composition/encoding."""
from __future__ import annotations

import json
import os
import signal
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QGuiApplication, QImage

from gifmaker.models.subtitles import Caption, SubtitleDocument
from gifmaker.services.gif_export import (
    QUALITY_PRESETS,
    _build_gif_filter_complex,
    _build_vf_filters,
    _ffmpeg_exe,
)
from gifmaker.services.subtitle_compositor import compose_subtitles
from gifmaker.services.webp_render import RenderCancelled, ensure_animated, run_command


def prepare_job(spec):
    from gifmaker.services.output_formats import get_output_format

    work = TemporaryDirectory(prefix="gifmaker-subtitle-render-")
    try:
        directory = Path(work.name)
        # Use the regular builder for validation, retaining its existing rules.
        get_output_format(spec.output_format).build_command(spec, directory / f"result{get_output_format(spec.output_format).suffix}")
        source = directory / "source.mp4"
        os.link(spec.source_path, source)
        job = asdict(spec.settings.shared) | asdict(spec.settings.visual)
        job.update(source=str(source), output_format=spec.output_format,
                   quality=spec.settings.quality_preset, subtitles=asdict(spec.subtitles))
        manifest = directory / "job.json"
        manifest.write_text(json.dumps(job), encoding="utf-8")
        return work, [sys.executable, "-m", "gifmaker.services.subtitle_render", str(manifest)]
    except BaseException:
        work.cleanup()
        raise


def encode_sequence(sequence, output, fps, count, quality="balanced", *, lossless=False):
    command = [_ffmpeg_exe(), "-v", "error", "-y", "-framerate", str(fps),
               "-i", str(sequence / "frame-%08d.png"), "-frames:v", str(count)]
    if output.suffix == ".gif":
        image = QImage(str(sequence / "frame-00000000.png"))
        command += ["-filter_complex", _build_gif_filter_complex(fps, image.width(), image.height(),
                                                                None, 1., quality, "off")]
    else:
        preset = QUALITY_PRESETS[quality]
        command += ["-c:v", "libwebp_anim", "-quality", str(preset["webp_quality"]),
                    "-preset", str(preset["webp_preset"])]
        if lossless:
            command += ["-lossless", "1"]
    run_command(command + ["-loop", "0", "-an", str(output)])
    if output.suffix == ".webp":
        ensure_animated(output, round(count * 1000 / fps))


def compose_sequence(directory, frames, *, fps, start_ms, speed, subtitles, quality, output_format="WebP"):
    """Draw only on transformed full-resolution frames, then encode once."""
    if not frames:
        raise ValueError("Renderer produced no frames")
    # Keep a lossless, uncaptioned animation for subsequent editing sessions.
    encode_sequence(frames[0].parent, directory / "clean.webp", fps, len(frames), lossless=True)
    app = QGuiApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QGuiApplication([])
    document = SubtitleDocument(tuple(Caption(**caption) for caption in subtitles["captions"]))
    painted = directory / "captioned"
    painted.mkdir()
    for index, frame in enumerate(frames):
        image = QImage(str(frame))
        if image.isNull():
            raise ValueError(f"Could not read transformed frame: {frame.name}")
        source_time = start_ms + index * 1000 / fps * speed
        image = compose_subtitles(image, document, source_time)
        if not image.save(str(painted / f"frame-{index:08d}.png")):
            raise OSError("Could not save captioned frame")
    suffix = ".webp" if output_format == "WebP" else ".gif"
    encode_sequence(painted, directory / f"result{suffix}", fps, len(frames), quality)


def render(manifest):
    job = json.loads(manifest.read_text(encoding="utf-8"))
    frames = manifest.parent / "visual"
    frames.mkdir()
    filters = _build_vf_filters(job["fps"], job["width"], job["height"], job["crop"],
                                job["playback_speed"], job["sharpness_preset"])
    run_command([_ffmpeg_exe(), "-v", "error", "-y", "-ss", str(job["start_seconds"]),
                 "-to", str(job["end_seconds"]), "-i", job["source"], "-vf", filters,
                 "-fps_mode", "passthrough", "-an", "-start_number", "0",
                 str(frames / "frame-%08d.png")])
    compose_sequence(manifest.parent, sorted(frames.glob("frame-*.png")), fps=job["fps"],
                     start_ms=job["start_seconds"] * 1000, speed=job["playback_speed"],
                     subtitles=job["subtitles"], quality=job["quality"], output_format=job["output_format"])


def main():
    def cancel(_signal, _frame):
        raise RenderCancelled("Subtitle render cancelled")

    signal.signal(signal.SIGTERM, cancel)
    try:
        render(Path(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 - worker failures belong in the parent UI
        print(f"Subtitle render failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
