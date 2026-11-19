"""Run the actual bundled PP-OCRv6 weights, including the recognition-only reread."""
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from subocr.core import OcrEngine, Settings


def sample_frame():
    image = Image.new('RGB', (960, 200), (30, 35, 45))
    draw = ImageDraw.Draw(image)
    draw.text((90, 30), 'Hello subtitle world.',
              font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 36), fill='white')
    draw.text((90, 110), '我们马上离开这里',
              font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 36), fill='white')
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


@unittest.skipUnless(Path('C:/Windows/Fonts/msyh.ttc').is_file(), 'Windows test fonts')
class OcrV6Tests(unittest.TestCase):
    def test_three_real_model_sizes_read_english_and_chinese_on_cpu(self):
        frame = sample_frame()
        for size in ('tiny', 'small', 'medium'):
            with self.subTest(size=size):
                engine = OcrEngine('cpu', size)
                self.assertEqual(engine.provider, 'CPUExecutionProvider')
                for section in (engine.engine.cfg.Det, engine.engine.cfg.Rec):
                    self.assertEqual(section.ocr_version.value, 'PP-OCRv6')
                    self.assertEqual(section.model_type.value, size)
                for lang, roi, expected in [('en', (0, 0, 960, 95), 'Hello subtitle world.'),
                                            ('zh', (0, 95, 960, 105), '我们马上离开这里')]:
                    actual = engine.read(frame, Settings(roi, lang, model_size=size))
                    self.assertEqual(actual.text, expected)
                    self.assertGreater(actual.score, .9)


if __name__ == '__main__':
    unittest.main()
