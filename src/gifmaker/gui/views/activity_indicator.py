"""A small palette-aware animated indicator for background work."""

from __future__ import annotations

from math import cos, pi, sin

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget


class ActivityIndicator(QWidget):
    """Draw a quiet, continuously rotating set of dots while work is active."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._step = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(18, 18)
        self.setVisible(False)

    def set_running(self, running: bool) -> None:
        """Start or stop the indicator without affecting the parent layout."""
        if running:
            self.setVisible(True)
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.setVisible(False)

    def _advance(self) -> None:
        self._step = (self._step + 1) % 12
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = self.palette().highlight().color()
        centre = self.rect().center()
        radius = 6
        for index in range(12):
            angle = 2 * pi * index / 12
            distance = 6
            alpha = 255 if index == self._step else 40 + ((index - self._step) % 12) * 14
            colour.setAlpha(min(alpha, 220))
            painter.setBrush(colour)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                round(centre.x() + cos(angle) * distance - 1.5),
                round(centre.y() + sin(angle) * distance - 1.5),
                3,
                3,
            )
