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

from subocr.colab import (ROOT, export_bundle, load_result, read_json, validate_job,
                         validate_result, verify_video, video_identity, write_result)
from subocr.core import Cue, OcrEngine, Settings
from subocr.video import ScanStats


class ColabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'test_artifacts')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'video.mp4'
        self.video.write_bytes(b'sample video bytes')
        self.cfg = Settings((10, 70, 300, 20), 'en', color=(255, 255, 255), line_bands=[(.5, .3)])
        self.folder = export_bundle(self.root, self.video, self.cfg, 320, 100, 4.8)
        with zipfile.ZipFile(self.folder / 'job.zip') as archive:
            self.names = archive.namelist()
            self.job = json.loads(archive.read('job.json'))

    def test_bundle_is_portable_and_english_model_is_included(self):
        self.assertEqual(asdict(validate_job(self.job)), asdict(self.cfg))
        self.assertIn('models/en_PP-OCRv4_rec_mobile.onnx', self.names)
        self.assertIn('colab/run_job.py', self.names)
        self.assertNotIn('subocr/ui.py', self.names)
        self.assertNotIn(self.video.name, self.names)
        self.assertTrue((self.folder / 'SubLens_Colab.ipynb').is_file())
        with zipfile.ZipFile(self.folder / 'job.zip') as archive:
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
        with zipfile.ZipFile(folder / 'job.zip') as archive:
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

    def test_cuda_requires_actual_sessions_and_cpu_remains_default(self):
        with patch('rapidocr_onnxruntime.RapidOCR') as rapid:
            OcrEngine()
            self.assertFalse(rapid.call_args.kwargs['det_use_cuda'])
            self.assertFalse(rapid.call_args.kwargs['rec_use_cuda'])
            # Strict shapes reflect RapidOCR 1.4.4: detector.infer, recognizer.session.
            detector_inference = SimpleNamespace(session=SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider']))
            recognizer_inference = SimpleNamespace(session=SimpleNamespace(get_providers=lambda: ['CUDAExecutionProvider']))
            rapid.return_value.text_det = SimpleNamespace(infer=detector_inference)
            rapid.return_value.text_rec = SimpleNamespace(session=recognizer_inference)
            with self.assertRaisesRegex(RuntimeError, 'GPU'):
                OcrEngine(use_cuda=True)
            detector_inference.session.get_providers = lambda: ['CUDAExecutionProvider', 'CPUExecutionProvider']
            engine = OcrEngine(use_cuda=True)
            self.assertTrue(rapid.call_args.kwargs['rec_use_cuda'])
            with patch('rapidocr_onnxruntime.ch_ppocr_rec.TextRecognizer') as english:
                english.return_value.session.session.get_providers.return_value = ['CPUExecutionProvider']
                with self.assertRaisesRegex(RuntimeError, 'tiếng Anh'):
                    engine.read_english(None)
                self.assertTrue(english.call_args.args[0]['use_cuda'])

    def test_cuda_check_uses_real_rapidocr_detector_and_recognizer_sessions(self):
        engine = OcrEngine()
        # Access real library objects on CPU: the guard must report the absent GPU,
        # rather than raise AttributeError from an invented detector attribute.
        for inference in (engine.engine.text_det.infer, engine.engine.text_rec.session):
            with self.subTest(inference=inference), self.assertRaisesRegex(RuntimeError, 'GPU'):
                engine._require_cuda(inference, 'test')
        # Only provider reporting is patched; object structure remains the real library's.
        with patch.object(engine.engine.text_det.infer.session, 'get_providers', return_value=['CUDAExecutionProvider']), \
                patch.object(engine.engine.text_rec.session.session, 'get_providers', return_value=['CUDAExecutionProvider']), \
                patch('rapidocr_onnxruntime.RapidOCR', return_value=engine.engine):
            OcrEngine(use_cuda=True)

    def test_chinese_bundle_omits_optional_model(self):
        folder = export_bundle(self.root, self.video, Settings((0, 70, 320, 30)), 320, 100, 4.8)
        with zipfile.ZipFile(folder / 'job.zip') as archive:
            self.assertNotIn('models/en_PP-OCRv4_rec_mobile.onnx', archive.namelist())


if __name__ == '__main__':
    unittest.main()
