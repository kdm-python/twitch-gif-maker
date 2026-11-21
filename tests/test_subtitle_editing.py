"""Caption data, composition, interaction and session persistence."""
import os
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gifmaker.models.render_settings import RenderSettings, RenderSpec
from gifmaker.models.subtitles import Caption, SubtitleDocument, SubtitleTiming
from gifmaker.services.subtitle_compositor import caption_path, compose_subtitles
from tests.test_subtitle_workspace import dispose, preview_window, wait_until


def test_source_time_mapping_preserves_action_after_trim_and_speed_changes():
    original = SubtitleTiming(1000, 8000, 2)
    caption = Caption(original.source_time(500), original.source_time(1500), text="Action")
    assert (caption.start_ms, caption.end_ms) == (2000, 4000)
    revised = SubtitleTiming(1500, 8000, .5)
    assert (revised.output_time(caption.start_ms), revised.output_time(caption.end_ms)) == (1000, 5000)
    assert caption.visible_at(2000)
    assert not caption.visible_at(4000)


def test_compositor_preserves_input_alpha_and_half_open_timing():
    app = QApplication.instance() or QApplication([])
    image = QImage(480, 240, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    original = image.copy()
    caption = Caption(100, 350, "A caption", size=.15)
    document = SubtitleDocument((caption,))
    assert compose_subtitles(image, document, 99) == original.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    drawn = compose_subtitles(image, document, 100)
    assert any(drawn.pixelColor(x, y) == Qt.white for x in range(480) for y in range(180, 240))
    assert drawn != compose_subtitles(image, document, 350)
    assert drawn.pixelColor(0, 0).alpha() == 0
    assert image == original
    empty = SubtitleDocument((replace(caption, text=""),))
    assert compose_subtitles(image, empty, 100) == compose_subtitles(image, empty, 1000)
    assert compose_subtitles(image, empty, 100, placeholders=True) != compose_subtitles(image, empty, 100)
    for styled in (replace(caption, bold=True), replace(caption, italic=True),
                   replace(caption, color="#808080"), replace(caption, size=.2)):
        assert compose_subtitles(image, SubtitleDocument((styled,)), 100) != drawn
    long = replace(caption, text="A very long caption " * 20, x=1, y=0)
    _path, bounds, _stroke = caption_path(long, 480, 240)
    assert bounds.left() >= -.01 and bounds.right() <= 480.01
    assert bounds.top() >= -.01 and bounds.bottom() <= 240.01
    app.processEvents()


def open_editor(app, window):
    window.open_subtitles()
    dialog = window.subtitle_controller.dialog
    wait_until(app, lambda: dialog.ready)
    dialog.activateWindow()
    dialog.setFocus()
    app.processEvents()
    return dialog


def test_typing_shortcut_letters_and_inline_click_editing():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    try:
        dialog = open_editor(app, window)
        original_selection = dialog.slider.selection()
        dialog.text_input.setFocus()
        app.processEvents()
        QTest.keyClicks(dialog.text_input, "l s c z x v b n p . , text")
        assert dialog.isVisible()
        assert dialog.document.captions[0].text == "l s c z x v b n p . , text"
        assert dialog.slider.selection() == original_selection
        assert not dialog.player.playing
        assert not any(shortcut.isEnabled() for shortcut in dialog.shortcuts)
        QTest.keyClick(dialog.text_input, Qt.Key_Return)
        app.processEvents()
        assert dialog.shortcuts[-1].isEnabled()
        rect = dialog.surface.caption_rect()
        assert not rect.isEmpty()
        QTest.mouseClick(dialog.surface, Qt.LeftButton, pos=rect.center().toPoint())
        assert dialog.surface.editor.isVisible()
        QTest.keyClicks(dialog.surface.editor, "Click edit l")
        assert dialog.document.captions[0].text == "Click edit l"
        assert dialog.text_input.text() == "Click edit l"
        assert dialog.isVisible()
        QTest.keyClick(dialog.surface.editor, Qt.Key_Return)
        app.processEvents()
        assert not dialog.surface.editor.isVisible()
        QTest.keyClick(dialog, Qt.Key_L)
        assert window.subtitle_controller.dialog is None
        assert window.subtitle_controller.document.captions[0].text == "Click edit l"
    finally:
        dispose(window)


def test_live_style_dragging_and_reopen_preserve_caption_without_changing_output():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    recipe = window._last_preview_spec
    try:
        dialog = open_editor(app, window)
        dialog._set_text("Move me")
        start = dialog.surface.caption_rect().center().toPoint()
        destination = start - QPoint(100, 90)
        QTest.mousePress(dialog.surface, Qt.LeftButton, pos=start)
        QTest.mouseMove(dialog.surface, destination)
        QTest.mouseRelease(dialog.surface, Qt.LeftButton, pos=destination)
        moved = dialog.document.captions[0]
        assert moved.x < .5 and moved.y < .9
        assert not dialog.surface.editor.isVisible()
        original_position = (moved.x, moved.y)
        dialog.resize(1050, 700)
        app.processEvents()
        assert (dialog.document.captions[0].x, dialog.document.captions[0].y) == original_position
        QTest.mouseClick(dialog.bold_button, Qt.LeftButton)
        QTest.mouseClick(dialog.italic_button, Qt.LeftButton)
        dialog.color_combo.setCurrentIndex(2)
        dialog.size_spin.setValue(12)
        dialog.slider.set_selection(1, 2)
        saved = dialog.document
        assert saved.captions[0].bold and saved.captions[0].italic
        assert saved.captions[0].color == "#808080"
        assert saved.captions[0].size == .12
        assert (saved.captions[0].start_ms, saved.captions[0].end_ms) == (100, 350)
        with patch.object(window.render_controller, "generate_gif_preview") as apply:
            dialog.close()
            assert apply.call_args.kwargs["spec"].subtitles == saved
        assert window._last_preview_spec == recipe
        assert window.preview_controller.position_ms() == 100
        reopened = open_editor(app, window)
        assert reopened.document == saved
        assert reopened.slider.selection() == (1, 2)
        assert reopened.text_input.text() == "Move me"
        assert reopened.bold_button.isChecked() and reopened.italic_button.isChecked()
        assert not window._preview_frame_timer.isActive()
    finally:
        dispose(window)


def test_reopen_remaps_source_range_using_displayed_recipe_not_live_controls():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    try:
        window._last_preview_spec = RenderSpec(window.current_video_path, "WebP", RenderSettings(1, 2.5, playback_speed=2))
        dialog = open_editor(app, window)
        dialog.slider.set_selection(1, 2)
        caption = dialog.document.captions[0]
        assert (caption.start_ms, caption.end_ms) == (1200, 1700)
        dialog.close()
        window._last_preview_spec = replace(window._last_preview_spec, settings=RenderSettings(.5, 3.5, playback_speed=4))
        reopened = open_editor(app, window)
        assert reopened.document.captions[0] == caption
        assert reopened.slider.selection() == (1, 2)  # Range displayed outward-snapped to actual boundaries.
        reopened.close()
        # A trimmed-out caption remains editable without silently rewriting its source range.
        window._last_preview_spec = replace(window._last_preview_spec, settings=RenderSettings(2, 3))
        outside = open_editor(app, window)
        assert outside.document.captions[0] == caption
        assert "outside" in outside.status.text()
        assert outside.surface.caption_rect().isEmpty()
        outside.close()
        window.subtitle_controller.reset()
        assert not window.subtitle_controller.document.captions
    finally:
        dispose(window)


def test_clicking_outside_text_and_size_inputs_restores_shortcuts():
    app = QApplication.instance() or QApplication([])
    window = preview_window()
    try:
        dialog = open_editor(app, window)
        for control in (dialog.text_input, dialog.size_spin, dialog.surface.editor):
            if control is dialog.surface.editor:
                QTest.mouseClick(dialog.surface, Qt.LeftButton, pos=dialog.surface.caption_rect().center().toPoint())
            else:
                control.setFocus()
            app.processEvents()
            assert not dialog.shortcuts[-1].isEnabled()
            # Blank canvas is not normally focusable on macOS.
            QTest.mouseClick(dialog.surface, Qt.LeftButton, pos=QPoint(10, 10))
            app.processEvents()
            assert dialog.shortcuts[-1].isEnabled()
            assert all(shortcut.isEnabled() for shortcut in dialog.shortcuts)
        for target in (dialog.bold_button, dialog.font_combo, dialog.status):
            dialog.text_input.setFocus()
            app.processEvents()
            QTest.mouseClick(target, Qt.LeftButton)
            if target is dialog.font_combo:
                dialog.font_combo.hidePopup()
            app.processEvents()
            assert dialog.shortcuts[-1].isEnabled()
        dialog.size_spin.setFocus()
        app.processEvents()
        QTest.keyClick(dialog.size_spin, Qt.Key_Return)
        assert dialog.shortcuts[-1].isEnabled()
        dialog.text_input.setFocus()
        app.processEvents()
        QTest.keyClicks(dialog.text_input, "l")
        assert dialog.isVisible() and dialog.document.captions[0].text == "l"
    finally:
        dispose(window)
