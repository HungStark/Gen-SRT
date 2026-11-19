# SubLens — OCR phụ đề video thành SRT

Ứng dụng Windows dùng **PaddleOCR PP-OCRv6** (bản ONNX qua RapidOCR 3.10.0), chạy bằng CPU hoặc GPU DirectML. Mặc định xuất tiếng Trung; có thể chọn tiếng Anh. Nhận diện chữ đã in trên hình video, không chuyển giọng nói thành chữ hoặc dịch phụ đề.

## Mở ứng dụng

Có thể đóng gói ứng dụng Windows bằng `build_windows.bat`, rồi chạy `install_windows.bat` để cài vào `%LOCALAPPDATA%\Programs\SubLens` và tạo biểu tượng **SubLens** trên Desktop và Start Menu. Bản `.exe` kèm thư viện, mô hình OCR và gói nguồn cần cho Colab; không cần Python hoặc uv để sử dụng. Khi chuyển sang máy khác, chép cả thư mục `dist\SubLens` cùng `install_windows.ps1` / `install_windows.bat` theo đúng cấu trúc dự án. Trong bản cài đặt, từ được chấp nhận và nhật ký nằm tại `%LOCALAPPDATA%\SubLens`, được giữ khi cập nhật. Tạo lại bản `.exe` và cài lại sau khi sửa mã nguồn.

Môi trường đã được cài trong thư mục dự án. Bấm đúp **`start.bat`**. Sau khi cập nhật, đóng cửa sổ cũ rồi mở lại.

Khi cần cài lại, cài [uv](https://docs.astral.sh/uv/getting-started/installation/), rồi chạy `setup.bat`. Python 3.12, thư viện và mô hình được tải vào thư mục dự án. Cần mạng lúc cài; sau đó OCR chạy cục bộ. Nếu di chuyển thư mục sang đường dẫn khác, hãy tạo lại môi trường bằng setup.

## Đưa nhiều video về cùng kích thước

Mở **Công cụ → Đưa video về cùng kích thước…**, chọn nhiều video, đặt chiều rộng/cao (mặc định **1920 × 1080**) và chọn nơi lưu, rồi bấm **Chuyển kích thước**. Có sẵn các kích thước 1920×1080, 1280×720 và 1080×1920; có thể nhập kích thước tùy chỉnh bằng số chẵn. Mỗi video được xuất riêng thành MP4, giữ âm thanh, thời lượng và tệp gốc. Có tiến trình và nút Dừng.

Hình được phóng/thu theo cùng một tỉ lệ sao cho **cả hai chiều đều lớn hơn hoặc bằng kích thước đích**, rồi **cắt giữa để bỏ phần dư**. Không thêm viền hay kéo méo hình. Ví dụ đích 1920×1080: video 2520×1080 giữ kích thước rồi cắt 300 pixel mỗi bên; video 1620×720 phóng thành 2430×1080 rồi cắt 255 pixel mỗi bên. Nội dung ở rìa, kể cả chữ phụ đề, có thể bị cắt; tăng độ phân giải không khôi phục chi tiết đã thiếu trong video nguồn.

Kết quả nằm trong thư mục mới `Video_<rộng>x<cao>_<thời gian>_<mã>/`, giữ tên gốc và đổi đuôi thành `.mp4`; tên trùng được thêm số. Tệp `ket_qua_chuyen_kich_thuoc.json` ghi các video đã xử lý, `resize.log` ghi lỗi nếu có. FFmpeg đi kèm bản Windows, không cần cài riêng. Công cụ này thay cho tính năng ghép video trước đó.

## Luồng riêng: quét bằng GPU Colab

Luồng cục bộ qua `app.py` / `start.bat` và nút **Đọc cả video** chạy trên máy với CPU/GPU theo Tùy chọn. Colab là một lựa chọn riêng trong menu **Colab GPU** ở hàng chọn video.

1. Mở video, khoanh vùng, chọn ngôn ngữ và tùy chọn như bình thường. Nếu bật khóa dòng, đọc thử trước; hoặc tắt khóa dòng trong Tùy chọn.
2. Chọn **Colab GPU → 1. Xuất gói chạy Colab…**, chọn thư mục lưu. App tạo thư mục `SubLens_Colab_<mã>` có `sublens_colab_<tênvideo>.zip`, `SubLens_Colab.ipynb` và `HUONG_DAN.txt`. Tên gói dùng tên video bỏ phần mở rộng: `Phim tập 01.mp4` → `sublens_colab_Phim tập 01.zip`. Gói chứa mã quét, cấu hình và mô hình tiếng Anh nếu cần; video tải riêng.
3. Mở [Google Colab](https://colab.research.google.com/), chọn **Upload notebook**, mở `SubLens_Colab.ipynb`. Chọn **Runtime → Change runtime type → GPU** rồi chạy các ô theo thứ tự.
4. Ở ô 2, nhập **video_name** (tên dùng cho thư mục kết quả, ví dụ `Phim tập 01`) trước khi chạy, rồi tải gói `sublens_colab_<tênvideo>.zip` lên. Ô 3 chọn video gốc từ Google Drive hoặc tải lên; nên dùng Drive cho video lớn. Không cắt/chuyển mã video sau khi xuất gói. Notebook kiểm tra dung lượng và dấu vân tay lấy mẫu đầu/giữa/cuối tệp, cho phép đổi tên tệp.
5. Ô 4 chạy OCR bằng CUDA, hiển thị tiến trình. Mặc định sao chép video Drive sang ổ tạm trước khi quét và lưu kết quả trực tiếp vào `MyDrive/SubLens/<video_name>/` (gồm JSON, SRT và log). Nếu thư mục đã có, tạo `<video_name> (2)`, `(3)`… để giữ kết quả cũ. Có thể tắt hai tùy chọn này trong notebook. Ô 5 tải một file `<video_name>.zip`, chứa thư mục `<video_name>` có cả `result.sublens.json` và `result.<ngôn ngữ>.srt`; giải nén để dùng.
6. Trong app, mở đúng video đã quét rồi chọn **Colab GPU → 2. Nhập kết quả Colab…**. Có thể chọn trực tiếp ZIP kết quả tải từ ô 5, hoặc tệp `result.sublens.json` đã giải nén. App tự đọc JSON bên trong ZIP, kể cả khi thư mục kết quả có tên tự đặt. Nội dung, thời gian và độ tin cậy được đưa vào bảng để sửa/xóa/gộp/hoàn tác và xuất SRT. App từ chối kết quả sai video hoặc sai định dạng, hỏi trước khi thay danh sách đang có. Gói xuất để chạy OCR và ZIP kết quả là hai tệp khác nhau; hãy chọn ZIP kết quả ở bước này.

Muốn **một gói dùng cho nhiều video**, chọn **Colab GPU → Xuất gói dùng cho nhiều video…** sau khi chọn vùng sub trên một video mẫu. Tên gói vẫn là `sublens_colab_<tênvideo mẫu>.zip`, nhưng cho phép chọn video khác cùng chiều rộng/cao khung hình. Vùng sub, ngôn ngữ, khóa dòng và bộ lọc được dùng chung, nên các video cần có bố cục phụ đề tương ứng. Nếu bố cục hoặc kích thước khác, hãy xuất gói phù hợp khác.

Trên Colab, chỉ tải gói này một lần ở ô 2. Chạy ô 3 → 4 → 5 để quét và tải kết quả cho từng video; xong quay lại ô 3 chọn video tiếp theo và nhập **result_name_for_this_video** để đặt tên kết quả mới (để trống dùng tên ở ô 2). Đây là xử lý lần lượt, chưa phải chọn cả loạt chạy tự động. Kết quả mỗi lượt chứa thông tin, dấu kiểm tra và thời lượng của video thực sự đã quét, nên khi nhập vào app vẫn phải mở đúng video đó. Luồng gói cho một video và luồng cục bộ tiếp tục hoạt động.

Colab xử lý video trên máy chủ Google. Ô 1 tạo môi trường Python 3.12 riêng bằng uv trong `/content/sublens_runtime_py312`, cài `rapidocr==3.10.0`, ONNX Runtime GPU 1.23.2 và CUDA/cuDNN. Ô 4 dùng đúng cặp model phát hiện/nhận dạng PP-OCRv6 đã chọn khi xuất gói; kiểm tra CUDA trên phiên OCR thực tế trước khi quét. Cần xuất lại gói từ app mới; các gói OCR cũ không dùng với notebook này.

Các ô chọn tệp/Drive chỉ dùng thư viện chuẩn và công cụ có sẵn của Colab; các bước đọc cấu hình, kiểm tra video và quét chạy trong môi trường OCR riêng. Không thay gói của kernel Colab hoặc môi trường Windows. Notebook kiểm tra CUDA trên phiên OCR thực tế và không tự chuyển sang CPU khi GPU lỗi. Xem [tài liệu CUDA của ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).

Nếu bước cài/quét lỗi, notebook hiện trực tiếp cả stdout và stderr. Nhật ký cài đặt nằm ở `/content/sublens_setup.log`; nhật ký quét nằm tại `ocr.log` trong thư mục kết quả của từng lượt. Khi cập nhật, mở lại app và xuất gói mới để lấy cả notebook lẫn mã quét trong `sublens_colab_<tênvideo>.zip`, rồi tải chúng lên Colab và chạy từ ô 1. Gói cũ trước bản sửa `TextDetector.infer` còn chứa lỗi kiểm tra GPU ở bộ quét, nên phải xuất lại gói .zip.

GPU và thời lượng phiên Colab không được bảo đảm; giữ notebook mở và tải/lưu kết quả trước khi ngắt phiên. Bản này chạy theo từng video, chưa tiếp tục được một lượt quét bị ngắt. Tổng thời gian còn phụ thuộc tải video, giải mã và khởi tạo GPU; chưa có số đo tăng tốc trên Colab. Xem [giới hạn Colab](https://research.google.com/colaboratory/faq.html).

Notebook nguồn nằm trong `colab/SubLens_Colab.ipynb`; có thể tái tạo bằng `.venv\Scripts\python.exe colab\build_notebook.py`. Để kiểm tra toàn luồng bằng CPU cục bộ (không thay chế độ mặc định của notebook):

```powershell
.venv\Scripts\python.exe tests\gui_colab.py
```

## Bố cục và cách quét

- **Bên trái:** khung video tỷ lệ 16:9, thanh tua, hàng nút gọn và nội dung đọc thử. Khung video ưu tiên dùng hết chiều ngang; khi cửa sổ thấp, tự thu nhỏ để vẫn thấy các nút. Video giữ tỷ lệ gốc bên trong khung, không kéo méo. Ô đọc thử/danh sách dòng có thanh cuộn khi nội dung dài.
- **Bên phải:** bảng bắt đầu, kết thúc, nội dung, tin cậy; các nút sửa, xóa, gộp, hoàn tác và xuất SRT.
- **Phía dưới:** tiến trình quét, nút Dừng và trạng thái. Có thể kéo vạch giữa hai cột để đổi tỷ lệ.

1. Kéo thả video vào cửa sổ, bấm vùng video trống hoặc bấm **Chọn video…**.
2. Tua tới đoạn có phụ đề rõ. Kéo chuột trái trên ảnh để khoanh vùng sát các dòng sub. Có thể khoanh cả Trung/Anh hoặc chỉ một dòng.
3. Chọn **Tiếng Trung** hoặc **Tiếng Anh**. Mặc định là tiếng Trung.
4. Bấm **Đọc thử khung hình**. Nội dung đọc được hiện phía dưới bên trái; khung xanh là dòng giữ, đỏ là dòng loại. Bỏ tích dòng chữ trong cảnh nếu nó bị nhận nhầm.
5. Bấm **Đọc cả video**. Tool quét mỗi **0,5 giây**, dùng lại kết quả OCR và chia đôi các khoảng đổi câu đến khoảng **0,1 giây**.
6. Kiểm tra, chỉnh sửa bảng bên phải rồi bấm **Xuất SRT…**. Tên mặc định `video.zh.srt` hoặc `video.en.srt`, mã hóa UTF-8 có BOM. Chỉ ghi tệp khi bạn xuất.

Trong **Tùy chọn…**, chọn **CPU** hoặc **GPU** và model **Tiny**, **Small** hoặc **Medium**. Mặc định CPU + Small. Tiny nhẹ nhất; Medium dùng nhiều bộ nhớ hơn. GPU trên Windows dùng DirectML (Intel/AMD/NVIDIA), Colab dùng CUDA. Các model được đóng gói sẵn, không cần tải lúc chạy. Nếu GPU không hoạt động, app báo lỗi để bạn chọn CPU. Ngoài ra có khóa dòng theo kết quả đọc thử, ngưỡng tin cậy OCR và lọc màu. Bấm **Chọn màu…** cạnh **Lọc theo màu mẫu** để mở bảng màu hoặc nhập mã HEX/RGB; màu đã chọn hiện bằng ô màu và mã HEX. Chọn màu sẽ tự bật bộ lọc. Cũng có thể bấm chuột phải vào phần màu đặc bên trong nét chữ trên video để lấy mẫu; tránh viền đen và nền. Nếu câu có thể xuống hai dòng, đọc thử ở đoạn có đủ hai dòng trước khi khóa. Nếu sub đổi vị trí hoặc màu, điều chỉnh/tắt bộ lọc tương ứng.

## Sửa, xóa và gộp kết quả

**Sửa:** chọn một dòng và bấm **Sửa chữ**, hoặc nhấp đúp ô Nội dung. Hỗ trợ chữ nhiều dòng; Enter xuống dòng, **Ctrl+Enter** lưu, Escape hủy. Bấm ra khỏi ô cũng lưu thay đổi. Có thể nhấp đúp ô Bắt đầu/Kết thúc để sửa thời gian bằng số giây (`12.350`) hoặc dạng `00:00:12,350`.

**Xóa:** chọn một hoặc nhiều dòng bằng Shift/Ctrl, bấm **Xóa đoạn**. Phím Delete cũng xóa các dòng được chọn khi bảng đang có focus và không đang nhập chữ.

**Gộp:** chọn ít nhất hai dòng **liền nhau**, bấm **Gộp đoạn…**. Trong hộp chọn, bấm nội dung của một trong các dòng nguồn rồi bấm **Gộp**. Đoạn mới dùng thời điểm bắt đầu sớm nhất và kết thúc muộn nhất của nhóm, giữ nguyên nội dung được chọn, gồm cả xuống dòng. Khoảng trống giữa các đoạn cũng nằm trong thời gian đoạn gộp. Chọn Hủy để giữ nguyên kết quả.

**Hoàn tác:** nút Hoàn tác phục hồi thao tác sửa/xóa/gộp gần nhất, tối đa 30 thao tác trong lượt kết quả hiện tại. Ctrl+Z hoạt động khi bảng có focus; khi đang nhập chữ, trình soạn thảo xử lý Ctrl+Z riêng. Một lượt quét thành công mới hoặc mở video mới thay thế danh sách và lịch sử hiện tại.

Màu nền dòng được chọn theo thứ tự ưu tiên **đỏ → cam → vàng**:

- **Đỏ:** điểm OCR gốc dưới **80%**; đúng 80% không thuộc điều kiện này.
- **Cam:** có từ tiếng Anh nghi sai chính tả, ví dụ `flm`, `frst`, `Offcial`. Chỉ cảnh báo và gợi ý, không tự sửa chữ.
- **Vàng:** nội dung giống hoặc gần giống dòng ngay trước/sau; cả hai dòng được đánh dấu. So sánh bỏ qua hoa/thường, dấu câu và khoảng trắng; câu dài dùng mức giống ít nhất 90%. Đây là cảnh báo, không tự gộp hoặc thay nội dung.
- **Trắng:** không mắc ba điều kiện trên. Điểm cao, cờ cần kiểm tra cũ hoặc đã sửa thủ công không tự làm đổi màu nền.

Rê chuột lên bất kỳ ô nào để xem tất cả lý do, kể cả khi một màu ưu tiên đã che các cảnh báo khác. Màu được tính lại sau khi sửa/xóa/gộp/hoàn tác. Cột tin cậy chuyển thành **Đã sửa** khi sửa/gộp; tooltip giữ điểm OCR gốc để tham khảo. Các lỗi thời gian/chữ rỗng hiển thị bằng chữ đỏ và tooltip lỗi, phải sửa trước khi xuất; không ghi đè quy tắc màu nền. Sau khi xóa/gộp, số thứ tự trong SRT được đánh lại liên tục.

Cảnh báo chính tả dùng từ điển tiếng Anh cục bộ, ưu tiên ít báo nhầm: chỉ nghi ngờ từ lệch một ký tự so với từ thông dụng, bỏ qua mã/số, chữ viết tắt và từ có chữ hoa giữa câu để giữ tên riêng như Kunzi. Các tên đã lưu trong accepted_words.txt vẫn được nạp; ô nhập tên riêng đã được bỏ khỏi Tùy chọn. Bộ kiểm tra này không kiểm tra ngữ pháp, không phát hiện mọi lỗi và không kiểm tra chính tả tiếng Trung.

## Cách xác định mốc thời gian

Tool giải mã video tuần tự, giữ ảnh vùng sub của khoảng đang xét trong RAM. OCR lấy mẫu khoảng 0,5 giây. Khi hai mẫu khác chữ, đọc điểm giữa và tiếp tục chia khoảng có thay đổi, tới khoảng 0,1 giây hoặc khi không còn frame nguồn ở giữa. Timestamp lấy từ khung hình thực qua PyAV, hỗ trợ VFR. Các mục ngắn hơn 0,08 giây bị loại để giảm nháy OCR.

Tool ổn định một số nhầm ký tự tiếng Anh như `I/l`, mất `i/l`, `rn/m` khi câu đủ dài và hình nét chữ cũng khớp. Thay đổi số, chữ Trung hoặc từ khác không được gộp chỉ vì câu gần giống. Sau lượt quét, các đoạn liền nhau có cùng chữ chuẩn hóa được tự gộp; khoảng hụt OCR tối đa 0,1 giây cũng được nối. Khoảng trống dài hơn hoặc có một câu khác ở giữa sẽ giữ riêng. Với khoảng trống thật rất ngắn giữa hai lần lặp cùng câu, quy tắc nối 0,1 giây cũng có thể gộp chúng; cần kiểm tra lại mốc của đoạn gộp. Ô thông báo ghi số kết quả OCR đã ổn định và số đoạn trùng được gộp. Các cờ bất định nội bộ không tự làm dòng đổi màu; bảng dùng các điều kiện màu nêu trên.

Các cụm chữ cùng hàng nhưng cách xa nhau được tách trước khi lọc ngôn ngữ, tránh ghép biển chữ ở rìa ảnh vào phụ đề. Crop nhận diện tiếng Anh được thu sát nét chữ để giảm dao động khi hộp OCR thừa/thiếu viền. So sánh hình nét chữ dùng tương phản cục bộ, giúp ổn định khi nền chuyển cảnh hoặc chữ mờ dần.

Hai đầu cùng chữ hoặc cùng trống vẫn có thể che giấu một câu/khoảng trống rất ngắn nằm hoàn toàn giữa hai mẫu. Bước quét 0,5 giây không bảo đảm tìm đủ câu ngắn hơn 0,5 giây. Mục tiêu 0,1 giây là độ rộng khoảng tìm biên, không phải cam kết OCR luôn đúng. Chữ mờ, hiệu ứng xuất hiện dần, karaoke, phụ đề đổi vị trí hoặc chữ trong cảnh giống sub vẫn cần kiểm tra lại.

Khung có chữ phù hợp nhưng OCR điểm thấp được thử đọc lại; nếu chưa rõ, không tự coi là phụ đề biến mất. Tool có thể vẫn bỏ sót hoàn toàn một vùng chữ khó đọc. Mô hình Trung đi kèm không bảo đảm đọc tốt mọi chữ phồn thể/hiếm/font cách điệu.

## Kiểm tra

Video mẫu trong `test_artifacts/demo_dual.mp4`, `demo_zh.mp4`, `demo_en.mp4`. Các ảnh giao diện và đầu ra kiểm thử cũng nằm trong thư mục này.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py -v
.venv\Scripts\python.exe tests\integration.py
.venv\Scripts\python.exe tests\gui_smoke.py
.venv\Scripts\python.exe tests\gui_editing.py
.venv\Scripts\python.exe tests\gui_review.py
.venv\Scripts\python.exe tests\gui_layout.py
```

Kiểm tra OCR thật gồm hai ngôn ngữ, một dòng, nhiều dòng, câu lặp, khoảng trống, lọc màu/vị trí và VFR. Kiểm tra sửa kết quả gồm nội dung nhiều dòng, thời gian, chọn nội dung gộp, xóa nhiều dòng, hoàn tác, hủy gộp, lưu ô đang sửa trước khi xuất và xác thực SRT. Kiểm tra giao diện ở nhiều kích thước/mức DPI. Lỗi ứng dụng ghi trong `sublens.log`.

## Thành phần

PySide6 Essentials, OpenCV, PyAV/FFmpeg, [RapidOCR](https://github.com/RapidAI/RapidOCR) và ONNX Runtime. Các model [PaddleOCR PP-OCRv6](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv6/PP-OCRv6.en.md) Tiny/Small/Medium dùng chung cho Trung/Anh, nguồn ONNX [RapidAI v3.10.0](https://www.modelscope.cn/models/RapidAI/RapidOCR/files); SHA256 cố định trong `subocr/ocr_models.py`. Gói Colab chỉ chứa hai model của cỡ đang chọn. Từ điển tiếng Anh lấy từ [SymSpellPy](https://github.com/mammothb/symspellpy/blob/master/symspellpy/frequency_dictionary_en_82_765.txt), đóng gói sẵn; nguồn, hash và giấy phép trong `assets/dictionaries`. Không cần cài thêm thư viện hay dùng mạng để kiểm tra từ. Các thành phần giữ giấy phép riêng của tác giả; xem kho nguồn và metadata trong môi trường trước khi phân phối lại.
