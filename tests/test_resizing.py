"""Verify proportional cover/crop with the requested wide-video examples."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

import av
from PIL import Image, ImageDraw

from subocr.resizing import ResizeCancelled, ffmpeg_executable, ordered_paths, resize_videos, validate_size

ROOT = Path(__file__).resolve().parents[1]


class ResizingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'test_artifacts')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_video(self, name, size, border=0, audio=True):
        image = Image.new('RGB', size, 'white')
        if border:
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, border - 1, size[1] - 1), fill='red')
            draw.rectangle((size[0] - border, 0, size[0] - 1, size[1] - 1), fill='blue')
        png = self.root / (name + '.png')
        image.save(png)
        path = self.root / name
        command = [ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-nostdin',
                   '-loop', '1', '-framerate', '5', '-i', str(png)]
        if audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=0.4']
        command += ['-t', '0.4', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-threads', '1', '-c:a', 'aac', str(path)]
        subprocess.run(command, check=True, capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return path

    def test_requested_examples_are_center_cropped_with_audio_and_no_black_bars(self):
        wide = self.make_video('1.mp4', (2520, 1080), border=300)
        small = self.make_video('2.mp4', (1620, 720), border=170)
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in (wide, small)}
        updates = []
        folder, results = resize_videos([small, wide], self.root, 1920, 1080,
                                         progress=lambda *args: updates.append(args))
        self.assertEqual([r['file'] for r in results], ['1.mp4', '2.mp4'])
        for source, result in zip((wide, small), results):
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before[source])
            self.assertEqual((result['output']['width'], result['output']['height']), (1920, 1080))
            with av.open(str(folder / result['file'])) as container:
                self.assertTrue(container.streams.audio)
                frames = list(container.decode(video=0))
            self.assertEqual(len(frames), 2)
            pixels = frames[0].to_ndarray(format='rgb24')
            # Colored edge bands must be cropped out; white must reach all edges.
            self.assertGreater(pixels[5:-5, :10].mean(), 230)
            self.assertGreater(pixels[5:-5, -10:].mean(), 230)
            self.assertGreater(pixels[:10].mean(), 230)
            self.assertGreater(pixels[-10:].mean(), 230)
            self.assertAlmostEqual(result['output']['duration'], .4, delta=.05)
        self.assertEqual(updates[-1][0], 1000)
        report = json.loads((folder / 'ket_qua_chuyen_kich_thuoc.json').read_text(encoding='utf-8'))
        self.assertTrue(report['complete'])

    def test_portrait_video_silent_and_duplicate_names(self):
        one = self.make_video('same.mp4', (160, 240), audio=False)
        other_dir = self.root / 'other'
        other_dir.mkdir()
        two = other_dir / 'same.mp4'
        two.write_bytes(one.read_bytes())
        folder, results = resize_videos([one, two], self.root, 320, 180)
        self.assertEqual(len({r['file'].casefold() for r in results}), 2)
        for result in results:
            self.assertEqual(result['output']['audio_codecs'], [])
            self.assertEqual((result['output']['width'], result['output']['height']), (320, 180))

    def test_validation_order_and_cancellation(self):
        self.assertEqual([p.name for p in ordered_paths([self.root / '10.mp4', self.root / '2.mp4', self.root / '1.mp4'])],
                         ['1.mp4', '2.mp4', '10.mp4'])
        for size in ((1919, 1080), (0, 1080), (1920, 1081), (9000, 1080)):
            with self.assertRaises(ValueError):
                validate_size(*size)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ResizeCancelled):
            resize_videos([self.root / 'missing.mp4'], self.root, cancel=cancel)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
