"""Frame-rate parsing and metadata fallback for source videos."""
import json
from unittest.mock import patch

import pytest

from gifmaker.video.probe import VideoProbeError, _parse_fps, probe_video


@pytest.mark.parametrize(("value", "expected"), [("60/1", 60), ("30000/1001", 30000 / 1001), ("24", 24)])
def test_parse_fps(value, expected):
    assert _parse_fps(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["30/0", "invalid"])
def test_parse_fps_rejects_invalid_rates(value):
    with pytest.raises(ValueError):
        _parse_fps(value)


def test_probe_uses_nominal_rate_if_average_is_unavailable(tmp_path):
    payload = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 640,
                             "height": 360, "avg_frame_rate": "0/0", "r_frame_rate": "30000/1001"}],
               "format": {"duration": "3"}}
    with patch("gifmaker.video.probe.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(payload)
        assert probe_video(tmp_path / "clip.mp4").fps == pytest.approx(30000 / 1001)
        payload["streams"][0]["r_frame_rate"] = "0/0"
        run.return_value.stdout = json.dumps(payload)
        with pytest.raises(VideoProbeError):
            probe_video(tmp_path / "clip.mp4")
