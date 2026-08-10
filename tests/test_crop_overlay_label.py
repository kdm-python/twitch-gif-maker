"""Tests for CropOverlayLabel geometry and interaction."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from gifmaker.gui.crop_overlay_label import CropOverlayLabel


def _make_label(label_w: int, label_h: int) -> CropOverlayLabel:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    label = CropOverlayLabel()
    label.resize(label_w, label_h)
    return label


def _set_pixmap(label: CropOverlayLabel, pix_w: int, pix_h: int) -> None:
    pix = QPixmap(pix_w, pix_h)
    pix.fill(Qt.GlobalColor.black)
    label.setPixmap(pix)


def test_rendered_rect_centered_in_label() -> None:
    label = _make_label(200, 200)
    _set_pixmap(label, 100, 100)

    rendered = label._get_pixmap_rendered_rect()

    assert rendered.x() == 50
    assert rendered.y() == 50
    assert rendered.width() == 100
    assert rendered.height() == 100


def test_label_to_video_coords_center_maps_correctly() -> None:
    label = _make_label(200, 200)
    _set_pixmap(label, 100, 100)
    label.set_video_size(400, 400)

    # Centre of the rendered rect (50+50, 50+50) = (100, 100) in label coords
    crop = QRect(75, 75, 50, 50)  # centred on the rendered rect
    vx, vy, vw, vh = label._label_rect_to_video_rect(crop)

    assert vx == 100
    assert vy == 100
    assert vw == 200
    assert vh == 200


def test_crop_is_square_on_draw() -> None:
    label = _make_label(200, 200)
    _set_pixmap(label, 160, 120)
    label.set_video_size(640, 480)

    # Simulate a drag from (20, 10) with unequal dx/dy; result must be square
    label._crop_mode = "drawing"
    label._drag_origin = QPoint(20, 10)
    label._update_drawing(QPoint(80, 60))  # dx=60, dy=50 → side=50

    assert label._crop_label_rect is not None
    r = label._crop_label_rect
    assert r.width() == r.height()
    assert r.width() == 50


def test_no_signal_emitted_without_pixmap() -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    label = CropOverlayLabel()
    label.resize(200, 200)
    label.set_video_size(640, 480)

    received: list[tuple[int, int, int, int]] = []
    label.cropChanged.connect(lambda x, y, w, h: received.append((x, y, w, h)))

    # Without a pixmap, the rendered rect is null — interaction is blocked.
    assert label._get_pixmap_rendered_rect().isNull()

    # Even if drawing state is forced, _emit_crop must not fire without a rendered rect.
    label._crop_mode = "drawing"
    label._drag_origin = QPoint(10, 10)
    label._update_drawing(QPoint(90, 90))
    label._emit_crop()

    assert received == []
