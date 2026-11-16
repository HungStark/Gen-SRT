import tempfile
import unittest
from pathlib import Path

from subocr.core import Cue, CueBuilder, Observation, has_han, matches_language, same_text, timestamp, write_srt


class CoreTests(unittest.TestCase):
    def test_language_filter_preserves_mixed_sentence(self):
        self.assertTrue(matches_language('第3组，Mike！', 'zh'))
        self.assertFalse(matches_language('第3组，Mike！', 'en'))
        self.assertTrue(matches_language('Hello, Mike! 123', 'en'))
        self.assertFalse(matches_language('Hello, Mike!', 'zh'))
        self.assertTrue(has_han('𠀀'))

    def test_short_chinese_changes_are_separate(self):
        self.assertFalse(same_text('不要走', '你要走'))
        self.assertTrue(same_text('Hello, world!', 'hello world'))

    def test_repeated_caption_after_gap_has_new_cue(self):
        builder = CueBuilder()
        for time, text in [(0, ''), (.1, '你好'), (.2, '你好'), (.3, ''), (.4, ''), (.5, '你好'), (.6, '你好')]:
            builder.feed(time, Observation(text, .95))
        cues = builder.finish(.7)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0].start, .1)
        self.assertAlmostEqual(cues[0].end, .3)
        self.assertAlmostEqual(cues[1].start, .5)
        self.assertAlmostEqual(cues[1].end, .7)

    def test_observed_consensus_and_review(self):
        builder = CueBuilder()
        for time, text in [(0, 'This is a long sentence.'), (.2, 'This is a long sentencf.'), (.4, 'This is a long sentence.')]:
            builder.feed(time, Observation(text, .9))
        cue = builder.finish(.6)[0]
        self.assertEqual(cue.text, 'This is a long sentence.')
        self.assertTrue(cue.review)

    def test_srt_and_validation(self):
        self.assertEqual(timestamp(3661.234), '01:01:01,234')
        self.assertEqual(timestamp(59.9996), '00:01:00,000')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sub.srt'
            write_srt(path, [Cue(.1, .9, '你好\n世界')])
            self.assertIn('00:00:00,100 --> 00:00:00,900\n你好\n世界', path.read_text(encoding='utf-8-sig'))
            with self.assertRaises(ValueError):
                write_srt(path, [Cue(1, 2, 'one'), Cue(1.5, 3, 'two')])
            with self.assertRaises(ValueError):
                write_srt(path, [Cue(1, 2, '')])


if __name__ == '__main__':
    unittest.main()
