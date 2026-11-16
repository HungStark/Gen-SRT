from collections import Counter
from contextlib import nullcontext
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

import numpy as np

from subocr.core import Observation, Settings
from subocr.video import Cancelled, ScanStats, extract


class FakeEngine:
    def __init__(self, state, uncertain_at=(), cancel=None):
        self.state, self.uncertain_at, self.cancel = state, set(uncertain_at), cancel
        self.indices = []
        self.retry = None

    def read(self, image, cfg):
        index = int(image[0, 0, 0])
        if self.retry is not None:
            index, self.retry = self.retry, None
        elif index in self.uncertain_at:
            self.retry = index
        self.indices.append(index)
        if self.cancel is not None and len(self.indices) == 3:
            self.cancel.set()
        if index in self.uncertain_at:
            return Observation(uncertain=True)
        return Observation(self.state(index), .98)


class AdaptiveTests(unittest.TestCase):
    def scan(self, state, times=None, interval=.5, uncertain_at=(), cancel=None, algorithm='adaptive',
             reference_spans=None, reference_padding=.7, outside_interval=2.):
        times = times if times is not None else [i * .04 for i in range(200)]
        stream = SimpleNamespace(duration=round((times[-1] + .04) * 1000) if times else 0,
                                 time_base=.001, average_rate=25, width=32, height=16)
        metadata = SimpleNamespace(streams=SimpleNamespace(video=[stream]))
        sequence = [(time, .04, np.full((16, 32, 3), index, dtype=np.uint8)) for index, time in enumerate(times)]
        cfg = Settings((0, 0, 32, 16), interval=interval, algorithm=algorithm,
                       reference_spans=reference_spans, reference_padding=reference_padding, outside_interval=outside_interval)
        stats, event = ScanStats(), cancel if cancel is not None else threading.Event()
        engine = FakeEngine(state, uncertain_at, cancel)
        with patch('subocr.video.av.open', return_value=nullcontext(metadata)), patch('subocr.video.frames', return_value=iter(sequence)):
            cues = extract('fake.mp4', cfg, engine, event, stats=stats)
        return cues, stats, engine

    def test_stable_caption_and_blank_need_few_reads(self):
        for value in ('你好', ''):
            cues, stats, engine = self.scan(lambda index: value)
            self.assertLess(stats.ocr_calls, 20)
            self.assertEqual(stats.refinement_calls, 0)
            self.assertEqual(len(cues), bool(value))
            self.assertTrue(all(count == 1 for count in Counter(engine.indices).values()))
            if cues:
                self.assertAlmostEqual(cues[0].end, 8.)

    def test_captions_hidden_between_equal_five_second_endpoints(self):
        def state(index):
            return '你好' if index < 25 or index >= 75 else '再见'
        cues, stats, engine = self.scan(state)
        self.assertEqual([cue.text for cue in cues], ['你好', '再见', '你好'])
        self.assertLessEqual(abs(cues[0].end - 1.), .10001)
        self.assertLessEqual(abs(cues[1].end - 3.), .10001)
        self.assertLess(stats.ocr_calls, 40)
        self.assertGreater(stats.cache_hits, 0)
        self.assertTrue(all(count == 1 for count in Counter(engine.indices).values()))

    def test_blank_to_text_to_blank_and_repeated_caption(self):
        cues, _, _ = self.scan(lambda i: '你好' if 20 <= i < 55 or 80 <= i < 120 else '')
        self.assertEqual([cue.text for cue in cues], ['你好', '你好'])
        for cue, expected in zip(cues, [(.8, 2.2), (3.2, 4.8)]):
            self.assertLessEqual(abs(cue.start - expected[0]), .10001)
            self.assertLessEqual(abs(cue.end - expected[1]), .10001)

    def test_third_state_at_midpoint_splits_both_halves(self):
        cues, _, _ = self.scan(lambda i: '甲' if i < 4 else ('乙' if i < 8 else '丙'))
        self.assertEqual([cue.text for cue in cues], ['甲', '乙', '丙'])

    def test_single_character_change_in_long_caption_is_kept(self):
        cues, _, _ = self.scan(lambda i: '请所有同学立刻停止军训' if i < 80 else '请所有同学立刻开始军训')
        self.assertEqual(len(cues), 2)

    def test_uncertain_frame_does_not_close_caption(self):
        cues, stats, _ = self.scan(lambda i: '你好', uncertain_at=(13,))
        self.assertEqual(len(cues), 1)
        self.assertTrue(cues[0].review)
        self.assertAlmostEqual(cues[0].end, 8.)
        self.assertEqual(stats.retry_calls, 1)
        self.assertEqual(stats.uncertain_samples, 1)

    def test_final_partial_interval_is_checked(self):
        times = [i * .04 for i in range(59)]
        cues, _, _ = self.scan(lambda i: '你好' if i < 55 else '', times)
        self.assertLessEqual(abs(cues[0].end - 2.2), .10001)

    def test_vfr_uses_timestamps_not_index_midpoint(self):
        times = [0, .04, .08, .12, .16, .2, .24, .6, .8, 1.2]
        cues, _, _ = self.scan(lambda i: '你好' if i >= 7 else '', times)
        self.assertEqual(cues[0].start, .6)

    def test_all_frame_mode_and_cancellation(self):
        _, stats, _ = self.scan(lambda i: '你好', interval=0, algorithm='linear')
        self.assertEqual(stats.ocr_calls, stats.decoded_frames)
        with self.assertRaises(Cancelled):
            self.scan(lambda i: '你好', cancel=threading.Event())


class GuidedTests(unittest.TestCase):
    scan = AdaptiveTests.scan

    def test_one_hint_can_produce_multiple_ocr_cues(self):
        state = lambda i: '你好' if 20 <= i < 35 else ('再见' if 35 <= i < 55 else '')
        cues, stats, engine = self.scan(state, reference_spans=((1., 2.),), outside_interval=None)
        self.assertEqual([cue.text for cue in cues], ['你好', '再见'])
        self.assertLessEqual(abs(cues[0].start - .8), .10001)
        self.assertLessEqual(abs(cues[0].end - 1.4), .10001)
        self.assertLessEqual(abs(cues[1].end - 2.2), .10001)
        self.assertGreater(stats.skipped_frames, 0)
        self.assertTrue(all(.3 - 1e-6 <= i * .04 <= 2.7 + 1e-6 for i in engine.indices))

    def test_padding_finds_early_start_and_late_end(self):
        cues, _, _ = self.scan(lambda i: '你好' if 20 <= i < 60 else '', reference_spans=((1., 2.),), outside_interval=None)
        self.assertEqual(len(cues), 1)
        self.assertLessEqual(abs(cues[0].start - .8), .10001)
        self.assertLessEqual(abs(cues[0].end - 2.4), .10001)
        self.assertFalse(cues[0].review)

    def test_optional_outside_scan_finds_omitted_caption(self):
        state = lambda i: '你好' if 25 <= i < 50 else ('再见' if 100 <= i < 140 else '')
        inside, _, _ = self.scan(state, reference_spans=((1., 2.),), outside_interval=None)
        full, stats, _ = self.scan(state, reference_spans=((1., 2.),))
        self.assertEqual([cue.text for cue in inside], ['你好'])
        self.assertEqual([cue.text for cue in full], ['你好', '再见'])
        self.assertGreater(stats.outside_samples, 0)
        self.assertLessEqual(abs(full[1].start - 4.), .10001)
        self.assertLessEqual(abs(full[1].end - 5.6), .10001)

    def test_blank_hint_does_not_fabricate_caption(self):
        cues, stats, _ = self.scan(lambda i: '', reference_spans=((1., 2.),), outside_interval=None)
        self.assertEqual(cues, [])
        self.assertEqual(stats.unmatched_reference_cues, 1)

    def test_text_at_unchecked_window_edges_is_flagged(self):
        cues, stats, _ = self.scan(lambda i: '你好' if 10 <= i < 90 else '',
                                   reference_spans=((1.4, 1.6),), reference_padding=.2, outside_interval=None)
        self.assertEqual(len(cues), 1)
        self.assertTrue(cues[0].review)
        self.assertAlmostEqual(cues[0].start, 1.2)
        self.assertAlmostEqual(cues[0].end, 1.8)
        self.assertEqual(stats.window_edge_events, 2)

    def test_overlapping_hints_do_not_repeat_ocr(self):
        cues, stats, engine = self.scan(lambda i: '你好' if 25 <= i < 75 else '',
                                        reference_spans=((1., 2.), (1.5, 3.)), outside_interval=None)
        self.assertEqual(len(cues), 1)
        self.assertEqual(stats.reference_windows, 1)
        self.assertEqual(stats.reference_cues, 2)
        self.assertEqual(stats.unmatched_reference_cues, 0)
        self.assertTrue(all(count == 1 for count in Counter(engine.indices).values()))

    def test_vfr_disjoint_windows_keep_separate_occurrences(self):
        cues, _, _ = self.scan(lambda i: '你好', times=[0., .5, 2., 3.],
                               reference_spans=((.4, .6), (1.9, 2.1)), reference_padding=0, outside_interval=None)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0].end, .6)
        self.assertAlmostEqual(cues[1].start, 2.)
        self.assertTrue(all(cue.review for cue in cues))

    def test_all_frame_mode_respects_selected_windows(self):
        cues, stats, engine = self.scan(lambda i: '你好' if 25 <= i < 50 else '',
                                        reference_spans=((1., 2.),), interval=0, algorithm='linear', outside_interval=None)
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0].start, 1.)
        self.assertAlmostEqual(cues[0].end, 2.)
        self.assertLess(stats.ocr_calls, stats.decoded_frames)


if __name__ == '__main__':
    unittest.main()
