from loguru import logger
from PySide6.QtWidgets import QApplication

from src.gifmaker.gui.main_window import MainWindow


def main() -> None:
    """Entry point for the gifmaker GUI application."""
    logger.info("Starting T10Nat GIF Maker...")
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
