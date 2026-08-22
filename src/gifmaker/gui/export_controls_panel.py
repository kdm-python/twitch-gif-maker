"""Export controls row and settings widgets."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)


class ExportControlsPanel(QWidget):
    """Compact export controls for render timing and target settings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.export_start_input = QLineEdit()
        self.export_start_input.setPlaceholderText("MM:SS:CC")
        self.export_start_input.setFixedWidth(92)

        self.export_end_input = QLineEdit()
        self.export_end_input.setPlaceholderText("MM:SS:CC")
        self.export_end_input.setFixedWidth(92)

        self.playback_speed_combo = QComboBox()
        self.playback_speed_combo.addItem("0.5×", 0.5)
        self.playback_speed_combo.addItem("1×", 1.0)
        self.playback_speed_combo.addItem("1.5×", 1.5)
        self.playback_speed_combo.addItem("2×", 2.0)
        self.playback_speed_combo.addItem("3×", 3.0)
        self.playback_speed_combo.setCurrentIndex(1)
        self.playback_speed_combo.setFixedWidth(88)

        self.export_width_input = QSpinBox()
        self.export_width_input.setRange(1, 8192)
        self.export_width_input.setValue(640)
        self.export_width_input.setFixedWidth(92)

        self.generate_preview_button = QPushButton("Generate Preview")
        self.apply_crop_button = QPushButton("Apply Crop")
        self.reset_crop_button = QPushButton("Reset Crop")

        self.gif_preview_play_button = QPushButton("Play")
        self.gif_preview_pause_button = QPushButton("Pause")

        self._layout.addWidget(QLabel("Start"))
        self._layout.addWidget(self.export_start_input)
        self._layout.addWidget(QLabel("End"))
        self._layout.addWidget(self.export_end_input)
        self._layout.addSpacing(8)
        self._layout.addWidget(QLabel("Speed"))
        self._layout.addWidget(self.playback_speed_combo)
        self._layout.addWidget(QLabel("Width"))
        self._layout.addWidget(self.export_width_input)
        self._layout.addSpacing(8)

        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["GIF", "WebP"])
        self._layout.addWidget(QLabel("Format"))
        self._layout.addWidget(self.export_format_combo)
        self._layout.addSpacing(8)

        self._layout.addWidget(self.gif_preview_play_button)
        self._layout.addWidget(self.gif_preview_pause_button)
        self._layout.addStretch(1)
        self._layout.addWidget(self.generate_preview_button)
        self._layout.addWidget(self.apply_crop_button)
        self._layout.addWidget(self.reset_crop_button)

    def bind_window(self, window) -> None:
        """Wire this panel to the main-window controller."""
        self.export_start_input.editingFinished.connect(window.on_export_start_adjusted)
        self.export_end_input.editingFinished.connect(window.on_export_end_adjusted)
        self.generate_preview_button.clicked.connect(window.generate_gif_preview)
        self.apply_crop_button.clicked.connect(window.apply_crop_to_preview)
        self.reset_crop_button.clicked.connect(window.reset_preview_crop)
        self.gif_preview_play_button.clicked.connect(window.play_gif_preview)
        self.gif_preview_pause_button.clicked.connect(window.pause_gif_preview)
