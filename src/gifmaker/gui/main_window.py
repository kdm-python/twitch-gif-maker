"""Main application window scaffold for the gifmaker GUI."""

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gifmaker.video.probe import VideoProbeError, probe_video


class MainWindow(QMainWindow):
    """Primary window scaffold for video/GIF import and export workflows."""

    def __init__(self) -> None:
        super().__init__()
        self.current_video_path: str | None = None

        self.setWindowTitle("GIF Maker")
        self.resize(1100, 760)

        self.create_menu()
        self.build_layout()
        logger.info("Main window initialized.")

    def create_menu(self) -> None:
        """Create the top-level menu structure."""
        menu_bar = self.menuBar()
        menu_bar.addMenu("File")
        menu_bar.addMenu("Edit")
        menu_bar.addMenu("View")
        menu_bar.addMenu("Help")

    def create_preview_panel(self) -> QGroupBox:
        """Create the expandable preview section."""
        group = QGroupBox("Video Preview")
        layout = QVBoxLayout(group)

        preview_placeholder = QLabel("Preview area placeholder")
        preview_placeholder.setAlignment(Qt.AlignCenter)
        preview_placeholder.setMinimumHeight(260)
        preview_placeholder.setStyleSheet("border: 1px dashed palette(mid);")

        layout.addWidget(preview_placeholder)
        return group

    def create_timeline_panel(self) -> QGroupBox:
        """Create a fixed-height timeline placeholder section."""
        group = QGroupBox("Timeline")
        group.setFixedHeight(170)

        layout = QVBoxLayout(group)
        timeline_placeholder = QLabel("Timeline placeholder")
        timeline_placeholder.setAlignment(Qt.AlignCenter)
        timeline_placeholder.setStyleSheet("border: 1px dashed palette(mid);")

        layout.addWidget(timeline_placeholder)
        return group

    def create_export_panel(self) -> QGroupBox:
        """Create export settings with placeholder controls."""
        group = QGroupBox("Export")

        root_layout = QVBoxLayout(group)
        form_layout = QFormLayout()

        start_input = QLineEdit()
        start_input.setPlaceholderText("e.g. 00:00:00")

        end_input = QLineEdit()
        end_input.setPlaceholderText("e.g. 00:00:05")

        fps_input = QSpinBox()
        fps_input.setRange(1, 120)
        fps_input.setValue(24)

        width_input = QSpinBox()
        width_input.setRange(1, 8192)
        width_input.setValue(640)

        form_layout.addRow("Start", start_input)
        form_layout.addRow("End", end_input)
        form_layout.addRow("FPS", fps_input)
        form_layout.addRow("Width", width_input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(QPushButton("Export GIF"))

        root_layout.addLayout(form_layout)
        root_layout.addLayout(button_row)

        return group

    def build_layout(self) -> None:
        """Assemble all panels into the window's central widget."""
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        open_button = QPushButton("Open Video File")
        open_button.clicked.connect(self.open_file_dialog)
        root_layout.addWidget(open_button)

        video_info_group = self.create_video_info_panel()
        root_layout.addWidget(video_info_group)

        preview_group = self.create_preview_panel()
        timeline_group = self.create_timeline_panel()
        export_group = self.create_export_panel()

        root_layout.addWidget(preview_group, stretch=1)
        root_layout.addWidget(timeline_group)
        root_layout.addWidget(export_group)

        self.setCentralWidget(central)

    def create_video_info_panel(self) -> QGroupBox:
        """Create a panel to display video metadata."""
        group = QGroupBox("Video Information")
        layout = QFormLayout(group)

        self.video_info_labels: dict[str, QLabel] = {
            "File": QLabel("-"),
            "Duration": QLabel("-"),
            "Resolution": QLabel("-"),
            "FPS": QLabel("-"),
            "Codec": QLabel("-"),
        }

        for label, widget in self.video_info_labels.items():
            layout.addRow(label, widget)

        return group

    def update_video_info(
        self,
        file_path: str,
        *,
        duration: float,
        width: int,
        height: int,
        fps: float,
        codec: str,
    ) -> None:
        """Update the video information panel with probed metadata."""
        self.video_info_labels["File"].setText(file_path)
        self.video_info_labels["Duration"].setText(f"{duration:.2f} s")
        self.video_info_labels["Resolution"].setText(f"{width}x{height}")
        self.video_info_labels["FPS"].setText(f"{fps:.2f}")
        self.video_info_labels["Codec"].setText(codec)

    def open_file_dialog(self) -> None:
        """Open a file dialog to select a video file."""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        file_dialog.setNameFilter("Video Files (*.mp4 *.avi *.mov)")
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.current_video_path = selected_files[0]
                logger.info("Selected file: {}", self.current_video_path)
                try:
                    video_info = probe_video(self.current_video_path)
                except VideoProbeError as exc:
                    logger.error(
                        "Failed to probe selected video '{}': {}",
                        self.current_video_path,
                        exc,
                    )
                    return

                self.update_video_info(
                    self.current_video_path,
                    duration=video_info.duration,
                    width=video_info.width,
                    height=video_info.height,
                    fps=video_info.fps,
                    codec=video_info.codec,
                )
            else:
                logger.info("No file selected.")
        else:
            logger.info("File dialog cancelled.")
