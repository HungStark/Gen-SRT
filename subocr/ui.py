from __future__ import annotations

import copy
from dataclasses import replace
import logging
from pathlib import Path
import threading
import zipfile

import cv2
from PySide6.QtCore import Qt, QThread, Signal, QRectF, QSize, QEvent, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QFontDatabase, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QComboBox, QCheckBox, QDoubleSpinBox, QSlider, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSizePolicy,
    QPlainTextEdit, QGroupBox, QAbstractItemView, QListWidget, QListWidgetItem,
    QSplitter, QDialog, QDialogButtonBox, QStyledItemDelegate, QMenu,
)

from .core import OcrEngine, Settings, write_srt, timestamp
from .editing import parse_time, cue_errors, consecutive_rows, merge_cues
from .review import EnglishSpellChecker, ACCEPTED_WORDS_PATH, accepted_words, review_rows, confidence_label
from .video import extract, Cancelled, ScanStats
from .colab import export_bundle, load_result


class VideoCanvas(QWidget):
    roi_changed = Signal()
    color_picked = Signal(tuple)
    open_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.frame = self.roi = self.drag_start = None
        self.lines = []

    def sizeHint(self):
        return QSize(520, 300)

    def display_rect(self):
        if self.frame is None:
            return QRectF()
        h, w = self.frame.shape[:2]
        scale = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * scale) / 2, (self.height() - h * scale) / 2, w * scale, h * scale)

    def image_point(self, pos):
        rect = self.display_rect()
        h, w = self.frame.shape[:2]
        return (min(w - 1, max(0, round((pos.x() - rect.x()) * w / rect.width()))),
                min(h - 1, max(0, round((pos.y() - rect.y()) * h / rect.height()))))

    def set_frame(self, frame):
        self.frame, self.lines = frame, []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setClipRect(self.rect())
        painter.fillRect(self.rect(), QColor('#f3f6f9' if self.frame is None else '#10151c'))
        if self.frame is None:
            painter.setPen(QColor('#273347'))
            painter.drawText(self.rect().adjusted(20, 12, -20, -12), Qt.AlignCenter | Qt.TextWordWrap,
                             'Kéo thả video vào đây\nhoặc bấm để chọn video từ thiết bị')
            return
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
        rect = self.display_rect()
        painter.drawImage(rect, image)
        sx, sy = rect.width() / w, rect.height() / h

        def mapped(x, y, rw, rh):
            return QRectF(rect.x() + x * sx, rect.y() + y * sy, rw * sx, rh * sy)

        if self.roi:
            painter.setPen(QPen(QColor('#f4bd4b'), 2))
            painter.drawRect(mapped(*self.roi))
            x, y, _, _ = self.roi
            for line in self.lines:
                left, top, right, bottom = line.box
                painter.setPen(QPen(QColor('#27d6a1' if line.accepted else '#ff6c77'), 2))
                painter.drawRect(mapped(x + left, y + top, right - left, bottom - top))

    def mousePressEvent(self, event):
        if self.frame is None:
            if event.button() == Qt.LeftButton:
                self.open_requested.emit()
            return
        if not self.isEnabled() or not self.display_rect().contains(event.position()):
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


class VideoViewport(QWidget):
    """Prefer full-width 16:9, fitting a smaller canvas on short windows."""
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        canvas.setParent(self)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumSize(260, 147)

    def sizeHint(self):
        return QSize(520, self.heightForWidth(520))

    def heightForWidth(self, width):
        return round(width * 9 / 16)

    def resizeEvent(self, event):
        width = min(self.width(), round(self.height() * 16 / 9))
        height = min(self.height(), round(width * 9 / 16))
        self.canvas.setGeometry((self.width() - width) // 2, 0, width, height)
        super().resizeEvent(event)


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float, float, int, str)

    def __init__(self, mode, source, cfg, engine=None):
        super().__init__()
        self.mode, self.source, self.cfg, self.engine = mode, source, cfg, engine
        self.cancel, self.stats = threading.Event(), ScanStats()

    def run(self):
        try:
            if self.engine is None:
                self.engine = OcrEngine()
            if self.cancel.is_set():
                raise Cancelled()
            result = self.engine.read(self.source, self.cfg) if self.mode == 'preview' else extract(
                self.source, self.cfg, self.engine, self.cancel,
                lambda *values: self.progress.emit(*values), stats=self.stats)
            self.done.emit((self.engine, result, self.mode))
        except Cancelled:
            self.failed.emit('Đã dừng lượt quét. Kết quả trước đó vẫn được giữ.')
        except Exception as error:
            logging.exception('OCR failed')
            self.failed.emit(str(error))


class ContentDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 2:
            editor = QPlainTextEdit(parent)
            editor.setPlaceholderText('Nhập phụ đề · Ctrl+Enter để lưu')
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QPlainTextEdit):
            editor.setPlainText(index.data(Qt.EditRole) or '')
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QPlainTextEdit):
            model.setData(index, editor.toPlainText(), Qt.EditRole)
        else:
            super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, option, index):
        rect = option.rect
        if isinstance(editor, QPlainTextEdit):
            height = min(editor.parentWidget().height(), max(90, rect.height()))
            rect.setTop(max(0, min(rect.top(), editor.parentWidget().height() - height)))
            rect.setHeight(height)
        editor.setGeometry(rect)

    def eventFilter(self, editor, event):
        if isinstance(editor, QPlainTextEdit) and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ControlModifier:
                    self.commitData.emit(editor)
                    self.closeEditor.emit(editor)
                    return True
                return False
        return super().eventFilter(editor, event)


class MergeDialog(QDialog):
    def __init__(self, cues, rows, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.setWindowTitle('Gộp các đoạn liền nhau')
        available = (parent.screen() if parent else QApplication.primaryScreen()).availableGeometry()
        self.resize(min(600, available.width() - 40), min(460, available.height() - 60))
        layout = QVBoxLayout(self)
        heading = QLabel(f'Gộp {len(rows)} đoạn · {timestamp(min(cues[r].start for r in rows))} '
                         f'→ {timestamp(max(cues[r].end for r in rows))}')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(QLabel('Chọn một đoạn làm nội dung cho đoạn gộp:'))
        self.choices = QListWidget()
        self.choices.setWordWrap(True)
        for row in rows:
            cue = cues[row]
            item = QListWidgetItem(f'Đoạn {row + 1} · {timestamp(cue.start)} → {timestamp(cue.end)}\n{cue.text}')
            self.choices.addItem(item)
        layout.addWidget(self.choices, 1)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(110)
        layout.addWidget(self.preview)
        self.choices.currentRowChanged.connect(lambda index: self.preview.setPlainText(cues[rows[index]].text) if index >= 0 else None)
        self.choices.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Gộp')
        buttons.button(QDialogButtonBox.Cancel).setText('Hủy')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def content_row(self):
        index = self.choices.currentRow()
        return self.rows[index] if index >= 0 else None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SubLens · Video → SRT')
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        self.resize(min(1240, available.width() - 32) if available else 1240,
                    min(820, available.height() - 56) if available else 820)
        self.setAcceptDrops(True)
        self.capture = self.video_path = self.engine = self.worker = None
        self.duration = self.current_time = 0.
        self.preview_bands, self.preview_lines, self.cues, self.undo_stack = [], [], [], []
        self.selected_color = self.last_scan_stats = None
        self.result_language = 'zh'
        self.spell_checker = EnglishSpellChecker()
        self._rendering = self.close_pending = False

        base = QWidget()
        self.setCentralWidget(base)
        root = QVBoxLayout(base)
        root.setContentsMargins(10, 10, 10, 8)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.left_panel = QWidget()
        left = QVBoxLayout(self.left_panel)
        left.setContentsMargins(0, 0, 4, 0)
        left.setSpacing(5)
        files = QHBoxLayout()
        self.open_button = QPushButton('Chọn video…')
        self.open_button.clicked.connect(self.choose_file)
        files.addWidget(self.open_button)
        self.file_label = QLabel('Chưa chọn video')
        self.file_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        files.addWidget(self.file_label, 1)
        self.options_button = QPushButton('Tùy chọn…')
        files.addWidget(self.options_button)
        self.colab_button = QPushButton('Colab GPU')
        colab_menu = QMenu(self.colab_button)
        colab_menu.setObjectName('colabMenu')
        self.colab_export_action = colab_menu.addAction('1. Xuất gói chạy Colab…')
        self.colab_export_action.triggered.connect(self.export_colab)
        self.colab_import_action = colab_menu.addAction('2. Nhập kết quả Colab…')
        self.colab_import_action.triggered.connect(self.import_colab)
        self.colab_button.setMenu(colab_menu)
        self.colab_button.setToolTip('Quét trên Colab, sau đó mang kết quả về chỉnh sửa trong app.')
        files.addWidget(self.colab_button)
        left.addLayout(files)
        self.canvas = VideoCanvas()
        self.canvas.open_requested.connect(self.choose_file)
        self.canvas.roi_changed.connect(self.invalidate_preview)
        self.canvas.color_picked.connect(self.pick_color)
        self.video_viewport = VideoViewport(self.canvas)
        left.addWidget(self.video_viewport)
        hint = QLabel('Kéo chuột trái: khoanh vùng sub · Chuột phải trên chữ: chọn màu')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        left.addWidget(hint)
        timeline = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek)
        timeline.addWidget(self.slider, 1)
        self.time_label = QLabel(timestamp(0))
        timeline.addWidget(self.time_label)
        left.addLayout(timeline)
        controls = QHBoxLayout()
        self.language = QComboBox()
        self.language.setObjectName('languageSelector')
        self.language.setItemDelegate(QStyledItemDelegate(self.language))
        self.language.addItem('Tiếng Trung', 'zh')
        self.language.addItem('Tiếng Anh', 'en')
        self.language.setToolTip('Ngôn ngữ xuất SRT · mặc định tiếng Trung')
        self.language.currentIndexChanged.connect(self.invalidate_preview)
        self.preview_button = QPushButton('Đọc thử khung hình')
        self.preview_button.clicked.connect(self.preview)
        self.run_button = QPushButton('Đọc cả video')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_video)
        for widget in (self.language, self.preview_button, self.run_button):
            widget.setMinimumHeight(34)
            controls.addWidget(widget, 1)
        left.addLayout(controls)
        self.preview_group = QGroupBox('Nội dung đọc thử')
        self.preview_group.setObjectName('previewGroup')
        self.preview_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        preview_layout = QVBoxLayout(self.preview_group)
        preview_layout.setContentsMargins(6, 8, 6, 6)
        preview_layout.setSpacing(4)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(48)
        self.log.setMaximumHeight(68)
        self.log.setPlaceholderText('Nội dung đọc thử hiển thị ở đây.\n\nTua tới đoạn có sub, khoanh vùng chữ rồi bấm Đọc thử khung hình.')
        preview_layout.addWidget(self.log, 1)
        self.line_picker = QListWidget()
        self.line_picker.setMaximumHeight(44)
        self.line_picker.setWordWrap(True)
        self.line_picker.itemChanged.connect(self.select_bands)
        self.line_picker.setToolTip('Bỏ tích chữ trong cảnh; giữ các dòng phụ đề cần OCR.')
        self.line_picker.hide()
        preview_layout.addWidget(self.line_picker)
        left.addWidget(self.preview_group)
        left.addStretch(1)
        self.splitter.addWidget(self.left_panel)

        self.right_panel = QWidget()
        right = QVBoxLayout(self.right_panel)
        right.setContentsMargins(4, 0, 0, 0)
        heading = QHBoxLayout()
        self.result_label = QLabel('Phụ đề · 0 đoạn')
        self.result_label.setObjectName('heading')
        heading.addWidget(self.result_label, 1)
        self.export_button = QPushButton('Xuất SRT…')
        self.export_button.clicked.connect(self.export)
        heading.addWidget(self.export_button)
        right.addLayout(heading)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Bắt đầu', 'Kết thúc', 'Nội dung', 'Tin cậy'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(True)
        self.table.setItemDelegate(ContentDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 105)
        self.table.setColumnWidth(1, 105)
        self.table.setColumnWidth(3, 70)
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.itemChanged.connect(self.edit_cell)
        self.table.cellClicked.connect(self.jump_to_cue)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_menu)
        right.addWidget(self.table, 1)
        edit_actions = QHBoxLayout()
        self.edit_button = QPushButton('Sửa chữ')
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton('Xóa đoạn')
        self.delete_button.clicked.connect(self.delete_selected)
        self.merge_button = QPushButton('Gộp đoạn…')
        self.merge_button.clicked.connect(self.merge_selected)
        self.undo_button = QPushButton('Hoàn tác')
        self.undo_button.clicked.connect(self.undo)
        for widget in (self.edit_button, self.delete_button, self.merge_button, self.undo_button):
            edit_actions.addWidget(widget)
        edit_actions.addStretch()
        right.addLayout(edit_actions)
        edit_hint = QLabel('Nhấp đúp để sửa · Ctrl+Enter lưu chữ · Shift/Ctrl chọn nhiều đoạn\nGộp: chọn các đoạn liền nhau và chọn một nội dung giữ lại.')
        edit_hint.setWordWrap(True)
        edit_hint.setObjectName('muted')
        right.addWidget(edit_hint)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([600, 620])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        progress = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Chia để trị · quét 0,5 giây · %p%')
        progress.addWidget(self.progress_bar, 1)
        self.cancel_button = QPushButton('Dừng')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_job)
        progress.addWidget(self.cancel_button)
        root.addLayout(progress)
        self._build_options()
        self.options_button.clicked.connect(self.options_dialog.exec)
        self.delete_shortcut = QShortcut(QKeySequence.Delete, self.table)
        self.delete_shortcut.setContext(Qt.WidgetShortcut)
        self.delete_shortcut.activated.connect(self.delete_selected)
        self.undo_shortcut = QShortcut(QKeySequence.Undo, self.table)
        self.undo_shortcut.setContext(Qt.WidgetShortcut)
        self.undo_shortcut.activated.connect(self.undo)
        self.job_controls = [self.open_button, self.options_button, self.canvas, self.slider,
                             self.language, self.preview_button, self.run_button, self.colab_button]
        self.statusBar().showMessage('Quét 0,5 giây · chia đôi mốc đổi câu đến khoảng 0,1 giây')
        self.update_actions()

    def _build_options(self):
        self.options_dialog = QDialog(self)
        self.options_dialog.setWindowTitle('Tùy chọn OCR')
        self.options_dialog.resize(470, 450)
        layout = QVBoxLayout(self.options_dialog)
        self.lock_line = QCheckBox('Khóa vị trí dòng theo kết quả đọc thử')
        self.lock_line.setChecked(True)
        layout.addWidget(self.lock_line)
        row = QHBoxLayout()
        row.addWidget(QLabel('Ngưỡng tin cậy OCR:'))
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(.1, .99)
        self.confidence.setSingleStep(.05)
        self.confidence.setValue(.60)
        self.confidence.valueChanged.connect(self.invalidate_preview)
        row.addWidget(self.confidence)
        layout.addLayout(row)
        colors = QHBoxLayout()
        self.color_check = QCheckBox('Lọc theo màu mẫu')
        self.color_check.toggled.connect(self.invalidate_preview)
        colors.addWidget(self.color_check)
        self.color_label = QLabel('Chưa chọn màu')
        colors.addWidget(self.color_label)
        colors.addStretch()
        layout.addLayout(colors)
        explanation = QLabel('Bấm chuột phải vào phần màu đặc của nét chữ trên video để lấy mẫu.\n\n'
                             'Quét cố định mỗi 0,5 giây, chia đôi khi đổi chữ đến khoảng 0,1 giây. '
                             'Câu rất ngắn nằm giữa hai mẫu có thể bị bỏ sót.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(QLabel('Tên riêng / từ tiếng Anh được chấp nhận (mỗi dòng một tên):'))
        self.accepted_words_edit = QPlainTextEdit()
        self.accepted_words_edit.setMaximumHeight(90)
        self.accepted_words_edit.setPlaceholderText('Ví dụ: Kunzi\nSeko Ai')
        try:
            self._saved_accepted_words = ACCEPTED_WORDS_PATH.read_text(encoding='utf-8-sig')
        except OSError:
            logging.exception('Cannot load accepted spelling words')
            self._saved_accepted_words = ''
        self.accepted_words_edit.setPlainText(self._saved_accepted_words)
        self.spell_checker.accepted = accepted_words(self._saved_accepted_words)
        layout.addWidget(self.accepted_words_edit)
        spelling_hint = QLabel('Chỉ cảnh báo chính tả tiếng Anh, không tự sửa. '
                              'Tên có chữ hoa giữa câu và chữ viết tắt được bỏ qua. '
                              'Đỏ: <80% · Cam: nghi sai từ · Vàng: giống câu liền kề. '
                              'Rê chuột lên dòng để xem lý do.')
        spelling_hint.setWordWrap(True)
        layout.addWidget(spelling_hint)
        self.options_dialog.finished.connect(self.apply_accepted_words)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('Đóng')
        buttons.rejected.connect(self.options_dialog.reject)
        layout.addWidget(buttons)

    def apply_accepted_words(self, *args):
        text = self.accepted_words_edit.toPlainText()
        self.spell_checker.accepted = accepted_words(text)
        self.refresh_styles()
        if text != self._saved_accepted_words:
            try:
                ACCEPTED_WORDS_PATH.write_text(text, encoding='utf-8')
                self._saved_accepted_words = text
            except OSError as error:
                logging.exception('Cannot save accepted spelling words')
                QMessageBox.warning(self, 'Không lưu được danh sách từ',
                                    f'Danh sách vẫn áp dụng trong lần mở này.\n{error}')

    def invalidate_preview(self, *args):
        self.preview_bands, self.preview_lines = [], []
        self.line_picker.blockSignals(True)
        self.line_picker.clear()
        self.line_picker.blockSignals(False)
        self.line_picker.hide()
        self.canvas.lines = []
        self.canvas.update()

    def select_bands(self, *args):
        self.preview_bands = []
        if not self.canvas.roi:
            return
        h = self.canvas.roi[3]
        for row in range(self.line_picker.count()):
            item = self.line_picker.item(row)
            line = self.preview_lines[item.data(Qt.UserRole)]
            line.accepted = item.checkState() == Qt.Checked
            if line.accepted:
                self.preview_bands.append(((line.box[1] + line.box[3]) / (2 * h), (line.box[3] - line.box[1]) / h))
        self.canvas.update()

    def pick_color(self, color):
        self.selected_color = color
        self.color_label.setText('#%02X%02X%02X' % color)
        self.color_check.setChecked(True)
        self.invalidate_preview()
        self.statusBar().showMessage('Đã lấy màu chữ mẫu. Có thể tắt lọc màu trong Tùy chọn.')

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Mở video', '', 'Video (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.ts);;Tất cả (*)')
        if path:
            self.open_video(path)

    def open_video(self, path):
        capture = cv2.VideoCapture(str(path))
        ok, frame = capture.read()
        if not ok:
            capture.release()
            QMessageBox.warning(self, 'Không mở được video', 'Không đọc được tệp. Hãy thử MP4/H.264.')
            return
        if self.capture:
            self.capture.release()
        self.capture, self.video_path = capture, str(Path(path).resolve())
        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        self.duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, round((self.duration - 1 / fps) * 1000)))
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.current_time = 0.
        self.time_label.setText(timestamp(0))
        h, w = frame.shape[:2]
        self.canvas.roi = (0, int(h * .75), w, h - int(h * .75))
        self.canvas.set_frame(frame)
        self.invalidate_preview()
        self.cues, self.undo_stack, self.last_scan_stats = [], [], None
        self.fill_table()
        self.selected_color = None
        self.color_check.setChecked(False)
        self.color_label.setText('Chưa chọn màu')
        self.file_label.setText(Path(path).name)
        self.file_label.setToolTip(self.video_path)
        self.log.setPlainText('Tua đến đoạn có sub và kéo chuột khoanh sát vùng chữ. Sau đó bấm Đọc thử khung hình.')
        self.progress_bar.setValue(0)
        self.statusBar().showMessage(f'{w} × {h} · {self.duration:.1f} giây · chia để trị 0,5 giây')

    def seek(self, milliseconds):
        if self.capture:
            self.capture.set(cv2.CAP_PROP_POS_MSEC, milliseconds)
            ok, frame = self.capture.read()
            if ok:
                self.canvas.set_frame(frame)
                self.current_time = milliseconds / 1000
                self.time_label.setText(timestamp(self.current_time))

    def settings(self, use_bands=True):
        if self.canvas.frame is None or not self.canvas.roi:
            raise ValueError('Mở video rồi kéo chọn vùng có phụ đề.')
        if self.color_check.isChecked() and self.selected_color is None:
            raise ValueError('Bấm chuột phải lên nét chữ để chọn màu, hoặc tắt lọc màu trong Tùy chọn.')
        return Settings(self.canvas.roi, self.language.currentData(), interval=.5,
                        confidence=self.confidence.value(),
                        line_bands=copy.deepcopy(self.preview_bands) if use_bands and self.lock_line.isChecked() else [],
                        color=self.selected_color if self.color_check.isChecked() else None,
                        algorithm='adaptive', boundary_precision=.1)

    def preview(self):
        try:
            cfg = self.settings(use_bands=False)
        except ValueError as error:
            QMessageBox.information(self, 'Chọn vùng phụ đề', str(error))
            return
        self.start_job('preview', self.canvas.frame.copy(), cfg)

    def run_video(self):
        try:
            cfg = self.settings()
            if self.lock_line.isChecked() and not self.preview_bands:
                raise ValueError('Đọc thử ở khung hình có sub để khóa dòng, hoặc tắt khóa dòng trong Tùy chọn.')
        except ValueError as error:
            QMessageBox.information(self, 'Cần đọc thử', str(error))
            return
        self.commit_editor()
        self.start_job('video', self.video_path, cfg)

    def export_colab(self):
        if self.worker is not None:
            return
        try:
            cfg = self.settings()
            if self.lock_line.isChecked() and not self.preview_bands:
                raise ValueError('Đọc thử để khóa dòng, hoặc tắt khóa dòng trong Tùy chọn trước khi xuất gói.')
        except ValueError as error:
            QMessageBox.information(self, 'Cần chọn vùng phụ đề', str(error))
            return
        parent = QFileDialog.getExistingDirectory(self, 'Chọn nơi lưu gói Colab')
        if not parent:
            return
        try:
            h, w = self.canvas.frame.shape[:2]
            folder = export_bundle(parent, self.video_path, cfg, w, h, self.duration)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, 'Không xuất được gói Colab', str(error))
            return
        self.log.setPlainText(f'Gói Colab: {folder}\n'
                              'Mở SubLens_Colab.ipynb trên colab.research.google.com, chọn runtime GPU.\n'
                              'Chạy các ô, tải job.zip và chọn video gốc (từ Drive hoặc tải lên).\n'
                              'Tải result.sublens.json rồi chọn Colab GPU → Nhập kết quả Colab.')
        self.statusBar().showMessage(f'Đã xuất gói Colab: {folder}')
        QMessageBox.information(self, 'Đã xuất gói Colab',
                                f'Đã lưu tại:\n{folder}\n\n'
                                '1. Mở colab.research.google.com → Upload notebook → SubLens_Colab.ipynb.\n'
                                '2. Chọn Runtime → Change runtime type → GPU, chạy các ô theo thứ tự.\n'
                                '3. Tải job.zip và chọn video gốc theo hướng dẫn trong notebook.\n'
                                '4. Tải result.sublens.json rồi nhập về qua menu Colab GPU.\n\n'
                                'Gói không chứa video. Khi dùng Colab, video sẽ được xử lý trên máy chủ Google.')

    def import_colab(self):
        if self.worker is not None:
            return
        if not self.video_path:
            QMessageBox.information(self, 'Cần mở video', 'Mở video gốc trước khi nhập kết quả Colab.')
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Nhập kết quả Colab', '',
                                             'Kết quả SubLens (*.sublens.json);;JSON (*.json)')
        if not path:
            return
        try:
            cfg, cues, stats, device = load_result(path, self.video_path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Không nhập được kết quả Colab', str(error))
            return
        self.commit_editor()
        if self.cues and QMessageBox.question(self, 'Thay kết quả hiện tại?',
                                              'Nhập kết quả Colab sẽ thay danh sách phụ đề đang sửa. Tiếp tục?',
                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.cues, self.undo_stack = cues, []
        self.result_language = cfg.language
        self.last_scan_stats = stats
        self.fill_table()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.log.setPlainText(f'Đã nhập {len(cues)} đoạn từ kết quả Colab ({device.upper()}).\n'
                              f'OCR {stats.ocr_calls} lần · {stats.elapsed:.1f} giây. '
                              'Chỉnh sửa bảng bên phải rồi xuất SRT.'
                              + ('\nKhông tìm thấy sub phù hợp. Kiểm tra vùng chọn và ngôn ngữ.' if not cues else ''))
        self.statusBar().showMessage('Đã nhập kết quả Colab. Có thể sửa chữ, xóa, gộp và xuất SRT.')

    def start_job(self, mode, source, cfg):
        if self.worker is not None:
            return
        for widget in self.job_controls:
            widget.setEnabled(False)
        self.table.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.log.setPlainText('Đang khởi tạo OCR…' if self.engine is None else 'Đang đọc phụ đề…')
        self.worker = Worker(mode, source, cfg, self.engine)
        self.worker.done.connect(self.job_done)
        self.worker.failed.connect(self.job_failed)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.job_finished)
        self.update_actions()
        self.worker.start()

    def update_progress(self, time, total, count, text):
        self.progress_bar.setRange(0, 1000 if total else 0)
        if total:
            self.progress_bar.setValue(min(1000, int(time / total * 1000)))
        self.statusBar().showMessage(f'{timestamp(time)} / {timestamp(total)} · {count} đoạn · {text.replace(chr(10), " / ")}')

    def job_done(self, payload):
        self.engine, result, mode = payload
        if mode == 'preview':
            self.preview_lines, self.canvas.lines = result.lines, result.lines
            self.line_picker.blockSignals(True)
            self.line_picker.clear()
            for index, line in enumerate(result.lines):
                if line.accepted:
                    item = QListWidgetItem(f'Giữ dòng: {line.text}')
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked)
                    item.setData(Qt.UserRole, index)
                    self.line_picker.addItem(item)
            self.line_picker.blockSignals(False)
            self.line_picker.setVisible(self.line_picker.count() > 0)
            self.select_bands()
            self.log.setPlainText('\n'.join(f'{"GIỮ" if line.accepted else "LOẠI"} · {line.score:.0%} · {line.text}' for line in result.lines)
                                  or 'Không thấy chữ. Hãy thử khung hình khác hoặc khoanh lại vùng sub.')
            if not result.text and result.lines:
                self.log.appendPlainText('Kiểm tra ngôn ngữ, ngưỡng OCR hoặc màu mẫu trong Tùy chọn.')
            self.statusBar().showMessage('Đọc thử xong. Bỏ tích chữ trong cảnh nếu có, rồi bấm Đọc cả video.')
        else:
            self.cues, self.undo_stack = result, []
            self.result_language = self.worker.cfg.language
            self.last_scan_stats = self.worker.stats
            self.fill_table()
            stats = self.last_scan_stats
            self.log.setPlainText(f'Đã quét xong: {len(result)} đoạn. Chỉnh sửa ở bảng bên phải.\n'
                                  f'OCR {stats.ocr_calls} lần · {stats.elapsed:.1f} giây · bước quét 0,5 giây.')
            if stats.stabilized_reads or stats.merged_duplicates:
                self.log.appendPlainText(f'Ổn định {stats.stabilized_reads} kết quả OCR dao động; '
                                         f'gộp {stats.merged_duplicates} đoạn trùng liền nhau.')
            if not result:
                self.log.appendPlainText('Không tìm thấy sub phù hợp. Kiểm tra vùng chọn và ngôn ngữ.')
            self.statusBar().showMessage('Quét hoàn tất. Có thể sửa chữ, xóa hoặc gộp các đoạn liền nhau.')
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)

    def job_failed(self, message):
        self.log.setPlainText(message)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage('Lượt đọc đã dừng.')

    def job_finished(self):
        old, self.worker = self.worker, None
        old.deleteLater()
        for widget in self.job_controls:
            widget.setEnabled(True)
        self.table.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.update_actions()
        if self.close_pending:
            QTimer.singleShot(0, self.close)

    def cancel_job(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage('Đang dừng sau lượt OCR hiện tại…')

    def selected_rows(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows())

    def update_actions(self):
        ready = self.worker is None
        rows = self.selected_rows()
        self.export_button.setEnabled(ready and bool(self.cues))
        self.edit_button.setEnabled(ready and len(rows) == 1)
        self.delete_button.setEnabled(ready and bool(rows))
        self.merge_button.setEnabled(ready and consecutive_rows(rows))
        self.merge_button.setToolTip('Chọn ít nhất hai đoạn liền nhau bằng Shift/Ctrl để gộp.')
        self.undo_button.setEnabled(ready and bool(self.undo_stack))

    def fill_table(self, selected=None):
        self._rendering = True
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.cues))
        for row, cue in enumerate(self.cues):
            # Avoid showing "80%" rounded up on a row that is actually <80%.
            score = confidence_label(cue.confidence)
            values = [timestamp(cue.start), timestamp(cue.end), cue.text, 'Đã sửa' if cue.edited else score]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self._rendering = False
        self.table.resizeRowsToContents()
        self.refresh_styles()
        if selected is not None and self.cues:
            self.table.selectRow(min(selected, len(self.cues) - 1))
        self.update_actions()

    def refresh_styles(self):
        blocked = self.table.blockSignals(True)
        errors = cue_errors(self.cues)
        reviews = review_rows(self.cues, self.spell_checker)
        for row, (cue, review) in enumerate(zip(self.cues, reviews)):
            reasons = [*review.reasons, f'Điểm OCR gốc: {confidence_label(cue.confidence, detailed=True)}.']
            if cue.edited:
                reasons.append('Nội dung hoặc thời gian đã được sửa thủ công.')
            if row in errors:
                reasons.append('Lỗi cần sửa trước khi xuất: ' + errors[row])
            for col in range(4):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(QColor(review.color))
                    item.setForeground(QColor('#b42318' if row in errors and col < 3 else '#203047'))
                    item.setToolTip('\n'.join(reasons))
        review_count = len(set(errors) | {row for row, review in enumerate(reviews) if review.level != 'none'})
        self.result_label.setText(f'Phụ đề · {len(self.cues)} đoạn' + (f' · {review_count} cần kiểm tra' if review_count else ''))
        self.table.blockSignals(blocked)

    def store_undo(self):
        self.undo_stack.append(copy.deepcopy(self.cues))
        self.undo_stack = self.undo_stack[-30:]

    def edit_cell(self, item):
        if self._rendering or item.column() == 3 or item.row() >= len(self.cues):
            return
        row, col = item.row(), item.column()
        cue = self.cues[row]
        try:
            new = replace(cue, **({'start': parse_time(item.text())} if col == 0 else
                                  {'end': parse_time(item.text())} if col == 1 else {'text': item.text()}), edited=True)
        except ValueError as error:
            self.table.blockSignals(True)
            item.setText(timestamp(cue.start if col == 0 else cue.end))
            self.table.blockSignals(False)
            self.statusBar().showMessage(str(error))
            return
        if (new.start, new.end, new.text) == (cue.start, cue.end, cue.text):
            return
        self.store_undo()
        self.cues[row] = new
        self.table.blockSignals(True)
        if col in (0, 1):
            item.setText(timestamp(new.start if col == 0 else new.end))
        self.table.item(row, 3).setText('Đã sửa')
        self.table.blockSignals(False)
        self.table.resizeRowToContents(row)
        self.refresh_styles()
        self.update_actions()
        self.statusBar().showMessage(f'Đã sửa đoạn {row + 1}.')

    def commit_editor(self):
        focus = QApplication.focusWidget()
        if focus is not None and focus is not self.table and self.table.isAncestorOf(focus):
            self.table.setFocus()

    def edit_selected(self):
        rows = self.selected_rows()
        if len(rows) == 1 and self.worker is None:
            item = self.table.item(rows[0], 2)
            self.table.setCurrentItem(item)
            self.table.editItem(item)

    def delete_selected(self):
        if self.worker is not None:
            return
        self.commit_editor()
        rows = self.selected_rows()
        if not rows:
            return
        self.store_undo()
        for row in reversed(rows):
            del self.cues[row]
        self.fill_table(selected=rows[0])
        self.statusBar().showMessage(f'Đã xóa {len(rows)} đoạn. Có thể bấm Hoàn tác.')

    def merge_selected(self):
        if self.worker is not None:
            return
        self.commit_editor()
        rows = self.selected_rows()
        if not consecutive_rows(rows):
            self.statusBar().showMessage('Chọn ít nhất hai đoạn liền nhau để gộp.')
            return
        dialog = MergeDialog(self.cues, rows, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            updated = merge_cues(self.cues, rows, dialog.content_row)
        except ValueError as error:
            QMessageBox.warning(self, 'Không gộp được', str(error))
            return
        self.store_undo()
        self.cues = updated
        self.fill_table(selected=rows[0])
        self.statusBar().showMessage(f'Đã gộp {len(rows)} đoạn, giữ nội dung của đoạn {dialog.content_row + 1}.')

    def undo(self):
        if self.worker is None and self.undo_stack:
            self.commit_editor()
            rows = self.selected_rows()
            self.cues = self.undo_stack.pop()
            self.fill_table(selected=rows[0] if rows else 0)
            self.statusBar().showMessage('Đã hoàn tác thay đổi gần nhất.')

    def table_menu(self, pos):
        menu = QMenu(self)
        for button in (self.edit_button, self.delete_button, self.merge_button, self.undo_button):
            action = menu.addAction(button.text())
            action.setEnabled(button.isEnabled())
            action.triggered.connect(button.click)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def jump_to_cue(self, row, col):
        if 0 <= row < len(self.cues):
            self.slider.setValue(round(self.cues[row].start * 1000))

    def export(self):
        self.commit_editor()
        if not self.cues or self.worker is not None:
            return
        errors = cue_errors(self.cues)
        if errors:
            first = min(errors)
            self.table.selectRow(first)
            QMessageBox.warning(self, 'Cần kiểm tra thời gian hoặc nội dung', f'Đoạn {first + 1}: {errors[first]}')
            return
        suggested = str(Path(self.video_path).with_suffix(f'.{self.result_language}.srt'))
        dialog = QFileDialog(self, 'Xuất phụ đề SRT', suggested, 'SubRip (*.srt)')
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setDefaultSuffix('srt')
        if dialog.exec() != QDialog.Accepted:
            return
        path = dialog.selectedFiles()[0]
        try:
            write_srt(path, self.cues)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Không xuất được SRT', str(error))
            return
        self.statusBar().showMessage(f'Đã xuất {len(self.cues)} đoạn: {path}')

    def dragEnterEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() != '.srt':
                event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker is None and event.mimeData().hasUrls():
            path = event.mimeData().urls()[0].toLocalFile()
            if Path(path).suffix.lower() != '.srt':
                self.open_video(path)

    def closeEvent(self, event):
        if self.worker is not None:
            self.close_pending = True
            self.cancel_job()
            event.ignore()
        else:
            if self.capture:
                self.capture.release()
            event.accept()


STYLE = '''
QWidget { color: #203047; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 12px; }
QMainWindow, QDialog { background: #f7f9fc; }
QPushButton { background: #ffffff; border: 1px solid #cad3df; border-radius: 5px; padding: 7px 10px; }
QPushButton:hover { background: #eef4fb; border-color: #8fa7c0; }
QPushButton:disabled { color: #9aa5b3; background: #f2f4f7; border-color: #dce1e8; }
QPushButton#primary { background: #167968; color: white; border-color: #167968; font-weight: 600; }
QPushButton#primary:hover { background: #106253; }
QPushButton#primary:disabled { background: #b7ccc7; border-color: #b7ccc7; }
QComboBox, QDoubleSpinBox { background: white; padding: 5px; border: 1px solid #cad3df; border-radius: 4px; }
QMenu#colabMenu { background: #262b34; color: #ffffff; border: 1px solid #526174; padding: 4px; }
QMenu#colabMenu::item { color: #ffffff; padding: 7px 12px; }
QMenu#colabMenu::item:selected { color: #ffffff; background: #167968; }
QMenu#colabMenu::item:disabled { color: #ffffff; }
QComboBox#languageSelector QAbstractItemView { background: #262b34; color: #ffffff; border: 1px solid #526174; selection-background-color: #167968; selection-color: #ffffff; outline: none; }
QComboBox#languageSelector QAbstractItemView::item { color: #ffffff; background: #262b34; min-height: 26px; }
QComboBox#languageSelector QAbstractItemView::item:selected { color: #ffffff; background: #167968; }
QPlainTextEdit, QListWidget, QTableWidget { background: white; border: 1px solid #d5dce6; border-radius: 3px; selection-background-color: #c8e3f5; selection-color: #172b42; }
QGroupBox { border: 1px solid #d5dce6; border-radius: 5px; margin-top: 8px; padding: 10px 6px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #53657b; }
QGroupBox#previewGroup { margin-top: 6px; padding: 6px 4px 4px; }
QHeaderView::section { background: #edf2f8; padding: 8px 5px; border: none; border-bottom: 1px solid #d5dce6; font-weight: 600; }
QTableWidget { gridline-color: #e8edf3; }
QLabel#muted { color: #6a7b8f; font-size: 11px; }
QLabel#heading { font-weight: 600; font-size: 14px; }
QProgressBar { border: 1px solid #cad3df; border-radius: 4px; text-align: center; min-height: 25px; background: white; }
QProgressBar::chunk { background: #a8d9cd; }
QSlider::groove:horizontal { height: 4px; background: #d3dce8; }
QSlider::handle:horizontal { background: #167968; width: 12px; margin: -5px 0; border-radius: 6px; }
QSplitter::handle { background: #d5dce6; width: 5px; }
'''


def configure_app(application):
    for name in ('segoeui.ttf', 'msyh.ttc'):
        path = Path('C:/Windows/Fonts') / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    font = QFont()
    font.setFamilies(['Segoe UI', 'Microsoft YaHei'])
    application.setFont(font)
    application.setStyle('Fusion')
    application.setStyleSheet(STYLE)
