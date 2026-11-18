"""Regenerate the distributable notebook using only the standard library."""
import json
from pathlib import Path
from textwrap import dedent


def markdown(text):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': dedent(text).strip().splitlines(True)}


def code(text, form=False):
    return {'cell_type': 'code', 'metadata': {'cellView': 'form'} if form else {},
            'execution_count': None, 'outputs': [], 'source': dedent(text).strip().splitlines(True)}


cells = [
    markdown('''
    # SubLens · OCR phụ đề bằng GPU Colab

    Đây là luồng riêng với app Windows: chọn vùng trong app → xuất gói → quét ở đây → nhập kết quả về app.
    Trong app chọn **Colab GPU → 1. Xuất gói chạy Colab** để lấy `sublens_colab_<tênvideo>.zip`.
    Để dùng chung gói cho nhiều video, chọn **Colab GPU → Xuất gói dùng cho nhiều video…**.
    Các video phải cùng kích thước khung hình, vị trí sub, ngôn ngữ và bộ lọc.
    Xử lý lần lượt từng video: tải kết quả ở ô 5, rồi chạy lại **ô 3 → 4 → 5** cho video tiếp theo.

    Chọn **Runtime → Change runtime type → GPU** (ví dụ T4 nếu được cấp), rồi chạy từng ô từ trên xuống.
    Notebook yêu cầu CUDA thực sự hoạt động; sẽ báo lỗi nếu engine chỉ dùng CPU.
    OCR dùng Python 3.12 trong môi trường riêng, kể cả khi kernel Colab dùng Python 3.13.
    Cài đặt lần đầu có thể mất vài phút và tải các thư viện CUDA/cuDNN.
    Video được xử lý trên máy chủ Google. Giữ notebook mở khi quét;
    Colab có thể ngắt phiên hoặc không cấp GPU. Notebook không tự khôi phục một lượt quét bị ngắt.
    [Giới hạn Colab](https://research.google.com/colaboratory/faq.html).
    '''),
    code('''
    # @title 1. Kiểm tra GPU và cài thư viện
    from collections import deque
    import os
    from pathlib import Path
    import subprocess
    import sys
    import textwrap

    # Explicitly pipe the child output: inherited stderr may be invisible in Colab.
    def run_logged(command, log_path='/content/sublens_setup.log', env=None, cwd=None):
        tail = deque(maxlen=60)
        log_path = Path(log_path)
        with log_path.open('a', encoding='utf-8') as log:
            log.write('COMMAND: ' + repr(command) + '\\n')
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding='utf-8', errors='replace', bufsize=1,
                                  env=env, cwd=cwd) as process:
                try:
                    for line in process.stdout:
                        print(line, end='', flush=True)
                        log.write(line)
                        log.flush()
                        tail.append(line)
                    returncode = process.wait()
                except BaseException:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise
        if returncode:
            details = ''.join(tail)
            raise RuntimeError(f'Tiến trình lỗi (mã {returncode}). Log: {log_path}\\n{details}') from None

    gpu = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
    if gpu.returncode:
        raise RuntimeError('Chưa có GPU. Chọn Runtime → Change runtime type → GPU rồi chạy lại.')
    print(gpu.stdout)
    print('Kernel notebook:', sys.version)
    OCR_PYTHON = None
    bootstrap = Path('/content/sublens_bootstrap')
    if not (bootstrap / 'uv/__main__.py').is_file():
        run_logged([sys.executable, '-m', 'pip', 'install', '--target', str(bootstrap), 'uv==0.11.23'])
    uv_env = {**os.environ, 'PYTHONPATH': str(bootstrap),
              'UV_PYTHON_INSTALL_DIR': '/content/sublens_python', 'UV_CACHE_DIR': '/content/sublens_cache'}
    uv = [sys.executable, '-m', 'uv', '--no-config']
    runtime = Path('/content/sublens_runtime_py312')
    python = runtime / 'bin/python'
    if not python.is_file():
        run_logged([*uv, 'venv', '--python', '3.12', '--managed-python', str(runtime)], env=uv_env)
    # Keep packages out of the Colab kernel and never substitute the unrelated `rapidocr` API.
    run_logged([*uv, 'pip', 'install', '--python', str(python), '--only-binary', ':all:',
                'rapidocr-onnxruntime==1.4.4', 'numpy==2.2.6', 'opencv-python==4.11.0.86',
                'av==16.0.1', 'Pillow==11.2.1'], env=uv_env)
    run_logged([*uv, 'pip', 'uninstall', '--python', str(python), 'onnxruntime', 'onnxruntime-gpu'], env=uv_env)
    run_logged([*uv, 'pip', 'install', '--python', str(python), '--only-binary', ':all:',
                'onnxruntime-gpu[cuda,cudnn]==1.23.2'], env=uv_env)
    OCR_ENV = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME'):
        OCR_ENV.pop(key, None)
    OCR_ENV['PYTHONUNBUFFERED'] = '1'
    gpu_check = textwrap.dedent("""
    import sys
    import numpy as np
    import av, cv2
    import onnxruntime as ort
    print('Python OCR:', sys.version, flush=True)
    print('ONNX Runtime:', ort.__version__, ort.get_available_providers(), flush=True)
    ort.preload_dlls(directory='')
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR(det_use_cuda=True, rec_use_cuda=True, intra_op_num_threads=2)
    for name, inference in (('text_det', ocr.text_det.infer), ('text_rec', ocr.text_rec.session)):
        providers = inference.session.get_providers()
        print(name, providers, flush=True)
        if providers[0] != 'CUDAExecutionProvider':
            raise RuntimeError('OCR chưa dùng được CUDA. Xem lỗi thư viện GPU ở phía trên.')
    ocr(np.zeros((96, 640, 3), dtype=np.uint8), use_cls=False)
    print('Đã chạy thử OCR trên GPU thành công.', flush=True)
    """)
    run_logged([str(python), '-u', '-c', gpu_check], env=OCR_ENV)
    OCR_PYTHON = str(python)
    print('Đã cài xong. Chạy ô 2 để tải gói sublens_colab_<tênvideo>.zip.')
    '''),
    code('''
    # @title 2. Tải gói sublens_colab_<tênvideo>.zip xuất từ app
    from google.colab import files
    from pathlib import Path
    import json
    import tempfile
    import zipfile
    from types import SimpleNamespace

    job = cfg = video = output = None
    if not globals().get('OCR_PYTHON'):
        raise RuntimeError('Chạy thành công ô 1 trước.')
    uploaded = files.upload()
    if len(uploaded) != 1:
        raise ValueError('Chỉ chọn một tệp .zip xuất từ app (sublens_colab_<tênvideo>.zip).')
    bundle = Path(next(iter(uploaded)))
    del uploaded
    required = {'job.json', 'subocr/__init__.py', 'subocr/core.py', 'subocr/video.py',
                'subocr/editing.py', 'subocr/colab.py', 'colab/run_job.py'}
    allowed = required | {'models/en_PP-OCRv4_rec_mobile.onnx'}
    workspace = Path(tempfile.mkdtemp(prefix='sublens_', dir='/content'))
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or not required <= set(names) or not set(names) <= allowed:
            raise ValueError('Gói không đúng định dạng. Hãy xuất lại từ app SubLens.')
        if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('Gói quá lớn. Video phải tải riêng, không nằm trong gói .zip.')
        for name in names:
            archive.extract(name, workspace)

    # Only the Python 3.12 subprocess imports OCR/video modules.
    run_logged([OCR_PYTHON, '-u', '-c',
                "from subocr.colab import read_json, validate_job; validate_job(read_json('job.json'))"],
               cwd=str(workspace), env=OCR_ENV)
    job = json.loads((workspace / 'job.json').read_text(encoding='utf-8-sig'))
    cfg = SimpleNamespace(**job['settings'])
    if job.get('reusable', False):
        print('Gói dùng cho nhiều video · video mẫu:', job['video']['name'])
        print('Kích thước yêu cầu:', job['video']['width'], '×', job['video']['height'])
        print('Giữ cùng vị trí sub, ngôn ngữ và bộ lọc. Chọn video cần quét ở ô 3.')
    else:
        print('Video gốc:', job['video']['name'])
    print('Ngôn ngữ:', cfg.language, '· vùng:', cfg.roi)
    print('Gói đã sẵn sàng. Chọn nguồn video trong ô 3.')
    '''),
    markdown('''
    ## Chọn video
    Với video lớn, nên dùng Google Drive: tải video gốc lên Drive, chọn **Google Drive** ở ô dưới
    và điền đường dẫn, ví dụ `/content/drive/MyDrive/video.mp4`.
    Với video nhỏ có thể chọn **Tải lên**.
    Với **gói cho một video**, dùng đúng tệp gốc, chưa cắt/chuyển mã; tên có thể khác.
    Với **gói dùng cho nhiều video**, chọn bất kỳ video cùng kích thước và cùng bố cục sub.
    Mỗi kết quả vẫn được gắn với đúng video đã quét để nhập lại app.
    '''),
    code('''
    # @title 3. Chọn video cần quét (chạy lại ô này cho video tiếp theo)
    video_source = "Google Drive" # @param ["Google Drive", "Tải lên"]
    drive_video_path = "/content/drive/MyDrive/video.mp4" # @param {type:"string"}
    copy_to_local = True # @param {type:"boolean"}

    import shutil
    video = output = None
    if video_source == 'Google Drive':
        from google.colab import drive
        drive.mount('/content/drive')
        video = Path(drive_video_path.strip())
    else:
        uploaded = files.upload()
        if len(uploaded) != 1:
            raise ValueError('Chỉ chọn một video gốc.')
        video = Path(next(iter(uploaded))).resolve()
        del uploaded
    if not video.is_file():
        raise ValueError('Không tìm thấy video. Kiểm tra đường dẫn ở trên.')
    run_logged([OCR_PYTHON, '-u', '-c',
                "import sys; from subocr.colab import read_json, verify_video; verify_video(read_json('job.json'), sys.argv[1])",
                str(video)], cwd=str(workspace), env=OCR_ENV)
    if video_source == 'Google Drive' and copy_to_local:
        # Sequential decoding from the local disk avoids repeated Drive reads.
        if shutil.disk_usage(workspace).free < video.stat().st_size + 256 * 1024 * 1024:
            raise ValueError('Không đủ dung lượng tạm. Tắt copy_to_local hoặc chọn video nhỏ hơn.')
        local_video = Path(tempfile.mkdtemp(prefix='video_', dir=workspace)) / video.name
        shutil.copyfile(video, local_video)
        video = local_video
    print('Video sẵn sàng:', video)
    ''' , form=True),
    code('''
    # @title 4. Quét OCR bằng GPU
    save_results_to_drive = True # @param {type:"boolean"}

    # A new output directory for every run prevents an older result being downloaded after an error.
    output = None
    if not globals().get('OCR_PYTHON'):
        raise RuntimeError('Chạy thành công ô 1 trước.')
    if globals().get('video') is None or not video.is_file():
        raise RuntimeError('Chọn video ở ô 3 trước.')
    run_output = Path(tempfile.mkdtemp(prefix='result_', dir=workspace))
    command = [OCR_PYTHON, '-u', str(workspace / 'colab/run_job.py'),
               '--job', str(workspace / 'job.json'), '--video', str(video), '--output', str(run_output)]
    # The child streams progress and checks CUDA on the actual OCR sessions.
    run_logged(command, log_path=run_output / 'ocr.log', env=OCR_ENV)
    output = run_output
    if save_results_to_drive:
        from google.colab import drive
        drive.mount('/content/drive')
        destination = Path('/content/drive/MyDrive/SubLens') / job['job_id'] / output.name
        destination.mkdir(parents=True, exist_ok=True)
        for source in output.iterdir():
            shutil.copyfile(source, destination / source.name)
        print('Đã lưu kết quả lên Drive:', destination)
    print('Quét xong. Chạy ô 5 để tải kết quả về máy.')
    ''' , form=True),
    code('''
    # @title 5. Tải kết quả về app
    if globals().get('output') is None or not (output / 'result.sublens.json').is_file():
        raise RuntimeError('Chưa có kết quả. Chạy thành công ô 4 trước.')
    files.download(str(output / 'result.sublens.json'))
    print('Trong app: mở video gốc → Colab GPU → 2. Nhập kết quả Colab → chọn result.sublens.json.')
    print('Sau đó sửa chữ, thời gian, xóa/gộp, hoàn tác và xuất SRT như bình thường.')
    print('Bản SRT cũng nằm tại:', output / ('result.' + cfg.language + '.srt'))
    if job.get('reusable', False):
        print('Video tiếp theo: chạy lại ô 3 → 4 → 5. Giữ nguyên gói ở ô 2.')
    '''),
]

notebook = {'cells': cells,
            'metadata': {'colab': {'name': 'SubLens_Colab.ipynb'}, 'accelerator': 'GPU',
                         'kernelspec': {'display_name': 'Python 3', 'name': 'python3'},
                         'language_info': {'name': 'python'}},
            'nbformat': 4, 'nbformat_minor': 5}
if __name__ == '__main__':
    for index, cell in enumerate(cells):
        cell['id'] = f'sublens-{index:02d}'
    target = Path(__file__).with_name('SubLens_Colab.ipynb')
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(target)
