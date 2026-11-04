"""Command-line entry point and GUI startup."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from gifmaker.services.clip_downloader import ClipDownloadError, download_clip
from gifmaker.video.probe import VideoProbeError, probe_video


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open a video or Twitch clip in GIF Maker.")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--file", metavar="PATH", help="open a local MP4 file")
    inputs.add_argument("--twitch-clip", metavar="URL", help="download and open a Twitch clip")
    args = parser.parse_args(argv)

    with TemporaryDirectory(prefix="gifmaker-") as temp_dir:
        try:
            source = None
            if args.file is not None:
                source = Path(args.file).expanduser().resolve()
                if source.suffix.lower() != ".mp4":
                    raise ValueError("Only MP4 files are supported.")
                if not source.is_file():
                    raise ValueError(f"File not found: {source}")
            elif args.twitch_clip is not None:
                source = download_clip(args.twitch_clip, Path(temp_dir))
            if source is not None:
                video_info = probe_video(source)
        except (ValueError, ClipDownloadError, VideoProbeError, OSError) as exc:
            print(f"gifmaker: {exc}", file=sys.stderr)
            return 1

        from PySide6.QtWidgets import QApplication

        from gifmaker.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        if source is not None:
            window.current_video_path = str(source)
            window.video_session_controller.load_video_preview(str(source), video_info, None)
        window.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
