from PySide6.QtWidgets import QApplication

from src.gifmaker.gui.main_window import MainWindow


def main() -> None:
    """Entry point for the gifmaker GUI application."""
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
