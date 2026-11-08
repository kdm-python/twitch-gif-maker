from unittest.mock import patch

import pytest

from gifmaker.main import main
from gifmaker.services.clip_downloader import (
    ClipDownloadError,
    download_clip,
    validate_clip_url,
)
from gifmaker.video.probe import VideoProbeError


@pytest.mark.parametrize(
    "url",
    [
        "https://clips.twitch.tv/FunnyClip-123?tt_content=share",
        "https://www.twitch.tv/example/clip/FunnyClip-123",
    ],
)
def test_valid_clip_urls(url):
    assert validate_clip_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://evil.test/clip/foo",
        "https://twitch.tv/example",
        "https://twitch.tv.evil.test/a/clip/b",
        "https://user@clips.twitch.tv/test",
    ],
)
def test_invalid_clip_urls(url):
    with pytest.raises(ClipDownloadError):
        validate_clip_url(url)


def test_downloader_returns_actual_mp4(tmp_path):
    class FakeYoutubeDL:
        def __init__(self, options):
            assert options["format"] == "best[ext=mp4]"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            (tmp_path / "clip.mp4").write_bytes(b"video")

    with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
        assert (
            download_clip("https://clips.twitch.tv/Test", tmp_path)
            == tmp_path / "clip.mp4"
        )


def test_invalid_cli_never_starts_gui(tmp_path, capsys):
    with patch("gifmaker.main.probe_video") as probe:
        assert main(["--file", str(tmp_path / "a.mov")]) == 1
        assert main(["--file", str(tmp_path / "missing.mp4")]) == 1
        assert main(["--twitch-clip", "https://example.com/"]) == 1
    probe.assert_not_called()
    assert "valid Twitch clip URL" in capsys.readouterr().err


def test_unreadable_video_exits_before_gui(tmp_path, capsys):
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"bad")
    with patch("gifmaker.main.probe_video", side_effect=VideoProbeError("bad video")):
        assert main(["--file", str(path)]) == 1
    assert "bad video" in capsys.readouterr().err


def test_shortcut_and_button_open_clip_dialog():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    from gifmaker.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.shortcut_manager.shortcuts["open_clip"].key() == QKeySequence(
        "Shift+L"
    )
    with patch(
        "gifmaker.controllers.video_session_controller.QInputDialog.getText",
        return_value=("", False),
    ) as dialog:
        window.clip_button.click()
        dialog.assert_called_once()
    window.close()
    app.quit()


def test_successful_cli_file_loads_probed_video(tmp_path):
    from unittest.mock import MagicMock

    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    info = object()
    app = MagicMock()
    app.exec.return_value = 0
    window = MagicMock()
    with (
        patch("gifmaker.main.probe_video", return_value=info),
        patch("PySide6.QtWidgets.QApplication.instance", return_value=app),
        patch("gifmaker.gui.main_window.MainWindow", return_value=window),
    ):
        assert main(["--file", str(path)]) == 0
    window.video_session_controller.load_video_preview.assert_called_once_with(
        str(path), info, None
    )
    window.show.assert_called_once()
