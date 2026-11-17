import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app import MainWindow, configure_app


def wait_job(app, window, timeout=90):
    limit = time.monotonic() + timeout
    while window.worker is not None:
        app.processEvents()
        time.sleep(.03)
        if time.monotonic() > limit:
            window.cancel_job()
            raise TimeoutError('GUI job did not finish')


def run():
    app = QApplication([])
    configure_app(app)
    def fail_dialog(*args):
        raise AssertionError(f'Unexpected dialog: {args[1:]}')
    QMessageBox.information = fail_dialog
    QMessageBox.warning = fail_dialog
    window = MainWindow()
    window.resize(1200, 760)
    window.show()
    app.processEvents()
    window.open_video('test_artifacts/demo_dual.mp4')
    assert window.video_path and window.language.currentData() == 'zh'
    assert not hasattr(window, 'reference_enabled')
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
    assert window.preview_bands and window.line_picker.count() == 1, window.log.toPlainText()
    window.slider.setValue(1000)
    item = window.line_picker.item(0)
    item.setCheckState(Qt.Unchecked)
    assert not window.preview_bands
    item.setCheckState(Qt.Checked)
    assert window.preview_bands
    assert window.settings().interval == .5 and window.settings().algorithm == 'adaptive'
    window.run_video()
    assert not window.edit_button.isEnabled() and not window.delete_button.isEnabled()
    wait_job(app, window)
    assert len(window.cues) == 3, window.log.toPlainText()
    assert window.last_scan_stats.ocr_calls < window.last_scan_stats.decoded_frames
    assert window.export_button.isEnabled()
    assert window.table.item(0, 2).text() == '请所有同学立刻停止军训'
    assert window.canvas.mapTo(window, QPoint(0, 0)).x() < window.table.mapTo(window, QPoint(0, 0)).x()
    window.table.selectRow(0)
    assert window.edit_button.isEnabled() and window.delete_button.isEnabled()
    assert not window.merge_button.isEnabled()
    window.grab().save('test_artifacts/app_preview.png')
    window.language.setCurrentIndex(1)
    assert not window.preview_bands
    window.slider.setValue(800)
    window.preview()
    wait_job(app, window)
    assert window.preview_bands and 'All students' in window.log.toPlainText()
    window.close()
    print('GUI OCR passed: two-column layout, ROI, preview, adaptive 0.5s scan, row actions and language switch.')


if __name__ == '__main__':
    run()
