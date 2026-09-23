"""Export controls row and settings widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ExportControlsPanel(QWidget):
    """Compact export controls for render timing and target settings."""

    COMPACT_WIDTH_THRESHOLD = 900

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._compact_mode = False

        self.primary_layout = QHBoxLayout()
        self.primary_layout.setContentsMargins(0, 0, 0, 0)
        self.primary_layout.setSpacing(8)

        self.secondary_layout = QHBoxLayout()
        self.secondary_layout.setContentsMargins(0, 0, 0, 0)
        self.secondary_layout.setSpacing(8)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(8)

        self.export_start_input = QLineEdit()
        self.export_start_input.setPlaceholderText("MM:SS:CC")
        self.export_start_input.setFixedWidth(92)

        self.export_end_input = QLineEdit()
        self.export_end_input.setPlaceholderText("MM:SS:CC")
        self.export_end_input.setFixedWidth(92)

        self.output_speed_slider = QSlider(Qt.Horizontal)
        self.output_speed_slider.setRange(25, 300)
        self.output_speed_slider.setSingleStep(5)
        self.output_speed_slider.setPageStep(25)
        self.output_speed_slider.setTickInterval(25)
        self.output_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.output_speed_slider.setValue(100)
        self.output_speed_slider.setFixedWidth(150)
        self.output_speed_value_label = QLabel("1×")
        self.output_speed_value_label.setMinimumWidth(42)

        self.output_fps_combo = QComboBox()
        for fps in (12, 15, 24, 30, 60):
            self.output_fps_combo.addItem(f"{fps} FPS", fps)
        self.output_fps_combo.setCurrentIndex(self.output_fps_combo.findData(24))
        self.output_fps_combo.setFixedWidth(86)

        self.export_width_input = QSpinBox()
        self.export_width_input.setRange(1, 8192)
        self.export_width_input.setValue(640)
        self.export_width_input.setFixedWidth(92)

        self.generate_preview_button = QPushButton("Generate Preview")
        self.apply_crop_button = QPushButton("Apply Crop")
        self.reset_crop_button = QPushButton("Reset Crop")

        self.gif_preview_play_button = QPushButton("Play")
        self.gif_preview_pause_button = QPushButton("Pause")

        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["GIF", "WebP"])

        self.primary_row = QWidget(self)
        self.primary_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.primary_row.setLayout(self.primary_layout)
        self.button_row = QWidget(self)
        self.button_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.button_row.setLayout(self.secondary_layout)

        self.primary_layout.addWidget(QLabel("Start"))
        self.primary_layout.addWidget(self.export_start_input)
        self.primary_layout.addWidget(QLabel("End"))
        self.primary_layout.addWidget(self.export_end_input)
        self.primary_layout.addSpacing(8)
        self.primary_layout.addWidget(QLabel("Output speed"))
        self.primary_layout.addWidget(self.output_speed_slider)
        self.primary_layout.addWidget(self.output_speed_value_label)
        self.primary_layout.addWidget(QLabel("FPS"))
        self.primary_layout.addWidget(self.output_fps_combo)
        self.primary_layout.addWidget(QLabel("Width"))
        self.primary_layout.addWidget(self.export_width_input)
        self.primary_layout.addSpacing(8)
        self.primary_layout.addWidget(QLabel("Format"))
        self.primary_layout.addWidget(self.export_format_combo)
        self.primary_layout.addStretch(1)

        self.secondary_layout.addWidget(self.gif_preview_play_button)
        self.secondary_layout.addWidget(self.gif_preview_pause_button)
        self.secondary_layout.addStretch(1)
        self.secondary_layout.addWidget(self.generate_preview_button)
        self.secondary_layout.addWidget(self.apply_crop_button)
        self.secondary_layout.addWidget(self.reset_crop_button)

        self.root_layout.addWidget(self.primary_row)
        self.root_layout.addWidget(self.button_row)
        self._compact_mode = False
        self._apply_layout_mode()

    def resize(self, *args, **kwargs):
        result = super().resize(*args, **kwargs)
        self._apply_layout_mode(
            self.parentWidget().width() if self.parentWidget() else self.width()
        )
        return result

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_layout_mode(
            self.parentWidget().width() if self.parentWidget() else self.width()
        )

    def _apply_layout_mode(self, width: int | None = None) -> None:
        target_width = self.width() if width is None else width
        if (
            width is None
            and self.parentWidget() is not None
            and self.parentWidget().width() > 0
        ):
            target_width = self.parentWidget().width()

        compact = target_width < self.COMPACT_WIDTH_THRESHOLD
        self._compact_mode = compact
        self.button_row.setVisible(True)
        self.root_layout.invalidate()

    def bind_window(self, window) -> None:
        """Wire this panel to the main-window controller."""
        self.export_start_input.editingFinished.connect(window.on_export_start_adjusted)
        self.export_end_input.editingFinished.connect(window.on_export_end_adjusted)
        self.output_speed_slider.valueChanged.connect(window.on_output_speed_changed)
        self.generate_preview_button.clicked.connect(window.generate_gif_preview)
        self.apply_crop_button.clicked.connect(window.apply_crop_to_preview)
        self.reset_crop_button.clicked.connect(window.reset_preview_crop)
        self.gif_preview_play_button.clicked.connect(window.play_gif_preview)
        self.gif_preview_pause_button.clicked.connect(window.pause_gif_preview)
