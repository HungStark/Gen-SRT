"""Opt-in real GPU check; no provider mocks or CPU substitution."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_ocr import sample_frame
from subocr.core import OcrEngine, Settings

frame = sample_frame()
report = []
for size in ('tiny', 'small', 'medium'):
    start = time.monotonic()
    engine = OcrEngine('gpu', size)
    texts = []
    for lang, roi, expected in [('en', (0, 0, 960, 95), 'Hello subtitle world.'),
                                ('zh', (0, 95, 960, 105), '我们马上离开这里')]:
        actual = engine.read(frame, Settings(roi, lang, device='gpu', model_size=size))
        assert actual.text == expected, (size, lang, actual)
        texts.append(actual.text)
    result = dict(size=size, provider=engine.provider, texts=texts, elapsed=time.monotonic() - start)
    report.append(result)
    print(result, flush=True)
Path('test_artifacts/ppocr6/gpu.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
