"""Experiment with decoding an animated WebP through Qt and re-encoding it.

Usage: QT_QPA_PLATFORM=offscreen GIFMAKER_FFMPEG=/path/to/ffmpeg \
    poetry run python scripts/prototype_webp_input.py /path/to/animation.webp

This deliberately does not change the application or preserve an output file.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from PySide6.QtGui import QImageReader


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    reader = QImageReader(str(args.source))
    if not reader.supportsAnimation():
        parser.error("Qt cannot read this as an animation")

    with tempfile.TemporaryDirectory(prefix="gifmaker-webp-prototype-") as directory:
        work = Path(directory)
        manifest = work / "frames.ffconcat"
        output = work / "output.webp"
        durations = []
        lines = ["ffconcat version 1.0"]
        alpha = False
        while True:
            image = reader.read()
            if image.isNull():
                break
            delay = reader.nextImageDelay()
            if delay <= 0:
                raise ValueError(f"Frame {len(durations)} has unsupported delay {delay} ms")
            frame = work / f"frame-{len(durations):06d}.png"
            if not image.save(str(frame), "PNG"):
                raise RuntimeError(f"Failed to write {frame}")
            alpha = alpha or image.hasAlphaChannel()
            durations.append(delay)
            lines.extend((f"file '{frame.name}'", "option framerate 1000", f"duration {delay / 1000:.3f}"))
        if len(durations) < 2:
            raise ValueError("Expected at least two decodable animation frames")
        # The final timestamp is needed for the concat demuxer to time the last frame.
        lines.extend((f"file '{frame.name}'", "option framerate 1000"))
        manifest.write_text("\n".join(lines) + "\n")
        duration = sum(durations) / 1000
        command = [os.environ.get("GIFMAKER_FFMPEG", "ffmpeg"), "-v", "error", "-y",
                   "-f", "concat", "-safe", "0", "-i", str(manifest), "-t", str(duration),
                   "-fps_mode", "vfr", "-c:v", "libwebp_anim", "-loop", "0", str(output)]
        subprocess.run(command, check=True)
        result = QImageReader(str(output))
        output_delays = []
        while not result.read().isNull():
            output_delays.append(result.nextImageDelay())
        print(f"Input: {len(durations)} frames, {duration:.3f}s, frame delays {dict(Counter(durations))}, alpha channel: {alpha}")
        print(f"Output: {len(output_delays)} frames, {sum(output_delays) / 1000:.3f}s, frame delays {dict(Counter(output_delays))}")
        print(f"Temporary PNG frames: {sum(p.stat().st_size for p in work.glob('frame-*.png')):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
