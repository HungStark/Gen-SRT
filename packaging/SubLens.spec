from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent
sources = ['subocr/__init__.py', 'subocr/core.py', 'subocr/video.py',
           'subocr/editing.py', 'subocr/colab.py', 'subocr/ocr_models.py', 'colab/run_job.py']
datas = [(str(root / name), str(Path(name).parent)) for name in sources]
datas += [(str(root / 'assets'), 'assets'),
          (str(root / 'colab/SubLens_Colab.ipynb'), 'colab'),
          (str(root / 'accepted_words.txt'), '.'), (str(root / 'README.md'), '.')]
datas += [(str(path), 'models') for path in sorted((root / 'models').glob('PP-OCRv6_*.onnx'))]
datas += collect_data_files('rapidocr', includes=['**/*.yaml', '**/*.txt', '**/*.ttf'])
datas += collect_data_files('imageio_ffmpeg')

a = Analysis([str(root / 'desktop_app.py')], pathex=[str(root)],
             binaries=collect_dynamic_libs('onnxruntime'), datas=datas,
             hiddenimports=['rapidocr', 'onnxruntime.capi.onnxruntime_pybind11_state'],
             excludes=['tkinter', 'matplotlib', 'pytest', 'IPython'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SubLens',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(root / 'assets/sublens.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SubLens')
