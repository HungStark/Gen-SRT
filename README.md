# SubLens — OCR phụ đề video thành SRT

Ứng dụng Windows chạy trên máy bằng CPU. Mặc định xuất tiếng Trung; có thể chọn tiếng Anh. Nhận diện chữ đã in trên hình video, không chuyển giọng nói thành chữ hoặc dịch phụ đề.

## Mở ứng dụng

Môi trường đã được cài trong thư mục dự án. Bấm đúp **`start.bat`**. Sau khi cập nhật, đóng cửa sổ cũ rồi mở lại.

Khi cần cài lại, cài [uv](https://docs.astral.sh/uv/getting-started/installation/), rồi chạy `setup.bat`. Python 3.12, thư viện và mô hình được tải vào thư mục dự án. Cần mạng lúc cài; sau đó OCR chạy cục bộ. Nếu di chuyển thư mục sang đường dẫn khác, hãy tạo lại môi trường bằng setup.

## Bố cục và cách quét

- **Bên trái:** video, thanh tua, chọn ngôn ngữ, Đọc thử khung hình, Đọc cả video và nội dung đọc thử.
- **Bên phải:** bảng bắt đầu, kết thúc, nội dung, tin cậy; các nút sửa, xóa, gộp, hoàn tác và xuất SRT.
- **Phía dưới:** tiến trình quét, nút Dừng và trạng thái. Có thể kéo vạch giữa hai cột để đổi tỷ lệ.

1. Kéo thả video vào cửa sổ, bấm vùng video trống hoặc bấm **Chọn video…**.
2. Tua tới đoạn có phụ đề rõ. Kéo chuột trái trên ảnh để khoanh vùng sát các dòng sub. Có thể khoanh cả Trung/Anh hoặc chỉ một dòng.
3. Chọn **Tiếng Trung** hoặc **Tiếng Anh**. Mặc định là tiếng Trung.
4. Bấm **Đọc thử khung hình**. Nội dung đọc được hiện phía dưới bên trái; khung xanh là dòng giữ, đỏ là dòng loại. Bỏ tích dòng chữ trong cảnh nếu nó bị nhận nhầm.
5. Bấm **Đọc cả video**. Tool quét mỗi **0,5 giây**, dùng lại kết quả OCR và chia đôi các khoảng đổi câu đến khoảng **0,1 giây**.
6. Kiểm tra, chỉnh sửa bảng bên phải rồi bấm **Xuất SRT…**. Tên mặc định `video.zh.srt` hoặc `video.en.srt`, mã hóa UTF-8 có BOM. Chỉ ghi tệp khi bạn xuất.

Trong **Tùy chọn…** có khóa dòng theo kết quả đọc thử, ngưỡng tin cậy OCR và lọc màu. Muốn chọn màu, bấm chuột phải vào phần màu đặc bên trong nét chữ trên video; tránh viền đen và nền. Nếu câu có thể xuống hai dòng, đọc thử ở đoạn có đủ hai dòng trước khi khóa. Nếu sub đổi vị trí hoặc màu, điều chỉnh/tắt bộ lọc tương ứng.

## Sửa, xóa và gộp kết quả

**Sửa:** chọn một dòng và bấm **Sửa chữ**, hoặc nhấp đúp ô Nội dung. Hỗ trợ chữ nhiều dòng; Enter xuống dòng, **Ctrl+Enter** lưu, Escape hủy. Bấm ra khỏi ô cũng lưu thay đổi. Có thể nhấp đúp ô Bắt đầu/Kết thúc để sửa thời gian bằng số giây (`12.350`) hoặc dạng `00:00:12,350`.

**Xóa:** chọn một hoặc nhiều dòng bằng Shift/Ctrl, bấm **Xóa đoạn**. Phím Delete cũng xóa các dòng được chọn khi bảng đang có focus và không đang nhập chữ.

**Gộp:** chọn ít nhất hai dòng **liền nhau**, bấm **Gộp đoạn…**. Trong hộp chọn, bấm nội dung của một trong các dòng nguồn rồi bấm **Gộp**. Đoạn mới dùng thời điểm bắt đầu sớm nhất và kết thúc muộn nhất của nhóm, giữ nguyên nội dung được chọn, gồm cả xuống dòng. Khoảng trống giữa các đoạn cũng nằm trong thời gian đoạn gộp. Chọn Hủy để giữ nguyên kết quả.

**Hoàn tác:** nút Hoàn tác phục hồi thao tác sửa/xóa/gộp gần nhất, tối đa 30 thao tác trong lượt kết quả hiện tại. Ctrl+Z hoạt động khi bảng có focus; khi đang nhập chữ, trình soạn thảo xử lý Ctrl+Z riêng. Một lượt quét thành công mới hoặc mở video mới thay thế danh sách và lịch sử hiện tại.

Dòng vàng: OCR cần xem lại. Dòng xanh nhạt: đã sửa thủ công. Dòng đỏ nhạt: thời gian không hợp lệ, chồng lấn hoặc chữ rỗng. Cột tin cậy chuyển thành **Đã sửa** khi sửa/gộp; tooltip giữ điểm OCR gốc để tham khảo. Các lỗi thời gian hoặc nội dung phải được chỉnh trước khi xuất. Sau khi xóa/gộp, số thứ tự trong SRT được đánh lại liên tục.

## Cách xác định mốc thời gian

Tool giải mã video tuần tự, giữ ảnh vùng sub của khoảng đang xét trong RAM. OCR lấy mẫu khoảng 0,5 giây. Khi hai mẫu khác chữ, đọc điểm giữa và tiếp tục chia khoảng có thay đổi, tới khoảng 0,1 giây hoặc khi không còn frame nguồn ở giữa. Timestamp lấy từ khung hình thực qua PyAV, hỗ trợ VFR. Các mục ngắn hơn 0,08 giây bị loại để giảm nháy OCR.

Tool ổn định một số nhầm ký tự tiếng Anh như `I/l`, mất `i/l`, `rn/m` khi câu đủ dài và hình nét chữ cũng khớp. Thay đổi số, chữ Trung hoặc từ khác không được gộp chỉ vì câu gần giống. Sau lượt quét, các đoạn liền nhau có cùng chữ chuẩn hóa được tự gộp; khoảng hụt OCR tối đa 0,1 giây cũng được nối và đánh dấu xem lại. Khoảng trống dài hơn hoặc có một câu khác ở giữa sẽ giữ riêng. Với khoảng trống thật rất ngắn giữa hai lần lặp cùng câu, quy tắc nối 0,1 giây cũng có thể gộp chúng; cần kiểm tra mục được đánh dấu. Ô thông báo ghi số kết quả OCR đã ổn định và số đoạn trùng được gộp.

Các cụm chữ cùng hàng nhưng cách xa nhau được tách trước khi lọc ngôn ngữ, tránh ghép biển chữ ở rìa ảnh vào phụ đề. Crop nhận diện tiếng Anh được thu sát nét chữ để giảm dao động khi hộp OCR thừa/thiếu viền. So sánh hình nét chữ dùng tương phản cục bộ, giúp ổn định khi nền chuyển cảnh hoặc chữ mờ dần.

Hai đầu cùng chữ hoặc cùng trống vẫn có thể che giấu một câu/khoảng trống rất ngắn nằm hoàn toàn giữa hai mẫu. Bước quét 0,5 giây không bảo đảm tìm đủ câu ngắn hơn 0,5 giây. Mục tiêu 0,1 giây là độ rộng khoảng tìm biên, không phải cam kết OCR luôn đúng. Chữ mờ, hiệu ứng xuất hiện dần, karaoke, phụ đề đổi vị trí hoặc chữ trong cảnh giống sub vẫn cần kiểm tra lại.

Khung có chữ phù hợp nhưng OCR điểm thấp được thử đọc lại; nếu chưa rõ, không tự coi là phụ đề biến mất. Các mục liên quan được đánh dấu xem lại. Tool có thể vẫn bỏ sót hoàn toàn một vùng chữ khó đọc. Mô hình Trung đi kèm không bảo đảm đọc tốt mọi chữ phồn thể/hiếm/font cách điệu.

## Kiểm tra

Video mẫu trong `test_artifacts/demo_dual.mp4`, `demo_zh.mp4`, `demo_en.mp4`. Các ảnh giao diện và đầu ra kiểm thử cũng nằm trong thư mục này.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py -v
.venv\Scripts\python.exe tests\integration.py
.venv\Scripts\python.exe tests\gui_smoke.py
.venv\Scripts\python.exe tests\gui_editing.py
.venv\Scripts\python.exe tests\gui_layout.py
```

Kiểm tra OCR thật gồm hai ngôn ngữ, một dòng, nhiều dòng, câu lặp, khoảng trống, lọc màu/vị trí và VFR. Kiểm tra sửa kết quả gồm nội dung nhiều dòng, thời gian, chọn nội dung gộp, xóa nhiều dòng, hoàn tác, hủy gộp, lưu ô đang sửa trước khi xuất và xác thực SRT. Kiểm tra giao diện ở nhiều kích thước/mức DPI. Lỗi ứng dụng ghi trong `sublens.log`.

## Thành phần

PySide6 Essentials, OpenCV, PyAV/FFmpeg, [RapidOCR](https://github.com/RapidAI/RapidOCR) và ONNX Runtime. Mô hình Trung/Anh PP-OCRv4 đi kèm `rapidocr-onnxruntime==1.4.4`; mô hình nhận diện tiếng Anh riêng trong `models/en_PP-OCRv4_rec_mobile.onnx`, nguồn [RapidAI](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx). Các thành phần giữ giấy phép riêng của tác giả; xem kho nguồn và metadata trong môi trường trước khi phân phối lại.
