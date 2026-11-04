"""Download a single Twitch clip into a caller-owned directory."""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


class ClipDownloadError(Exception):
    """A clip URL is invalid or its video could not be downloaded."""


def validate_clip_url(url: str) -> str:
    url = url.strip()
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        # Reject credentials, unusual ports and non-Twitch URLs before yt-dlp sees them.
        if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password or parsed.port:
            raise ValueError
        slug = r"[A-Za-z0-9_-]+"
        if host == "clips.twitch.tv":
            valid = re.fullmatch(rf"/{slug}/?", parsed.path)
        elif host in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
            valid = re.fullmatch(rf"/[A-Za-z0-9_]+/clip/{slug}/?", parsed.path)
        else:
            valid = None
        if not valid:
            raise ValueError
    except ValueError as exc:
        raise ClipDownloadError("Enter a valid Twitch clip URL.") from exc
    return url


def download_clip(url: str, output_dir: Path) -> Path:
    url = validate_clip_url(url)
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise ClipDownloadError("yt-dlp is not installed. Install the project dependencies.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "clip.mp4"
    options = {
        "outtmpl": str(output_dir / "clip.%(ext)s"),
        "format": "best[ext=mp4]",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
    }
    try:
        with YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except (DownloadError, OSError) as exc:
        raise ClipDownloadError(f"Could not download Twitch clip: {exc}") from exc
    if not output.is_file() or output.stat().st_size == 0:
        raise ClipDownloadError("The clip download did not produce an MP4 file.")
    return output


def main() -> int:
    try:
        download_clip(sys.argv[1], Path(sys.argv[2]))
    except (ClipDownloadError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
