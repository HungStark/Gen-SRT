"""Exercise the replacement tool's Qt controls and actual background conversion."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QFileDialog
from app import MainWindow, configure_app
from subocr.resize_ui import ResizeVideoDialog

root = Path(__file__).resolve().parents[1]
application = QApplication([])
configure_app(application)
window = MainWindow()
assert window.resize_video_action.isEnabled() and not hasattr(window, 'join_video_action')
with tempfile.TemporaryDirectory(dir=root / 'test_artifacts') as directory:
    dialog = ResizeVideoDialog(window)
    dialog.show()
    dialog.preset.setCurrentIndex(1)
    assert (dialog.width_input.value(), dialog.height_input.value()) == (1280, 720)
    dialog.preset.setCurrentIndex(3)
    dialog.width_input.setValue(640)
    dialog.height_input.setValue(360)
    with patch.object(QFileDialog, 'getOpenFileNames', return_value=([str(root / 'test_artifacts/demo_en.mp4')], '')):
        dialog.add_button.click()
    dialog.destination.setText(directory)
    dialog.start_button.click()
    assert dialog.worker is not None and not dialog.width_input.isEnabled()
    deadline = time.monotonic() + 60
    while dialog.worker is not None:
        application.processEvents()
        time.sleep(.02)
        if time.monotonic() > deadline:
            dialog.stop()
            raise AssertionError('Resize worker timed out')
    assert dialog.result_folder, dialog.status.text()
    assert (dialog.result_folder / 'demo_en.mp4').is_file()
    assert dialog.open_button.isEnabled() and dialog.start_button.isEnabled()
    application.processEvents()
    dialog.grab().save(str(root / 'test_artifacts/resize_video_dialog.png'))
    dialog.close()
window.close()
print('Resize dialog passed: preset, custom dimensions, file selection, background job and result.')
