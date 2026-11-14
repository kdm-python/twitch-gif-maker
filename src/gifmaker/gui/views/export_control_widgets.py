"""Widget construction for the shared output controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
)


class SpeedControls:
    """Create the SpeedControls widgets independently of a layout."""

    def __init__(self) -> None:
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


class FpsControls:
    """Create the FpsControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.output_fps_combo = QComboBox()
        for fps in (12, 15, 24, 30, 60):
            self.output_fps_combo.addItem(f"{fps} FPS", fps)
        self.output_fps_combo.setCurrentIndex(self.output_fps_combo.findData(24))
        self.output_fps_combo.setFixedWidth(86)


class SizeControls:
    """Create the SizeControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.export_width_input = QSpinBox()
        self.export_width_input.setRange(1, 8192)
        self.export_width_input.setValue(640)
        self.export_width_input.setFixedWidth(92)

        self.export_height_input = QSpinBox()
        self.export_height_input.setRange(1, 8192)
        self.export_height_input.setValue(360)
        self.export_height_input.setFixedWidth(92)

        self.aspect_ratio_lock = QCheckBox("Lock")
        self.aspect_ratio_lock.setChecked(True)
        self.original_size_button = QPushButton("Original")


class WebPQualityControls:
    """Create the WebPQualityControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.quality_preset_combo = QComboBox()
        self.quality_preset_combo.addItem("Small file", "small")
        self.quality_preset_combo.addItem("Balanced", "balanced")
        self.quality_preset_combo.addItem("High quality", "high")
        self.quality_preset_combo.setCurrentIndex(
            self.quality_preset_combo.findData("balanced")
        )
        self.quality_preset_combo.setToolTip(
            "WebP quality: Small reduces file size; Balanced favours detail at "
            "a moderate size; High retains more detail and creates larger files."
        )
        self.quality_preset_combo.setFixedWidth(112)
        self.quality_label = QLabel("WebP quality")


class SharpnessControls:
    """Create the SharpnessControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.sharpness_combo = QComboBox()
        self.sharpness_combo.addItem("Off", "off")
        self.sharpness_combo.addItem("Mild", "mild")
        self.sharpness_combo.addItem("Strong", "strong")
        self.sharpness_combo.setCurrentIndex(self.sharpness_combo.findData("mild"))
        self.sharpness_combo.setFixedWidth(86)


class RenderActionControls:
    """Create the RenderActionControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.generate_preview_button = QPushButton("Generate Preview")
        self.apply_crop_button = QPushButton("Apply Crop")
        self.reset_crop_button = QPushButton("Reset Crop")


class PreviewPlaybackControls:
    """Create the PreviewPlaybackControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.gif_preview_play_button = QPushButton("Play")
        self.gif_preview_pause_button = QPushButton("Pause")


class FormatControls:
    """Create the FormatControls widgets independently of a layout."""

    def __init__(self) -> None:
        self.export_format_combo = QComboBox()
        # WebP provides materially better visual quality for the Discord use
        # case. GIF remains available as a compatibility fallback.
        self.export_format_combo.addItems(["WebP", "GIF"])


class ExportControlWidgets:
    """Compose the existing control groups for the output panel."""

    def __init__(self) -> None:
        self.groups = (SpeedControls(), FpsControls(), SizeControls(), WebPQualityControls(), SharpnessControls(), RenderActionControls(), PreviewPlaybackControls(), FormatControls())
        for group in self.groups:
            for name, widget in vars(group).items():
                setattr(self, name, widget)
