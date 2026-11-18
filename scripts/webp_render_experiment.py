"""Experimental constant-cadence bridge from prepared WebP frames to FFmpeg.

This is a backend experiment, not the application's rendering path. The caller
owns the source and temporary directory; the command does not delete either.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import threading
from fractions import Fraction
from pathlib import Path

from PySide6.QtGui import QImageReader

from gifmaker.services.gif_export import _build_vf_filters
from gifmaker.sources.model import LoadedSource


class RenderCancelled(Exception):
    """The experimental encoder was cancelled."""


def run_cancellable(command: list[str], cancel: threading.Event) -> None:
    """Run a subprocess, ensuring a cancelled child is reaped."""
    if cancel.is_set():
        raise RenderCancelled("Render cancelled")
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr)
        try:
            while process.poll() is None:
                if cancel.wait(0.02):
                    raise RenderCancelled("Render cancelled")
            if process.returncode:
                stderr.seek(0)
                raise subprocess.CalledProcessError(process.returncode, command, stderr=stderr.read())
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def prepare_sampled_frames(source: LoadedSource, directory: Path, *, start_ms: int,
                           end_ms: int, fps: int, speed: float) -> int:
    """Sample the half-open source selection at the desired output cadence.

    Symlinks refer to the prepared lossless source frames; they do not duplicate
    image contents. Source and links must remain alive until FFmpeg has exited.
    """
    if source.closed or not source.frames:
        raise ValueError("A live animated source is required")
    duration_ms = source.frames[-1].start_ms + source.frames[-1].duration_ms
    if not 0 <= start_ms < end_ms <= duration_ms:
        raise ValueError("Selection must lie within the source")
    if fps <= 0 or not math.isfinite(speed) or speed <= 0:
        raise ValueError("FPS and speed must be positive")
    rate = Fraction(str(speed))
    count = math.ceil(Fraction(end_ms - start_ms, 1000) * fps / rate)
    directory.mkdir(parents=True, exist_ok=False)
    for index in range(count):
        source_time = Fraction(start_ms) + Fraction(index * 1000, fps) * rate
        frame = source.frame_at(int(source_time))
        (directory / f"frame-{index:08d}.png").symlink_to(frame.path.resolve())
    return count


def build_experiment_command(ffmpeg: str, frames: Path, destination: Path, *,
                             fps: int, width: int, height: int, frame_count: int,
                             crop: tuple[int, int, int, int] | None = None,
                             sharpness: str = "off", lossless: bool = True) -> list[str]:
    """Use the application's visual filters on already-retimed sample frames."""
    filters = _build_vf_filters(fps, width, height, crop, 1.0, sharpness)
    cmd = [ffmpeg, "-v", "error", "-y", "-framerate", str(fps),
           "-i", str(frames / "frame-%08d.png"), "-frames:v", str(frame_count),
           "-vf", filters, "-c:v", "libwebp_anim"]
    if lossless:
        cmd.extend(["-lossless", "1"])
    else:
        cmd.extend(["-quality", "85", "-preset", "photo"])
    return [*cmd, "-loop", "0", "-an", str(destination)]


def ensure_animated(destination: Path, *, duration_ms: int, mux: str = "webpmux") -> bool:
    """Repair an encoder-collapsed still, or fail without replacing it.

    This experiment requires webpmux only when FFmpeg emitted a still. It is
    not yet the production export implementation.
    """
    reader = QImageReader(str(destination))
    if not reader.canRead():
        raise ValueError("FFmpeg did not produce a readable WebP")
    if reader.supportsAnimation():
        return False
    if duration_ms < 2:
        raise ValueError("Animation duration is too short to mux")
    tool = shutil.which(mux)
    if tool is None:
        raise FileNotFoundError("webpmux is required to preserve an unchanged animation")
    first = duration_ms // 2
    second = duration_ms - first
    if second > 0xFFFFFF:
        raise ValueError("Animation duration exceeds the mux experiment limit")
    with tempfile.TemporaryDirectory(prefix="webp-mux-", dir=destination.parent) as work:
        output = Path(work) / "animated.webp"
        subprocess.run([tool, "-frame", str(destination), f"+{first}+0+0+1-b",
                        "-frame", str(destination), f"+{second}+0+0+1-b",
                        "-loop", "0", "-bgcolor", "0,0,0,0", "-o", str(output)],
                       check=True, capture_output=True)
        if not QImageReader(str(output)).supportsAnimation():
            raise ValueError("webpmux did not produce an animation")
        output.replace(destination)
    return True
