# Kế hoạch chuyển bot sang AI học từ dữ liệu chơi

## Mục tiêu và phạm vi

Bot hiện chụp màn hình, nhận diện bằng OpenCV/OCR, chọn hành động theo luật trong `botcore.py`, rồi điều khiển game từ `main.py`. Bước đầu sẽ huấn luyện AI **chọn thẻ kỹ năng và combination**. Phần di chuyển và các màn hình xác nhận tiếp tục dùng bot hiện tại cho đến khi có đủ dữ liệu và cách đánh giá riêng.

Không thay trực tiếp toàn bộ bot bằng một mô hình chưa đo được chất lượng. Mỗi giai đoạn phải có cách so với bot hiện tại và có thể tắt AI bằng cấu hình.

## Bước 0 — Dọn và phân loại ảnh hiện có

- [x] Chuyển toàn bộ ảnh `.png`/`.jpg` nằm ở thư mục gốc vào `captures/` để thư mục gốc chỉ còn mã nguồn, cấu hình và tài liệu.
- [x] Xem lại từng ảnh trong `captures/`, gắn nhãn nguồn, kích thước vùng game, loại màn hình và trạng thái sao combination nếu thấy rõ (Đã hoàn thành qua `scripts/inspect_captures.py`, lưu tại `captures/manifest.json`).
- [x] Giữ `assets/` cho mẫu nhận diện đang được code dùng và `rules/` cho ảnh quy tắc. Không chuyển hai nhóm này nếu chưa sửa đường dẫn liên quan.

## Bước 1 — Chốt bài toán và số đo gốc

- [ ] Chạy bot luật hiện tại qua nhiều ván, ghi lại thời gian sống, cấp đạt được, số lần chọn thẻ, combination thành công, lỗi bấm nhầm và số lần phải can thiệp tay.
- [ ] Định nghĩa hành động AI đầu tiên: chọn một trong các thẻ đang hiện, hoặc chọn combination hợp lệ. Khi thiếu thông tin, AI trả về `không chắc` để bot luật xử lý.
- [ ] Chốt tiêu chí thử nghiệm trước khi huấn luyện: không tăng lỗi bấm nhầm; tỉ lệ chọn hợp lệ đạt mức chấp nhận; thời gian sống/cấp đạt được không kém mốc bot luật trên cùng điều kiện.

**Đầu ra:** bảng số đo gốc và tiêu chí đạt/rớt rõ ràng.

## Bước 2 — Thu dữ liệu có cấu trúc

- [x] Thêm chế độ ghi log theo từng quyết định: ảnh vùng game, thời điểm, loại màn hình, danh sách thẻ OCR đọc được, cấp từng magic nếu nhận diện được, trạng thái sao combination, hành động bot chọn, mức tin cậy và kết quả sau khi bấm (Đã hoàn thành module `data_recorder.py` và tích hợp vào luồng game trong `main.py`).
- [x] Gắn một `run_id` cho mỗi ván; lưu ảnh và log theo ván trong `data/runs/<run_id>/`, tự động dọn dẹp các ván cũ (giữ tối đa 50 ván gần nhất).
- [ ] Thu cả các trường hợp khó: sao xám/đỏ, OCR sai, thẻ bị che, menu combination không có lựa chọn hợp lệ, độ phân giải khác nhau (Đang tự động thu thập trong quá trình bot chạy).
- [ ] Cho phép gắn nhãn thủ công hành động đúng và đánh dấu ảnh không dùng được. Chỉ thu dữ liệu từ game và tài khoản do mình điều khiển.

**Đầu ra:** tập dữ liệu có ảnh, hành động và kết quả khớp nhau; có thể phát lại một quyết định để kiểm tra.

## Bước 3 — Làm bộ đánh giá offline

- [ ] Chia dữ liệu theo **ván chơi**, không chia ngẫu nhiên từng ảnh liên tiếp, để ảnh gần giống nhau không lọt sang cả tập huấn luyện và tập kiểm tra.
- [ ] Tạo bộ tình huống cố định cho màn chọn thẻ, sao combination, màn khác dễ nhận nhầm và ảnh OCR lỗi.
- [ ] Đo độ chính xác chọn hành động, tỉ lệ `không chắc`, tỉ lệ bấm sai và độ trễ mỗi quyết định. So với quyết định của bot luật trên đúng bộ ảnh đó.

**Đầu ra:** lệnh đánh giá lặp lại được và báo cáo lỗi theo từng loại màn hình.

## Bước 4 — Huấn luyện mô hình đầu tiên

- [ ] Bắt đầu bằng học có giám sát từ các quyết định đã gắn nhãn. Đầu vào nên là dữ liệu đã đọc từ màn hình (tên thẻ, cấp, build hiện tại, combination hợp lệ); chỉ dùng ảnh trực tiếp nếu OCR/nhận diện không đủ tin cậy.
- [ ] Mô hình phải xuất lựa chọn, điểm tin cậy và lý do ngắn có thể ghi log. Lưu phiên bản mô hình cùng phiên bản dữ liệu.
- [ ] Điều chỉnh trên tập huấn luyện/validation; chỉ công bố kết quả một lần trên tập kiểm tra giữ riêng. Xem các lỗi bấm sai trước khi chạy trong game.

**Đầu ra:** mô hình có thể dự đoán offline và vượt tiêu chí ở Bước 1.

## Bước 5 — Chạy thử không điều khiển

- [ ] Chạy AI song song khi bot luật chơi: AI chỉ ghi đề xuất, không gửi phím/chuột.
- [ ] So từng đề xuất với hành động thật và kết quả sau đó; bổ sung nhãn cho các trường hợp bất đồng.
- [ ] Đo độ trễ trên máy đang chạy game và kiểm tra việc ghi dữ liệu không làm giảm tốc độ bot.

**Đầu ra:** báo cáo chạy thử qua nhiều ván, chỉ rõ khi nào AI tốt hơn hoặc kém hơn luật.

## Bước 6 — Bật AI có kiểm soát

- [ ] Thêm công tắc AI trong cấu hình; mặc định tắt. Chỉ cho AI chọn ở loại màn hình đã đạt tiêu chí.
- [ ] Trước khi bấm vẫn xác thực loại màn hình, vị trí thẻ và điều kiện sao combination đỏ. Nếu AI thiếu chắc chắn, OCR mâu thuẫn hoặc không có combination hợp lệ, trả quyền quyết định cho bot luật hoặc bỏ qua.
- [ ] Giữ F9 để dừng ngay. Ghi lại mọi quyết định AI, hành động thực tế và kết quả để phát hiện hồi quy.
- [ ] Thử số ván nhỏ trước, rồi tăng dần nếu số đo thực tế đạt tiêu chí ở Bước 1.

**Đầu ra:** AI chỉ điều khiển phần chọn kỹ năng đã kiểm chứng; có thể quay lại bot luật ngay.

## Bước 7 — Tự cải thiện và mở rộng

- [x] Đã triển khai module học thích ứng sau mỗi ván ([`learning_engine.py`](file:///d:/magic-survival-autofarm/learning_engine.py)): Đánh giá thời gian sống sót của ván chơi và cập nhật bảng trọng số kỹ năng/synergy thích ứng (`data/learned_policy.json`). Các kỹ năng mang lại chiến thắng/thời gian sống lâu tự động được cộng điểm ưu tiên trong các ván tiếp theo.
- [ ] Dùng các ván mới để tìm tình huống AI sai hoặc thiếu chắc chắn, gắn nhãn rồi huấn luyện lại theo phiên bản. Không tự cập nhật mô hình đang chạy giữa ván.
- [ ] Khi dữ liệu đủ tốt, thử mô hình chọn hướng di chuyển riêng. Số đo cho phần này gồm thời gian sống, lượng sát thương nhận, kinh nghiệm nhặt được và độ ổn định điều khiển.
- [ ] Chỉ cân nhắc reinforcement learning sau khi có môi trường thử nhanh hoặc khả năng phát lại, hàm thưởng rõ ràng và bộ kiểm tra tránh hành động sai. Chạy thử và so với mô hình học có giám sát trước khi thay thế.

## Nguyên tắc dữ liệu và thư mục dự kiến

- `captures/`: ảnh thử nghiệm hiện có, dùng để xem và tuyển chọn thủ công.
- `assets/`: ảnh mẫu mà mã nguồn đang sử dụng; không coi là tập huấn luyện.
- `rules/`: ảnh quy tắc do người dùng tạo.
- `data/runs/<run_id>/`: ảnh và log quyết định theo ván, sẽ tạo ở Bước 2.
- `data/labels/`: nhãn đã kiểm tra, sẽ tạo ở Bước 2.
- `models/`: mô hình đã huấn luyện kèm metadata phiên bản, sẽ tạo ở Bước 4.

Các thư mục `data/` và `models/` chưa cần tạo cho đến khi có chức năng tương ứng. Trước khi thu dữ liệu lâu dài, cần quyết định dung lượng tối đa và thời gian giữ ảnh để ổ đĩa không đầy.
