from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata

import cv2
import numpy as np


def has_han(text: str) -> bool:
    return any('\u3400' <= c <= '\u9fff' or '\U00020000' <= c <= '\U0003134f' for c in text)


def matches_language(text: str, language: str) -> bool:
    if language == 'zh':
        return has_han(text)
    return not has_han(text) and bool(re.search('[a-zA-Z]', text))


def normalized(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def same_text(a: str, b: str, threshold: float = .88) -> bool:
    x, y = normalized(a), normalized(b)
    if not x or not y:
        return x == y
    if x == y:
        return True
    # One-character changes in short Chinese captions can change the meaning.
    if min(len(x), len(y)) < 10:
        return False
    return SequenceMatcher(None, x, y, autojunk=False).ratio() >= threshold


@dataclass
class Line:
    text: str
    score: float
    box: tuple[int, int, int, int]
    color: tuple[int, int, int] = (255, 255, 255)
    accepted: bool = False


@dataclass
class Settings:
    roi: tuple[int, int, int, int]
    language: str = 'zh'
    interval: float = .5
    confidence: float = .60
    line_bands: list[tuple[float, float]] = field(default_factory=list)
    color: tuple[int, int, int] | None = None  # RGB
    color_tolerance: float = 75
    min_duration: float = .08
    algorithm: str = 'adaptive'
    boundary_precision: float = .1
    reference_spans: tuple[tuple[float, float], ...] | None = None
    reference_padding: float = .7
    outside_interval: float | None = 2.


@dataclass
class Observation:
    text: str = ''
    score: float = 0
    lines: list[Line] = field(default_factory=list)
    uncertain: bool = False


@dataclass
class Cue:
    start: float
    end: float
    text: str
    confidence: float = 1.0
    review: bool = False


class OcrEngine:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=1,
                               det_limit_type='max', det_limit_side_len=1600, text_score=.1)
        self.english = None

    def read_english(self, image):
        if self.english is None:
            from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
            model = Path(__file__).resolve().parents[1] / 'models' / 'en_PP-OCRv4_rec_mobile.onnx'
            if not model.is_file():
                raise ValueError('Thiếu mô hình tiếng Anh. Chạy setup.bat để tải lại.')
            self.english = TextRecognizer(dict(model_path=str(model), use_cuda=False, use_dml=False,
                                               intra_op_num_threads=4, inter_op_num_threads=1,
                                               rec_img_shape=[3, 48, 320], rec_batch_num=6))
        results, _ = self.english(image)
        return results[0]

    def read(self, frame: np.ndarray, cfg: Settings) -> Observation:
        x, y, w, h = cfg.roi
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            raise ValueError('Vùng OCR rỗng. Hãy chọn lại vùng phụ đề.')
        scale = min(3.0, max(1.0, 130 / h))
        enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        results, _ = self.engine(enlarged, use_cls=False)
        fragments = []
        for points, text, score in results or []:
            pts = np.array(points) / scale
            baseline = pts[1] - pts[0]
            if abs(baseline[1]) > max(2, abs(baseline[0]) * .22):
                continue
            left, top = np.floor(pts.min(axis=0)).astype(int)
            right, bottom = np.ceil(pts.max(axis=0)).astype(int)
            fragments.append(Line(str(text).strip(), float(score),
                                  (max(0, left), max(0, top), min(w, right), min(h, bottom))))
        rows: list[list[Line]] = []
        for line in sorted(fragments, key=lambda z: (z.box[1] + z.box[3]) / 2):
            cy = (line.box[1] + line.box[3]) / 2
            target = next((row for row in rows if abs(cy - np.mean([(r.box[1] + r.box[3]) / 2 for r in row]))
                           <= .42 * max(line.box[3] - line.box[1], np.mean([r.box[3] - r.box[1] for r in row]))), None)
            if target is None:
                rows.append([line])
            else:
                target.append(line)
        lines = []
        uncertain = False
        for row in rows:
            row.sort(key=lambda r: r.box[0])
            sep = '' if has_han(''.join(r.text for r in row)) else ' '
            box = (min(r.box[0] for r in row), min(r.box[1] for r in row),
                   max(r.box[2] for r in row), max(r.box[3] for r in row))
            text = sep.join(r.text for r in row)
            score = sum(r.score * max(1, len(r.text)) for r in row) / sum(max(1, len(r.text)) for r in row)
            if cfg.language == 'en' and matches_language(text, 'en'):
                left, top, right, bottom = box
                patch = enlarged[max(0, round(top * scale) - 2): min(enlarged.shape[0], round(bottom * scale) + 2),
                                 max(0, round(left * scale) - 2): min(enlarged.shape[1], round(right * scale) + 2)]
                if patch.size:
                    text, score = self.read_english(patch)
            line = Line(text, score, box)
            left, top, right, bottom = box
            center = (top + bottom) / (2 * h)
            height = (bottom - top) / h
            band_ok = not cfg.line_bands or any(abs(center - cy) < max(.045, bh * .65)
                       and .45 * bh <= height <= 2 * bh for cy, bh in cfg.line_bands)
            color_ok = True
            patch = crop[top:bottom, left:right]
            if cfg.color is not None and patch.size:
                delta = np.linalg.norm(patch.astype(np.float32) - np.array(cfg.color[::-1]), axis=2)
                mask = (delta < cfg.color_tolerance).astype(np.uint8)
                edges = cv2.Canny(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 60, 140)
                near = cv2.dilate(mask, np.ones((3, 3), np.uint8))
                # Require the selected color near actual glyph edges, not just somewhere in the crop.
                color_ok = float((near * (edges > 0)).sum()) / max(1, (edges > 0).sum()) > .22
            # Scene lettering with a steep baseline is unlikely to be a horizontal subtitle.
            numeric_in_band = bool(cfg.line_bands) and band_ok and bool(re.search(r'\d', text)) and not has_han(text) and not re.search('[a-zA-Z]', text)
            candidate = (matches_language(text, cfg.language) or numeric_in_band) and band_ok and color_ok
            line.accepted = score >= cfg.confidence and candidate
            uncertain = uncertain or (candidate and score < cfg.confidence)
            lines.append(line)
        selected = [line for line in lines if line.accepted]
        return Observation('\n'.join(line.text for line in selected),
                           min((line.score for line in selected), default=0), lines, uncertain)


class CueBuilder:
    """Track caption occurrences, choosing an actual observed reading by weighted consensus."""
    def __init__(self, min_duration=.08, strict=False):
        self.cues: list[Cue] = []
        self.start = 0.0
        self.last_time = None
        self.current = ''
        self.variants: dict[str, list[float]] = {}
        self.min_duration = min_duration
        self.strict = strict
        self.review_current = False
        self.unresolved = False

    def _finish(self, end):
        if self.current and end - self.start >= self.min_duration:
            best = max(self.variants, key=lambda t: sum(self.variants[t]))
            confidence = sum(self.variants[best]) / len(self.variants[best])
            self.cues.append(Cue(self.start, end, best, confidence,
                                 confidence < .85 or len(self.variants) > 1 or self.review_current))

    def feed(self, time: float, observation: Observation):
        text = observation.text
        if self.last_time is not None and time < self.last_time:
            raise ValueError('Timestamp video không tăng.')
        if observation.uncertain:
            # An unreadable line is not evidence that the subtitle disappeared.
            self.review_current = True
            self.unresolved = True
            self.last_time = time
            return
        equal = normalized(self.current) == normalized(text) if self.strict else same_text(self.current, text)
        changed = bool(text) != bool(self.current) or (text and not equal)
        if changed:
            # The first frame carrying the new state defines its presentation timestamp.
            boundary = time
            self._finish(boundary)
            self.start = boundary
            self.current = text
            self.variants = {}
            self.review_current = self.unresolved
        if text:
            self.variants.setdefault(text, []).append(observation.score)
        self.last_time = time
        self.unresolved = False

    def finish(self, end: float):
        self._finish(end)
        self.current = ''
        self.variants = {}
        self.review_current = False
        self.unresolved = False
        return self.cues


def timestamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'


def write_srt(path: str | Path, cues: list[Cue]):
    previous = 0.0
    blocks = []
    for i, cue in enumerate(cues, 1):
        if cue.start < previous or cue.end <= cue.start or not cue.text.strip():
            raise ValueError(f'Mục {i}: thời gian không hợp lệ, chồng lấn hoặc nội dung rỗng.')
        if round(cue.end * 1000) <= round(cue.start * 1000):
            raise ValueError(f'Mục {i}: thời lượng nhỏ hơn 1 mili giây.')
        blocks.append(f'{i}\n{timestamp(cue.start)} --> {timestamp(cue.end)}\n{cue.text.strip()}\n')
        previous = cue.end
    Path(path).write_text('\n'.join(blocks), encoding='utf-8-sig')
