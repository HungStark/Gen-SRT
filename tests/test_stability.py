from dataclasses import asdict
import unittest

import numpy as np
import cv2

from subocr.core import Cue, CueBuilder, Line, Observation, OcrEngine, Settings, coalesce_equal_cues, same_caption, subtitle_mask, same_glyphs


TEXT = 'This film received creative support from Seko Ai'
MISREAD = 'This flm received creative support from Seko Ai'


def mask():
    result = np.zeros((32, 384), dtype=bool)
    result[6:26, 8:376:8] = True
    return result


class StabilityTests(unittest.TestCase):
    def test_four_identical_fragments_from_screenshot_become_one(self):
        source = [Cue(20.267, 20.4, TEXT, .99), Cue(20.4, 22.2, TEXT, .99),
                  Cue(22.2, 23., TEXT, .99), Cue(23.067, 23.5, TEXT, .99)]
        before = [asdict(cue) for cue in source]
        result = coalesce_equal_cues(source)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].start, result[0].end, result[0].text), (20.267, 23.5, TEXT))
        self.assertTrue(result[0].review)
        self.assertEqual([asdict(cue) for cue in source], before)

    def test_long_gap_or_another_caption_prevents_automatic_merge(self):
        self.assertEqual(len(coalesce_equal_cues([Cue(0, 1, TEXT), Cue(1.2, 2, TEXT)])), 2)
        self.assertEqual(len(coalesce_equal_cues([Cue(0, 1, TEXT), Cue(1, 1.1, 'Another caption'), Cue(1.1, 2, TEXT)])), 3)

    def test_spaces_linebreaks_and_punctuation_do_not_fragment_same_text(self):
        cues = coalesce_equal_cues([Cue(0, 1, 'Hello, world!'), Cue(1, 2, 'Hello\nworld')])
        self.assertEqual(len(cues), 1)

    def test_lookalike_requires_matching_glyphs(self):
        a = Observation(TEXT, .99, visual_mask=mask())
        self.assertTrue(same_caption(a, Observation(MISREAD, .99, visual_mask=mask())))
        shifted = np.roll(mask(), 1, axis=1)
        self.assertTrue(same_caption(a, Observation(MISREAD, .99, visual_mask=shifted)))
        other = mask()
        other[6:26, 120:160] = False
        self.assertFalse(same_caption(a, Observation(MISREAD, .99, visual_mask=other)))
        self.assertFalse(same_caption(a, Observation(MISREAD, .99)))

    def test_real_word_number_and_chinese_changes_are_preserved(self):
        for first, second in [(TEXT, TEXT.replace('support', 'supports')),
                              ('The total amount today is 100 dollars', 'The total amount today is 101 dollars'),
                              ('请所有同学立刻停止军训', '请所有同学立刻开始军训')]:
            self.assertFalse(same_caption(Observation(first, .99, visual_mask=mask()),
                                          Observation(second, .99, visual_mask=mask())))

    def test_wobble_and_dropout_keep_observed_consensus_text(self):
        builder = CueBuilder(strict=True)
        for time, text in [(20.267, TEXT), (20.4, MISREAD), (21., MISREAD), (22.2, TEXT),
                           (22.6, TEXT), (23., ''), (23.067, TEXT), (23.3, TEXT), (23.5, '')]:
            builder.feed(time, Observation(text, .99, visual_mask=mask() if text else None))
        result = coalesce_equal_cues(builder.finish(23.6))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, TEXT)
        self.assertEqual(result[0].start, 20.267)
        self.assertEqual(result[0].end, 23.5)

    def test_mask_handles_fading_text_and_detector_padding(self):
        first = np.full((80, 500, 3), 25, dtype=np.uint8)
        second = np.full((80, 500, 3), 70, dtype=np.uint8)
        cv2.putText(first, 'This film received support', (12, 50), cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 180, 180), 1, cv2.LINE_AA)
        cv2.putText(second, 'This film received support', (12, 50), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 1, cv2.LINE_AA)
        a = subtitle_mask(first, [Line(TEXT, .99, (5, 20, 400, 60))])
        b = subtitle_mask(second, [Line(TEXT, .99, (3, 16, 403, 64))])
        self.assertTrue(same_glyphs(a, b))

    def test_distant_scene_text_does_not_poison_english_row(self):
        engine = OcrEngine.__new__(OcrEngine)
        def box(left, right):
            return [[left, 50], [right, 50], [right, 80], [left, 80]]
        engine.engine = lambda *args, **kwargs: ([[box(20, 600), TEXT, .99], [box(900, 990), '隆质餐', .95]], None)
        engine.read_english = lambda patch: (TEXT, .99)
        observation = engine.read(np.zeros((130, 1000, 3), dtype=np.uint8), Settings((0, 0, 1000, 130), 'en'))
        self.assertEqual(observation.text, TEXT)
        self.assertEqual(len(observation.lines), 2)
        self.assertFalse(observation.lines[1].accepted)


if __name__ == '__main__':
    unittest.main()
