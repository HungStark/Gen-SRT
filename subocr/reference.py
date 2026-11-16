"""SRT timing hints. Reference text is never used as OCR output."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from pathlib import Path
import re


STAMP = r'(\d{1,4}):(\d{2}):(\d{2})[,.](\d{3})'
TIMING = re.compile(r'^\s*' + STAMP + r'\s*-->\s*' + STAMP + r'(?:\s+.*)?\s*$')


def read_reference_srt(path: str | Path) -> tuple[tuple[float, float], ...]:
    data = Path(path).read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = data.decode('utf-16')
    else:
        # Only ASCII timing lines are needed, so legacy subtitle encodings can keep their timing hints.
        text = data.decode('utf-8-sig', errors='replace')
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        raise ValueError('SRT tham chiếu rỗng.')
    spans = []
    for number, block in enumerate(re.split(r'\n[ \t]*\n+', text), 1):
        lines = block.strip().splitlines()
        line_number = 1 if lines[0].strip().isdigit() else 0
        if line_number >= len(lines):
            raise ValueError(f'Mục tham chiếu {number}: thiếu dòng thời gian.')
        match = TIMING.fullmatch(lines[line_number])
        if not match:
            raise ValueError(f'Mục tham chiếu {number}: thời gian phải có dạng 00:00:01,200 --> 00:00:03,400.')
        values = [int(value) for value in match.groups()]
        if any(value > 59 for value in (values[1], values[2], values[5], values[6])):
            raise ValueError(f'Mục tham chiếu {number}: phút và giây phải nằm trong 00–59.')
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        if end <= start:
            raise ValueError(f'Mục tham chiếu {number}: kết thúc phải lớn hơn bắt đầu.')
        spans.append((start, end))
    return tuple(sorted(spans))


@dataclass(frozen=True)
class ReferencePlan:
    windows: tuple[tuple[float, float], ...]
    anchors: tuple[float, ...]
    starts: tuple[float, ...]

    def window_at(self, time: float):
        index = bisect_right(self.starts, time + 1e-6) - 1
        if index >= 0 and time <= self.windows[index][1] + 1e-6:
            return self.windows[index]
        return None

    def crosses_anchor(self, previous: float, current: float):
        index = bisect_right(self.anchors, previous + 1e-6)
        return index < len(self.anchors) and self.anchors[index] <= current + 1e-6


def build_reference_plan(spans, padding=.7, duration=0.) -> ReferencePlan:
    if not math.isfinite(padding) or padding < 0:
        raise ValueError('Khoảng đệm SRT phải là số không âm.')
    if not spans:
        raise ValueError('Chưa có mốc SRT tham chiếu. Hãy chọn tệp SRT hoặc tắt chế độ tham chiếu.')
    expanded, anchors = [], set()
    for start, end in sorted(spans):
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError('Mốc SRT tham chiếu không hợp lệ.')
        left, right = max(0., start - padding), end + padding
        if duration > 0:
            right = min(duration, right)
        if right <= left:
            continue
        expanded.append((left, right))
        anchors.update((left, right))
        # Keep original cue boundaries even if padded windows merge into one large window.
        anchors.update(t for t in (start, end) if left <= t <= right)
    if not expanded:
        raise ValueError('Các mốc SRT nằm ngoài thời lượng video. Kiểm tra đúng video và tệp SRT.')
    merged = []
    for left, right in expanded:
        if merged and left <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return ReferencePlan(tuple(merged), tuple(sorted(anchors)), tuple(left for left, _ in merged))
