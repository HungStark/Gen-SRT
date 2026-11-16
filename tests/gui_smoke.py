import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog

from app import MainWindow, configure_app


def wait_job(app, window, timeout=90):
    limit = time.monotonic() + timeout
    while window.worker is not None:
        app.processEvents()
        time.sleep(.03)  # Release the GIL so the OCR worker can make progress.
        if time.monotonic() > limit:
            window.cancel_job()
            raise TimeoutError('GUI job did not finish')


def run():
    app = QApplication([])
    def fail_dialog(*args):
        raise AssertionError(f'Unexpected dialog: {args[1:]}')
    QMessageBox.information = fail_dialog
    QMessageBox.warning = fail_dialog
    configure_app(app)
    window = MainWindow()
    window.show()
    app.processEvents()
    window.open_video('test_artifacts/demo_dual.mp4')
    print('GUI opened video', flush=True)
    assert window.video_path and window.language.currentData() == 'zh'
    window.slider.setValue(800)
    app.processEvents()
    rect = window.canvas.display_rect()
    start = QPoint(round(rect.x() + rect.width() * .03), round(rect.y() + rect.height() * .76))
    end = QPoint(round(rect.x() + rect.width() * .97), round(rect.y() + rect.height() * .97))
    QTest.mousePress(window.canvas, Qt.LeftButton, pos=start)
    QTest.mouseMove(window.canvas, end)
    QTest.mouseRelease(window.canvas, Qt.LeftButton, pos=end)
    assert window.canvas.roi[1] > 400, window.canvas.roi
    window.preview()
    wait_job(app, window)
    print('GUI preview completed', window.log.toPlainText(), flush=True)
    assert window.preview_bands, window.log.toPlainText()
    assert window.line_picker.count() == 1
    window.slider.setValue(1000)
    item = window.line_picker.item(0)
    item.setCheckState(Qt.Unchecked)
    assert not window.preview_bands
    item.setCheckState(Qt.Checked)
    assert window.preview_bands
    assert window.speed.currentData() == .5
    assert window.settings().algorithm == 'adaptive'
    window.run_video()
    wait_job(app, window)
    print('GUI extraction completed', flush=True)
    assert len(window.cues) == 3, window.log.toPlainText()
    assert window.last_scan_stats.ocr_calls < window.last_scan_stats.decoded_frames
    assert window.export_button.isEnabled()
    assert window.table.item(0, 2).text() == '请所有同学立刻停止军训'
    window.grab().save('test_artifacts/app_preview.png')
    export_path = str(Path('test_artifacts/gui_export.zh.srt').resolve())
    QFileDialog.getSaveFileName = lambda *args: (export_path, 'SubRip (*.srt)')
    window.table.item(0, 2).setText(window.table.item(0, 2).text() + '。')
    window.export()
    assert Path(export_path).is_file()
    assert '请所有同学立刻停止军训。' in Path(export_path).read_text(encoding='utf-8-sig')
    # Changing language invalidates the learned line band.
    window.language.setCurrentIndex(1)
    assert not window.preview_bands
    window.slider.setValue(800)
    window.preview()
    wait_job(app, window)
    assert window.preview_bands
    assert 'All students' in window.log.toPlainText()
    reference = Path('test_artifacts/gui_reference.srt')
    reference.write_text('1\n00:00:00,900 --> 00:00:03,900\nWRONG REFERENCE TEXT\n', encoding='utf-8-sig')
    window.load_reference(reference)
    assert window.reference_enabled.isChecked()
    assert len(window.settings().reference_spans) == 1
    window.reference_outside.setChecked(False)
    assert not window.outside_interval.isEnabled()
    assert window.settings().outside_interval is None
    window.run_video()
    wait_job(app, window)
    assert len(window.cues) == 3, window.log.toPlainText()
    assert window.last_scan_stats.reference_cues == 1
    assert window.table.item(0, 2).text() == 'All students, stop training now.'
    assert 'WRONG' not in window.table.item(0, 2).text()
    window.content_scroll.ensureWidgetVisible(window.reference_group)
    app.processEvents()
    window.grab().save('test_artifacts/reference_ui.png')
    window.clear_reference()
    assert window.settings().reference_spans is None
    assert not window.reference_padding.isEnabled()
    window.close()
    print('GUI smoke passed: ROI, OCR, export, language switch, reference load, guided scan and clear.')


if __name__ == '__main__':
    run()
