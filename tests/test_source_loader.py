from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtGui import QColor, QImage

from gifmaker.models.video_info import VideoInfo
from gifmaker.sources import SourceLoadError, load_source
from gifmaker.video.probe import VideoProbeError

FIXTURES = Path(__file__).parent / "fixtures" / "webp_input"


def test_webp_source_frames_timing_and_cleanup():
    with load_source(FIXTURES / "variable_delays.webp") as source:
        assert source.original_path == (FIXTURES / "variable_delays.webp").resolve()
        assert source.media_path is None
        assert source.info.duration_seconds == pytest.approx(0.75)
        assert (source.info.width, source.info.height, source.info.codec) == (16, 16, "webp")
        assert [(f.start_ms, f.duration_ms) for f in source.frames] == [(0, 100), (100, 250), (350, 400)]
        assert [source.frame_at(t) for t in (0, 99, 100, 349, 350, 750)] == [
            source.frames[i] for i in (0, 0, 1, 1, 2, 2)
        ]
        with pytest.raises(ValueError):
            source.frame_at(751)
        frame_paths = [frame.path for frame in source.frames]
        assert all(path.is_file() for path in frame_paths)
        assert QImage(str(frame_paths[1])).pixelColor(0, 0).name() == "#00ff00"
    assert source.closed
    assert not any(path.exists() for path in frame_paths)
    source.close()
    with pytest.raises(ValueError, match="closed"):
        source.frame_at(0)


def test_webp_source_preserves_composited_transparency():
    with load_source(FIXTURES / "transparent.webp") as source:
        for index, frame in enumerate(source.frames):
            image = QImage(str(frame.path))
            assert image.pixelColor(index * 4 + 1, 5).alpha() == 255
            assert image.pixelColor(((index + 1) % 3) * 4 + 1, 5).alpha() == 0


def test_static_and_invalid_webp_rejected(tmp_path):
    still = tmp_path / "still.webp"
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(still), "WEBP")
    with pytest.raises(SourceLoadError, match="at least two|animated"):
        load_source(still)
    bad = tmp_path / "bad.webp"
    bad.write_bytes(b"not webp")
    with pytest.raises(SourceLoadError, match="WebP"):
        load_source(bad)


def test_mp4_loader_delegates_and_never_deletes_input(tmp_path):
    source_path = tmp_path / "clip.MP4"
    source_path.touch()
    with (patch("gifmaker.sources.loader.probe_video", return_value=VideoInfo(2, 640, 360, 30, "h264")),
          load_source(source_path) as source):
        assert source.media_path == source_path
        assert source.info.average_fps == 30
        assert source.frames == ()
    assert source_path.exists()


def test_load_errors(tmp_path):
    with pytest.raises(SourceLoadError, match="not found"):
        load_source(tmp_path / "missing.webp")
    bad = tmp_path / "bad.gif"
    bad.touch()
    with pytest.raises(SourceLoadError, match="Unsupported"):
        load_source(bad)
    video = tmp_path / "bad.mp4"
    video.touch()
    with (patch("gifmaker.sources.loader.probe_video", side_effect=VideoProbeError("broken")),
          pytest.raises(SourceLoadError, match="broken")):
        load_source(video)


def test_failed_frame_write_cleans_prepared_directory(tmp_path):
    from tempfile import TemporaryDirectory

    created = []

    def make_directory(*, prefix):
        temp = TemporaryDirectory(prefix=prefix, dir=tmp_path)
        created.append(Path(temp.name))
        return temp

    with (patch("gifmaker.sources.loader.TemporaryDirectory", side_effect=make_directory),
          patch.object(QImage, "save", return_value=False),
          pytest.raises(SourceLoadError, match="save")):
        load_source(FIXTURES / "variable_delays.webp")
    assert len(created) == 1
    assert not created[0].exists()
