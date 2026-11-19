"""Batch resolution conversion with proportional scale and center crop."""
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
                             QFileDialog, QLineEdit, QProgressBar, QMessageBox, QSpinBox, QComboBox)

from .resizing import ordered_paths, resize_videos, validate_size, ResizeCancelled


class ResizeWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, paths, parent, width, height):
        super().__init__()
        self.paths, self.output_parent, self.width, self.height = paths, parent, width, height
        self.cancel = threading.Event()

    def run(self):
        try:
            self.done.emit(resize_videos(self.paths, self.output_parent, self.width, self.height,
                                        self.cancel, self.progress.emit))
        except ResizeCancelled:
            self.failed.emit('Đã dừng. Các video hoàn thành vẫn được giữ trong thư mục kết quả.')
        except Exception as error:
            self.failed.emit(str(error))


class ResizeVideoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Đưa video về cùng kích thước')
        self.resize(680, 530)
        self.paths, self.worker, self.result_folder = [], None, None
        self.close_pending = False
        layout = QVBoxLayout(self)
        hint = QLabel('Giữ tỉ lệ hình, phóng/thu sao cho cả hai chiều đủ phủ kín khung đích, '
                      'sau đó cắt phần dư ở giữa. Không thêm viền, không kéo méo. '
                      'Nội dung ở rìa, kể cả chữ phụ đề, có thể bị cắt.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        size_row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem('Full HD · 1920 × 1080', (1920, 1080))
        self.preset.addItem('HD · 1280 × 720', (1280, 720))
        self.preset.addItem('Dọc · 1080 × 1920', (1080, 1920))
        self.preset.addItem('Tùy chỉnh', None)
        self.preset.currentIndexChanged.connect(self.apply_preset)
        size_row.addWidget(self.preset, 1)
        self.width_input, self.height_input = QSpinBox(), QSpinBox()
        self._setting_size = False
        for control, value in ((self.width_input, 1920), (self.height_input, 1080)):
            control.setRange(2, 8192)
            control.setSingleStep(2)
            control.setValue(value)
            control.setSuffix(' px')
            control.valueChanged.connect(self.mark_custom_size)
        size_row.addWidget(QLabel('Rộng:'))
        size_row.addWidget(self.width_input)
        size_row.addWidget(QLabel('Cao:'))
        size_row.addWidget(self.height_input)
        layout.addLayout(size_row)
        row = QHBoxLayout()
        self.add_button = QPushButton('Chọn video…')
        self.add_button.clicked.connect(self.add_videos)
        self.remove_button = QPushButton('Bỏ video đã chọn')
        self.remove_button.clicked.connect(self.remove_videos)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        self.files = QListWidget()
        self.files.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.files, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel('Lưu tại:'))
        self.destination = QLineEdit()
        self.destination.setPlaceholderText('Chọn thư mục lưu các video mới')
        self.browse_button = QPushButton('Chọn thư mục…')
        self.browse_button.clicked.connect(self.choose_destination)
        row.addWidget(self.destination, 1)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        layout.addWidget(self.progress_bar)
        self.status = QLabel('Mỗi video xuất riêng thành MP4, giữ âm thanh và tệp nguồn.')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.start_button = QPushButton('Chuyển kích thước')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton('Dừng')
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        self.open_button = QPushButton('Mở thư mục kết quả')
        self.open_button.clicked.connect(self.open_result)
        self.open_button.setEnabled(False)
        self.close_button = QPushButton('Đóng')
        self.close_button.clicked.connect(self.reject)
        for button in (self.start_button, self.stop_button, self.open_button, self.close_button):
            row.addWidget(button)
        layout.addLayout(row)

    def apply_preset(self):
        value = self.preset.currentData()
        if value:
            self._setting_size = True
            try:
                self.width_input.setValue(value[0])
                self.height_input.setValue(value[1])
            finally:
                self._setting_size = False

    def mark_custom_size(self):
        if not self._setting_size and self.preset.currentData() is not None:
            self.preset.setCurrentIndex(3)

    def refresh(self):
        self.paths = ordered_paths(self.paths)
        self.files.clear()
        for path in self.paths:
            self.files.addItem(f'{path.name}   —   {path.parent}')

    def add_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Chọn các video cần chuyển kích thước', '',
                                               'Video (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.ts)')
        self.paths.extend(Path(path) for path in paths)
        self.refresh()

    def remove_videos(self):
        removed = {index.row() for index in self.files.selectedIndexes()}
        self.paths = [path for index, path in enumerate(self.paths) if index not in removed]
        self.refresh()

    def choose_destination(self):
        folder = QFileDialog.getExistingDirectory(self, 'Chọn thư mục lưu video')
        if folder:
            self.destination.setText(folder)

    def set_busy(self, busy):
        for widget in (self.add_button, self.remove_button, self.destination, self.browse_button,
                       self.start_button, self.preset, self.width_input, self.height_input):
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)

    def start(self):
        if self.worker:
            return
        if not self.paths or not self.destination.text().strip():
            QMessageBox.information(self, 'Chọn video và thư mục', 'Chọn các video và thư mục lưu trước khi chuyển.')
            return
        try:
            validate_size(self.width_input.value(), self.height_input.value())
        except ValueError as error:
            QMessageBox.information(self, 'Kích thước không hợp lệ', str(error))
            return
        self.set_busy(True)
        self.open_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.worker = ResizeWorker(list(self.paths), self.destination.text().strip(),
                                   self.width_input.value(), self.height_input.value())
        self.worker.progress.connect(self.show_progress)
        self.worker.done.connect(self.finished_resize)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def show_progress(self, done, total, message):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status.setText(message)

    def finished_resize(self, payload):
        folder, videos = payload
        self.result_folder = folder
        self.status.setText(f'Hoàn thành {len(videos)} video. Lưu tại: {folder}')
        self.progress_bar.setValue(1000)
        self.open_button.setEnabled(True)

    def worker_finished(self):
        old, self.worker = self.worker, None
        old.deleteLater()
        self.set_busy(False)
        if self.close_pending:
            super().reject()

    def stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop_button.setEnabled(False)
            self.status.setText('Đang dừng chuyển kích thước…')

    def open_result(self):
        if self.result_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_folder)))

    def reject(self):
        if self.worker:
            self.close_pending = True
            self.stop()
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.close_pending = True
            self.stop()
            event.ignore()
        else:
            super().closeEvent(event)
