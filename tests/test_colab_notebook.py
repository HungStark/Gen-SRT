"""Test the notebook's real subprocess wrapper without Colab, downloads or a GPU."""
import ast
from collections import deque
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import textwrap


ROOT = Path(__file__).resolve().parents[1]


class ColabNotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'test_artifacts')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        nb = json.loads((ROOT / 'colab/SubLens_Colab.ipynb').read_text(encoding='utf-8'))
        self.cells = [''.join(cell['source']) for cell in nb['cells'] if cell['cell_type'] == 'code']
        tree = ast.parse(self.cells[0])
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_logged')
        namespace = {'deque': deque, 'Path': Path, 'subprocess': subprocess}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<notebook logger>', 'exec'), namespace)
        self.run_logged = namespace['run_logged']

    def test_stdout_stderr_and_original_error_are_visible_and_saved(self):
        stream = io.StringIO()
        log = self.root / 'failure.log'
        with contextlib.redirect_stdout(stream), self.assertRaisesRegex(RuntimeError, 'missing_ocr') as error:
            self.run_logged([sys.executable, '-u', '-c',
                             "import sys; print('started', flush=True); print('ModuleNotFoundError: missing_ocr', file=sys.stderr); sys.exit(7)"],
                            log_path=log)
        for text in ('started', 'ModuleNotFoundError: missing_ocr'):
            self.assertIn(text, stream.getvalue())
            self.assertIn(text, log.read_text(encoding='utf-8'))
        self.assertIn('7', str(error.exception))

    def test_installation_targets_python312_and_keeps_kernel_packages(self):
        # Execute the real setup cell, replacing only actual external commands.
        tree = ast.parse(self.cells[0].replace('/content', self.root.as_posix()))
        tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef)]
        commands = []
        def logged(command, **kwargs):
            commands.append((command, kwargs))
        namespace = {'run_logged': logged}
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='T4')), \
                contextlib.redirect_stdout(io.StringIO()):
            exec(compile(tree, '<notebook setup>', 'exec'), namespace)
        managed = [cmd for cmd, _ in commands if 'venv' in cmd]
        self.assertEqual(len(managed), 1)
        self.assertIn('3.12', managed[0])
        installs = [cmd for cmd, _ in commands if 'install' in cmd and 'pip' in cmd and '--python' in cmd]
        self.assertTrue(any('rapidocr-onnxruntime==1.4.4' in cmd for cmd in installs))
        self.assertTrue(all(cmd[cmd.index('--python') + 1] != sys.executable for cmd in installs))
        self.assertFalse(any('rapidocr' in cmd for cmd, _ in commands))
        # The preflight actually imports the legacy API and performs an OCR inference.
        self.assertIn('from rapidocr_onnxruntime import RapidOCR', commands[-1][0][-1])
        self.assertIn('ocr(np.zeros', commands[-1][0][-1])
        self.assertTrue(Path(namespace['OCR_PYTHON']).as_posix().endswith('sublens_runtime_py312/bin/python'))

    def test_gpu_preflight_uses_real_library_structure(self):
        import onnxruntime as ort
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        # Extract and run the GPU probe exactly as distributed in the notebook.
        tree = ast.parse(self.cells[0])
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'gpu_check' for t in node.targets))
        probe = textwrap.dedent(ast.literal_eval(assignment.value.args[0]))
        with patch.object(ort, 'preload_dlls', create=True), \
                patch('rapidocr_onnxruntime.RapidOCR', return_value=ocr), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'CUDA'):
                exec(compile(probe, '<GPU probe, actual CPU library>', 'exec'), {})
            with patch.object(ocr.text_det.infer.session, 'get_providers', return_value=['CUDAExecutionProvider']), \
                    patch.object(ocr.text_rec.session.session, 'get_providers', return_value=['CUDAExecutionProvider']):
                # Inference really runs on CPU here; this verifies the integration's
                # attribute access and success path, not GPU availability or speed.
                exec(compile(probe, '<GPU probe, reported CUDA>', 'exec'), {})

    def test_step4_uses_ocr_interpreter_and_clears_old_result_on_failure(self):
        workspace = self.root / 'workspace'
        (workspace / 'colab').mkdir(parents=True)
        runner = workspace / 'colab/run_job.py'
        runner.write_text("import sys\nprint('ModuleNotFoundError: rapidocr_onnxruntime', file=sys.stderr)\nsys.exit(1)\n", encoding='utf-8')
        video = workspace / 'input.mp4'
        video.write_bytes(b'video')
        env = {'Path': Path, 'tempfile': tempfile, 'workspace': workspace, 'video': video,
               'OCR_PYTHON': sys.executable, 'OCR_ENV': dict(os.environ),
               'sys': SimpleNamespace(executable='wrong-kernel-python'), 'run_logged': self.run_logged,
               'output': self.root / 'old-result'}
        tree = ast.parse(self.cells[3])
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'save_results_to_drive' for t in node.targets):
                node.value = ast.Constant(False)
        ast.fix_missing_locations(tree)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'rapidocr_onnxruntime'):
            exec(compile(tree, '<notebook step4>', 'exec'), env)
        self.assertIsNone(env['output'])
        self.assertEqual(env['command'][0], sys.executable)
        self.assertIn('rapidocr_onnxruntime', (env['run_output'] / 'ocr.log').read_text())
        # A later successful retry gets a separate output directory and streams its log too.
        failed_output = env['run_output']
        runner.write_text("import sys\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index('--output')+1])\n(p/'result.sublens.json').write_text('{}')\nprint('OCR finished')\n", encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            exec(compile(tree, '<notebook step4>', 'exec'), env)
        self.assertNotEqual(env['output'], failed_output)
        self.assertTrue((env['output'] / 'result.sublens.json').is_file())
        self.assertIn('OCR finished', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
