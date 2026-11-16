# SubLens — lấy phụ đề có sẵn trên hình video thành SRT

Ứng dụng Windows chạy trên máy, dùng CPU. Video không gửi lên máy chủ. Mặc định chỉ xuất tiếng Trung; có thể chuyển sang tiếng Anh. Đây là OCR chữ đã in trên hình video, không phải nhận diện giọng nói hoặc dịch phụ đề.

## Mở ứng dụng

Trên máy hiện tại, môi trường và mô hình đã được cài trong thư mục dự án. Bấm đúp **`start.bat`**.

Các nút Đọc thử, Nhận diện, Dừng và Xuất SRT nằm cố định ở đáy cửa sổ. Nếu cửa sổ thấp hoặc Windows phóng đại màn hình, cuộn vùng nội dung để xem đầy đủ thiết lập và bảng kết quả.

Khi cài lại: cần Windows 10/11 x64 và [uv](https://docs.astral.sh/uv/getting-started/installation/). Chạy `setup.bat` để tải Python 3.12, thư viện và mô hình vào chính thư mục dự án. Cần mạng lúc cài; sau đó OCR dùng mô hình cục bộ. Không di chuyển riêng `.venv`; hãy chạy lại setup nếu đổi đường dẫn thư mục.

## Cách sử dụng

1. **Mở video** hoặc kéo thả tệp vào cửa sổ.
2. Kéo thanh thời gian tới đoạn có phụ đề rõ. Kéo chuột trái trên ảnh để khoanh vùng sát chữ. Có thể khoanh cả hai ngôn ngữ hoặc chỉ một dòng.
3. Chọn **Tiếng Trung** hoặc **Tiếng Anh**. Với video chỉ có một dòng, chọn đúng ngôn ngữ của dòng đó.
4. Bấm **Đọc thử khung hình**. Khung xanh là dòng được giữ; khung đỏ là dòng bị loại. Danh sách bên dưới cho phép bỏ tích chữ trong cảnh nếu nó nằm trong vùng OCR. Không thấy dòng cần đọc: thử khung khác, khoanh lại vùng, giảm ngưỡng OCR hoặc bỏ lọc màu.
5. Giữ bật **Khóa vị trí dòng** để chỉ lấy các dải dòng đã tích. Nếu một câu có thể xuống hai dòng, hãy đọc thử ở đoạn có đủ hai dòng đó. Nếu phụ đề thường xuyên đổi vị trí, nên tắt khóa dòng và khoanh vùng thích hợp; cần kiểm tra kết quả kỹ hơn.
6. Tùy chọn: bấm chuột phải lên phần màu đặc bên trong nét chữ rồi bật **Lọc theo màu mẫu**. Chọn phần chữ trắng/vàng, tránh viền đen và nền. Lọc màu có thể bỏ sót nếu video đổi màu sub.
7. Bấm **Nhận diện toàn video**. Có thể bấm Dừng; lượt dừng không tự ghi tệp hoặc xuất kết quả dở dang.
8. Kiểm tra bảng. Bấm một mục để tua tới nó; sửa thời gian theo số giây và nội dung trực tiếp. Màu vàng chỉ ra độ tin cậy thấp hoặc OCR không thống nhất. Điểm OCR cao vẫn có thể sai.
9. Bấm **Xuất SRT**, chọn nơi lưu. Tên mặc định là `tenvideo.zh.srt` hoặc `tenvideo.en.srt`. Tệp UTF-8 có BOM để giữ chữ Trung. Tệp chỉ được ghi sau thao tác xuất.

Video mẫu: `test_artifacts/demo_dual.mp4`, `demo_zh.mp4`, `demo_en.mp4`. Có biển chữ trong cảnh để thử vùng chọn và bộ lọc.

## Dùng SRT tham chiếu tạo từ âm thanh

1. Mở đúng video, rồi bấm **SRT tham chiếu…** ở phía trên hoặc kéo thả tệp `.srt` vào cửa sổ. Khi đổi video, tool bỏ lựa chọn SRT cũ để bạn nạp tệp của video mới.
2. Sau khi nạp, **Dùng SRT tham chiếu** được bật; giao diện hiện tên tệp, số mục và mốc kết thúc. Tool chụp lại các mốc đã nạp cho lượt chạy. Có thể bỏ tích để trở về quét toàn video, hoặc bấm **Bỏ SRT** để gỡ tệp.
3. **Đệm trước/sau** mặc định là **0,7 giây mỗi bên**. Ví dụ mốc 10–13 giây trở thành khoảng 9,3–13,7 giây. Tăng đệm nếu phụ đề trên hình hiện sớm hoặc giữ lâu hơn lời nói.
4. Chế độ quét đang chọn áp dụng **bên trong** các khoảng này. Mặc định quét 0,5 giây, chia đôi ranh giới đến khoảng 0,1 giây. Tool kiểm tra thêm quanh mốc đầu/cuối của từng mục tham chiếu; các khoảng đệm chồng nhau được gộp để không chạy OCR trùng.
5. **Quét bổ sung ngoài các khoảng SRT** mặc định bật với bước **2 giây**. Bước này tìm thêm chú thích hoặc phụ đề mà SRT bỏ sót. Có thể điều chỉnh 0,5–10 giây, hoặc tắt để chỉ OCR trong các khoảng đã mở rộng.
6. Đọc thử, khóa dòng, nhận diện và xuất như bình thường. Tên đầu ra mặc định của lượt dùng tham chiếu có thêm `.ocr`, ví dụ `video.ocr.zh.srt`. Tệp tham chiếu chỉ được đọc, không tự sửa.

**SRT chỉ cung cấp mốc thời gian.** Nội dung trong tệp tham chiếu có thể sai hoặc khác ngôn ngữ; đầu ra luôn lấy từ OCR của ngôn ngữ bạn chọn. Một mục tham chiếu có thể sinh nhiều mục SRT thực tế; nhiều mục tham chiếu cũng có thể ứng với một câu giữ nguyên trên hình. Khi không tìm thấy chữ, tool không chép lời thoại tham chiếu vào kết quả để lấp chỗ trống.

Sau khi chạy, ô thông báo ghi số khoảng OCR, tổng thời lượng ưu tiên, mẫu bổ sung ngoài khoảng và số mục tham chiếu không tìm thấy sub. Nếu tắt quét bên ngoài mà chữ vẫn còn hiện ở mép khoảng OCR, tool kết thúc tại mép khoảng và đánh dấu mục đó để kiểm tra. Tăng đệm hoặc bật quét ngoài để tìm tiếp; mốc bị cắt ở biên chưa được xác nhận là lúc phụ đề thật sự xuất hiện/biến mất.

Tệp cần có dòng thời gian SRT hợp lệ, hỗ trợ UTF-8/BOM, UTF-16 có BOM, dấu phẩy hoặc dấu chấm cho phần mili giây. Các mục sai thời gian được báo lỗi; các mốc hoàn toàn ngoài video cũng được báo để chọn lại tệp. Tool vẫn giải mã video tuần tự; số lần OCR tiết kiệm được phụ thuộc độ phủ của các khoảng. Nếu phần lớn video nằm trong các khoảng tham chiếu, tốc độ có thể tương đương quét thông thường. Bước quét bên trong/bên ngoài vẫn có thể bỏ sót câu hoặc khoảng trống ngắn hơn bước đã chọn.

Có thể thử `test_artifacts/reference_demo.srt` với `demo_dual.mp4`: một mục tham chiếu có nội dung cố ý sai được dùng để tìm ba mục phụ đề thực tế trên hình.

## Chế độ tốc độ và thời gian

- **Chia đôi — mặc định:** quét mỗi khoảng 0,5 giây. Nếu hai mẫu khác chữ hoặc có OCR chưa rõ, đọc frame ở giữa rồi tiếp tục chia những khoảng có thay đổi, đến khoảng 0,1 giây hoặc khi không còn frame ở giữa. Kết quả OCR được lưu lại trong khoảng đang xét; hai mẫu cùng chữ không bị đọc lại.
- **Chia đôi nhanh:** cùng thuật toán, bước quét ban đầu 1 giây. Nhanh hơn trên đoạn chữ giữ lâu, nhưng dễ bỏ sót câu ngắn hơn.
- **Kỹ:** OCR mọi khung hình, phù hợp khi có câu ngắn. Chậm hơn; tốc độ phụ thuộc máy, kích thước vùng và số chữ.
- **Cân bằng:** lấy mẫu khoảng 0,12 giây; đọc lại các khung giữa hai mẫu khi phát hiện đổi câu.
- **Nhanh:** lấy mẫu khoảng 0,25 giây; có bước đọc lại điểm đổi câu tương tự.

Các chế độ lấy mẫu có thể bỏ sót một câu hoặc một khoảng trống nằm hoàn toàn giữa hai mẫu, kể cả khi hai đầu cùng chữ hoặc đều trống. Bước quét 0,5 giây không bảo đảm bắt được câu ngắn hơn 0,5 giây. Chọn Kỹ nếu cần tránh việc bỏ qua các frame đó. Tool vẫn giải mã video tuần tự để lấy đúng frame và timestamp; phần tiết kiệm là số lần OCR. Chỉ giữ ảnh vùng sub của khoảng đang xét trong RAM, không giữ toàn bộ video và không ghi ảnh video lên đĩa.

Trong chế độ chia đôi, khoảng `chữ → trống` và `trống → chữ` được tìm ranh giới tương tự `câu A → câu B`. Khung có chữ phù hợp nhưng điểm OCR thấp được coi là chưa rõ, thử xử lý ảnh và đọc lại một lần; nếu vẫn chưa rõ thì không tự coi là phụ đề biến mất. Các mục liên quan được đánh dấu xem lại. OCR bỏ sót hoàn toàn vùng chữ vẫn có thể gây sai.

Thời gian lấy từ timestamp thực của khung hình bằng PyAV, hỗ trợ video có tốc độ khung hình thay đổi. Mốc chuyển câu dùng khung đầu tiên nhận ra trạng thái mới trong các mẫu đã kiểm tra. Với chia đôi, mục tiêu khoảng 0,1 giây là khoảng chặn ranh giới, không phải cam kết độ chính xác OCR; nếu video có khoảng cách frame lớn hơn 0,1 giây thì chỉ xác định được tới frame nguồn. Các mục dưới 0,08 giây bị loại để giảm nháy OCR.

Sau mỗi lượt chạy, ô thông báo hiển thị số lần OCR, tổng frame giải mã, số frame đọc thêm để tìm mốc, số lần đọc lại và thời gian thực tế. Chế độ chia đôi dùng so sánh chữ chuẩn hóa chặt hơn để giữ thay đổi một ký tự trong câu dài; khoảng trắng, hoa/thường và dấu câu được bỏ qua khi so sánh. Nội dung SRT vẫn lấy từ kết quả OCR gốc.

Ứng dụng nhóm chữ cùng hàng, lọc ngôn ngữ, loại chữ nghiêng mạnh, có thể khóa độ cao/vị trí dòng và lọc màu gần cạnh nét chữ. Cùng một câu liên tục được ghép thành một mục; cùng câu xuất hiện lại sau khoảng trống sẽ thành mục khác. Câu có số, dấu câu và tên Latin vẫn được giữ nguyên trong dòng Trung. Dòng chỉ có số được nhận theo vị trí dòng đã khóa; nếu chưa khóa, ứng dụng không đoán ngôn ngữ cho dòng chỉ có số.

## Giới hạn của bản thử

- Không bảo đảm phân biệt được chữ trong cảnh nếu nó có cùng vị trí, cỡ chữ và màu với phụ đề. Khoanh vùng sát hoặc bỏ tích dòng ngoài cảnh khi đọc thử.
- Mô hình Trung đi kèm bản này là PP-OCRv4 Trung/Anh; không cam kết đọc tốt mọi chữ phồn thể, chữ hiếm hoặc font cách điệu.
- OCR có thể sai ký tự, khoảng trắng và dấu câu dù điểm tin cậy cao. Mô hình tiếng Anh riêng được dùng để cải thiện khoảng trắng giữa từ.
- Phụ đề karaoke, chữ chạy, nội dung xuất hiện dần hoặc phụ đề đổi vị trí chưa được xử lý chuyên biệt.
- Thanh tua xem trước dùng OpenCV nên vị trí xem trên một số video VFR có thể lệch. Mốc SRT dùng timestamp của PyAV.
- Mới kiểm chứng trên video tổng hợp; cần đánh giá tiếp bằng video thực tế của bạn.

## Kiểm thử

Chạy từ thư mục dự án:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py -v
.venv\Scripts\python.exe tests\integration.py
.venv\Scripts\python.exe tests\gui_smoke.py
.venv\Scripts\python.exe tests\benchmark_adaptive.py
.venv\Scripts\python.exe tests\integration_reference.py
```

Kiểm thử tích hợp chạy mô hình thật trên ba video tổng hợp: hai ngôn ngữ, một dòng Trung, một dòng Anh. Kiểm tra nội dung, câu lặp, khoảng trống, mốc thời gian, lọc màu/vị trí, hủy tác vụ và timestamp VFR. Kiểm thử giao diện dùng Qt offscreen, gồm kéo vùng, đọc thử, chọn dòng, tua và chạy OCR. Kết quả trong `test_artifacts/`; lỗi ứng dụng được ghi vào `sublens.log`.

Kiểm thử thuật toán bổ sung kiểm tra hai đầu 5 giây cùng câu nhưng giữa có câu khác, khoảng trống, câu lặp, mẫu OCR chưa rõ, cache, frame cuối và timestamp VFR. Benchmark so sánh chế độ Kỹ với Chia đôi trên cùng video tổng hợp 8 giây/25 FPS, dùng cùng mô hình đã khởi tạo; kết quả trong `test_artifacts/benchmark_adaptive.json`. Đây là phép đo trên video mẫu, không đại diện cho mọi video thực tế.

Lượt đo tại máy hiện tại: Kỹ dùng 200 lần OCR, mất 17,59 giây; Chia đôi dùng 23 lần OCR, mất 2,13 giây. Giảm 88,5% số lần OCR, thời gian xử lý nhanh hơn khoảng 8,27 lần trong bài đo này. Cả hai trả đúng hai câu và các mốc 0–3,2–6,4 giây. Thời gian này không bao gồm khởi tạo mô hình lần đầu.

Kiểm thử SRT tham chiếu gồm parser, gộp khoảng, mốc đầu/cuối, quét bổ sung, tắt quét ngoài, cảnh báo cắt biên, cache và VFR. Kiểm thử OCR thật chạy cả Trung/Anh, bật/tắt quét ngoài, với một mục tham chiếu chữ sai nhưng đầu ra phải đúng ba câu thực tế; báo cáo ở `test_artifacts/reference_report.json`. Kiểm thử giao diện kiểm tra nạp, bật/tắt và bỏ SRT, chạy OCR theo mốc và xuất kết quả.

## Thành phần và nguồn mô hình

- Giao diện: PySide6 Essentials.
- Đọc video: OpenCV; timestamp/xử lý video: PyAV/FFmpeg.
- OCR: [RapidOCR](https://github.com/RapidAI/RapidOCR), ONNX Runtime; mô hình Trung đi kèm `rapidocr-onnxruntime==1.4.4`.
- Mô hình Anh: [RapidAI en_PP-OCRv4_rec_mobile.onnx](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx), nguồn kê khai trong [danh mục chính thức](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml). SHA256: `e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318`.

Các thư viện và mô hình giữ giấy phép riêng của tác giả; xem metadata/giấy phép trong `.venv/Lib/site-packages` và kho nguồn tương ứng trước khi phân phối lại.
