"""Compare actual OCR calls and elapsed time on the same synthetic clip."""
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2
from integration import image, ZH
from subocr.core import OcrEngine, Settings, write_srt
from subocr.video import ScanStats, extract


def run():
    path = Path('test_artifacts/benchmark_25fps.mp4')
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 25, (960, 540))
    assert writer.isOpened()
    images = [image(0), image(1), image(None)]
    for i in range(200):
        writer.write(images[0 if i < 80 else (1 if i < 160 else 2)])
    writer.release()
    engine = OcrEngine()
    roi = (20, 410, 920, 115)
    engine.read(images[0], Settings(roi))  # Warm up before timing either mode.
    report = {}
    outputs = {}
    for name, cfg in [('every_frame', Settings(roi, interval=0, algorithm='linear')),
                      ('adaptive', Settings(roi))]:
        stats = ScanStats()
        cues = extract(path, cfg, engine, threading.Event(), stats=stats)
        assert [cue.text for cue in cues] == ZH, cues
        for cue, expected in zip(cues, [(0., 3.2), (3.2, 6.4)]):
            assert abs(cue.start - expected[0]) <= .10001 and abs(cue.end - expected[1]) <= .10001, cue
        outputs[name] = cues
        report[name] = vars(stats)
        write_srt(path.with_suffix(f'.{name}.zh.srt'), cues)
        print(f'{name}: OCR={stats.ocr_calls}, seconds={stats.elapsed:.2f}', flush=True)
    report['ocr_reduction_percent'] = round(100 * (1 - report['adaptive']['ocr_calls'] / report['every_frame']['ocr_calls']), 1)
    report['elapsed_speedup'] = round(report['every_frame']['elapsed'] / report['adaptive']['elapsed'], 2)
    assert report['ocr_reduction_percent'] > 60, report
    Path('test_artifacts/benchmark_adaptive.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
