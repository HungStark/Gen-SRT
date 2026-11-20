"""Verify actual cell brushes, tooltip reasons and recoloring after table edits."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from app import MainWindow, configure_app
from subocr.core import Cue
from subocr.review import ROW_COLORS


def run():
    app = QApplication([])
    configure_app(app)
    window = MainWindow()
    window.resize(1240, 800)
    window.show()
    window.cues = [
        Cue(0, 1, 'Offcial media say it was a nuclear leak.', .799),
        Cue(1, 2, 'Offcial media say it was a nuclear leak.', .99),
        Cue(2, 3, 'Official media say it was a nuclear leak.', .99),
        Cue(3, 4, 'Stinky Kunzi, you scared me to death.', .99, review=True),
        Cue(4, 5, 'The film is ready.', .80, review=True, edited=True),
    ]
    window.fill_table()
    app.processEvents()

    def colors():
        return [window.table.item(row, 2).background().color().name() for row in range(len(window.cues))]

    def assert_levels(*levels):
        assert colors() == [ROW_COLORS[level] for level in levels], colors()

    assert_levels('red', 'orange', 'yellow', 'none', 'none')
    assert window.table.item(0, 3).text() == '79.9%'
    tooltip = window.table.item(0, 2).toolTip()
    assert all(reason in tooltip for reason in ['Đỏ:', 'Cam:', 'Vàng:', 'official'])
    assert '3 cần kiểm tra' in window.result_label.text()
    window.table.clearSelection()
    window.grab().save('test_artifacts/review_colors.png')

    # A manual edit must clear stale warnings on BOTH sides of the edited row.
    window.table.item(1, 2).setText('We should go back now.')
    assert_levels('red', 'none', 'none', 'none', 'none')
    window.undo()
    assert_levels('red', 'orange', 'yellow', 'none', 'none')
    window.table.selectRow(1)
    window.delete_selected()
    assert_levels('red', 'yellow', 'none', 'none')
    window.table.selectRow(0)
    window.delete_selected()
    assert_levels('none', 'none', 'none')
    window.undo()
    assert_levels('red', 'yellow', 'none', 'none')

    # Invalid timing remains an export error, without overriding requested row colors.
    window.table.item(2, 1).setText('2.5')
    assert_levels('red', 'yellow', 'none', 'none')
    assert 'Lỗi cần sửa trước khi xuất' in window.table.item(2, 1).toolTip()
    assert window.table.item(2, 1).foreground().color().name() == '#b42318'
    window.undo()
    assert window.table.item(2, 1).foreground().color().name() == '#203047'

    # Short Chinese OCR substitutions are warnings even at high confidence.
    window.cues = [Cue(0, 1, '但是总感觉不对劲', .95),
                   Cue(1, 2, '但是总感觉不对动', .96),
                   Cue(2, 3, '但是总感党不对动', .98)]
    window.fill_table()
    assert_levels('yellow', 'yellow', 'yellow')
    assert 'Vàng:' in window.table.item(1, 2).toolTip()
    window.table.item(1, 2).setText('我们马上离开这里')
    assert_levels('none', 'none', 'none')
    window.undo()
    assert_levels('yellow', 'yellow', 'yellow')

    # Existing accepted words still load, while Options only exposes OCR controls.
    custom_path = Path('test_artifacts/accepted_words_test.txt').resolve()
    custom_path.write_text('FLM\nKunzi', encoding='utf-8')
    with patch('subocr.ui.ACCEPTED_WORDS_PATH', custom_path):
        second = MainWindow()
        assert not hasattr(second, 'accepted_words_edit')
        second.cues = [Cue(0, 1, 'A flm is here.', .99)]
        second.fill_table()
        assert second.table.item(0, 2).background().color().name() == ROW_COLORS['none']
        second.close()
    window.close()
    print('GUI review passed: priorities, exact threshold, names, tooltips, edit/delete/undo and existing accepted words.')


if __name__ == '__main__':
    run()
