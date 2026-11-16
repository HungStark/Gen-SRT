from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
import math
import threading
from time import perf_counter

import av
import cv2
import numpy as np

from .core import CueBuilder, Observation, OcrEngine, Settings, normalized, same_text
from .reference import build_reference_plan


class Cancelled(Exception):
    pass


@dataclass
class ScanStats:
    decoded_frames: int = 0
    coarse_samples: int = 0
    ocr_calls: int = 0
    refinement_calls: int = 0
    retry_calls: int = 0
    cache_hits: int = 0
    uncertain_samples: int = 0
    elapsed: float = 0
    reference_cues: int = 0
    reference_windows: int = 0
    reference_seconds: float = 0
    outside_samples: int = 0
    skipped_frames: int = 0
    unmatched_reference_cues: int = 0
    window_edge_events: int = 0


@dataclass
class Sample:
    time: float
    image: np.ndarray
    observation: Observation | None = None


def frames(path):
    """Use presentation timestamps; never infer VFR timestamps from frame index."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        origin = None
        last = -1.0
        for frame in container.decode(stream):
            if frame.time is None:
                raise ValueError('Video thiếu timestamp. Hãy chuyển video sang MP4 trước.')
            if origin is None:
                origin = float(frame.time)
            time = float(frame.time) - origin
            if time <= last:
                continue
            duration = float(frame.duration * frame.time_base) if frame.duration else 0
            last = time
            yield time, duration, frame.to_ndarray(format='bgr24')


def equivalent(a: Observation, b: Observation, strict=True) -> bool:
    if a.uncertain or b.uncertain:
        return False
    if bool(a.text) != bool(b.text):
        return False
    return normalized(a.text) == normalized(b.text) if strict else same_text(a.text, b.text)


class IntervalReader:
    """Cache readings within one sampling interval; retry uncertain frames only once."""
    def __init__(self, cfg, engine, cancel, stats):
        self.cfg, self.engine, self.cancel, self.stats = cfg, engine, cancel, stats

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    def read(self, sample: Sample, refine=False):
        self.check_cancel()
        if sample.observation is not None:
            self.stats.cache_hits += 1
            return sample.observation
        self.stats.ocr_calls += 1
        if refine:
            self.stats.refinement_calls += 1
        observation = self.engine.read(sample.image, self.cfg)
        if observation.uncertain:
            self.check_cancel()
            # A preprocessing variant can recover low-confidence text; blanks are not invented.
            if self.cfg.color is None:
                gray = cv2.cvtColor(sample.image, cv2.COLOR_BGR2GRAY)
                enhanced = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(gray)
                enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
            else:
                # Preserve hue for user-selected color filtering.
                enhanced = cv2.detailEnhance(sample.image, sigma_s=10, sigma_r=.15)
            self.stats.ocr_calls += 1
            self.stats.retry_calls += 1
            retry = self.engine.read(enhanced, self.cfg)
            if retry.text and not retry.uncertain:
                observation = retry
        sample.observation = observation
        if observation.uncertain:
            self.stats.uncertain_samples += 1
        return observation

    def refine(self, samples: list[Sample]):
        """Split unequal/uncertain brackets, stopping at the requested time precision."""
        times = [sample.time for sample in samples]
        visited = {0, len(samples) - 1}

        def split(left, right):
            self.check_cancel()
            a, b = self.read(samples[left]), self.read(samples[right])
            if right - left <= 1 or times[right] - times[left] <= self.cfg.boundary_precision + 1e-9:
                return
            if equivalent(a, b):
                return
            center = (times[left] + times[right]) / 2
            middle = min(right - 1, max(left + 1, bisect_left(times, center, left + 1, right)))
            self.read(samples[middle], refine=True)
            visited.add(middle)
            split(left, middle)
            split(middle, right)

        split(0, len(samples) - 1)
        return [samples[index] for index in sorted(visited) if index > 0]


def extract(path, cfg: Settings, engine: OcrEngine, cancel: threading.Event,
            progress=lambda *args: None, stats: ScanStats | None = None):
    stats = stats if stats is not None else ScanStats()
    started = perf_counter()
    if not math.isfinite(cfg.interval) or cfg.interval < 0:
        raise ValueError('Bước quét phải là số không âm.')
    if not math.isfinite(cfg.boundary_precision) or cfg.boundary_precision <= 0:
        raise ValueError('Độ chính xác thời gian phải lớn hơn 0.')
    if cfg.algorithm not in ('adaptive', 'linear'):
        raise ValueError('Chế độ nhận diện không hợp lệ.')
    if cancel.is_set():
        raise Cancelled()
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('Tệp không có luồng video.')
        stream = container.streams.video[0]
        total = float(stream.duration * stream.time_base) if stream.duration else (container.duration or 0) / 1e6
        nominal = 1 / float(stream.average_rate or 25)
        x, y, w, h = cfg.roi
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > stream.width or y + h > stream.height:
            raise ValueError('Vùng OCR nằm ngoài khung hình. Hãy chọn lại vùng phụ đề.')
    plan = None
    if cfg.reference_spans is not None:
        plan = build_reference_plan(cfg.reference_spans, cfg.reference_padding, total)
        if cfg.outside_interval is not None and (not math.isfinite(cfg.outside_interval) or cfg.outside_interval <= 0):
            raise ValueError('Bước quét bổ sung ngoài SRT phải lớn hơn 0.')
        stats.reference_cues = len(cfg.reference_spans)
        stats.reference_windows = len(plan.windows)
        stats.reference_seconds = sum(end - start for start, end in plan.windows)
    adaptive = cfg.algorithm == 'adaptive' and cfg.interval > 0
    builder = CueBuilder(cfg.min_duration, strict=adaptive)
    # Only ROI images for the current interval stay in memory.
    reader = IntervalReader(replace(cfg, roi=(0, 0, w, h)), engine, cancel, stats)
    previous = None
    pending = []
    last_time, last_duration = 0., nominal
    last_frame_time = -math.inf
    active_window = None
    next_idle_progress = 0.

    def process(sample):
        nonlocal previous, pending
        observation = reader.read(sample)
        stats.coarse_samples += 1
        if plan is not None and plan.window_at(sample.time) is None:
            stats.outside_samples += 1
        if previous is not None:
            old = reader.read(previous)
            if adaptive:
                if not equivalent(old, observation):
                    for point in reader.refine([previous, *pending, sample]):
                        if point is not sample:
                            builder.feed(point.time, reader.read(point))
            elif not equivalent(old, observation, strict=False):
                for point in pending:
                    builder.feed(point.time, reader.read(point, refine=True))
        builder.feed(sample.time, observation)
        previous, pending = sample, []
        progress(sample.time, total, len(builder.cues), observation.text)

    def flush_tail():
        if pending:
            sample = pending.pop()
            process(sample)

    def close_window(end):
        nonlocal previous, pending
        flush_tail()
        if builder.current:
            # Closing an unchecked region is a truncation, never evidence of a blank frame.
            builder.review_current = True
            stats.window_edge_events += 1
        builder.finish(end)
        previous, pending = None, []

    try:
        for time, duration, frame in frames(path):
            reader.check_cancel()
            stats.decoded_frames += 1
            last_time, last_duration = time, duration or nominal
            window = plan.window_at(time) if plan is not None else None
            anchor = plan is not None and plan.crosses_anchor(last_frame_time, time)
            last_frame_time = time
            only_windows = plan is not None and cfg.outside_interval is None
            if only_windows and window is None:
                if active_window is not None:
                    close_window(active_window[1])
                    active_window = None
                stats.skipped_frames += 1
                if time >= next_idle_progress:
                    progress(time, total, len(builder.cues), 'Ngoài khoảng SRT · bỏ qua OCR')
                    next_idle_progress = time + 1.
                continue
            # Two disjoint windows can fall between adjacent VFR frames with no frame in the gap.
            if only_windows and active_window is not None and window != active_window:
                close_window(active_window[1])
            first_in_window = only_windows and previous is None
            active_window = window
            interval = cfg.interval if plan is None or window is not None else cfg.outside_interval
            sample = Sample(time, frame[y:y + h, x:x + w].copy())
            if previous is not None and not anchor and time + 1e-6 < previous.time + interval:
                pending.append(sample)
                continue
            process(sample)
            if first_in_window and window[0] > 0 and sample.observation.text:
                builder.review_current = True
                stats.window_edge_events += 1
        flush_tail()
        result = builder.finish(last_time + last_duration)
        if plan is not None:
            cue_ends = [cue.end for cue in result]
            for start, end in cfg.reference_spans:
                index = bisect_right(cue_ends, max(0., start - cfg.reference_padding))
                if index == len(result) or result[index].start >= end + cfg.reference_padding:
                    stats.unmatched_reference_cues += 1
        return result
    finally:
        stats.elapsed = perf_counter() - started
