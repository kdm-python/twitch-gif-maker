"""Interactive caption surface using the same composition as rendered frames."""
from dataclasses import replace

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLineEdit

from gifmaker.gui.views.video_preview_panel import AnimationSurface
from gifmaker.models.subtitles import SubtitleDocument
from gifmaker.services.subtitle_compositor import caption_path, compose_subtitles


class SubtitleSurface(AnimationSurface):
    textEdited = Signal(str)
    positionEdited = Signal(float, float)
    interactionStarted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.document = SubtitleDocument()
        self.source_ms = 0.
        self._press = None
        self._dragged = False
        self.setMouseTracking(True)
        self.editor = QLineEdit(self)
        self.editor.setPlaceholderText("Your text here")
        self.editor.setAccessibleName("Edit caption on canvas")
        self.editor.hide()
        self.editor.installEventFilter(self)
        self.editor.textEdited.connect(self.textEdited)
        self.editor.editingFinished.connect(self._finish_editing)

    def set_frame(self, image):
        self.image = image
        self.refresh()

    def set_document(self, document, source_ms):
        self.document, self.source_ms = document, source_ms
        self.refresh()

    def refresh(self):
        if not self.image.isNull():
            super().set_frame(compose_subtitles(self.image, self.document, self.source_ms,
                                               placeholders=True))

    def image_rect(self):
        if self.image.isNull():
            return QRectF()
        fitted = self.image.size().scaled(self.contentsRect().size(), Qt.KeepAspectRatio)
        rect = QRectF(0, 0, fitted.width(), fitted.height())
        rect.moveCenter(QRectF(self.contentsRect()).center())
        return rect

    def caption_rect(self):
        if self.image.isNull() or not self.document.captions:
            return QRectF()
        caption = self.document.captions[0]
        if not caption.visible_at(self.source_ms):
            return QRectF()
        drawn = caption if caption.text else replace(caption, text="Your text here")
        _path, bounds, _stroke = caption_path(drawn, self.image.width(), self.image.height())
        canvas = self.image_rect()
        scale = canvas.width() / self.image.width()
        return QRectF(canvas.left() + bounds.left() * scale, canvas.top() + bounds.top() * scale,
                      bounds.width() * scale, bounds.height() * scale)

    def mousePressEvent(self, event):
        self._finish_editing()
        if event.button() == Qt.LeftButton and self.caption_rect().contains(event.position()):
            self.interactionStarted.emit()
            self._press = event.position()
            self._anchor = self.document.captions[0]
            self._dragged = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None:
            delta = event.position() - self._press
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragged = True
            if self._dragged:
                rect = self.image_rect()
                self.positionEdited.emit(max(0., min(1., self._anchor.x + delta.x() / rect.width())),
                                         max(0., min(1., self._anchor.y + delta.y() / rect.height())))
            event.accept()
        else:
            self.setCursor(Qt.OpenHandCursor if self.caption_rect().contains(event.position()) else Qt.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press is not None and event.button() == Qt.LeftButton:
            if not self._dragged:
                self._edit_text()
            self._press = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _edit_text(self):
        rect = self.caption_rect().toAlignedRect()
        rect.setWidth(max(160, rect.width()))
        rect.setHeight(max(self.editor.sizeHint().height(), rect.height()))
        rect.moveLeft(max(0, min(rect.left(), self.width() - rect.width())))
        rect.moveTop(max(0, min(rect.top(), self.height() - rect.height())))
        self.editor.setGeometry(rect)
        self.editor.setText(self.document.captions[0].text)
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _finish_editing(self):
        if self.editor.isVisible():
            focused = self.editor.hasFocus()
            self.editor.hide()
            if focused:
                self.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._finish_editing()
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        self._finish_editing()
        super().resizeEvent(event)
