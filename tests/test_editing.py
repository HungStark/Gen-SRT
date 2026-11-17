from dataclasses import asdict
import unittest

from subocr.core import Cue
from subocr.editing import parse_time, cue_errors, consecutive_rows, merge_cues


class EditingTests(unittest.TestCase):
    def test_time_formats_and_invalid_values(self):
        self.assertAlmostEqual(parse_time('01:02:03,004'), 3723.004)
        self.assertAlmostEqual(parse_time('1,25'), 1.25)
        self.assertAlmostEqual(parse_time('00:00:01.2'), 1.2)
        for value in ('nan', 'inf', '-1', '00:60:01,000', '00:00:60,000', 'abc'):
            with self.assertRaises(ValueError):
                parse_time(value)

    def test_merge_keeps_exact_chosen_content_and_all_selected_time(self):
        cues = [Cue(.2, 1., 'first', .9), Cue(1.4, 2.6, '你好\nWorld', .82, True), Cue(3., 4., 'last')]
        before = [asdict(cue) for cue in cues]
        result = merge_cues(cues, [0, 1], 1)
        self.assertEqual(len(result), 2)
        self.assertEqual((result[0].start, result[0].end, result[0].text), (.2, 2.6, '你好\nWorld'))
        self.assertEqual(result[0].confidence, .82)
        self.assertTrue(result[0].edited and result[0].review)
        self.assertEqual([asdict(cue) for cue in cues], before)

    def test_only_adjacent_rows_and_a_selected_source_can_merge(self):
        cues = [Cue(0, 1, 'a'), Cue(1, 2, 'b'), Cue(2, 3, 'c')]
        self.assertTrue(consecutive_rows([2, 1]))
        self.assertFalse(consecutive_rows([0, 2]))
        self.assertFalse(consecutive_rows([1]))
        for rows, source in (([0, 2], 0), ([0, 1], 2), ([0], 0)):
            with self.assertRaises(ValueError):
                merge_cues(cues, rows, source)

    def test_empty_source_is_rejected_but_another_source_can_be_chosen(self):
        cues = [Cue(0, 1, ''), Cue(1, 2, 'keep')]
        with self.assertRaises(ValueError):
            merge_cues(cues, [0, 1], 0)
        self.assertEqual(merge_cues(cues, [0, 1], 1)[0].text, 'keep')

    def test_validation_finds_overlap_empty_and_bad_duration(self):
        errors = cue_errors([Cue(0, 2, 'a'), Cue(1.5, 3, 'b'), Cue(4, 3.5, ''), Cue(5, 6, 'ok')])
        self.assertEqual(set(errors), {0, 1, 2})
        self.assertEqual(cue_errors([Cue(0, 1, 'a'), Cue(1, 2, 'b')]), {})


if __name__ == '__main__':
    unittest.main()
