"""Audio-only extraction through the existing asynchronous FFmpeg pipeline."""
from math import isfinite
from pathlib import Path

from gifmaker.models.render_settings import AudioSettings, RenderSpec
from gifmaker.services.gif_export import GifExportError, _ffmpeg_exe


def build_mp3_command(spec: RenderSpec, destination: str | Path) -> list[str]:
    source, destination = Path(spec.source_path), Path(destination)
    settings = spec.settings
    audio = settings.format_settings
    if not source.is_file() or source.suffix.lower() != ".mp4":
        raise GifExportError("MP3 extraction requires an MP4 source.")
    if destination.suffix.lower() != ".mp3" or not destination.parent.is_dir():
        raise GifExportError("Choose an existing output directory and a .mp3 filename.")
    if destination.resolve() == source.resolve() or (destination.exists() and source.samefile(destination)):
        raise GifExportError("Choose an output file different from the original source.")
    start, end, speed = settings.start_seconds, settings.end_seconds, settings.playback_speed
    if not all(isfinite(v) for v in (start, end, speed)) or start < 0 or end <= start or not 0.25 <= speed <= 3:
        raise GifExportError("Select a valid clip range and speed between 0.25× and 3×.")
    if not isinstance(audio, AudioSettings) or not 0 <= audio.volume_percent <= 200:
        raise GifExportError("Invalid MP3 audio settings.")
    filters = []
    # Keep each tempo stage within the range that blends rather than skips samples.
    remaining = speed
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2:
        filters.append("atempo=2")
        remaining /= 2
    filters.extend((f"atempo={remaining:g}", f"volume={audio.volume_percent / 100:g}"))
    if audio.fade_edges:
        duration = (end - start) / speed
        fade = min(0.05, duration / 2)
        filters.extend((f"afade=t=in:d={fade:g}", f"afade=t=out:st={duration-fade:g}:d={fade:g}"))
    return [_ffmpeg_exe(), "-y", "-ss", str(start), "-t", str(end-start), "-i", str(source),
            "-map", "0:a:0", "-vn", "-af", ",".join(filters), "-c:a", "libmp3lame",
            "-q:a", "2", "-map_metadata", "-1", str(destination)]
