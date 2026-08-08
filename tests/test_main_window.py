import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGroupBox, QSplitter

from gifmaker.gui.main_window import MainWindow


def test_main_window_uses_splitter_for_resizable_preview_sections() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    central_layout = window.centralWidget().layout()
    resizable_container = central_layout.itemAt(2).widget()

    assert isinstance(resizable_container, QSplitter)
    assert resizable_container.count() == 3
    assert isinstance(resizable_container.widget(0), QGroupBox)
    assert isinstance(resizable_container.widget(1), QGroupBox)
    assert isinstance(resizable_container.widget(2), QGroupBox)

    app.quit()
