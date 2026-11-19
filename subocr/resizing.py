"""Resize each video to cover the target rectangle, then crop the center."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading

import av


class ResizeCancelled(Exception):
    pass


def ordered_paths(paths):
    def key(path):
        return tuple(int(piece) if piece.isdigit() else piece.casefold()
                     for piece in re.split(r'(\d+)', path.name))
    unique = dict.fromkeys(Path(path).resolve() for path in paths)
    return sorted(unique, key=lambda path: (key(path), str(path).casefold()))


def validate_size(width, height):
    if any(type(n) is not int or n < 2 or n > 8192 or n % 2 for n in (width, height)):
        raise ValueError('Chiều rộng và chiều cao phải là số chẵn từ 2 đến 8192 pixel.')


def cover_filter(width, height):
    validate_size(width, height)
    # DAR includes non-square source pixels. Round the scaled size UP to even
    # dimensions so both dimensions cover the target, then crop exact pixels.
    return (f"scale=w='if(gte(dar,{width}/{height}),ceil({height}*dar/2)*2,{width})':"
            f"h='if(gte(dar,{width}/{height}),{height},ceil({width}/dar/2)*2)':flags=lanczos,"
            f'setsar=1,crop=w={width}:h={height}:x=(iw-ow)/2:y=(ih-oh)/2:exact=1,setsar=1')


def probe_video(path):
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError(f'{Path(path).name}: tệp không có hình ảnh video.')
        video = container.streams.video[0]
        duration = max((container.duration or 0) / 1e6,
                       float(video.duration * video.time_base) if video.duration else 0)
        return {'width': video.width, 'height': video.height, 'duration': duration,
                'audio_codecs': [stream.codec_context.name for stream in container.streams.audio]}


def ffmpeg_executable():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def check_cancel(cancel):
    if cancel.is_set():
        raise ResizeCancelled()


def _run_ffmpeg(args, log_path, cancel, on_time):
    check_cancel(cancel)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    lines = queue.Queue()
    with Path(log_path).open('a', encoding='utf-8') as log:
        log.write('COMMAND: ' + repr(args) + '\n')
        log.flush()
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=log, text=True, encoding='utf-8', errors='replace', creationflags=flags)

        def read_progress():
            for line in process.stdout:
                lines.put(line.strip())

        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()

        def drain():
            while True:
                try:
                    line = lines.get_nowait()
                except queue.Empty:
                    return
                if line.startswith('out_time_us='):
                    try:
                        on_time(max(0., int(line.split('=', 1)[1]) / 1e6))
                    except ValueError:
                        pass

        try:
            while process.poll() is None:
                drain()
                if cancel.wait(.15):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise ResizeCancelled()
            reader.join(timeout=2)
            drain()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join(timeout=2)
            process.stdout.close()
    if process.returncode:
        tail = '\n'.join(Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines()[-12:])
        raise ValueError(f'Không chuyển được kích thước video. Xem resize.log trong thư mục kết quả.\n{tail}')


def resize_videos(paths, parent, width=1920, height=1080, cancel=None, progress=lambda *args: None):
    validate_size(width, height)
    cancel = cancel if cancel is not None else threading.Event()
    check_cancel(cancel)
    ordered = ordered_paths(paths)
    if not ordered:
        raise ValueError('Chọn ít nhất một video.')
    metadata = []
    for index, path in enumerate(ordered):
        check_cancel(cancel)
        progress(0, 1000, f'Đọc video {index + 1}/{len(ordered)}: {path.name}')
        metadata.append(probe_video(path))
    parent = Path(parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=f'Video_{width}x{height}_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_', dir=parent))
    outputs = []
    report = {'width': width, 'height': height, 'method': 'scale_to_cover_center_crop',
              'inputs': [str(path) for path in ordered], 'videos': outputs, 'complete': False}
    try:
        with tempfile.TemporaryDirectory(prefix='.working_', dir=folder) as temp:
            used = set()
            for index, (path, info) in enumerate(zip(ordered, metadata)):
                check_cancel(cancel)
                name, sequence = path.stem + '.mp4', 2
                while name.casefold() in used:
                    name = f'{path.stem} ({sequence}).mp4'
                    sequence += 1
                used.add(name.casefold())
                target, staged = folder / name, Path(temp) / name
                message = f'Đang chuyển {index + 1}/{len(ordered)}: {path.name}'

                def show_time(seconds):
                    fraction = min(.999, seconds / info['duration']) if info['duration'] else 0.
                    progress(int((index + fraction) / len(ordered) * 1000), 1000, message)

                progress(int(index / len(ordered) * 1000), 1000, message)
                audio_codec = 'copy' if all(codec in ('aac', 'mp3', 'alac') for codec in info['audio_codecs']) else 'aac'
                args = [ffmpeg_executable(), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-y',
                        '-i', str(path), '-map', '0:v:0', '-map', '0:a?', '-vf', cover_filter(width, height),
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                        '-fps_mode', 'passthrough', '-threads', '4', '-c:a', audio_codec]
                if audio_codec == 'aac':
                    args += ['-b:a', '192k']
                args += ['-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(staged)]
                _run_ffmpeg(args, folder / 'resize.log', cancel, show_time)
                actual = probe_video(staged)
                if (actual['width'], actual['height']) != (width, height):
                    raise ValueError(f'{path.name}: kích thước đầu ra không đúng yêu cầu.')
                check_cancel(cancel)
                staged.replace(target)
                outputs.append({'source': str(path), 'file': target.name, 'input': info, 'output': actual})
                progress(int((index + 1) / len(ordered) * 1000), 1000, f'Đã tạo {target.name}')
        report['complete'] = True
        return folder, outputs
    finally:
        (folder / 'ket_qua_chuyen_kich_thuoc.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
