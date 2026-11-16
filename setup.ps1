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
uv pip install --only-binary :all: --python .venv\Scripts\python.exe -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Khong cai duoc thu vien. Kiem tra ket noi mang.' }
$modelDir = Join-Path $PSScriptRoot 'models'
New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
$model = Join-Path $modelDir 'en_PP-OCRv4_rec_mobile.onnx'
$modelHash = 'E8770C967605983D1570CDF5352041DFB68FA0C21664F49F47B155ABD3E0E318'
if (-not (Test-Path -LiteralPath $model) -or (Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash -ne $modelHash) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx' -OutFile $model
}
if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash -ne $modelHash) { throw 'Mo hinh OCR khong dung checksum.' }
Write-Host 'Da cai xong. Mo start.bat de su dung.'
