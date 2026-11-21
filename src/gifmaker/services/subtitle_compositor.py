"""Draw captions at final canvas resolution; reusable by preview and export.

No widgets or player state are used here. A Qt GUI application is required for
font resolution. Empty captions are only drawn when a caller requests editing
placeholders; they never become literal subtitle text.
"""
from dataclasses import replace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

from gifmaker.models.subtitles import Caption, SubtitleDocument


def caption_path(caption: Caption, width: int, height: int) -> tuple[QPainterPath, QRectF, float]:
    font = QFont(caption.font_family)
    font.setPixelSize(max(1, round(height * caption.size)))
    font.setBold(caption.bold)
    font.setItalic(caption.italic)
    path = QPainterPath()
    path.addText(0, 0, font, caption.text)
    bounds = path.boundingRect()
    stroke = max(.25, height * caption.size * .055)
    # Fit long text while retaining the requested size for shorter replacements.
    if bounds.width() > max(1, width - 2 * stroke):
        from PySide6.QtGui import QTransform

        factor = max(1, width - 2 * stroke) / bounds.width()
        path = QTransform.fromScale(factor, factor).map(path)
        bounds = path.boundingRect()
    left = min(max(stroke, caption.x * width - bounds.width() / 2),
               max(stroke, width - stroke - bounds.width()))
    top = min(max(stroke, caption.y * height - bounds.height()),
              max(stroke, height - stroke - bounds.height()))
    path = path.translated(left - bounds.left(), top - bounds.top())
    return path, path.boundingRect().adjusted(-stroke, -stroke, stroke, stroke), stroke


def compose_subtitles(image: QImage, document: SubtitleDocument, source_ms: float,
                      *, placeholders: bool = False) -> QImage:
    """Return a painted copy without mutating the decoded animation frame."""
    output = image.convertToFormat(QImage.Format_ARGB32_Premultiplied).copy()
    if output.isNull():
        return output
    painter = QPainter(output)
    painter.setRenderHint(QPainter.Antialiasing)
    for caption in document.captions:
        if not caption.visible_at(source_ms) or (not caption.text and not placeholders):
            continue
        drawn = caption if caption.text else replace(caption, text="Your text here")
        path, _bounds, stroke = caption_path(drawn, image.width(), image.height())
        # Paint the fill last so a thin glyph is not swallowed by its outline.
        painter.strokePath(path, QPen(QColor("#000000"), stroke * 2))
        painter.fillPath(path, QColor(drawn.color))
    painter.end()
    return output
