import unittest

from subocr.core import Cue
from subocr.review import EnglishSpellChecker, accepted_words, review_rows, similar_content, confidence_label


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.checker = EnglishSpellChecker()

    def levels(self, cues):
        return [review.level for review in review_rows(cues, self.checker)]

    def test_common_ocr_misspellings_without_changing_text(self):
        text = 'This flm received support. Students should run frst. Offcial media reported it.'
        warnings = self.checker.check(text)
        self.assertEqual({issue.word: issue.suggestion for issue in warnings},
                         {'flm': 'film', 'frst': 'first', 'Offcial': 'official'})
        cue = Cue(0, 1, text, .99)
        self.assertEqual(self.levels([cue]), ['orange'])
        self.assertEqual(cue.text, text)

    def test_names_acronyms_contractions_and_chinese(self):
        for text in ['Stinky Kunzi, you scared me to death.', 'Kunzi, wait for Kuki Orochi.',
                     'Seko Ai created this film.', 'Kuki Orochi is here.',
                     "I’m sure we’ll go back when it’s safe. Don’t worry, let's go.",
                     'GPU AI SRT FLM Kunzi’s film is ready.', '请所有同学立刻停止军训']:
            with self.subTest(text=text):
                self.assertFalse(self.checker.check(text))

    def test_allowlist_applies_case_insensitively_and_ignores_comments(self):
        self.assertTrue(self.checker.check('A flm is here.'))
        self.checker.accepted = accepted_words('# Comment\nFLM # custom term\nKunzi\nSeko Ai')
        self.assertFalse(self.checker.check('A flm is here.'))
        self.assertEqual(self.checker.accepted, {'flm', 'kunzi', 'seko', 'ai'})
        self.checker.accepted = set()
        self.assertTrue(self.checker.check('A flm is here.'))

    def test_confidence_threshold_is_strictly_below_80(self):
        for confidence, expected in [(.799, 'red'), (.799999, 'red'), (.80, 'none'), (.85, 'none'), (.99, 'none')]:
            with self.subTest(confidence=confidence):
                self.assertEqual(self.levels([Cue(0, 1, 'The film is ready.', confidence)]), [expected])
        self.assertEqual(confidence_label(.799), '79.9%')
        self.assertEqual(confidence_label(.799999), '<80%')
        self.assertEqual(confidence_label(.80), '80%')

    def test_old_review_and_manual_edit_flags_do_not_color_clean_rows(self):
        self.assertEqual(self.levels([Cue(0, 1, 'The film is ready.', .99, review=True, edited=True)]), ['none'])

    def test_consecutive_duplicate_chain_marks_both_neighbors(self):
        cues = [Cue(i, i + 1, text, .99) for i, text in enumerate([
            'Official media say it was a nuclear leak.',
            'Official media say it was a nuclear leak!',
            'Official media said it was a nuclear leak.',
            'Students in front, run.',
        ])]
        reviews = review_rows(cues, self.checker)
        self.assertEqual([review.level for review in reviews], ['yellow', 'yellow', 'yellow', 'none'])
        self.assertIn('1, 3', reviews[1].reasons[0])

    def test_red_over_orange_over_yellow_and_all_reasons_kept(self):
        cues = [Cue(0, 1, 'Offcial media say it was a nuclear leak.', .79),
                Cue(1, 2, 'Offcial media say it was a nuclear leak.', .99),
                Cue(2, 3, 'Official media say it was a nuclear leak.', .99)]
        reviews = review_rows(cues, self.checker)
        self.assertEqual([review.level for review in reviews], ['red', 'orange', 'yellow'])
        self.assertEqual(len(reviews[0].reasons), 3)
        self.assertEqual(len(reviews[1].reasons), 2)

    def test_only_immediate_neighbors_are_compared(self):
        cues = [Cue(i, i + 1, text) for i, text in enumerate([
            'The film is ready.', 'Students in front, run.', 'The film is ready.'])]
        self.assertEqual(self.levels(cues), ['none', 'none', 'none'])

    def test_short_lines_empty_text_and_chinese(self):
        self.assertTrue(similar_content('Yes.', 'YES!'))
        self.assertFalse(similar_content('', ''))
        self.assertFalse(similar_content('No.', 'Now!'))
        self.assertTrue(similar_content('请所有同学立刻停止军训', '请所有同学立刻停止军训！'))
        self.assertFalse(similar_content('The film is ready.', 'Students in front, run.'))


if __name__ == '__main__':
    unittest.main()
