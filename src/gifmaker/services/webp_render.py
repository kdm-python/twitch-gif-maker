"""Render a prepared animation using the same visual settings as video input."""
from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from PySide6.QtGui import QImageReader

from gifmaker.models.render_settings import RenderSpec
from gifmaker.services.gif_export import QUALITY_PRESETS, _build_vf_filters, _ffmpeg_exe
from gifmaker.sources.model import LoadedSource


class RenderCancelled(Exception):
    """A render worker was asked to stop."""


def prepare_job(source: LoadedSource, spec: RenderSpec):
    """Snapshot frame references so an export survives a source change."""
    if source.closed or not source.frames or spec.output_format != "WebP":
        raise ValueError("A loaded animation and WebP output are required")
    work = tempfile.TemporaryDirectory(prefix="gifmaker-webp-render-")
    try:
        directory = Path(work.name)
        frames = []
        for index, frame in enumerate(source.frames):
            target = directory / f"source-{index:08d}.png"
            os.link(frame.path, target)
            frames.append([str(target), frame.start_ms, frame.duration_ms])
        settings = spec.settings
        manifest = {
            "frames": frames,
            "start_ms": round(settings.start_seconds * 1000),
            "end_ms": round(settings.end_seconds * 1000),
            "fps": settings.fps,
            "speed": settings.playback_speed,
            "width": settings.width,
            "height": settings.height,
            "crop": settings.crop,
            "sharpness": settings.sharpness_preset,
            "quality": settings.quality_preset,
        }
        manifest_path = directory / "job.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return work, [sys.executable, "-m", "gifmaker.services.webp_render", str(manifest_path)]
    except BaseException:
        work.cleanup()
        raise


def run_command(command: list[str]) -> None:
    """Forward termination to an encoder or mux process and retain its errors."""
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            returncode = process.wait()
            if returncode:
                errors.seek(0)
                message = errors.read().decode(errors="replace").strip()
                raise RuntimeError(message or f"{command[0]} exited with status {returncode}")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def render(manifest_path: Path) -> None:
    job = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = job["frames"]
    start, end, fps = job["start_ms"], job["end_ms"], job["fps"]
    speed = Fraction(str(job["speed"]))
    duration = frames[-1][1] + frames[-1][2]
    if not 0 <= start < end <= duration or fps <= 0 or speed <= 0:
        raise ValueError("Invalid animation selection, FPS or speed")
    count = math.ceil(Fraction(end - start, 1000) * fps / speed)
    sequence = manifest_path.parent / "sequence"
    sequence.mkdir()
    frame_index = 0
    for index in range(count):
        source_time = Fraction(start) + Fraction(index * 1000, fps) * speed
        while frame_index + 1 < len(frames) and frames[frame_index + 1][1] <= source_time:
            frame_index += 1
        (sequence / f"frame-{index:08d}.png").symlink_to(frames[frame_index][0])
    output = manifest_path.parent / "result.webp"
    filters = _build_vf_filters(fps, job["width"], job["height"], job["crop"], 1.0, job["sharpness"])
    quality = QUALITY_PRESETS[job["quality"]]
    command = [_ffmpeg_exe(), "-v", "error", "-y", "-framerate", str(fps),
               "-i", str(sequence / "frame-%08d.png"), "-frames:v", str(count),
               "-vf", filters, "-c:v", "libwebp_anim", "-quality", str(quality["webp_quality"]),
               "-preset", str(quality["webp_preset"]), "-loop", "0", "-an", str(output)]
    run_command(command)
    reader = QImageReader(str(output))
    if not reader.canRead():
        raise ValueError("FFmpeg produced an unreadable WebP")
    if not reader.supportsAnimation():
        duration_ms = round(count * 1000 / fps)
        if duration_ms < 2 or duration_ms > 2 * 0xFFFFFF:
            raise ValueError("Animation duration cannot be represented by webpmux")
        mux = os.environ.get("GIFMAKER_WEBPMUX", "webpmux")
        executable = shutil.which(mux)
        if not executable:
            raise FileNotFoundError("webpmux is required for an unchanged animation; install it or set GIFMAKER_WEBPMUX")
        first = duration_ms // 2
        second = duration_ms - first
        repaired = manifest_path.parent / "animated.webp"
        run_command([executable, "-frame", str(output), f"+{first}+0+0+1-b",
                     "-frame", str(output), f"+{second}+0+0+1-b", "-loop", "0",
                     "-bgcolor", "0,0,0,0", "-o", str(repaired)])
        if not QImageReader(str(repaired)).supportsAnimation():
            raise ValueError("webpmux did not produce an animation")
        repaired.replace(output)


def main() -> int:
    def cancel(_signal, _frame):
        raise RenderCancelled("Render cancelled")

    signal.signal(signal.SIGTERM, cancel)
    try:
        render(Path(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 - report worker failures to the parent process
        print(f"WebP render failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
