$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache\uv'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.cache\pyinstaller'
$env:PYTHONUSERBASE = Join-Path $PSScriptRoot '.cache\python-user'
$env:PYTHONNOUSERSITE = '1'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.bat first.' }
& $python -c 'from subocr.ocr_models import model_paths, MODEL_SIZES; [model_paths(size) for size in MODEL_SIZES]'
if ($LASTEXITCODE -ne 0) { throw 'Missing or corrupt PP-OCRv6 weights. Run setup.bat.' }
& $python 'colab\build_notebook.py'
if ($LASTEXITCODE -ne 0) { throw 'Could not generate Colab notebook.' }
& $python -c 'import PyInstaller'
if ($LASTEXITCODE -ne 0) {
    uv pip install --python $python 'pyinstaller==6.22.3'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install PyInstaller.' }
}
& $python 'packaging\make_icon.py'
if ($LASTEXITCODE -ne 0) { throw 'Could not create the icon.' }
& $python -m PyInstaller --noconfirm --distpath 'dist' --workpath 'build' 'packaging\SubLens.spec'
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Host 'Built: dist\SubLens\SubLens.exe'
