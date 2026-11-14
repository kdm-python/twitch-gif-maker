"""Load a supported source without depending on GUI state."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from PySide6.QtGui import QImageReader

from gifmaker.sources.model import LoadedSource, SourceFrame, SourceInfo
from gifmaker.video.probe import VideoProbeError, probe_video


class SourceLoadError(Exception):
    """A source cannot be read or prepared for editing."""


class SourceLoader(Protocol):
    def load(self, path: Path) -> LoadedSource: ...


class Mp4SourceLoader:
    """Probe an MP4 while retaining its original direct media path."""

    def load(self, path: Path) -> LoadedSource:
        try:
            info = probe_video(path)
        except VideoProbeError as exc:
            raise SourceLoadError(f"Could not read MP4: {exc}") from exc
        return LoadedSource(path, SourceInfo(info.duration, info.width, info.height,
                                             info.codec, info.fps), media_path=path)


class WebpSourceLoader:
    """Decode a single animation cycle to lossless, composited temporary frames."""

    def load(self, path: Path) -> LoadedSource:
        reader = QImageReader(str(path))
        reader.setDecideFormatFromContent(True)
        if bytes(reader.format()).lower() != b"webp" or not reader.canRead():
            raise SourceLoadError(f"Could not read WebP: {reader.errorString()}")
        if not reader.supportsAnimation():
            raise SourceLoadError("WebP source must be animated")
        expected_count = reader.imageCount()
        if expected_count <= 0:
            raise SourceLoadError("WebP frame count could not be determined")
        temp = TemporaryDirectory(prefix="gifmaker-source-")
        try:
            frames = []
            elapsed = 0
            dimensions = None
            while True:
                image = reader.read()
                if image.isNull():
                    break
                if dimensions is None:
                    dimensions = (image.width(), image.height())
                elif dimensions != (image.width(), image.height()):
                    raise SourceLoadError("WebP frames have inconsistent canvas sizes")
                delay = reader.nextImageDelay()
                if delay <= 0:
                    raise SourceLoadError("WebP frame has an unsupported delay")
                frame_path = Path(temp.name) / f"frame-{len(frames):08d}.png"
                if not image.save(str(frame_path), "PNG"):
                    raise SourceLoadError("Could not save a decoded WebP frame")
                frames.append(SourceFrame(frame_path, elapsed, delay))
                elapsed += delay
            if len(frames) != expected_count:
                raise SourceLoadError("WebP animation could not be decoded completely")
            if len(frames) < 2 or dimensions is None:
                raise SourceLoadError("WebP source must contain at least two readable frames")
            duration = elapsed / 1000
            info = SourceInfo(duration, *dimensions, "webp", len(frames) / duration)
            return LoadedSource(path, info, frames=tuple(frames), temporary_directory=temp)
        except Exception:
            temp.cleanup()
            raise


_LOADERS: dict[str, SourceLoader] = {".mp4": Mp4SourceLoader(), ".webp": WebpSourceLoader()}


def load_source(path: str | Path) -> LoadedSource:
    """Prepare a local source; the caller owns and must close the result."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise SourceLoadError(f"Source file not found: {source}")
    try:
        loader = _LOADERS[source.suffix.lower()]
    except KeyError as exc:
        raise SourceLoadError(f"Unsupported source format: {source.suffix or '(none)'}") from exc
    try:
        return loader.load(source)
    except OSError as exc:
        raise SourceLoadError(f"Could not prepare source: {exc}") from exc
