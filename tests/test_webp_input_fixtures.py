"""Guard the deterministic animation data used by future source tests."""
import struct
from pathlib import Path

import pytest
from PySide6.QtGui import QImageReader

FIXTURES = Path(__file__).parent / "fixtures" / "webp_input"


def frame_headers(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    headers = []
    offset = 12
    while offset + 8 <= len(data):
        kind = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        payload = data[offset + 8:offset + 8 + size]
        assert len(payload) == size
        if kind == b"ANMF":
            assert len(payload) >= 16
            headers.append((int.from_bytes(payload[12:15], "little"), payload[15]))
        offset += 8 + size + (size % 2)
    return headers


@pytest.mark.parametrize("name", ["variable_delays.webp", "transparent.webp"])
def test_animation_frame_delays_and_composition_flags(name):
    headers = frame_headers(FIXTURES / name)
    assert [duration for duration, _ in headers] == [100, 250, 400]
    # Dispose to background and replace the canvas rather than blending.
    assert all(flags & 3 == 3 for _, flags in headers)


def test_decoded_opaque_frames_have_known_colors_and_delays():
    reader = QImageReader(str(FIXTURES / "variable_delays.webp"))
    assert reader.imageCount() == 3
    for color, delay in zip(("#ff0000", "#00ff00", "#0000ff"), (100, 250, 400), strict=True):
        frame = reader.read()
        assert not frame.isNull()
        assert (frame.width(), frame.height()) == (16, 16)
        assert frame.pixelColor(0, 0).name() == color
        assert reader.nextImageDelay() == delay


def test_transparent_frames_are_composited_as_expected():
    reader = QImageReader(str(FIXTURES / "transparent.webp"))
    for index, color in enumerate(("#ff0000", "#00ff00", "#0000ff")):
        frame = reader.read()
        assert not frame.isNull()
        for region in range(3):
            pixel = frame.pixelColor(region * 4 + 1, 5)
            assert pixel.alpha() == (255 if region == index else 0)
            if region == index:
                assert pixel.name() == color
