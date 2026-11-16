from __future__ import annotations

import copy
import logging
from pathlib import Path
import sys
import threading

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QFontDatabase, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QCheckBox, QDoubleSpinBox,
    QSlider, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QScrollArea, QLayout, QSizePolicy, QPlainTextEdit, QGroupBox, QAbstractItemView, QListWidget, QListWidgetItem,
)

from subocr.core import Cue, OcrEngine, Settings, write_srt, timestamp
from subocr.video import extract, Cancelled, ScanStats
from subocr.reference import read_reference_srt

ROOT = Path(__file__).resolve().parent


class VideoCanvas(QWidget):
    roi_changed = Signal()
    color_picked = Signal(tuple)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 200)
        self.setMaximumHeight(320)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.frame = None
        self.roi = None
        self.lines = []
        self.drag_start = None
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(640, 280)

    def display_rect(self):
        if self.frame is None:
            return QRectF()
        h, w = self.frame.shape[:2]
        scale = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * scale) / 2, (self.height() - h * scale) / 2,
                      w * scale, h * scale)

    def image_point(self, pos):
        rect = self.display_rect()
        if rect.isEmpty():
            return None
        h, w = self.frame.shape[:2]
        return (min(w - 1, max(0, round((pos.x() - rect.x()) * w / rect.width()))),
                min(h - 1, max(0, round((pos.y() - rect.y()) * h / rect.height()))))

    def set_frame(self, frame):
        self.frame = frame
        self.lines = []
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setClipRect(self.rect())
        p.fillRect(self.rect(), QColor('#0b1018'))
        if self.frame is None:
            p.setPen(QColor('#9daec5'))
            p.drawText(self.rect(), Qt.AlignCenter, 'Kéo thả video vào đây hoặc bấm “Mở video”')
            return
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
        rect = self.display_rect()
        p.drawImage(rect, image)
        sx, sy = rect.width() / w, rect.height() / h

        def mapped(box):
            x, y, rw, rh = box
            return QRectF(rect.x() + x * sx, rect.y() + y * sy, rw * sx, rh * sy)

        if self.roi:
            p.setPen(QPen(QColor('#ffce62'), 2))
            p.drawRect(mapped(self.roi))
            for line in self.lines:
                left, top, right, bottom = line.box
                x, y, _, _ = self.roi
                p.setPen(QPen(QColor('#4be3b1' if line.accepted else '#fa7b89'), 2))
                p.drawRect(mapped((x + left, y + top, right - left, bottom - top)))

    def mousePressEvent(self, event):
        if self.frame is None or not self.isEnabled() or not self.display_rect().contains(event.position()):
            return
        point = self.image_point(event.position())
        if event.button() == Qt.RightButton:
            x, y = point
            self.color_picked.emit(tuple(int(v) for v in self.frame[y, x, ::-1]))
        elif event.button() == Qt.LeftButton:
            self.drag_start = point

    def mouseMoveEvent(self, event):
        if self.drag_start is None:
            return
        x, y = self.drag_start
        ex, ey = self.image_point(event.position())
        self.roi = (min(x, ex), min(y, ey), abs(ex - x) + 1, abs(ey - y) + 1)
        self.lines = []
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag_start is not None:
            self.mouseMoveEvent(event)
            self.drag_start = None
            if self.roi[2] < 10 or self.roi[3] < 8:
                self.roi = None
            self.roi_changed.emit()


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float, float, int, str)

    def __init__(self, mode, source, cfg, engine=None):
        super().__init__()
        self.mode, self.source, self.cfg = mode, source, cfg
        self.engine = engine
        self.cancel = threading.Event()
        self.stats = ScanStats()

    def run(self):
        try:
            if self.engine is None:
                self.engine = OcrEngine()
            if self.cancel.is_set():
                raise Cancelled()
            if self.mode == 'preview':
                result = self.engine.read(self.source, self.cfg)
            else:
                result = extract(self.source, self.cfg, self.engine, self.cancel,
                                 lambda time, total, count, text: self.progress.emit(
                                     time, total, count, f'{text} · OCR {self.stats.ocr_calls} lần'), stats=self.stats)
            self.done.emit((self.engine, result, self.mode))
        except Cancelled:
            self.failed.emit('Đã dừng. Kết quả của lượt chạy này chưa được xuất.')
        except Exception as error:
            logging.exception('OCR failed')
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SubLens · Video → SRT')
        self.resize(1100, 820)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1100, available.width() - 40), min(820, available.height() - 60))
        self.setAcceptDrops(True)
        self.capture = None
        self.video_path = None
        self.duration = 0
        self.current_time = 0
        self.engine = None
        self.worker = None
        self.preview_bands = []
        self.preview_lines = []
        self.selected_color = None
        self.result_language = 'zh'
        self.cues = []
        self.last_scan_stats = None
        self.reference_path = None
        self.reference_spans = ()

        base = QWidget()
        self.setCentralWidget(base)
        layout = QVBoxLayout(base)
        layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel('SubLens  /  Nhận diện phụ đề từ video')
        title.setWordWrap(True)
        title.setStyleSheet('font-size: 21px; font-weight: 650; color: #edf5ff')
        layout.addWidget(title)
        top = QHBoxLayout()
        self.open_button = QPushButton('Mở video…')
        self.open_button.clicked.connect(self.choose_file)
        top.addWidget(self.open_button)
        self.file_label = QLabel('Chưa chọn video')
        self.file_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(self.file_label, 1)
        self.reference_button = QPushButton('SRT tham chiếu…')
        self.reference_button.clicked.connect(self.choose_reference)
        top.addWidget(self.reference_button)
        layout.addLayout(top)

        # Scroll the content instead of squeezing controls below their size hints.
        # The action buttons remain outside this area and are always accessible.
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.content_scroll, 1)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.content_scroll.setWidget(content)
        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = VideoCanvas()
        self.canvas.roi_changed.connect(self.invalidate_preview)
        self.canvas.color_picked.connect(self.pick_color)
        upper_layout.addWidget(self.canvas, 1)
        canvas_hint = QLabel('Kéo chuột trái: khoanh vùng sub  ·  Chuột phải trên nét chữ: chọn màu mẫu')
        canvas_hint.setWordWrap(True)
        upper_layout.addWidget(canvas_hint)
        timeline = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek)
        timeline.addWidget(self.slider, 1)
        self.time_label = QLabel('00:00:00,000')
        timeline.addWidget(self.time_label)
        upper_layout.addLayout(timeline)
        content_layout.addWidget(upper)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        options = QGroupBox('Thiết lập nhận diện')
        options_layout = QVBoxLayout(options)
        first = QHBoxLayout()
        first.addWidget(QLabel('Xuất ngôn ngữ:'))
        self.language = QComboBox()
        self.language.addItem('Tiếng Trung (mặc định)', 'zh')
        self.language.addItem('Tiếng Anh', 'en')
        self.language.currentIndexChanged.connect(self.invalidate_preview)
        first.addWidget(self.language)
        first.addWidget(QLabel('Chế độ:'))
        self.speed = QComboBox()
        self.speed.addItem('Chia đôi · quét 0,5 giây (mặc định)', .5)
        self.speed.addItem('Chia đôi nhanh · quét 1 giây', 1.)
        self.speed.addItem('Kỹ · OCR mọi khung hình (chậm)', 0.)
        self.speed.addItem('Cân bằng · OCR mỗi 0,12 giây', .12)
        self.speed.addItem('Nhanh · OCR mỗi 0,25 giây', .25)
        self.speed.setToolTip('Chia đôi: quét thưa, tìm mốc đổi câu đến khoảng 0,1 giây. Câu hoặc khoảng trống ngắn hơn bước quét có thể bị bỏ sót.')
        first.addWidget(self.speed, 1)
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(.1, .99)
        self.confidence.setSingleStep(.05)
        self.confidence.setValue(.60)
        self.confidence.valueChanged.connect(self.invalidate_preview)
        first.addWidget(QLabel('Ngưỡng OCR:'))
        first.addWidget(self.confidence)
        options_layout.addLayout(first)
        second = QHBoxLayout()
        self.lock_line = QCheckBox('Khóa vị trí dòng theo kết quả đọc thử')
        self.lock_line.setChecked(True)
        self.lock_line.setToolTip('Giảm nhầm chữ trong cảnh. Đọc thử ở đoạn có đủ các dòng cần giữ.')
        second.addWidget(self.lock_line)
        self.color_check = QCheckBox('Lọc theo màu mẫu')
        self.color_check.toggled.connect(self.invalidate_preview)
        second.addWidget(self.color_check)
        self.color_label = QLabel('Chưa chọn màu')
        second.addWidget(self.color_label)
        second.addStretch()
        self.preview_button = QPushButton('1. Đọc thử khung hình')
        self.preview_button.clicked.connect(self.preview)
        options_layout.addLayout(second)
        self.scan_hint = QLabel()
        self.scan_hint.setWordWrap(True)
        self.scan_hint.setStyleSheet('color: #94b5d9')
        options_layout.addWidget(self.scan_hint)
        self.speed.currentIndexChanged.connect(self.update_scan_hint)
        self.update_scan_hint()
        options.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lower_layout.addWidget(options)

        self.reference_group = QGroupBox('Mốc thời gian từ SRT bên ngoài')
        ref_layout = QVBoxLayout(self.reference_group)
        ref_top = QHBoxLayout()
        self.reference_enabled = QCheckBox('Dùng SRT tham chiếu')
        ref_top.addWidget(self.reference_enabled)
        self.reference_label = QLabel('Chưa chọn tệp · bấm SRT tham chiếu… ở phía trên')
        self.reference_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        ref_top.addWidget(self.reference_label, 1)
        self.reference_clear = QPushButton('Bỏ SRT')
        self.reference_clear.clicked.connect(self.clear_reference)
        ref_top.addWidget(self.reference_clear)
        ref_layout.addLayout(ref_top)
        ref_padding_row = QHBoxLayout()
        ref_padding_row.addWidget(QLabel('Đệm trước/sau mỗi mục (giây):'))
        self.reference_padding = QDoubleSpinBox()
        self.reference_padding.setRange(0, 15)
        self.reference_padding.setSingleStep(.1)
        self.reference_padding.setValue(.7)
        ref_padding_row.addWidget(self.reference_padding)
        padding_hint = QLabel('OCR xác nhận chữ và mốc; một mục tham chiếu có thể tách thành nhiều sub.')
        padding_hint.setWordWrap(True)
        ref_padding_row.addWidget(padding_hint, 1)
        ref_layout.addLayout(ref_padding_row)
        ref_outside_row = QHBoxLayout()
        self.reference_outside = QCheckBox('Quét bổ sung ngoài các khoảng SRT')
        self.reference_outside.setChecked(True)
        ref_outside_row.addWidget(self.reference_outside)
        ref_outside_row.addWidget(QLabel('Bước quét (giây):'))
        self.outside_interval = QDoubleSpinBox()
        self.outside_interval.setRange(.5, 10)
        self.outside_interval.setSingleStep(.5)
        self.outside_interval.setValue(2.)
        ref_outside_row.addWidget(self.outside_interval)
        ref_outside_row.addStretch()
        ref_layout.addLayout(ref_outside_row)
        self.reference_outside.setToolTip('Tìm thêm sub mà SRT bên ngoài bỏ sót. Tắt để chỉ OCR trong các khoảng đã mở rộng.')
        self.reference_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.reference_enabled.toggled.connect(self.update_reference_controls)
        self.reference_outside.toggled.connect(self.update_reference_controls)
        lower_layout.addWidget(self.reference_group)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(65)
        self.log.setPlaceholderText('Tua đến đoạn có sub, khoanh vùng sát các dòng rồi bấm Đọc thử. Khung xanh: giữ; đỏ: loại.')
        lower_layout.addWidget(self.log)
        self.line_picker = QListWidget()
        self.line_picker.setMaximumHeight(50)
        self.line_picker.setToolTip('Bỏ tích chữ trong cảnh; chỉ tích các dòng phụ đề cần giữ. Vị trí các dòng được tích sẽ dùng khi khóa dòng.')
        self.line_picker.itemChanged.connect(self.select_bands)
        lower_layout.addWidget(self.line_picker)
        actions = QHBoxLayout()
        actions.addWidget(self.preview_button)
        self.run_button = QPushButton('2. Nhận diện toàn video')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_video)
        actions.addWidget(self.run_button)
        self.cancel_button = QPushButton('Dừng')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_job)
        actions.addWidget(self.cancel_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        actions.addStretch(1)
        self.export_button = QPushButton('3. Xuất SRT…')
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        layout.addWidget(self.progress_bar)
        self.table = QTableWidget(0, 4)
        self.table.setMinimumHeight(150)
        self.table.setHorizontalHeaderLabels(['Bắt đầu (giây)', 'Kết thúc (giây)', 'Nội dung · bấm để sửa', 'Độ tin cậy'])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(3, 110)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellClicked.connect(self.jump_to_cue)
        lower_layout.addWidget(self.table, 1)
        table_hint = QLabel('Dòng vàng cần kiểm tra. Bấm một mục để xem video; sửa thời gian/nội dung trực tiếp trước khi xuất.')
        table_hint.setWordWrap(True)
        lower_layout.addWidget(table_hint)
        content_layout.addWidget(lower, 1)
        self.statusBar().showMessage('OCR chạy trên máy. Video không được tải lên dịch vụ bên ngoài.')
        self.job_controls = [self.open_button, self.canvas, self.slider, self.language, self.speed,
                             self.confidence, self.lock_line, self.color_check, self.preview_button, self.run_button,
                             self.line_picker, self.reference_button, self.reference_group]
        self.update_reference_controls()

    def update_scan_hint(self, *args):
        interval = self.speed.currentData()
        if interval >= .5:
            self.scan_hint.setText(f'Quét mỗi {interval:g} giây; chia đôi mốc đổi câu đến khoảng 0,1 giây. '
                                   'Câu hoặc khoảng trống ngắn hơn bước quét có thể bị bỏ sót.')
        elif interval == 0:
            self.scan_hint.setText('Đọc mọi khung hình. Phù hợp với câu rất ngắn; thời gian xử lý lâu hơn.')
        else:
            self.scan_hint.setText('Quét theo bước đã chọn; đọc các khung giữa hai mẫu khi thấy đổi câu.')
        if hasattr(self, 'reference_enabled') and self.reference_enabled.isChecked():
            self.scan_hint.setText('Trong khoảng SRT: ' + self.scan_hint.text())

    def update_reference_controls(self, *args):
        enabled = self.reference_enabled.isChecked()
        self.reference_padding.setEnabled(enabled)
        self.reference_outside.setEnabled(enabled)
        self.outside_interval.setEnabled(enabled and self.reference_outside.isChecked())
        self.reference_clear.setEnabled(self.reference_path is not None)
        self.update_scan_hint()

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Chọn SRT tham chiếu của video', '', 'SubRip (*.srt);;Tất cả (*)')
        if path:
            self.load_reference(path)

    def load_reference(self, path):
        try:
            spans = read_reference_srt(path)
        except (OSError, ValueError, UnicodeError) as error:
            QMessageBox.warning(self, 'Không đọc được SRT tham chiếu', str(error))
            return
        self.reference_path = str(Path(path).resolve())
        self.reference_spans = spans
        self.reference_label.setText(f'{Path(path).name} · {len(spans)} mục · đến {timestamp(max(end for _, end in spans))}')
        self.reference_label.setToolTip(self.reference_path)
        self.reference_enabled.setChecked(True)
        self.update_reference_controls()
        self.statusBar().showMessage('Đã nạp mốc SRT. Nội dung đầu ra sẽ được nhận diện từ hình ảnh video.')

    def clear_reference(self):
        self.reference_path, self.reference_spans = None, ()
        self.reference_enabled.setChecked(False)
        self.reference_label.setText('Chưa chọn tệp · bấm SRT tham chiếu… ở phía trên')
        self.reference_label.setToolTip('')
        self.update_reference_controls()

    def invalidate_preview(self, *args):
        self.preview_bands = []
        self.preview_lines = []
        self.line_picker.blockSignals(True)
        self.line_picker.clear()
        self.line_picker.blockSignals(False)
        self.canvas.lines = []
        self.canvas.update()

    def select_bands(self, *args):
        self.preview_bands = []
        if not self.canvas.roi:
            return
        h = self.canvas.roi[3]
        for row in range(self.line_picker.count()):
            item = self.line_picker.item(row)
            index = item.data(Qt.UserRole)
            line = self.preview_lines[index]
            line.accepted = item.checkState() == Qt.Checked
            if line.accepted:
                self.preview_bands.append(((line.box[1] + line.box[3]) / (2 * h),
                                           (line.box[3] - line.box[1]) / h))
        self.canvas.update()

    def pick_color(self, color):
        self.selected_color = color
        self.color_label.setText('#%02X%02X%02X' % color)
        self.color_label.setStyleSheet('color: rgb(%d,%d,%d); font-weight: bold' % color)
        self.color_check.setChecked(True)
        self.invalidate_preview()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Mở video', '', 'Video (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.ts);;Tất cả (*)')
        if path:
            self.open_video(path)

    def open_video(self, path):
        capture = cv2.VideoCapture(str(path))
        ok, frame = capture.read()
        if not ok:
            capture.release()
            QMessageBox.warning(self, 'Không mở được', 'Không đọc được video. Hãy thử MP4/H.264 hoặc kiểm tra tệp.')
            return
        if self.capture:
            self.capture.release()
        self.capture = capture
        self.video_path = str(Path(path).resolve())
        self.clear_reference()
        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        self.duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, int((self.duration - 1 / fps) * 1000)))
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.current_time = 0
        self.time_label.setText(timestamp(0))
        h, w = frame.shape[:2]
        self.canvas.roi = (0, int(h * .75), w, h - int(h * .75))
        self.canvas.set_frame(frame)
        self.invalidate_preview()
        self.cues = []
        self.table.setRowCount(0)
        self.export_button.setEnabled(False)
        self.selected_color = None
        self.color_check.setChecked(False)
        self.color_label.setText('Chưa chọn màu')
        self.color_label.setStyleSheet('')
        self.file_label.setText(Path(path).name)
        self.file_label.setToolTip(self.video_path)
        self.log.setPlainText('Đã mở video. Tua đến đoạn có sub và kéo chuột khoanh vùng sát chữ. Khung vàng là vùng OCR.')
        self.statusBar().showMessage(f'{w} × {h} · khoảng {self.duration:.1f} giây')

    def seek(self, milliseconds):
        if not self.capture:
            return
        self.capture.set(cv2.CAP_PROP_POS_MSEC, milliseconds)
        ok, frame = self.capture.read()
        if ok:
            self.canvas.set_frame(frame)
            self.current_time = milliseconds / 1000
            self.time_label.setText(timestamp(self.current_time))

    def settings(self, use_bands=True, use_reference=True):
        if self.canvas.frame is None or not self.canvas.roi:
            raise ValueError('Hãy mở video và kéo chọn vùng có phụ đề.')
        if self.color_check.isChecked() and self.selected_color is None:
            raise ValueError('Bấm chuột phải vào nét chữ để chọn màu, hoặc tắt lọc màu.')
        interval = self.speed.currentData()
        guided = use_reference and self.reference_enabled.isChecked()
        if guided and not self.reference_spans:
            raise ValueError('Hãy chọn tệp SRT tham chiếu, hoặc tắt Dùng SRT tham chiếu.')
        return Settings(self.canvas.roi, self.language.currentData(), interval,
                        self.confidence.value(), copy.deepcopy(self.preview_bands) if use_bands and self.lock_line.isChecked() else [],
                        self.selected_color if self.color_check.isChecked() else None,
                        algorithm='adaptive' if interval >= .5 else 'linear',
                        reference_spans=self.reference_spans if guided else None,
                        reference_padding=self.reference_padding.value(),
                        outside_interval=self.outside_interval.value() if self.reference_outside.isChecked() else None)

    def preview(self):
        try:
            cfg = self.settings(use_bands=False, use_reference=False)
        except ValueError as error:
            QMessageBox.information(self, 'Chọn vùng phụ đề', str(error))
            return
        self.start_job('preview', self.canvas.frame.copy(), cfg)

    def run_video(self):
        try:
            cfg = self.settings()
            if self.lock_line.isChecked() and not self.preview_bands:
                raise ValueError('Hãy đọc thử tại khung hình có phụ đề trước để khóa dòng, hoặc tắt khóa vị trí dòng.')
        except ValueError as error:
            QMessageBox.information(self, 'Cần đọc thử', str(error))
            return
        self.start_job('video', self.video_path, cfg)

    def start_job(self, mode, source, cfg):
        if self.worker is not None:
            return
        for widget in self.job_controls:
            widget.setEnabled(False)
        self.export_button.setEnabled(False)
        self.table.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.log.setPlainText('Đang khởi tạo mô hình OCR…' if self.engine is None else 'Đang nhận diện…')
        self.worker = Worker(mode, source, cfg, self.engine)
        self.worker.done.connect(self.job_done)
        self.worker.failed.connect(self.job_failed)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.job_finished)
        self.worker.start()

    def update_progress(self, time, total, count, text):
        self.progress_bar.setRange(0, 1000 if total else 0)
        if total:
            self.progress_bar.setValue(min(1000, int(time / total * 1000)))
        self.statusBar().showMessage(f'{timestamp(time)} / {timestamp(total)} · {count} mục đã ghép · {text.replace(chr(10), " / ")}')

    def job_done(self, payload):
        self.engine, result, mode = payload
        if mode == 'preview':
            self.preview_lines = result.lines
            self.canvas.lines = result.lines
            self.canvas.update()
            h = self.canvas.roi[3]
            self.preview_bands = [((line.box[1] + line.box[3]) / (2 * h), (line.box[3] - line.box[1]) / h)
                                  for line in result.lines if line.accepted]
            self.line_picker.blockSignals(True)
            self.line_picker.clear()
            for index, line in enumerate(result.lines):
                if not line.accepted:
                    continue
                item = QListWidgetItem(f'Giữ dòng ở y={line.box[1]}: {line.text}')
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setData(Qt.UserRole, index)
                self.line_picker.addItem(item)
            self.line_picker.blockSignals(False)
            details = ['GIỮ' if line.accepted else 'LOẠI' for line in result.lines]
            self.log.setPlainText('\n'.join(f'{tag} · {line.score:.0%} · {line.text}' for tag, line in zip(details, result.lines))
                                  or 'Không thấy chữ. Hãy chọn vùng khác hoặc khung hình rõ hơn.')
            if not result.text and result.lines:
                self.log.appendPlainText('Không có dòng phù hợp. Kiểm tra ngôn ngữ, màu mẫu và ngưỡng OCR.')
            self.statusBar().showMessage('Đọc thử xong. Kiểm tra khung xanh, khoanh vùng hẹp hơn nếu còn giữ chữ trong cảnh.')
        else:
            self.result_language = self.worker.cfg.language
            self.last_scan_stats = self.worker.stats
            self.cues = result
            self.fill_table()
            count = sum(cue.review for cue in self.cues)
            self.log.setPlainText(f'Hoàn tất: {len(self.cues)} mục, {count} mục cần kiểm tra. Sửa trong bảng rồi bấm Xuất SRT.'
                                  if result else 'Không tìm thấy phụ đề phù hợp. Kiểm tra vùng chọn, ngôn ngữ và khóa vị trí dòng.')
            stats = self.last_scan_stats
            self.log.appendPlainText(f'OCR {stats.ocr_calls} lần / {stats.decoded_frames} khung hình · '
                                     f'đọc thêm {stats.refinement_calls} frame để tìm mốc · '
                                     f'đọc lại {stats.retry_calls} lần · {stats.elapsed:.1f} giây.')
            if stats.uncertain_samples:
                self.log.appendPlainText(f'{stats.uncertain_samples} frame OCR chưa rõ; các mục liên quan được đánh dấu để xem lại.')
            if stats.reference_cues:
                self.log.appendPlainText(f'SRT tham chiếu: {stats.reference_cues} mục → {stats.reference_windows} khoảng OCR '
                                         f'({stats.reference_seconds:.1f} giây); lấy thêm {stats.outside_samples} mẫu ngoài khoảng.')
                if stats.unmatched_reference_cues:
                    self.log.appendPlainText(f'{stats.unmatched_reference_cues} mục tham chiếu không tìm thấy sub phù hợp; '
                                             'kiểm tra độ lệch thời gian hoặc tăng khoảng đệm.')
                if stats.window_edge_events:
                    self.log.appendPlainText(f'{stats.window_edge_events} lượt sub chạm biên khoảng OCR; '
                                             'các mục này được đánh dấu. Tăng đệm hoặc bật quét ngoài để kiểm tra tiếp.')
            self.statusBar().showMessage('Nhận diện hoàn tất. Chưa ghi tệp SRT.')
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)

    def job_failed(self, message):
        self.log.setPlainText(message)
        self.statusBar().showMessage('Lượt nhận diện đã dừng.')
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)

    def job_finished(self):
        old = self.worker
        self.worker = None
        old.deleteLater()
        for widget in self.job_controls:
            widget.setEnabled(True)
        self.update_reference_controls()
        self.table.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.export_button.setEnabled(bool(self.cues))

    def cancel_job(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.log.appendPlainText('Đang dừng sau lượt OCR hiện tại…')

    def fill_table(self):
        self.table.setRowCount(len(self.cues))
        for row, cue in enumerate(self.cues):
            for col, text in enumerate([f'{cue.start:.3f}', f'{cue.end:.3f}', cue.text,
                                        f'{cue.confidence:.0%}' + (' · xem lại' if cue.review else '')]):
                item = QTableWidgetItem(text)
                if col == 3:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if cue.review:
                    item.setBackground(QColor('#51431e'))
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    def jump_to_cue(self, row, col):
        try:
            self.slider.setValue(round(float(self.table.item(row, 0).text().replace(',', '.')) * 1000))
        except (ValueError, AttributeError):
            pass

    def export(self):
        try:
            cues = [Cue(float(self.table.item(row, 0).text().replace(',', '.')),
                        float(self.table.item(row, 1).text().replace(',', '.')),
                        self.table.item(row, 2).text()) for row in range(self.table.rowCount())]
        except (ValueError, AttributeError):
            QMessageBox.warning(self, 'Dữ liệu chưa hợp lệ', 'Thời gian phải là số giây, ví dụ 12.350.')
            return
        suffix = f'.ocr.{self.result_language}.srt' if self.last_scan_stats and self.last_scan_stats.reference_cues else f'.{self.result_language}.srt'
        suggested = str(Path(self.video_path).with_suffix(suffix))
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất phụ đề SRT', suggested, 'SubRip (*.srt)')
        if not path:
            return
        if not path.lower().endswith('.srt'):
            path += '.srt'
        try:
            write_srt(path, cues)
            self.statusBar().showMessage(f'Đã xuất {len(cues)} mục: {path}')
            self.log.appendPlainText(f'Đã lưu: {path}')
        except Exception as error:
            QMessageBox.warning(self, 'Không xuất được SRT', str(error))

    def dragEnterEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if Path(path).suffix.lower() == '.srt':
                self.load_reference(path)
            else:
                self.open_video(path)

    def closeEvent(self, event):
        if self.worker is not None:
            self.cancel_job()
            self.log.appendPlainText('Đợi nhận diện dừng rồi đóng ứng dụng.')
            event.ignore()
            return
        if self.capture:
            self.capture.release()
        event.accept()


STYLE = '''
QWidget { background: #141c29; color: #dce7f5; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 12px; }
QPushButton { background: #27364c; border: 1px solid #3b4b63; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { background: #354b67; }
QPushButton:disabled { color: #6c7c94; background: #1c2635; }
QPushButton#primary { background: #12695b; border-color: #288d79; }
QPushButton#primary:hover { background: #16816e; }
QPushButton#primary:disabled { background: #233b38; color: #759b93; }
QGroupBox { border: 1px solid #35445b; border-radius: 7px; margin-top: 10px; padding: 12px 9px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #94b5d9; }
QComboBox, QDoubleSpinBox { padding: 5px; border: 1px solid #43526b; border-radius: 4px; background: #202e42; }
QPlainTextEdit, QTableWidget { background: #101722; border: 1px solid #314159; border-radius: 5px; selection-background-color: #315474; }
QHeaderView::section { background: #25354a; color: #cedded; padding: 7px; border: none; }
QProgressBar { border: 1px solid #35455d; border-radius: 4px; text-align: center; min-height: 22px; }
QProgressBar::chunk { background: #248371; }
QSlider::groove:horizontal { background: #34435b; height: 5px; }
QSlider::handle:horizontal { background: #57d5b8; width: 13px; margin: -5px 0; border-radius: 6px; }
QSplitter::handle { background: #35445a; height: 4px; }
'''


def configure_app(application):
    # Explicit fonts also work when the offscreen Qt platform cannot enumerate system fonts.
    for name in ('segoeui.ttf', 'msyh.ttc'):
        path = Path('C:/Windows/Fonts') / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    font = QFont()
    font.setFamilies(['Segoe UI', 'Microsoft YaHei'])
    application.setFont(font)
    application.setStyle('Fusion')
    application.setStyleSheet(STYLE)


def main():
    logging.basicConfig(filename=ROOT / 'sublens.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
    application = QApplication(sys.argv)
    configure_app(application)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        window.open_video(sys.argv[1])
    return application.exec()


if __name__ == '__main__':
    sys.exit(main())
