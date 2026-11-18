"""Run an exported SubLens job. CUDA is required unless --cpu is explicitly given."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subocr.colab import read_json, validate_job, bind_video_job, write_result
from subocr.core import OcrEngine, write_srt
from subocr.video import extract, ScanStats


def run(job_path, video_path, output_dir, use_cuda=True):
    job = bind_video_job(read_json(job_path), video_path)
    cfg = validate_job(job)
    if use_cuda:
        import onnxruntime as ort
        # Load the CUDA 12 / cuDNN 9 libraries installed by the notebook.
        if hasattr(ort, 'preload_dlls'):
            ort.preload_dlls(directory='')
        if 'CUDAExecutionProvider' not in ort.get_available_providers():
            raise RuntimeError('Chưa có CUDAExecutionProvider. Chọn runtime GPU rồi chạy lại ô cài đặt.')
    engine = OcrEngine(use_cuda=use_cuda)
    stats = ScanStats()
    last_print = -10.

    def progress(time, total, count, text):
        nonlocal last_print
        now = monotonic()
        if now - last_print >= 2:
            print(f'{time:.1f}/{total:.1f} giây · {count} đoạn · {text[:80]!r}', flush=True)
            last_print = now

    cues = extract(video_path, cfg, engine, threading.Event(), progress, stats)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / 'result.sublens.json'
    write_result(result_path, job, cues, stats, 'cuda' if use_cuda else 'cpu')
    write_srt(output_dir / f'result.{cfg.language}.srt', cues)
    print(f'Hoàn tất: {len(cues)} đoạn, {stats.elapsed:.1f} giây. Kết quả: {result_path}', flush=True)
    return result_path


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--video', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cpu', action='store_true', help='Chỉ dùng để kiểm tra cục bộ, không cần GPU.')
    args = parser.parse_args()
    run(args.job, args.video, args.output, use_cuda=not args.cpu)
