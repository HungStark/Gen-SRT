"""Real OCR: one deliberately wrong transcript cue guides three visual subtitles."""
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from integration import make_video, ZH, EN
from subocr.core import OcrEngine, Settings, write_srt
from subocr.reference import read_reference_srt
from subocr.video import ScanStats, extract


def run():
    out = Path('test_artifacts')
    out.mkdir(exist_ok=True)
    video = out / 'demo_dual.mp4'
    if not video.is_file():
        make_video(video)
    reference = out / 'reference_demo.srt'
    original = '1\n00:00:00,900 --> 00:00:03,900\nThis transcript is intentionally wrong and must never become the OCR output.\n'
    reference.write_text(original, encoding='utf-8-sig')
    spans = read_reference_srt(reference)
    engine = OcrEngine()
    report = {}
    for language in ('zh', 'en'):
        for outside in (None, 2.):
            cfg = Settings((20, 410, 920, 115), language, reference_spans=spans, outside_interval=outside)
            stats = ScanStats()
            cues = extract(video, cfg, engine, threading.Event(), stats=stats)
            expected = ZH if language == 'zh' else EN
            assert [cue.text for cue in cues] == [expected[0], expected[1], expected[0]], cues
            for cue, (start, end) in zip(cues, [(.4, 1.6), (2., 3.2), (3.6, 4.4)]):
                assert abs(cue.start - start) <= .11001 and abs(cue.end - end) <= .11001, cue
            assert stats.reference_cues == 1 and stats.unmatched_reference_cues == 0, stats
            assert stats.window_edge_events == 0, stats
            assert reference.read_text(encoding='utf-8-sig') == original
            name = f'{language}:outside={outside}'
            report[name] = dict(stats=vars(stats), cues=[vars(cue) for cue in cues])
            write_srt(out / f'reference_demo.ocr.{language}.{outside}.srt', cues)
            print(f'{name}: {len(cues)} cues, OCR {stats.ocr_calls} calls', flush=True)
    (out / 'reference_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Reference integration passed: wrong transcript ignored, one hint split into three actual captions.')


if __name__ == '__main__':
    run()
