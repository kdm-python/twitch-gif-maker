from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QWidget


class MarkerSeekSlider(QSlider):
    """Seek slider with draggable start/end frame markers and shaded selection."""

    selectionChanged = Signal(int, int)

    def __init__(
        self, orientation: Qt.Orientation, parent: QWidget | None = None
    ) -> None:
        super().__init__(orientation, parent)
        self._total_frames = 0
        self._start_frame = 0
        self._end_frame = 0
        self._min_gap_frames = 2
        self._dragging_marker: str | None = None
        self._marker_hit_radius = 8

    def set_total_frames(self, total_frames: int) -> None:
        """Set total frame count and ensure marker bounds remain valid."""
        self._total_frames = max(total_frames, 0)
        if self._total_frames <= 0:
            self._start_frame = 0
            self._end_frame = 0
            self.update()
            return

        self.set_selection(self._start_frame, self._end_frame, emit_signal=False)

    def set_selection(
        self, start_frame: int, end_frame: int, *, emit_signal: bool = True
    ) -> None:
        """Set marker selection while enforcing ordering and minimum gap."""
        if self._total_frames <= 0:
            return

        max_frame = self._total_frames - 1
        min_end = min(max_frame, self._min_gap_frames)
        clamped_start = max(
            0, min(start_frame, max(0, max_frame - self._min_gap_frames))
        )
        clamped_end = max(min_end, min(end_frame, max_frame))

        if clamped_end - clamped_start < self._min_gap_frames:
            if self._dragging_marker == "start":
                clamped_start = max(0, clamped_end - self._min_gap_frames)
            else:
                clamped_end = min(max_frame, clamped_start + self._min_gap_frames)

        if clamped_end - clamped_start < self._min_gap_frames:
            clamped_start = 0
            clamped_end = min(max_frame, max(self._min_gap_frames, 0))

        changed = clamped_start != self._start_frame or clamped_end != self._end_frame
        self._start_frame = clamped_start
        self._end_frame = clamped_end
        self.update()

        if changed and emit_signal:
            self.selectionChanged.emit(self._start_frame, self._end_frame)

    def selection(self) -> tuple[int, int]:
        """Return current start/end frame selection."""
        return self._start_frame, self._end_frame

    def nudge_start(self, delta: int) -> None:
        """Move start marker by delta frames with clamped bounds."""
        self._dragging_marker = "start"
        self.set_selection(self._start_frame + delta, self._end_frame)
        self._dragging_marker = None

    def nudge_end(self, delta: int) -> None:
        """Move end marker by delta frames with clamped bounds."""
        self._dragging_marker = "end"
        self.set_selection(self._start_frame, self._end_frame + delta)
        self._dragging_marker = None

    def _groove_rect(self) -> tuple[int, int, int]:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.CC_Slider,
            option,
            QStyle.SC_SliderGroove,
            self,
        )
        left = groove.left()
        right = groove.right()
        width = max(1, right - left)
        return left, right, width

    def _frame_to_x(self, frame: int) -> int:
        if self._total_frames <= 1:
            left, _, _ = self._groove_rect()
            return left

        left, _, width = self._groove_rect()
        ratio = frame / (self._total_frames - 1)
        return left + round(ratio * width)

    def _x_to_frame(self, x_pos: int) -> int:
        if self._total_frames <= 1:
            return 0

        left, right, width = self._groove_rect()
        clamped_x = max(left, min(x_pos, right))
        ratio = (clamped_x - left) / width
        return round(ratio * (self._total_frames - 1))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._total_frames <= 0:
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.CC_Slider,
            option,
            QStyle.SC_SliderGroove,
            self,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        start_x = self._frame_to_x(self._start_frame)
        end_x = self._frame_to_x(self._end_frame)

        if end_x > start_x:
            selection_color = self.palette().highlight().color()
            selection_color.setAlpha(90)
            painter.fillRect(
                start_x, groove.top(), end_x - start_x, groove.height(), selection_color
            )

        marker_color = self.palette().highlight().color()
        painter.setPen(marker_color)
        painter.drawLine(start_x, groove.top() - 4, start_x, groove.bottom() + 4)
        painter.drawLine(end_x, groove.top() - 4, end_x, groove.bottom() + 4)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton or self._total_frames <= 0:
            super().mousePressEvent(event)
            return

        press_x = event.position().toPoint().x()
        start_x = self._frame_to_x(self._start_frame)
        end_x = self._frame_to_x(self._end_frame)
        start_dist = abs(press_x - start_x)
        end_dist = abs(press_x - end_x)

        if min(start_dist, end_dist) <= self._marker_hit_radius:
            self._dragging_marker = "start" if start_dist <= end_dist else "end"
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging_marker is None:
            super().mouseMoveEvent(event)
            return

        frame = self._x_to_frame(event.position().toPoint().x())
        if self._dragging_marker == "start":
            self.set_selection(frame, self._end_frame)
        else:
            self.set_selection(self._start_frame, frame)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging_marker is None:
            super().mouseReleaseEvent(event)
            return

        self._dragging_marker = None
        event.accept()
