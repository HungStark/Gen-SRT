from __future__ import annotations

from dataclasses import dataclass, field, replace
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


@dataclass
class Observation:
    text: str = ''
    score: float = 0
    lines: list[Line] = field(default_factory=list)
    uncertain: bool = False
    visual_mask: np.ndarray | None = field(default=None, repr=False, compare=False)


def ocr_lookalike(a: str, b: str) -> bool:
    """Conservative Latin OCR confusions; actual numbers and Chinese changes stay distinct."""
    if has_han(a) or has_han(b):
        return False
    x, y = normalized(a), normalized(b)
    if min(len(x), len(y)) < 20 or re.findall(r'\d+', x) != re.findall(r'\d+', y):
        return False
    matcher = SequenceMatcher(None, x, y, autojunk=False)
    if matcher.ratio() < .96:
        return False
    for kind, a0, a1, b0, b1 in matcher.get_opcodes():
        if kind == 'equal':
            continue
        left, right = x[a0:a1], y[b0:b1]
        if left + right and set(left + right) <= {'i', 'l'}:
            continue
        if (left, right) in (('rn', 'm'), ('m', 'rn'), ('vv', 'w'), ('w', 'vv')):
            continue
        return False
    return True


def text_ink_mask(patch: np.ndarray, color=None):
    """Separate thin subtitle strokes from a changing background without a fixed white cutoff."""
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    if color is not None and np.mean(color) < 128:
        gray = 255 - gray
    kernel = max(5, min(31, (patch.shape[0] // 4) | 1))
    contrast = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, np.ones((kernel, kernel), np.uint8))
    threshold, _ = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return (contrast > max(10, threshold)).astype(np.uint8)


def tight_english_patch(patch: np.ndarray):
    ink = text_ink_mask(patch)
    x, y, w, h = cv2.boundingRect(ink)
    # Do not cut away a large portion of a line if the contrast estimate is incomplete.
    if ink.sum() < 30 or w < patch.shape[1] * .7 or h < patch.shape[0] * .3:
        return patch
    return patch[max(0, y - 1):min(patch.shape[0], y + h + 1),
                 max(0, x - 1):min(patch.shape[1], x + w + 1)]


def subtitle_mask(crop: np.ndarray, lines: list[Line], color=None, tolerance=75):
    masks = []
    for line in lines:
        left, top, right, bottom = line.box
        patch = crop[top:bottom, left:right]
        if not patch.size:
            return None
        glyphs = text_ink_mask(patch, color)
        left, top, width, height = cv2.boundingRect(glyphs)
        if glyphs.sum() < 30 or width <= 0 or height <= 0:
            return None
        glyphs = glyphs[top:top + height, left:left + width]
        mask = cv2.resize(glyphs * 255, (384, 32), interpolation=cv2.INTER_AREA) >= 110
        masks.append(mask)
    return np.concatenate(masks, axis=0) if masks else None


def same_glyphs(a, b) -> bool:
    if a is None or b is None or a.shape != b.shape or min(a.sum(), b.sum()) < 30:
        return False
    # Allow only a tiny translation from OCR boxes/encoding, then check local glyph differences.
    best = None
    expanded_a = cv2.dilate(a.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    padded = np.pad(b, ((1, 1), (2, 2)))
    for dy in range(3):
        for dx in range(5):
            candidate = padded[dy:dy + a.shape[0], dx:dx + a.shape[1]]
            expanded_b = cv2.dilate(candidate.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            mismatch = (a & ~expanded_b) | (candidate & ~expanded_a)
            union = max(1, np.logical_or(a, candidate).sum())
            score = (mismatch.sum() / union, np.logical_xor(a, candidate).sum() / union)
            if best is None or score < best[0]:
                best = (score, mismatch, candidate)
    if best[0][1] > .35:
        return False
    _, _, candidate = best
    if abs(int(a.sum()) - int(candidate.sum())) / max(a.sum(), candidate.sum()) > .08:
        return False
    # A one-pixel stroke tolerance also handles a one-pixel change in detected line height.
    mismatch = best[1]
    if mismatch.sum() / max(1, np.logical_or(a, candidate).sum()) > .015:
        return False
    for top in range(0, a.shape[0], 32):
        for left in range(0, a.shape[1], 24):
            region = np.s_[top:top + 32, left:left + 24]
            union = np.logical_or(a[region], candidate[region]).sum()
            if union >= 12 and mismatch[region].sum() / union > .10:
                return False
    return True


def same_caption(a: Observation, b: Observation) -> bool:
    if a.uncertain or b.uncertain or bool(a.text) != bool(b.text):
        return False
    if normalized(a.text) == normalized(b.text):
        return True
    return ocr_lookalike(a.text, b.text) and same_glyphs(a.visual_mask, b.visual_mask)


@dataclass
class Cue:
    start: float
    end: float
    text: str
    confidence: float = 1.0
    review: bool = False
    edited: bool = False


class OcrEngine:
    def __init__(self, use_cuda=False):
        from rapidocr_onnxruntime import RapidOCR
        self.use_cuda = use_cuda
        self.engine = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=1,
                               det_limit_type='max', det_limit_side_len=1600, text_score=.1,
                               det_use_cuda=use_cuda, rec_use_cuda=use_cuda)
        self.english = None
        if use_cuda:
            self._require_cuda(self.engine.text_det.infer, 'phát hiện chữ')
            self._require_cuda(self.engine.text_rec.session, 'nhận dạng chữ')

    @staticmethod
    def _require_cuda(inference, name):
        if inference.session.get_providers()[0] != 'CUDAExecutionProvider':
            raise RuntimeError(f'OCR {name} chưa dùng được GPU. Kiểm tra runtime GPU và CUDA/cuDNN trong notebook.')

    def read_english(self, image):
        if self.english is None:
            from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
            model = Path(__file__).resolve().parents[1] / 'models' / 'en_PP-OCRv4_rec_mobile.onnx'
            if not model.is_file():
                raise ValueError('Thiếu mô hình tiếng Anh. Chạy setup.bat để tải lại.')
            english = TextRecognizer(dict(model_path=str(model), use_cuda=self.use_cuda, use_dml=False,
                                               intra_op_num_threads=4, inter_op_num_threads=1,
                                               rec_img_shape=[3, 48, 320], rec_batch_num=6))
            if self.use_cuda:
                self._require_cuda(english.session, 'tiếng Anh')
            self.english = english
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
        # Same baseline is insufficient: scene text far away from the caption must stay separate.
        horizontal_runs = []
        for row in rows:
            row.sort(key=lambda line: line.box[0])
            limit = max(3 * float(np.median([line.box[3] - line.box[1] for line in row])), w * .04)
            run = []
            for line in row:
                if run and line.box[0] - run[-1].box[2] > limit:
                    horizontal_runs.append(run)
                    run = []
                run.append(line)
            if run:
                horizontal_runs.append(run)
        lines = []
        uncertain = False
        for row in horizontal_runs:
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
                    text, score = self.read_english(tight_english_patch(patch))
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
        text = '\n'.join(line.text for line in selected)
        signature = subtitle_mask(crop, selected, cfg.color, cfg.color_tolerance) if cfg.language == 'en' and len(normalized(text)) >= 20 else None
        return Observation(text, min((line.score for line in selected), default=0), lines, uncertain, signature)


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
        self.current_observation = Observation()
        self.stabilized_reads = 0

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
        equal = same_caption(self.current_observation, observation) if self.strict else same_text(self.current, text)
        if self.strict and equal and normalized(self.current) != normalized(text):
            self.stabilized_reads += 1
        changed = bool(text) != bool(self.current) or (text and not equal)
        if changed:
            # The first frame carrying the new state defines its presentation timestamp.
            boundary = time
            self._finish(boundary)
            self.start = boundary
            self.current = text
            self.current_observation = observation
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
        self.current_observation = Observation()
        return self.cues


def coalesce_equal_cues(cues: list[Cue], max_gap=.1) -> list[Cue]:
    """Join identical adjacent scan results, bridging at most one small OCR dropout."""
    result = []
    votes = {}
    observed_duration = 0.
    for cue in cues:
        weight = max(.001, cue.end - cue.start) * cue.confidence
        if result and normalized(result[-1].text) == normalized(cue.text) and -1e-9 <= cue.start - result[-1].end <= max_gap + 1e-9:
            previous = result[-1]
            gap = max(0., cue.start - previous.end)
            duration = cue.end - cue.start
            votes[cue.text] = votes.get(cue.text, 0.) + weight
            result[-1] = replace(previous, end=cue.end, text=max(votes, key=votes.get),
                                 confidence=(previous.confidence * observed_duration + cue.confidence * duration) / (observed_duration + duration),
                                 review=previous.review or cue.review or gap > 1e-6,
                                 edited=previous.edited or cue.edited)
            observed_duration += duration
        else:
            result.append(replace(cue))
            votes = {cue.text: weight}
            observed_duration = cue.end - cue.start
    return result


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
