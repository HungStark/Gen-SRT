from pathlib import Path
import tempfile
import unittest

from subocr.reference import build_reference_plan, read_reference_srt


class ReferenceTests(unittest.TestCase):
    def read(self, text, encoding='utf-8-sig'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reference.srt'
            path.write_text(text, encoding=encoding)
            return read_reference_srt(path)

    def test_bom_utf16_multiline_and_unsorted_cues(self):
        text = ('2\n00:00:03,000 --> 00:00:05,250\nWrong transcript\nMore text\n\n'
                '1\n00:00:01,100 --> 00:00:02,000\n你好\n')
        for encoding in ('utf-8-sig', 'utf-16'):
            self.assertEqual(self.read(text, encoding), ((1.1, 2.), (3., 5.25)))

    def test_missing_index_and_decimal_point(self):
        self.assertEqual(self.read('00:00:01.000 --> 00:00:02.000\nanything'), ((1., 2.),))

    def test_invalid_inputs_are_reported(self):
        for text in ('', 'plain text', '1\n', '1\n00:00:02,000 --> 00:00:01,000\nA',
                     '1\n00:00:60,000 --> 00:01:02,000\nA',
                     '1\n00:00:01,000 --> 00:00:02,000\nA\n\n2\ninvalid\nB'):
            with self.assertRaises(ValueError):
                self.read(text)

    def test_padding_merges_windows_but_preserves_original_anchors(self):
        plan = build_reference_plan(((1., 2.), (2.5, 4.), (8., 9.)), padding=.7, duration=8.5)
        self.assertEqual(plan.windows, ((.30000000000000004, 4.7), (7.3, 8.5)))
        self.assertIn(2.5, plan.anchors)
        self.assertEqual(plan.window_at(3.), plan.windows[0])
        self.assertIsNone(plan.window_at(5.))
        self.assertTrue(plan.crosses_anchor(2.4, 2.6))
        self.assertFalse(plan.crosses_anchor(5., 6.))

    def test_outside_video_empty_and_invalid_ranges(self):
        for spans, padding in (((), .7), (((99., 100.),), .7), (((1., 2.),), -1), (((float('nan'), 2.),), .7)):
            with self.assertRaises(ValueError):
                build_reference_plan(spans, padding, duration=8.)


if __name__ == '__main__':
    unittest.main()
