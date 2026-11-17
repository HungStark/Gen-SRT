from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
import math
import threading
from time import perf_counter

import av
import cv2
import numpy as np

from .core import CueBuilder, Observation, OcrEngine, Settings, same_caption, same_text, coalesce_equal_cues


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
    stabilized_reads: int = 0
    merged_duplicates: int = 0


@dataclass
class Sample:
    time: float
    image: np.ndarray
    observation: Observation | None = None
    duration: float = 0.


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
    return same_caption(a, b) if strict else same_text(a.text, b.text)


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
    adaptive = cfg.algorithm == 'adaptive' and cfg.interval > 0
    builder = CueBuilder(cfg.min_duration, strict=adaptive)
    # Only ROI images for the current interval stay in memory.
    reader = IntervalReader(replace(cfg, roi=(0, 0, w, h)), engine, cancel, stats)
    previous = None
    pending = []
    last_time, last_duration = 0., nominal

    def process(sample):
        nonlocal previous, pending
        observation = reader.read(sample)
        stats.coarse_samples += 1
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

    try:
        for time, duration, frame in frames(path):
            reader.check_cancel()
            stats.decoded_frames += 1
            last_time, last_duration = time, duration or nominal
            sample = Sample(time, frame[y:y + h, x:x + w].copy())
            if previous is not None and time + 1e-6 < previous.time + cfg.interval:
                pending.append(sample)
                continue
            process(sample)
        flush_tail()
        raw = builder.finish(last_time + last_duration)
        result = coalesce_equal_cues(raw)
        stats.stabilized_reads = builder.stabilized_reads
        stats.merged_duplicates = len(raw) - len(result)
        return result
    finally:
        stats.elapsed = perf_counter() - started
