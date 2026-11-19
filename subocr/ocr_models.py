"""Pinned PP-OCRv6 ONNX weights from RapidAI/RapidOCR v3.10.0."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_SIZES = ('tiny', 'small', 'medium')
HASHES = {
    ('tiny', 'det'): 'f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5',
    ('small', 'det'): '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    ('medium', 'det'): '92078b7355007ccfffcd4c8cd441a3afd4538904d06881b29a155e1e679907c2',
    ('tiny', 'rec'): 'e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b',
    ('small', 'rec'): '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
    ('medium', 'rec'): 'eef444829dbbe18d7fea59a3f6eb75647518d2b3a9568d27c92e42940204894b',
}


def model_files(size):
    if size not in MODEL_SIZES:
        raise ValueError('Model OCR phải là tiny, small hoặc medium.')
    return tuple(f'models/PP-OCRv6_{task}_{size}.onnx' for task in ('det', 'rec'))


def model_paths(size):
    paths = tuple(ROOT / name for name in model_files(size))
    for task, path in zip(('det', 'rec'), paths):
        if not path.is_file():
            raise ValueError(f'Thiếu {path.name}. Chạy setup.bat hoặc cài lại SubLens.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != HASHES[size, task]:
                raise ValueError(f'Model {path.name} bị hỏng. Chạy setup.bat để tải lại.')
    return paths


def download_models():
    import requests
    from concurrent.futures import ThreadPoolExecutor

    def download(item):
        (size, task), digest = item
        name = f'PP-OCRv6_{task}_{size}.onnx'
        path = ROOT / 'models' / name
        path.parent.mkdir(exist_ok=True)
        if path.is_file():
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == digest:
                    return
        url = f'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/{task}/{name}'
        temp = path.with_suffix('.download')
        print(f'Đang tải {name}…', flush=True)
        try:
            with requests.get(url, stream=True, timeout=(30, 180)) as response:
                response.raise_for_status()
                with temp.open('wb') as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        stream.write(chunk)
            with temp.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise ValueError(f'Sai SHA256: {name}')
            temp.replace(path)
            print(f'Đã tải {name}: {path.stat().st_size / 1024**2:.1f} MB', flush=True)
        finally:
            temp.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, HASHES.items()))


if __name__ == '__main__':
    download_models()
