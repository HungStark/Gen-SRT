import copy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import cv2

from subocr.colab import (ROOT, export_bundle, load_result, read_json, validate_job,
                         validate_result, verify_video, video_identity, write_result, bind_video_job)
from subocr.core import Cue, OcrEngine, Settings
from subocr.video import ScanStats


class ColabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'test_artifacts')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'video.mp4'
        self.video.write_bytes(b'sample video bytes')
        self.cfg = Settings((10, 70, 300, 20), 'en', color=(255, 255, 255), line_bands=[(.5, .3)], model_size='tiny')
        self.folder = export_bundle(self.root, self.video, self.cfg, 320, 100, 4.8)
        with zipfile.ZipFile(self.folder / 'sublens_colab_video.zip') as archive:
            self.names = archive.namelist()
            self.job = json.loads(archive.read('job.json'))

    def test_bundle_is_portable_and_selected_v6_models_are_included(self):
        self.assertEqual(asdict(validate_job(self.job)), asdict(self.cfg))
        self.assertIn('models/PP-OCRv6_det_tiny.onnx', self.names)
        self.assertIn('models/PP-OCRv6_rec_tiny.onnx', self.names)
        self.assertNotIn('models/PP-OCRv6_rec_medium.onnx', self.names)
        self.assertEqual(self.job['ocr'], 'PP-OCRv6')
        self.assertIn('colab/run_job.py', self.names)
        self.assertNotIn('subocr/ui.py', self.names)
        self.assertNotIn(self.video.name, self.names)
        self.assertTrue((self.folder / 'SubLens_Colab.ipynb').is_file())
        with zipfile.ZipFile(self.folder / 'sublens_colab_video.zip') as archive:
            for name in self.names:
                self.assertFalse(Path(name).is_absolute())
                self.assertNotIn('..', Path(name).parts)
                if name.endswith('.py'):
                    compile(archive.read(name), name, 'exec')
        notebook = read_json(self.folder / 'SubLens_Colab.ipynb')
        for i, cell in enumerate(notebook['cells']):
            if cell['cell_type'] == 'code':
                compile(''.join(cell['source']), f'cell-{i}', 'exec')

    def test_result_roundtrip_preserves_scores_multiline_and_stats(self):
        cues = [Cue(.4, 1.6, 'Hello\n你好', .79, True), Cue(2, 3.2, 'Next', .95)]
        path = self.root / 'result.sublens.json'
        stats = ScanStats(ocr_calls=12, elapsed=2.5)
        write_result(path, self.job, cues, stats, 'cuda')
        cfg, actual, actual_stats, device = load_result(path, self.video)
        self.assertEqual(actual, cues)
        self.assertEqual(asdict(actual_stats), asdict(stats))
        self.assertEqual(asdict(cfg), asdict(self.cfg))
        self.assertEqual(device, 'cuda')
        # Exact bytes with a new name are accepted; wrong content of the same size is rejected.
        renamed = self.root / 'renamed.mp4'
        renamed.write_bytes(self.video.read_bytes())
        verify_video(self.job, renamed)
        renamed.write_bytes(b'x' * self.video.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'khớp'):
            load_result(path, renamed)

    def test_corrupt_settings_and_nonfinite_values_are_rejected(self):
        for key, value in [('roi', [0, 0, 999, 20]), ('confidence', float('nan')),
                           ('interval', -1), ('language', 'xx'), ('line_bands', 'bad'),
                           ('color', [255, 256, 255])]:
            job = copy.deepcopy(self.job)
            job['settings'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_job(job)
        for data in (None, {}, {'schema': 999}, {'schema': 1, 'kind': 'sublens-colab-job'}):
            with self.assertRaises(ValueError):
                validate_job(data)

    def test_numpy_line_bands_from_locked_preview_export_as_portable_numbers(self):
        cfg = copy.deepcopy(self.cfg)
        # select_bands computes these from the OCR model's NumPy integer boxes.
        top, bottom, height = np.int64(15), np.int64(19), 20
        cfg.line_bands = [((top + bottom) / (2 * height), (bottom - top) / height)]
        cfg.confidence = np.float32(.6)
        cfg.color = tuple(np.uint8(255) for _ in range(3))
        folder = export_bundle(self.root, self.video, cfg, 320, 100, 4.8)
        with zipfile.ZipFile(folder / 'sublens_colab_video.zip') as archive:
            job = json.loads(archive.read('job.json'))
        loaded = validate_job(job)
        self.assertEqual(loaded.line_bands, [(0.85, 0.2)])
        self.assertTrue(all(type(value) is float for value in loaded.line_bands[0]))
        self.assertEqual(loaded.color, (255, 255, 255))
        for value in (True, np.bool_(True), float('nan'), np.float64('inf'), np.float64(1.1)):
            broken = copy.deepcopy(job)
            broken['settings']['line_bands'] = [[value, .2]]
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_job(broken)

    def test_malformed_result_never_passes_validation(self):
        path = self.root / 'result.sublens.json'
        write_result(path, self.job, [Cue(0, 1, 'Hello', .9)], ScanStats(), 'cpu')
        data = read_json(path)
        for key, value in [('end', float('inf')), ('text', ''), ('text', 10),
                           ('start', 2), ('confidence', 1.1), ('edited', 'false')]:
            broken = copy.deepcopy(data)
            broken['cues'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_result(broken)
        broken = copy.deepcopy(data)
        broken['cues'].append(asdict(Cue(.5, 1.5, 'Overlap')))
        with self.assertRaises(ValueError):
            validate_result(broken)
        broken = copy.deepcopy(data)
        broken['stats']['elapsed'] = float('nan')
        with self.assertRaises(ValueError):
            validate_result(broken)
        # A successful job with no detected subtitles is still importable.
        data['cues'] = []
        self.assertEqual(validate_result(data)[1], [])

    def test_gpu_requires_available_provider_and_cpu_remains_default(self):
        engine = OcrEngine(model_size='tiny')
        self.assertEqual(engine.provider, 'CPUExecutionProvider')
        for part in (engine.engine.text_det, engine.engine.text_rec):
            self.assertEqual(part.session.session.get_providers(), ['CPUExecutionProvider'])
            with self.assertRaisesRegex(RuntimeError, 'CUDAExecutionProvider'):
                engine._require_provider(part.session.session, 'CUDAExecutionProvider', 'test')
        with patch('onnxruntime.get_available_providers', return_value=['CPUExecutionProvider']):
            with self.assertRaisesRegex(RuntimeError, 'GPU'):
                OcrEngine('gpu', 'tiny')

    def test_legacy_settings_remain_importable_but_invalid_models_are_rejected(self):
        legacy = copy.deepcopy(self.job)
        del legacy['settings']['device'], legacy['settings']['model_size']
        cfg = validate_job(legacy)
        self.assertEqual((cfg.device, cfg.model_size), ('cpu', 'small'))
        for key, value in [('device', 'cuda'), ('model_size', 'large')]:
            broken = copy.deepcopy(self.job)
            broken['settings'][key] = value
            with self.assertRaises(ValueError):
                validate_job(broken)

    def test_chinese_bundle_uses_same_multilingual_v6_models(self):
        folder = export_bundle(self.root, self.video, Settings((0, 70, 320, 30)), 320, 100, 4.8)
        with zipfile.ZipFile(folder / 'sublens_colab_video.zip') as archive:
            self.assertIn('models/PP-OCRv6_rec_small.onnx', archive.namelist())
            self.assertNotIn('models/en_PP-OCRv4_rec_mobile.onnx', archive.namelist())

    def make_video(self, name, size=(320, 100), count=5, color=0):
        path = self.root / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, size)
        self.assertTrue(writer.isOpened())
        try:
            for _ in range(count):
                writer.write(np.full((size[1], size[0], 3), color, dtype=np.uint8))
        finally:
            writer.release()
        return path

    def test_reusable_bundle_binds_each_result_to_its_actual_video(self):
        sample = self.make_video('episode 1.mp4', count=5)
        second = self.make_video('episode 2.mp4', count=20, color=100)
        folder = export_bundle(self.root, sample, self.cfg, 320, 100, .5, reusable=True)
        with zipfile.ZipFile(folder / 'sublens_colab_episode 1.zip') as archive:
            template = json.loads(archive.read('job.json'))
        before = copy.deepcopy(template)
        self.assertTrue(template['reusable'])
        verify_video(template, second)
        one, two = bind_video_job(template, sample), bind_video_job(template, second)
        self.assertEqual(template, before)
        self.assertFalse(two['reusable'])
        self.assertNotEqual(one['job_id'], two['job_id'])
        self.assertEqual(two['video']['name'], second.name)
        self.assertEqual(two['video']['sample_sha256'], video_identity(second)['sample_sha256'])
        self.assertAlmostEqual(two['video']['duration'], 2.)
        self.assertEqual(two['settings'], template['settings'])
        path = self.root / 'episode2.sublens.json'
        # Past the template video's end: validation must use the scanned video's duration.
        write_result(path, two, [Cue(1.5, 1.9, 'Second episode', .9)], ScanStats(), 'cpu')
        self.assertEqual(load_result(path, second)[1][0].text, 'Second episode')
        download = self.root / 'Tên tự đặt.zip'
        with zipfile.ZipFile(download, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, 'Tên tự đặt/result.sublens.json')
            archive.writestr('Tên tự đặt/result.en.srt', 'subtitle')
        self.assertEqual(load_result(download, second)[1][0].text, 'Second episode')
        with self.assertRaisesRegex(ValueError, 'khớp'):
            load_result(path, sample)
        with self.assertRaisesRegex(ValueError, 'khớp') as mismatch:
            load_result(download, sample)
        self.assertIn('episode 2.mp4', str(mismatch.exception))
        self.assertIn('episode 1.mp4', str(mismatch.exception))
        with self.assertRaisesRegex(ValueError, 'chưa gắn'):
            write_result(path, template, [], ScanStats(), 'cpu')

    def test_reusable_bundle_rejects_other_dimensions_and_invalid_mode(self):
        template = copy.deepcopy(self.job)
        template['reusable'] = True
        other_size = self.make_video('wrong_size.mp4', size=(640, 200))
        with self.assertRaisesRegex(ValueError, '320.*100'):
            bind_video_job(template, other_size)
        template['reusable'] = 'true'
        with self.assertRaises(ValueError):
            validate_job(template)

    def test_result_import_distinguishes_job_zip_corrupt_zip_and_multiple_results(self):
        with self.assertRaisesRegex(ValueError, 'gói dùng để chạy OCR'):
            load_result(self.folder / 'sublens_colab_video.zip', self.video)
        broken = self.root / 'broken.zip'
        broken.write_bytes(b'not a zip')
        with self.assertRaisesRegex(ValueError, 'Không đọc được ZIP'):
            load_result(broken, self.video)
        ambiguous = self.root / 'two_videos.zip'
        with zipfile.ZipFile(ambiguous, 'w') as archive:
            archive.writestr('one/result.sublens.json', '{}')
            archive.writestr('two/result.sublens.json', '{}')
        with self.assertRaisesRegex(ValueError, 'nhiều tệp JSON'):
            load_result(ambiguous, self.video)


if __name__ == '__main__':
    unittest.main()
