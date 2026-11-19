"""Portable Colab jobs and validated results; no Qt or network dependencies."""
from __future__ import annotations

from dataclasses import asdict, fields
import copy
import hashlib
import json
import math
from numbers import Integral, Real
from pathlib import Path
import shutil
import uuid
import zipfile

from .core import Cue, Settings
from .editing import cue_errors
from .ocr_models import model_files, model_paths

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
SOURCE_FILES = ('subocr/__init__.py', 'subocr/core.py', 'subocr/video.py',
                'subocr/editing.py', 'subocr/colab.py', 'subocr/ocr_models.py', 'colab/run_job.py')


class VideoMismatchError(ValueError):
    pass


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Tệp JSON quá lớn (tối đa 64 MB).')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Tệp JSON không hợp lệ.') from error


def read_result_data(path):
    """Read either the result JSON or the download ZIP without extracting files."""
    path = Path(path)
    if path.suffix.lower() != '.zip':
        return read_json(path)
    try:
        with zipfile.ZipFile(path) as archive:
            results = [info for info in archive.infolist()
                       if not info.is_dir() and info.filename.lower().endswith('.sublens.json')]
            if not results:
                if 'job.json' in archive.namelist():
                    raise ValueError('Đây là gói dùng để chạy OCR. Chọn ZIP kết quả tải từ ô 5, hoặc tệp result.sublens.json bên trong.')
                raise ValueError('ZIP không chứa tệp kết quả .sublens.json. Chọn ZIP tải từ ô 5 trên Colab.')
            if len(results) != 1:
                raise ValueError('ZIP có nhiều tệp JSON kết quả. Giải nén và chọn JSON của video cần nhập.')
            info = results[0]
            if info.file_size > 64 * 1024 * 1024:
                raise ValueError('Tệp JSON trong ZIP quá lớn (tối đa 64 MB).')
            return json.loads(archive.read(info).decode('utf-8-sig'))
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError, NotImplementedError) as error:
        raise ValueError('Không đọc được ZIP kết quả. Hãy tải lại từ ô 5 hoặc giải nén và chọn tệp JSON.') from error


def video_identity(path):
    """Fast content fingerprint: file size and three 1 MiB samples, independent of name."""
    path = Path(path)
    size = path.stat().st_size
    block = 1024 * 1024
    digest = hashlib.sha256(str(size).encode('ascii'))
    with path.open('rb') as stream:
        for offset in sorted({0, max(0, size // 2 - block // 2), max(0, size - block)}):
            stream.seek(offset)
            digest.update(str(offset).encode('ascii'))
            digest.update(stream.read(block))
    return {'size': size, 'sample_sha256': digest.hexdigest()}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} không hợp lệ.')
    # OCR coordinates can be NumPy scalars. Keep portable Python numbers in JSON.
    return int(value) if isinstance(value, Integral) else float(value)


def validate_job(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('kind') != 'sublens-colab-job':
        raise ValueError('Gói Colab không đúng định dạng hoặc phiên bản.')
    if not isinstance(data.get('job_id'), str) or not data['job_id']:
        raise ValueError('Thiếu mã tác vụ Colab.')
    if type(data.get('reusable', False)) is not bool:
        raise ValueError('Chế độ dùng lại gói Colab không hợp lệ.')
    video = data.get('video')
    if not isinstance(video, dict) or not isinstance(video.get('name'), str):
        raise ValueError('Thiếu thông tin video.')
    _number(video.get('size'), 'Dung lượng video', 1, 10**15)
    if not isinstance(video.get('sample_sha256'), str) or len(video['sample_sha256']) != 64:
        raise ValueError('Thiếu dấu kiểm tra video.')
    for key in ('width', 'height'):
        if type(video.get(key)) is not int or video[key] <= 0:
            raise ValueError('Kích thước video không hợp lệ.')
    _number(video.get('duration'), 'Thời lượng video', 0.001, 10**9)
    raw = data.get('settings')
    # Schema 1 results exported before PP-OCRv6 remain importable.
    if isinstance(raw, dict):
        raw = {'device': 'cpu', 'model_size': 'small', **raw}
    if not isinstance(raw, dict) or set(raw) != {f.name for f in fields(Settings)}:
        raise ValueError('Cấu hình OCR không hợp lệ.')
    if raw['device'] not in ('cpu', 'gpu') or raw['model_size'] not in ('tiny', 'small', 'medium'):
        raise ValueError('Thiết bị hoặc model OCR không hợp lệ.')
    roi = raw['roi']
    if not isinstance(roi, (list, tuple)) or len(roi) != 4 or any(type(v) is not int for v in roi):
        raise ValueError('Vùng phụ đề không hợp lệ.')
    x, y, w, h = roi
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > video['width'] or y + h > video['height']:
        raise ValueError('Vùng phụ đề nằm ngoài video.')
    if raw['language'] not in ('zh', 'en') or raw['algorithm'] not in ('adaptive', 'linear'):
        raise ValueError('Ngôn ngữ hoặc thuật toán không hợp lệ.')
    numeric = {}
    for key, low, high in (('interval', 0, 60), ('confidence', 0, 1),
                           ('boundary_precision', .001, 60), ('color_tolerance', 0, 442),
                           ('min_duration', .001, 60)):
        numeric[key] = _number(raw[key], key, low, high)
    bands = raw['line_bands']
    if not isinstance(bands, (list, tuple)):
        raise ValueError('Vị trí dòng không hợp lệ.')
    portable_bands = []
    for band in bands:
        if not isinstance(band, (list, tuple)) or len(band) != 2:
            raise ValueError('Vị trí dòng không hợp lệ.')
        portable_bands.append(tuple(_number(value, 'Vị trí dòng', 0, 1) for value in band))
    color = raw['color']
    if color is not None:
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            raise ValueError('Màu chữ không hợp lệ.')
        color = tuple(_number(value, 'Màu chữ', 0, 255) for value in color)
    return Settings(**{**raw, **numeric, 'roi': tuple(roi), 'line_bands': portable_bands,
                       'color': color})


def verify_video(job, path):
    validate_job(job)
    if job.get('reusable', False):
        actual = video_metadata(path)
        if any(actual[key] != job['video'][key] for key in ('width', 'height')):
            raise ValueError(f'Gói dùng lại cần video {job["video"]["width"]} × {job["video"]["height"]}. '
                             f'Video đã chọn là {actual["width"]} × {actual["height"]}. '
                             'Xuất gói khác với vùng phụ đề phù hợp kích thước mới.')
        return actual
    actual = video_identity(path)
    if any(actual[key] != job['video'][key] for key in actual):
        raise VideoMismatchError('Video không khớp gói Colab. Chọn đúng tệp gốc, chưa cắt hoặc chuyển mã.')


def video_metadata(path):
    import av
    path = Path(path)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('Tệp không có luồng video.')
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration else (container.duration or 0) / 1e6
        if duration <= 0:
            raise ValueError('Không xác định được thời lượng video. Hãy thử chuyển sang MP4.')
        metadata = {'name': path.name, 'width': stream.width, 'height': stream.height, 'duration': duration}
    return {**metadata, **video_identity(path)}


def bind_video_job(job, path):
    """Turn a reusable preset into a result tied to the video actually being scanned."""
    actual = verify_video(job, path)
    bound = copy.deepcopy(job)
    if job.get('reusable', False):
        bound.update(job_id=uuid.uuid4().hex, reusable=False, video=actual)
    return bound


def export_bundle(parent, video_path, cfg, width, height, duration, reusable=False):
    video_path = Path(video_path)
    job = {'schema': SCHEMA, 'kind': 'sublens-colab-job', 'job_id': uuid.uuid4().hex,
           'video': {'name': video_path.name, 'width': width, 'height': height,
                     'duration': duration, **video_identity(video_path)}, 'settings': asdict(cfg),
           'reusable': reusable, 'ocr': 'PP-OCRv6'}
    job['settings'] = asdict(validate_job(job))
    model_paths(cfg.model_size)  # Verify the selected weights before exporting.
    sources = [*SOURCE_FILES, *model_files(cfg.model_size)]
    notebook = ROOT / 'colab/SubLens_Colab.ipynb'
    for source in [*(ROOT / name for name in sources), notebook]:
        if not source.is_file():
            raise ValueError(f'Thiếu tệp {source.name}. Cập nhật dự án hoặc chạy setup.bat để tải mô hình.')
    folder = Path(parent) / f'SubLens_Colab_{job["job_id"][:8]}'
    archive_name = f'sublens_colab_{video_path.stem}.zip'
    folder.mkdir()
    try:
        with zipfile.ZipFile(folder / archive_name, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('job.json', json.dumps(job, ensure_ascii=False, allow_nan=False))
            for name in sources:
                archive.write(ROOT / name, name)
        shutil.copyfile(notebook, folder / notebook.name)
        (folder / 'HUONG_DAN.txt').write_text(
            '1. Mở https://colab.research.google.com/ và tải notebook SubLens_Colab.ipynb lên.\n'
            '2. Chọn Runtime > Change runtime type > GPU rồi chạy lần lượt các ô.\n'
            f'3. Khi được hỏi, tải {archive_name} lên. Video gốc tải riêng hoặc chọn từ Google Drive.\n'
            + (f'Gói dùng lại: chọn bất kỳ video {width} × {height} có cùng vùng sub/ngôn ngữ/bộ lọc.\n'
               'Sau mỗi video, tải kết quả ở ô 5 rồi quay lại ô 3 chọn video tiếp theo; không cần tải lại gói.\n'
               if reusable else f'Video gốc: {video_path.name}\n') +
            '4. Nhập tên video ở ô 2. Ô 4 lưu kết quả vào MyDrive/SubLens/<tên video> nếu bật lưu Drive.\n'
            '5. Ô 5 tải ZIP gồm JSON và SRT; mở đúng video trong app, chọn Colab GPU > Nhập kết quả rồi chọn ZIP hoặc JSON.\n'
            'Gói không chứa video. Video sẽ được xử lý trên máy chủ Google khi bạn tải/chọn nó.\n'
            'Giữ notebook mở khi chạy. Colab có thể ngắt phiên; lưu kết quả về Drive nếu cần.\n',
            encoding='utf-8-sig')
    except Exception:
        # Only remove the three files created by this call, never an existing directory tree.
        for name in (archive_name, notebook.name, 'HUONG_DAN.txt'):
            (folder / name).unlink(missing_ok=True)
        folder.rmdir()
        raise
    return folder


def write_result(path, job, cues, stats, device):
    validate_job(job)
    data = {'schema': SCHEMA, 'kind': 'sublens-colab-result', 'job': job,
            'cues': [asdict(cue) for cue in cues], 'stats': asdict(stats), 'device': device}
    validate_result(data)
    write_json(path, data)


def validate_result(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('kind') != 'sublens-colab-result':
        raise ValueError('Chọn tệp result.sublens.json do notebook SubLens xuất ra.')
    cfg = validate_job(data.get('job'))
    if data['job'].get('reusable', False):
        raise ValueError('Kết quả chưa gắn với video đã quét. Chạy lại ô 4 để xuất kết quả riêng cho video.')
    raw_cues = data.get('cues')
    if not isinstance(raw_cues, list):
        raise ValueError('Danh sách phụ đề không hợp lệ.')
    cues = []
    for raw in raw_cues:
        if not isinstance(raw, dict) or set(raw) != {f.name for f in fields(Cue)}:
            raise ValueError('Đoạn phụ đề sai định dạng.')
        for key in ('start', 'end'):
            _number(raw[key], 'Thời gian phụ đề', 0, data['job']['video']['duration'] + 2)
        _number(raw['confidence'], 'Độ tin cậy', 0, 1)
        if not isinstance(raw['text'], str) or any(type(raw[k]) is not bool for k in ('review', 'edited')):
            raise ValueError('Nội dung phụ đề sai định dạng.')
        cues.append(Cue(**raw))
    if cue_errors(cues):
        raise ValueError('Kết quả có phụ đề rỗng, thời gian lỗi hoặc chồng lấn.')
    stats = data.get('stats')
    if not isinstance(stats, dict):
        raise ValueError('Thống kê kết quả không hợp lệ.')
    from .video import ScanStats
    if set(stats) != {f.name for f in fields(ScanStats)}:
        raise ValueError('Thống kê kết quả sai định dạng.')
    for key, value in stats.items():
        _number(value, key, 0, 10**15)
        if key != 'elapsed' and type(value) is not int:
            raise ValueError('Số đếm thống kê không hợp lệ.')
    if data.get('device') not in ('cuda', 'cpu'):
        raise ValueError('Thông tin thiết bị OCR không hợp lệ.')
    return cfg, cues, ScanStats(**stats)


def load_result(path, video_path):
    data = read_result_data(path)
    cfg, cues, stats = validate_result(data)
    try:
        verify_video(data['job'], video_path)
    except VideoMismatchError as error:
        raise ValueError(f'Kết quả được tạo từ video: {data["job"]["video"]["name"]}\n'
                         f'Video đang mở: {Path(video_path).name}\n'
                         'Dữ liệu video không khớp. Mở đúng tệp đã đưa lên Colab, chưa cắt hoặc chuyển mã. '
                         'Tên thư mục kết quả chỉ để đặt tên; đổi tên tệp không ảnh hưởng việc đối chiếu.') from error
    return cfg, cues, stats, data['device']
