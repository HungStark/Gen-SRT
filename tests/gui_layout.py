import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication
from app import MainWindow, configure_app
from subocr.core import Cue

app = QApplication([])
configure_app(app)
window = MainWindow()
window.show()
window.open_video('test_artifacts/demo_dual.mp4')
window.slider.setValue(800)
window.cues = [Cue(.4, 1.6, '请所有同学立刻停止军训', .98), Cue(2, 3.2, '我们马上离开这里', .94), Cue(3.6, 4.4, '请所有同学立刻停止军训', .82, True)]
window.fill_table()
scale = os.environ.get('QT_SCALE_FACTOR', '1')
for width, height in [(760, 560), (960, 640), (1240, 800), (1280, 640)]:
    window.resize(width, height)
    app.processEvents()
    assert window.width() <= width and window.height() <= height, (window.size(), width, height)
    assert window.canvas.height() >= 140 and window.table.height() >= 150
    assert window.canvas.mapTo(window, QPoint(0, 0)).x() < window.table.mapTo(window, QPoint(0, 0)).x()
    for control in (window.open_button, window.options_button, window.language, window.preview_button,
                    window.run_button, window.export_button, window.edit_button, window.delete_button,
                    window.merge_button, window.undo_button, window.progress_bar, window.cancel_button):
        rect = QRect(control.mapTo(window, QPoint(0, 0)), control.size())
        assert window.rect().contains(rect), (scale, width, height, control.objectName(), rect)
        assert control.height() >= control.minimumSizeHint().height(), (control, control.height())
        local_rect = QRect(control.mapTo(control.parentWidget(), QPoint(0, 0)), control.size())
        assert control.parentWidget().rect().contains(local_rect), (control, local_rect)
    if (width, height) == (1240, 800):
        window.grab().save(f'test_artifacts/two_column_{scale}.png')
    print(f'Layout OK: scale={scale}, {width}x{height}', flush=True)
window.close()
