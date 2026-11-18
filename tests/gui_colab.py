"""Exercise export -> portable runner (CPU locally) -> GUI import -> edit -> SRT."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import zipfile
import cv2
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QDialog
from app import MainWindow, configure_app
from subocr.colab import ROOT, load_result, write_json
from subocr.core import OcrEngine


def run():
    app = QApplication([])
    configure_app(app)
    window = MainWindow()
    window.show()
    artifacts = ROOT / 'test_artifacts/colab_smoke'
    artifacts.mkdir(exist_ok=True)
    report = {}
    engine = OcrEngine()
    for lang in ('zh', 'en'):
        video = ROOT / f'test_artifacts/demo_{lang}.mp4'
        window.open_video(video)
        window.canvas.roi = (20, 410, 920, 110)
        window.language.setCurrentIndex(0 if lang == 'zh' else 1)
        # Exercise the normal workflow: read a frame and keep line locking enabled.
        window.lock_line.setChecked(True)
        window.slider.setValue(800)
        preview = engine.read(window.canvas.frame, window.settings(use_bands=False))
        window.job_done((engine, preview, 'preview'))
        assert window.preview_bands
        old = set(artifacts.iterdir())
        with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(artifacts)), \
                patch.object(QMessageBox, 'information') as info:
            window.export_colab()
            assert info.call_args.args[1] == 'Đã xuất gói Colab'
        folder, = set(artifacts.iterdir()) - old
        extracted = folder / 'unpacked'
        with zipfile.ZipFile(folder / f'sublens_colab_{video.stem}.zip') as archive:
            archive.extractall(extracted)
        result_dir = folder / 'result'
        subprocess.run([sys.executable, str(extracted / 'colab/run_job.py'),
                        '--job', str(extracted / 'job.json'), '--video', str(video),
                        '--output', str(result_dir), '--cpu'], cwd=extracted, check=True)
        result = result_dir / 'result.sublens.json'
        cfg, cues, stats, device = load_result(result, video)
        assert len(cues) == 3, [(c.start, c.end, c.text) for c in cues]
        assert device == 'cpu' and stats.ocr_calls > 0
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(result), '')):
            window.import_colab()
        assert window.cues == cues and window.table.rowCount() == 3
        assert window.result_language == lang and window.last_scan_stats.ocr_calls == stats.ocr_calls
        # Reject a result for another video without touching the existing subtitles.
        other = ROOT / f'test_artifacts/demo_{"en" if lang == "zh" else "zh"}.mp4'
        cfg_before = window.video_path
        window.video_path = str(other)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(result), '')), \
                patch.object(QMessageBox, 'warning') as warning:
            window.import_colab()
            assert warning.called and window.cues == cues
        window.video_path = cfg_before
        # Replacing existing edits can be canceled.
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(result), '')), \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            window.import_colab()
            assert window.cues == cues
        original = cues[0].text
        window.table.item(0, 2).setText(original + '\nEdited')
        assert window.cues[0].edited
        window.undo()
        assert window.cues[0].text == original
        target = folder / f'gui_export.{lang}.srt'
        with patch.object(QFileDialog, 'exec', return_value=QDialog.Accepted), \
                patch.object(QFileDialog, 'selectedFiles', return_value=[str(target)]):
            window.export()
        assert original in target.read_text(encoding='utf-8-sig')
        report[lang] = {'cues': [asdict(cue) for cue in cues], 'stats': asdict(stats), 'bundle': str(folder)}
    # Export one reusable package, then scan two distinct files with the same subtitle layout.
    video = ROOT / 'test_artifacts/demo_en.mp4'
    second = artifacts / 'episode_two.mp4'
    capture = cv2.VideoCapture(str(video))
    writer = cv2.VideoWriter(str(second), cv2.VideoWriter_fourcc(*'mp4v'), 10, (960, 540))
    assert writer.isOpened()
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame[:12, :12] = 255  # Different content outside the subtitle region.
        writer.write(frame)
    capture.release()
    writer.release()
    old = set(artifacts.iterdir())
    with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(artifacts)), \
            patch.object(QMessageBox, 'information'):
        window.export_colab(reusable=True)
    folder, = set(artifacts.iterdir()) - old
    extracted = folder / 'unpacked'
    with zipfile.ZipFile(folder / f'sublens_colab_{video.stem}.zip') as archive:
        archive.extractall(extracted)
    for index, source in enumerate((video, second)):
        result_dir = folder / f'episode_{index}'
        subprocess.run([sys.executable, str(extracted / 'colab/run_job.py'),
                        '--job', str(extracted / 'job.json'), '--video', str(source),
                        '--output', str(result_dir), '--cpu'], cwd=extracted, check=True)
        result = result_dir / 'result.sublens.json'
        assert len(load_result(result, source)[1]) == 3
        other = second if index == 0 else video
        try:
            load_result(result, other)
        except ValueError:
            pass
        else:
            raise AssertionError('Reusable job result accepted the wrong episode')
        window.open_video(source)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(result), '')):
            window.import_colab()
        assert len(window.cues) == 3
    for width, height in ((760, 560), (1240, 800)):
        window.resize(width, height)
        app.processEvents()
        rect = QRect(window.colab_button.mapTo(window, QPoint()), window.colab_button.size())
        assert window.rect().contains(rect) and window.colab_button.isVisible()
    window.grab().save(str(artifacts / 'colab_menu.png'))
    write_json(artifacts / 'report.json', report)
    window.close()
    print('Colab export / portable CPU runner / import / edit / SRT passed: zh, en, and one reusable package for two videos.', flush=True)


if __name__ == '__main__':
    run()
