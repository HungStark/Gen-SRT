"""Exercise actual Qt edit delegates, deletion, merge choice, undo and SRT export."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QDialog, QFileDialog, QMessageBox

from app import MainWindow, MergeDialog, configure_app
from subocr.core import Cue


def select(window, rows):
    window.table.clearSelection()
    selection = window.table.selectionModel()
    for row in rows:
        selection.select(window.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    QApplication.processEvents()


def editor(window):
    window.edit_selected()
    QApplication.processEvents()
    result = next(widget for widget in window.table.findChildren(QPlainTextEdit) if widget.isVisible())
    return result


def run():
    app = QApplication([])
    configure_app(app)
    window = MainWindow()
    window.resize(1200, 760)
    window.show()
    app.processEvents()
    window.video_path = str(Path('test_artifacts/demo_dual.mp4').resolve())
    window.cues = [Cue(.1, 1., 'First', .95), Cue(1.4, 2.6, 'Keep second\n第二行', .91), Cue(3., 4., 'Third', .82, True)]
    window.fill_table()
    assert not hasattr(window, 'reference_enabled')

    select(window, [0])
    text_editor = editor(window)
    text_editor.setPlainText('Đã sửa\n你好')
    QTest.keyClick(text_editor, Qt.Key_Return, Qt.ControlModifier)
    app.processEvents()
    assert window.cues[0].text == 'Đã sửa\n你好'
    assert window.cues[0].edited and len(window.undo_stack) == 1
    window.table.item(0, 0).setText('0.200')
    assert window.cues[0].start == .2
    assert window.table.item(0, 0).text() == '00:00:00,200'
    select(window, [0, 2])
    assert not window.merge_button.isEnabled()
    assert window.delete_button.isEnabled()

    select(window, [0, 1])
    assert window.merge_button.isEnabled()
    def choose_second(dialog):
        dialog.choices.setCurrentRow(1)
        assert dialog.preview.toPlainText() == 'Keep second\n第二行'
        return QDialog.Accepted
    with patch.object(MergeDialog, 'exec', choose_second):
        window.merge_selected()
    assert len(window.cues) == 2
    assert (window.cues[0].start, window.cues[0].end, window.cues[0].text) == (.2, 2.6, 'Keep second\n第二行')
    assert window.table.item(0, 3).text() == 'Đã sửa'

    select(window, [0, 1])
    before = list(window.cues)
    with patch.object(MergeDialog, 'exec', return_value=QDialog.Rejected):
        window.merge_selected()
    assert window.cues == before
    target = Path('test_artifacts/editor_export.zh.srt').resolve()
    with patch.object(QFileDialog, 'exec', return_value=QDialog.Accepted), patch.object(QFileDialog, 'selectedFiles', return_value=[str(target)]):
        window.export()
    contents = target.read_text(encoding='utf-8-sig')
    assert '00:00:00,200 --> 00:00:02,600\nKeep second\n第二行' in contents
    assert '\n2\n00:00:03,000 --> 00:00:04,000\nThird' in contents

    select(window, [0])
    window.delete_selected()
    assert [cue.text for cue in window.cues] == ['Third']
    window.undo()
    assert len(window.cues) == 2
    window.undo()
    assert len(window.cues) == 3 and window.cues[0].text == 'Đã sửa\n你好'
    assert window.cues[0].start == .2

    # Calling export while the text editor is open must save the edit first.
    select(window, [0])
    text_editor = editor(window)
    text_editor.setPlainText('Pending edit')
    with patch.object(QFileDialog, 'exec', return_value=QDialog.Accepted), patch.object(QFileDialog, 'selectedFiles', return_value=[str(target)]):
        window.export()
    assert window.cues[0].text == 'Pending edit'
    assert 'Pending edit' in target.read_text(encoding='utf-8-sig')

    window.table.item(0, 0).setText('nan')
    assert window.cues[0].start == .2
    window.table.item(0, 1).setText('0.05')
    with patch.object(QMessageBox, 'warning') as warning:
        window.export()
        assert warning.called
    window.undo()
    assert window.cues[0].end == 1.
    select(window, [0, 2])
    window.delete_selected()
    assert [cue.text for cue in window.cues] == ['Keep second\n第二行']
    window.undo()
    select(window, [0, 1, 2])
    window.delete_selected()
    assert not window.cues and not window.export_button.isEnabled()
    window.undo()
    assert len(window.cues) == 3
    window.grab().save('test_artifacts/editor_layout.png')
    window.close()
    print('GUI editing passed: multiline edit, time edit, merge source choice, delete, undo, pending edit and export validation.')


if __name__ == '__main__':
    run()
