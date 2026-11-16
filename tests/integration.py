"""Real model + generated video test. Run from project root; artifacts stay local."""
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import av
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from subocr.core import OcrEngine, Settings, has_han, write_srt
from subocr.video import extract, frames, Cancelled

OUT = Path('test_artifacts')
OUT.mkdir(exist_ok=True)
ZH = ['请所有同学立刻停止军训', '我们马上离开这里']
EN = ['All students, stop training now.', 'We will leave this place now.']
FONT_ZH = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 30)
FONT_EN = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 24)


def image(index, mode='dual'):
    yy, xx = np.mgrid[:540, :960]
    bg = np.stack([25 + xx // 15, 37 + yy // 12, 50 + xx // 25], axis=-1).astype(np.uint8)
    im = Image.fromarray(bg)
    draw = ImageDraw.Draw(im)
    # Scene text inside the broad ROI but outside the locked subtitle band.
    draw.rectangle((35, 352, 230, 397), fill=(40, 65, 90))
    draw.text((50, 355), '商店 SHOP', font=FONT_ZH, fill=(255, 215, 35))
    if index is not None:
        lines = []
        if mode in ('dual', 'zh'):
            lines.append((ZH[index], FONT_ZH, 430))
        if mode in ('dual', 'en'):
            lines.append((EN[index], FONT_EN, 478 if mode == 'dual' else 450))
        for text, font, y in lines:
            width = draw.textlength(text, font=font)
            draw.text(((960 - width) / 2, y), text, font=font, fill='white', stroke_width=2, stroke_fill='black')
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def make_video(path, mode='dual'):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (960, 540))
    assert writer.isOpened()
    for index in range(48):
        text_index = 0 if 4 <= index < 16 or 36 <= index < 44 else (1 if 20 <= index < 32 else None)
        writer.write(image(text_index, mode))
    writer.release()


def run():
    start = time.perf_counter()
    engine = OcrEngine()
    report = {}
    for mode in ['dual', 'zh', 'en']:
        path = OUT / f'demo_{mode}.mp4'
        make_video(path, mode)
        languages = ('zh', 'en') if mode == 'dual' else (mode,)
        for language in languages:
            cfg = Settings((20, 345, 920, 180), language)
            preview = engine.read(image(0, mode), cfg)
            accepted = [line for line in preview.lines if line.accepted and line.box[1] > 65]
            assert accepted, (mode, language, preview)
            cfg.line_bands = [((line.box[1] + line.box[3]) / 360, (line.box[3] - line.box[1]) / 180) for line in accepted]
            cues = extract(path, cfg, engine, threading.Event())
            assert len(cues) == 3, (mode, language, cues)
            expected = ZH if language == 'zh' else EN
            assert [c.text for c in cues] == [expected[0], expected[1], expected[0]], cues
            for cue, (begin, end) in zip(cues, [(.4, 1.6), (2., 3.2), (3.6, 4.4)]):
                assert abs(cue.start - begin) <= .11 and abs(cue.end - end) <= .11, cue
                assert ('商店' not in cue.text and 'SHOP' not in cue.text), cue
                assert has_han(cue.text) == (language == 'zh'), cue
            write_srt(OUT / f'{mode}.{language}.srt', cues)
            report[f'{mode}:{language}'] = [vars(c) for c in cues]

    # Verify user-selected color rejects a yellow sign even without a locked band.
    cfg = Settings((20, 345, 920, 180), 'zh', color=(255, 255, 255), color_tolerance=60)
    observation = engine.read(image(0), cfg)
    assert observation.text == ZH[0], observation

    # The default high-accuracy mode processes every source frame.
    exact_cfg = Settings((20, 410, 920, 115), 'zh', interval=0)
    exact = extract(OUT / 'demo_dual.mp4', exact_cfg, engine, threading.Event())
    assert len(exact) == 3, exact
    assert [(round(c.start, 2), round(c.end, 2)) for c in exact] == [(.4, 1.6), (2., 3.2), (3.6, 4.4)], exact
    report['every_frame_zh'] = [vars(c) for c in exact]

    # Two physical rows in one language must become one subtitle block.
    im = Image.fromarray(cv2.cvtColor(image(None), cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(im)
    for text, y in [('请所有同学', 420), ('立刻停止军训', 464)]:
        width = draw.textlength(text, font=FONT_ZH)
        draw.text(((960 - width) / 2, y), text, font=FONT_ZH, fill='white', stroke_width=2, stroke_fill='black')
    wrapped = engine.read(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR), Settings((20, 410, 920, 115)))
    assert wrapped.text == '请所有同学\n立刻停止军训', wrapped
    report['wrapped_zh'] = wrapped.text

    event = threading.Event()
    event.set()
    try:
        extract(OUT / 'demo_dual.mp4', cfg, engine, event)
        raise AssertionError('Cancellation ignored')
    except Cancelled:
        pass

    # Actual VFR presentation timestamps: 0, .04, .20, .24, .60 seconds.
    from fractions import Fraction
    vfr_path = OUT / 'vfr.mp4'
    with av.open(str(vfr_path), 'w') as container:
        stream = container.add_stream('libx264', rate=25)
        stream.width, stream.height = 960, 540
        stream.pix_fmt = 'yuv420p'
        stream.time_base = Fraction(1, 1000)
        for ms in [0, 40, 200, 240, 600]:
            frame = av.VideoFrame.from_ndarray(image(0), format='bgr24')
            frame.pts, frame.time_base = ms, Fraction(1, 1000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    actual = [round(t, 3) for t, _, _ in frames(vfr_path)]
    assert actual == [0, .04, .20, .24, .60], actual
    report['vfr_timestamps'] = actual
    report['seconds'] = round(time.perf_counter() - start, 2)
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
