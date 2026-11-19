"""Windows executable entry point; the source app.py launcher remains available."""
from pathlib import Path
import json
import os
import shutil
import sys


def prepare_user_data(test_output=None):
    root = Path(__file__).resolve().parent
    if test_output is not None:
        data_dir = Path(test_output).resolve().parent / 'app_selftest_data'
    else:
        data_dir = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'SubLens'
    data_dir.mkdir(parents=True, exist_ok=True)
    accepted = data_dir / 'accepted_words.txt'
    if not accepted.exists():
        shutil.copyfile(root / 'accepted_words.txt', accepted)
    # Set the path before UI imports its reference to the user's dictionary.
    from subocr import review
    review.ACCEPTED_WORDS_PATH = accepted
    import app
    app.ROOT = data_dir
    return app


def self_test(report_path):
    """Exercise the actual bundled Qt, codecs, CPU OCR, models and Colab payload."""
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'executable': sys.executable}
    try:
        app_module = prepare_user_data(report_path)
        import cv2
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        from PySide6.QtWidgets import QApplication
        from subocr.core import OcrEngine, Settings, write_srt
        from subocr.video import extract, ScanStats
        from subocr.colab import export_bundle, read_json, write_result, load_result
        from subocr.review import english_frequencies
        import threading
        import zipfile

        application = QApplication([])
        app_module.configure_app(application)
        window = app_module.MainWindow()
        engine = OcrEngine()
        canvas = Image.new('RGB', (960, 200), (30, 35, 45))
        draw = ImageDraw.Draw(canvas)
        draw.text((90, 30), 'Hello subtitle world.',
                  font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 36), fill='white')
        draw.text((90, 110), '\u6211\u4eec\u9a6c\u4e0a\u79bb\u5f00\u8fd9\u91cc',
                  font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 36), fill='white')
        frame = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
        english = engine.read(frame, Settings((0, 0, 960, 95), 'en')).text
        chinese = engine.read(frame, Settings((0, 95, 960, 105), 'zh')).text
        if 'Hello subtitle world' not in english or not chinese:
            raise AssertionError(f'Bundled OCR failed: {english!r}, {chinese!r}')
        video = report_path.parent / 'bundled_demo.mp4'
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (960, 200))
        if not writer.isOpened():
            raise AssertionError('Bundled OpenCV codec failed')
        for _ in range(12):
            writer.write(frame)
        writer.release()
        cfg = Settings((0, 0, 960, 95), 'en')
        stats = ScanStats()
        cues = extract(video, cfg, engine, threading.Event(), stats=stats)
        if len(cues) != 1 or 'Hello subtitle world' not in cues[0].text:
            raise AssertionError('Bundled video scan failed')
        window.open_video(video)
        window.cues = cues
        window.result_language = 'en'
        window.fill_table()
        window.show()
        application.processEvents()
        window.grab().save(str(report_path.with_suffix('.png')))
        folder = export_bundle(report_path.parent, video, cfg, 960, 200, 1.2, reusable=True)
        with zipfile.ZipFile(folder / f'sublens_colab_{video.stem}.zip') as archive:
            job = json.loads(archive.read('job.json'))
            for name in archive.namelist():
                if name.endswith('.py'):
                    compile(archive.read(name), name, 'exec')
        from subocr.colab import bind_video_job
        job = bind_video_job(job, video)
        result_path = report_path.parent / 'result.sublens.json'
        write_result(result_path, job, cues, stats, 'cpu')
        write_srt(report_path.parent / 'result.en.srt', cues)
        downloaded = report_path.parent / 'bundled_results.zip'
        with zipfile.ZipFile(downloaded, 'w') as archive:
            archive.write(result_path, 'Video/result.sublens.json')
        if load_result(downloaded, video)[1] != cues:
            raise AssertionError('Bundled result ZIP import failed')
        window.close()
        report.update(ok=True, english=english, chinese=chinese, cues=len(cues),
                      dictionary_words=len(english_frequencies()), colab_bundle=str(folder),
                      user_data=str(app_module.ROOT), stats=vars(stats))
    except Exception:
        import traceback
        report['error'] = traceback.format_exc()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        raise SystemExit(self_test(sys.argv[2]))
    raise SystemExit(prepare_user_data().main())
