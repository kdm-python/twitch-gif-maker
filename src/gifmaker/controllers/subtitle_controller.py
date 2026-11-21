"""Main-app handoff into the otherwise independent subtitle workspace."""
from loguru import logger
from PySide6.QtWidgets import QMessageBox


class SubtitleController:
    def __init__(self, window):
        self.window = window
        self.dialog = None

    def open(self):
        window = self.window
        if self.dialog is not None:
            self.dialog.raise_()
            return
        path = window._preview_temp_file
        if path is None or path.suffix.lower() != ".webp" or not path.is_file():
            QMessageBox.information(window, "Subtitles", "Generate a WebP output preview first.")
            return
        session = window.video_session_controller
        if session._load_future is not None or window._pending_video_path or session._clip_process:
            QMessageBox.information(window, "Subtitles", "Wait for the source to finish loading first.")
            return
        render = window.render_controller
        render.suspend_preview()
        window.pause_gif_preview()
        window.media_player.pause()
        if session._animation_player is not None:
            session._animation_player.pause()
        position = window.preview_controller.position_ms()
        self._shortcut_states = [(s, s.isEnabled()) for s in window.shortcut_manager.shortcuts.values()]
        for shortcut, _enabled in self._shortcut_states:
            shortcut.setEnabled(False)
        self._menu_enabled = window.menuBar().isEnabled()
        window.menuBar().setEnabled(False)
        try:
            from gifmaker.gui.subtitle_dialog import SubtitleDialog

            self.dialog = SubtitleDialog(path, position, window)
            self.dialog.finished.connect(self._finished)
            self.dialog.show()
        except Exception as exc:  # noqa: BLE001 - optional editor failures must leave the host usable
            logger.exception("Could not open subtitles")
            self._restore()
            QMessageBox.warning(window, "Could not open subtitles", str(exc))

    def _finished(self, *_args):
        dialog = self.dialog
        self._restore()
        if dialog is not None:
            dialog.deleteLater()

    def _restore(self):
        self.dialog = None
        for shortcut, enabled in self._shortcut_states:
            shortcut.setEnabled(enabled)
        self.window.menuBar().setEnabled(self._menu_enabled)
        self.window.render_controller.resume_preview()
        self.window.setFocus()
