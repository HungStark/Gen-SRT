"""Subtitle edits shared by the table, export validation and tests."""
from dataclasses import replace
import math
import re


def parse_time(value: str) -> float:
    value = value.strip().replace(',', '.')
    if ':' in value:
        match = re.fullmatch(r'(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?', value)
        if not match:
            raise ValueError('Nhập số giây hoặc thời gian dạng 00:00:01,200.')
        hours, minutes, seconds = map(int, match.groups()[:3])
        if minutes > 59 or seconds > 59:
            raise ValueError('Phút và giây phải nằm trong 00–59.')
        value = hours * 3600 + minutes * 60 + seconds + float('0.' + (match[4] or '0'))
    else:
        try:
            value = float(value)
        except ValueError:
            raise ValueError('Nhập số giây hoặc thời gian dạng 00:00:01,200.') from None
    if not math.isfinite(value) or value < 0:
        raise ValueError('Thời gian phải là số không âm.')
    return value


def cue_errors(cues):
    errors = {}
    previous_end, previous_row = 0., None
    for row, cue in enumerate(cues):
        messages = []
        if not math.isfinite(cue.start) or not math.isfinite(cue.end) or cue.start < 0 or cue.end <= cue.start:
            messages.append('Kết thúc phải lớn hơn bắt đầu và thời gian không được âm.')
        elif round(cue.end * 1000) <= round(cue.start * 1000):
            messages.append('Đoạn phải dài ít nhất 1 mili giây.')
        if not cue.text.strip():
            messages.append('Nội dung rỗng. Nhập chữ hoặc xóa đoạn này.')
        if cue.start < previous_end - 1e-9:
            messages.append('Thời gian chồng lên đoạn trước hoặc không đúng thứ tự.')
            if previous_row is not None:
                errors.setdefault(previous_row, 'Thời gian chồng lên đoạn sau.')
        if messages:
            errors[row] = ' '.join(messages)
        if cue.end > previous_end:
            previous_end, previous_row = cue.end, row
    return errors


def consecutive_rows(rows):
    rows = sorted(set(rows))
    return len(rows) >= 2 and rows == list(range(rows[0], rows[-1] + 1))


def merge_cues(cues, rows, content_row):
    rows = sorted(set(rows))
    if not consecutive_rows(rows) or rows[0] < 0 or rows[-1] >= len(cues):
        raise ValueError('Chọn ít nhất hai đoạn liền nhau để gộp.')
    if content_row not in rows:
        raise ValueError('Chọn nội dung từ một trong các đoạn được gộp.')
    source = cues[content_row]
    if not source.text.strip():
        raise ValueError('Đoạn được chọn làm nội dung đang rỗng.')
    selected = [cues[row] for row in rows]
    start, end = min(c.start for c in selected), max(c.end for c in selected)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError('Thời gian của các đoạn được gộp chưa hợp lệ.')
    merged = replace(source, start=start, end=end, edited=True, review=any(c.review for c in selected))
    return [*cues[:rows[0]], merged, *cues[rows[-1] + 1:]]
