"""Generate WebP fixtures using the cwebp and webpmux command-line tools."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = (100, 250, 400)
COLORS = ("#ff0000", "#00ff00", "#0000ff")


def create_animation(destination: Path, *, transparent: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="webp-fixtures-") as tmp:
        directory = Path(tmp)
        command = ["webpmux"]
        for index, (color, duration) in enumerate(zip(COLORS, DURATIONS, strict=True)):
            image = QImage(16, 16, QImage.Format.Format_ARGB32)
            image.fill(QColor("transparent") if transparent else QColor(color))
            if transparent:
                painter = QPainter(image)
                painter.fillRect(index * 4, 4, 4, 8, QColor(color))
                painter.end()
            png = directory / f"frame-{index}.png"
            encoded = directory / f"frame-{index}.webp"
            if not image.save(str(png), "PNG"):
                raise RuntimeError(f"Could not save {png}")
            subprocess.run(["cwebp", "-quiet", "-lossless", "-exact", str(png), "-o", str(encoded)], check=True)
            command.extend(["-frame", str(encoded), f"+{duration}+0+0+1-b"])
        command.extend(["-loop", "0", "-bgcolor", "0,0,0,0", "-o", str(destination)])
        subprocess.run(command, check=True, capture_output=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/fixtures/webp_input")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    create_animation(args.output / "variable_delays.webp", transparent=False)
    create_animation(args.output / "transparent.webp", transparent=True)


if __name__ == "__main__":
    main()
