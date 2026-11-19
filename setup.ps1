$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.runtime'
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache\uv'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Can cai uv tu https://docs.astral.sh/uv/getting-started/installation/ roi chay lai setup.bat.'
}
uv python install 3.12
if ($LASTEXITCODE -ne 0) { throw 'Khong tai duoc Python.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    uv venv --python 3.12 .venv
    if ($LASTEXITCODE -ne 0) { throw 'Khong tao duoc moi truong.' }
}
uv pip uninstall --python .venv\Scripts\python.exe rapidocr-onnxruntime onnxruntime onnxruntime-gpu onnxruntime-directml opencv-python opencv-python-headless
if ($LASTEXITCODE -ne 0) { throw 'Khong go duoc runtime OCR cu.' }
uv pip install --python .venv\Scripts\python.exe -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Khong cai duoc thu vien. Kiem tra ket noi mang.' }
& .venv\Scripts\python.exe -X utf8 -m subocr.ocr_models
if ($LASTEXITCODE -ne 0) { throw 'Khong tai duoc model PP-OCRv6.' }
Write-Host 'Da cai xong. Mo start.bat de su dung.'
