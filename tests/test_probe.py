"""
Testing functionality of the VideoInfo class and the video probe functionality.
"""

from gifmaker.video.probe import _parse_fps, probe_video, VideoProbeError

# --- _parse_fps() ---


def test_parse_fps_integer():
    assert _parse_fps("60/1") == 60.0


def test_parse_fps_fraction():
    assert round(_parse_fps("30000/1001"), 2) == 29.97


def test_parse_fps_plain_number():
    assert _parse_fps("24") == 24.0


def test_parse_fps_zero_denominator():
    try:
        _parse_fps("30/0")
    except ValueError as e:
        assert str(e) == "frame rate denominator is zero"
    else:
        assert False, "Expected ValueError for zero denominator"


def test_parse_fps_invalid_string():
    try:
        _parse_fps("invalid")
    except ValueError:
        pass  # Expected exception
    else:
        assert False, "Expected ValueError for invalid string"


# --- probe_video() ---
