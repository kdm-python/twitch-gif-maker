"""Crop overlay widget for the GIF preview panel."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel

_MIN_CROP_PX = 20
_HANDLE_RADIUS = 8
_HANDLE_SIZE = 6


class CropOverlayLabel(QLabel):
    """Drop-in QLabel replacement that draws a 1:1 crop overlay over the GIF preview."""

    cropChanged = Signal(int, int, int, int)  # x, y, w, h in source-video pixels

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._video_w: int = 0
        self._video_h: int = 0
        self._crop_label_rect: QRect | None = None
        # "idle" | "drawing" | "moving" | "resizing"
        self._crop_mode: str = "idle"
        self._drag_origin: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._resize_corner: str | None = None
        # Stored in Qt inclusive coords (right = x+w-1, bottom = y+h-1)
        self._resize_anchor: QPoint | None = None
        self.setMouseTracking(True)

    def set_video_size(self, w: int, h: int) -> None:
        """Set the source-video dimensions used for coordinate mapping."""
        if w != self._video_w or h != self._video_h:
            self._video_w = w
            self._video_h = h
            self.clear_crop()

    def clear_crop(self) -> None:
        """Remove the current crop selection and reset interaction state."""
        self._crop_label_rect = None
        self._crop_mode = "idle"
        self._drag_origin = None
        self._drag_offset = None
        self._resize_corner = None
        self._resize_anchor = None
        self.update()

    # ── Geometry helpers ───────────────────────────────────────────────────────

    def _get_pixmap_rendered_rect(self) -> QRect:
        """Return the rect where the pixmap is actually painted inside contentsRect."""
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return QRect()
        cr = self.contentsRect()
        x_off = (cr.width() - pix.width()) // 2
        y_off = (cr.height() - pix.height()) // 2
        return QRect(cr.x() + x_off, cr.y() + y_off, pix.width(), pix.height())

    def _clamp_to_rendered(self, pos: QPoint) -> QPoint:
        """Clamp pos to the inclusive bounds of the rendered video rect."""
        r = self._get_pixmap_rendered_rect()
        if r.isNull():
            return pos
        return QPoint(
            max(r.left(), min(pos.x(), r.right())),
            max(r.top(), min(pos.y(), r.bottom())),
        )

    def _clamp_rect_in_rendered(self, rect: QRect) -> QRect:
        """Translate rect to keep it fully within the rendered video area."""
        r = self._get_pixmap_rendered_rect()
        if r.isNull():
            return rect
        w = min(rect.width(), r.width())
        h = min(rect.height(), r.height())
        # r.right() = r.x() + r.width() - 1; clamping x so x+w-1 <= r.right()
        x = max(r.left(), min(rect.x(), r.right() - w + 1))
        y = max(r.top(), min(rect.y(), r.bottom() - h + 1))
        return QRect(x, y, w, h)

    def _hit_corner(self, pos: QPoint) -> str | None:
        """Return which corner handle pos overlaps, or None."""
        if self._crop_label_rect is None:
            return None
        r = self._crop_label_rect
        for name, cx, cy in (
            ("TL", r.left(), r.top()),
            ("TR", r.right(), r.top()),
            ("BL", r.left(), r.bottom()),
            ("BR", r.right(), r.bottom()),
        ):
            if (
                abs(pos.x() - cx) <= _HANDLE_RADIUS
                and abs(pos.y() - cy) <= _HANDLE_RADIUS
            ):
                return name
        return None

    def _get_anchor_for_corner(self, corner: str) -> QPoint:
        """Return the opposite corner (Qt inclusive coords) used as the fixed resize anchor."""
        r = self._crop_label_rect
        if corner == "TL":
            return QPoint(r.right(), r.bottom())
        if corner == "TR":
            return QPoint(r.left(), r.bottom())
        if corner == "BL":
            return QPoint(r.right(), r.top())
        return QPoint(r.left(), r.top())  # BR

    def _label_rect_to_video_rect(self, rect: QRect) -> tuple[int, int, int, int]:
        """Convert a label-space rect to (x, y, w, h) in source-video pixels."""
        rendered = self._get_pixmap_rendered_rect()
        if rendered.isNull() or rendered.width() == 0 or rendered.height() == 0:
            return (0, 0, 0, 0)
        if self._video_w <= 0 or self._video_h <= 0:
            return (0, 0, 0, 0)
        sx = self._video_w / rendered.width()
        sy = self._video_h / rendered.height()
        vx = max(0, round((rect.x() - rendered.x()) * sx))
        vy = max(0, round((rect.y() - rendered.y()) * sy))
        vw = max(1, round(rect.width() * sx))
        vh = max(1, round(rect.height() * sy))
        vx = min(vx, max(0, self._video_w - 1))
        vy = min(vy, max(0, self._video_h - 1))
        vw = min(vw, self._video_w - vx)
        vh = min(vh, self._video_h - vy)
        return (vx, vy, vw, vh)

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        """Render the label normally, then draw the crop overlay on top."""
        super().paintEvent(event)
        if self._crop_label_rect is None or not self._crop_label_rect.isValid():
            return

        r = self._crop_label_rect
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        painter.fillRect(r, QColor(0, 120, 255, 60))

        painter.setPen(QPen(QColor(0, 120, 255, 220), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        hs = _HANDLE_SIZE // 2
        fill = QColor(255, 255, 255, 200)
        for cx, cy in (
            (r.left(), r.top()),
            (r.right(), r.top()),
            (r.left(), r.bottom()),
            (r.right(), r.bottom()),
        ):
            handle = QRect(cx - hs, cy - hs, _HANDLE_SIZE, _HANDLE_SIZE)
            painter.fillRect(handle, fill)
            painter.drawRect(handle)

        painter.end()

    # ── Cursor management ──────────────────────────────────────────────────────

    def _update_cursor(self, pos: QPoint) -> None:
        rendered = self._get_pixmap_rendered_rect()
        if rendered.isNull() or not rendered.contains(pos):
            self.unsetCursor()
            return
        corner = self._hit_corner(pos)
        if corner in ("TL", "BR"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif corner in ("TR", "BL"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif self._crop_label_rect is not None and self._crop_label_rect.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # ── Mouse events ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position().toPoint()
        rendered = self._get_pixmap_rendered_rect()
        if rendered.isNull() or not rendered.contains(pos):
            super().mousePressEvent(event)
            return

        corner = self._hit_corner(pos)
        if corner is not None:
            self._crop_mode = "resizing"
            self._resize_corner = corner
            self._resize_anchor = self._get_anchor_for_corner(corner)
            return

        if self._crop_label_rect is not None and self._crop_label_rect.contains(pos):
            self._crop_mode = "moving"
            self._drag_offset = pos - self._crop_label_rect.topLeft()
            return

        self._crop_mode = "drawing"
        self._drag_origin = self._clamp_to_rendered(pos)
        self._crop_label_rect = None
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._crop_mode == "idle":
            self._update_cursor(pos)
            return
        if self._crop_mode == "drawing":
            self._update_drawing(pos)
        elif self._crop_mode == "moving":
            self._update_moving(pos)
        elif self._crop_mode == "resizing":
            self._update_resizing(pos)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        pos = event.position().toPoint()

        if self._crop_mode == "drawing":
            if (
                self._crop_label_rect is None
                or self._crop_label_rect.width() < _MIN_CROP_PX
            ):
                self._crop_label_rect = None
                self.update()
            else:
                self._emit_crop()
        elif self._crop_mode == "moving":
            self._update_moving(pos)
            self._emit_crop()
        elif self._crop_mode == "resizing":
            self._update_resizing(pos)
            if (
                self._crop_label_rect is not None
                and self._crop_label_rect.width() >= _MIN_CROP_PX
            ):
                self._emit_crop()
            else:
                self._crop_label_rect = None
                self.update()

        self._crop_mode = "idle"
        self._drag_origin = None
        self._drag_offset = None
        self._resize_corner = None
        self._resize_anchor = None
        self._update_cursor(pos)

    # ── Drag update helpers ────────────────────────────────────────────────────

    def _update_drawing(self, pos: QPoint) -> None:
        if self._drag_origin is None:
            return
        clamped = self._clamp_to_rendered(pos)
        dx = clamped.x() - self._drag_origin.x()
        dy = clamped.y() - self._drag_origin.y()
        side = min(abs(dx), abs(dy))
        x = self._drag_origin.x() if dx >= 0 else self._drag_origin.x() - side
        y = self._drag_origin.y() if dy >= 0 else self._drag_origin.y() - side
        self._crop_label_rect = QRect(x, y, side, side)
        self.update()

    def _update_moving(self, pos: QPoint) -> None:
        if self._drag_offset is None or self._crop_label_rect is None:
            return
        new_tl = pos - self._drag_offset
        new_rect = QRect(
            new_tl.x(),
            new_tl.y(),
            self._crop_label_rect.width(),
            self._crop_label_rect.height(),
        )
        self._crop_label_rect = self._clamp_rect_in_rendered(new_rect)
        self.update()

    def _update_resizing(self, pos: QPoint) -> None:
        if self._resize_anchor is None:
            return
        clamped = self._clamp_to_rendered(pos)
        anchor = self._resize_anchor
        dx = clamped.x() - anchor.x()
        dy = clamped.y() - anchor.y()
        side = max(_MIN_CROP_PX, min(abs(dx), abs(dy)))
        # anchor uses Qt inclusive right/bottom, so offset by +1 when rect extends leftward/upward
        x1 = anchor.x() if dx >= 0 else anchor.x() - side + 1
        y1 = anchor.y() if dy >= 0 else anchor.y() - side + 1
        self._crop_label_rect = QRect(x1, y1, side, side)
        self.update()

    def _emit_crop(self) -> None:
        if self._crop_label_rect is None:
            return
        x, y, w, h = self._label_rect_to_video_rect(self._crop_label_rect)
        if w > 0 and h > 0:
            self.cropChanged.emit(x, y, w, h)
