"""Load a supported source without depending on GUI state."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from gifmaker.sources.model import LoadedSource, SourceInfo
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
        from gifmaker.sources.webp_decoder import load_reference_webp

        try:
            return load_reference_webp(path)
        except (OSError, ValueError, RuntimeError, AttributeError) as exc:
            raise SourceLoadError(f"Could not read animated WebP: {exc}") from exc


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
