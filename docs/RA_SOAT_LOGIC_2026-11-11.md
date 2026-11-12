# Rà soát và sửa logic bot — 11/11/2026

Đã rà các module nhận diện/di chuyển (`botcore.py`), GUI (`main.py`), CLI (`bot_cli.py`), ADB (`adb_controller.py`), ghi dữ liệu (`data_recorder.py`), học trọng số (`learning_engine.py`), ghi thao tác người chơi (`record_human_play.py`), các script chạy và bộ kiểm tra.

| Vấn đề tìm thấy | Thay đổi đã thực hiện |
|---|---|
| GUI chụp desktop giữa chuỗi thao tác ADB; CLI dùng lại ảnh trước cú bấm | Dùng `capture_frame()` chung cho các lần chụp. Mất ảnh ADB thì nhả điều khiển và báo lỗi; không thay bằng ảnh desktop. |
| Mất kết nối ADB có thể tự chuyển sang điều khiển chuột/bàn phím Windows | Bỏ chuyển chế độ âm thầm; lỗi kết nối được thông báo. Giữ đúng thiết bị ADB đã chỉ định. |
| F9 có thể bị rơi khi hàng đợi preview đầy, hoặc chuỗi bấm tiếp tục sau khi dừng | Tách hàng đợi hotkey; F9 xóa trạng thái chạy ngay. Kiểm tra trạng thái và thế hệ phiên trước từng input, kể cả khi dừng rồi chạy lại trong lúc OCR còn xử lý. |
| Cửa sổ khác chỉ cần chồng lên game đã có thể được coi là popup game | Chỉ nhận cửa sổ game, cửa sổ con/chủ sở hữu hoặc cùng tiến trình. DirectInput chờ đúng focus. |
| Escape được gửi qua hai cách liên tiếp | Chỉ dùng cách thứ hai khi cách đầu lỗi. Vector đứng yên ở chế độ chuột sẽ nhả kéo joystick. |
| GUI thiếu import `botcore`; CLI thiếu import `math` | Bổ sung import cần thiết và bỏ các import không còn dùng sau khi gom luồng. |
| Nhánh màu có thể coi vòng đạn đỏ là sao combination | Bỏ nhánh đoán theo cụm đỏ rỗng; yêu cầu khớp ảnh mẫu ngôi sao và màu đỏ tại vùng khớp. |
| Học combination được ghi nhận trước khi Learn thành công | Dùng thao tác chung trong `game_actions.py`; kiểm tra nút Learn hoạt động và xác nhận chuyển màn hình. Không tìm được lựa chọn thì đóng menu, đọc ảnh mới và giãn lần thử sao tiếp theo. |
| Mọi màn thuộc tính đều bị ghi thành cấp 7 | Chỉ cập nhật kỹ năng sau thao tác xác nhận. Đọc cấp từ thẻ; không suy ra cấp tối đa từ số cú bấm hoặc từ việc mở màn thuộc tính. |
| Thẻ max vẫn có thể được chọn qua nhánh passive, trait hoặc mặc định | Loại cả ô không hợp lệ khỏi mọi nhánh chấm điểm. Nếu không còn ô hợp lệ thì không bấm. |
| Dòng có chữ “Mana” bị loại, kể cả kỹ năng Mana Factory | Chỉ bỏ dòng Mana Retrieve; giữ tên kỹ năng và cấp OCR đọc được. |
| OCR lỗi làm biến `full_text` chưa được khởi tạo và crash khi chấm cổ vật | Khởi tạo dữ liệu rỗng trước OCR; chấm điểm còn lại vẫn hoạt động khi OCR không khả dụng. |
| Lấy toàn bộ danh sách ưu tiên làm kỹ năng đang sở hữu | Tính tương tác cổ vật từ kỹ năng đã ghi nhận; danh sách ưu tiên tiếp tục dùng để xếp lựa chọn kỹ năng. |
| CLI bỏ qua các công tắc và quy tắc thủ công | Áp dụng Auto Restart, Auto Level Up, Auto Chest, Auto Close Ads và giới hạn phiên; thực thi quy tắc sau hai lần khớp liên tiếp. |
| Mua/xem đồ dùng ảnh cũ hoặc bấm X theo tọa độ đoán sau khi shop đã đóng | Chụp lại sau khi đổi món, kiểm tra Buy trước khi bấm, chỉ đóng khi tìm được nút X trên ảnh mới. Rương một món không bị duyệt như rương ba món. |
| Điểm hút rương lớn có thể thắng điểm phạt va chạm | Khi có đường thoát đủ trống, loại hướng va chạm tức thời khỏi các lựa chọn, kể cả đang hướng về tháp. |
| Mã ván bị mất trước lúc học; màn kết quả lặp có thể học trùng | Giữ ID trước khi kết thúc bản ghi, xóa trạng thái kết quả đã xử lý; bộ học cũng từ chối ID đã học gần đây. |
| Dùng thời gian ngoài đời, gồm cả thời gian xem menu, làm thời gian sống | Chỉ cập nhật trọng số khi đọc được thời gian HUD. Đồng hồ ba chữ số phút không bị cắt mất chữ số đầu. |
| Bộ chấm thẻ dùng một bản trọng số cũ khác bộ vừa học | GUI/CLI truyền cùng đối tượng learner vào chấm thẻ. |
| Hai ván tạo cùng giây có thể ghi đè ảnh; ghi log dù lưu ảnh thất bại | ID gồm microsecond và UUID; chỉ ghi dòng quyết định khi ảnh lưu thành công. |
| Dọn bản ghi có thể xóa thư mục không thuộc recorder hoặc phiên chưa hoàn tất | Chỉ dọn thư mục ván đã hoàn tất có summary khớp ID, nằm trực tiếp trong thư mục runs; bỏ qua liên kết và thư mục phiên đang chạy. |
| File JSON có thể bị cắt giữa chừng khi lưu | Ghi file tạm, flush rồi thay thế nguyên tử. Kiểm tra dữ liệu trọng số và thời gian không hữu hạn trước khi học. |
| Bộ ghi người chơi tự đoán thẻ 1 khi không bắt được click | Ghi `unknown` với độ tin cậy 0; không thêm kỹ năng đoán vào build. Thao tác mua chỉ được ghi là lần thử mua khi bắt được click tương ứng. |
| Các file chạy phụ thuộc thư mục hiện tại của terminal | Launcher CLI, ghi người chơi và kiểm tra LDPlayer chuyển về thư mục dự án trước khi chạy. |

Các hàm dùng chung mới nằm ở `game_actions.py`; ghi JSON nguyên tử nằm ở `storage.py`.

Kiểm chứng đã thực hiện:

- `python -m unittest discover -s tests -q`: **98 bài kiểm tra đạt**, gồm 37 bài bổ sung so với 61 bài ban đầu.
- Kiểm tra cú pháp toàn bộ module, script và test bằng `compileall`: đạt.
- `git diff --check`: đạt.
- Các test bổ sung dùng ảnh tổng hợp, mock điều khiển và thư mục tạm; có kiểm tra luồng CLI với màn kết quả lặp lại, tùy chọn tắt tự động, mất ảnh ADB và F9 khi hàng đợi đầy.

Giới hạn cần hiểu khi chạy bản này:

- Chưa chạy một ván game thật sau đợt sửa. Kết quả kiểm tra xác nhận logic và các tình huống mô phỏng, chưa chứng minh thời gian sống hoặc hiệu suất farm tăng.
- OCR và ảnh mẫu vẫn phụ thuộc ngôn ngữ, độ phân giải, hiệu ứng và phiên bản game. Không có bảo đảm nhận diện đúng 100%.
- Bộ học hiện tại vẫn là điều chỉnh trọng số theo kết quả ván, chưa phải mô hình reinforcement learning. Cần đánh giá theo kế hoạch AI trước khi coi trọng số mới là tốt hơn.
- Bảng công thức combination/ưu tiên có sẵn chưa được đối chiếu lại với phiên bản game hiện tại. Luồng học yêu cầu tín hiệu sao đỏ, menu phù hợp và Learn hoạt động; không tự suy ra công thức mới.
- Vẫn còn chi phí gọi OCR nhiều lần và ước lượng vị trí rương/tháp khi chúng tạm biến mất. Cần đo trên phiên chạy thật trước khi chỉnh tốc độ quét hoặc tham số di chuyển.
- `max_data_runs` dọn các ván hoàn tất; phiên chưa có summary được giữ lại để tránh mất dữ liệu. Nhiều phiên bị ngắt có thể khiến số thư mục thực tế vượt giới hạn này.

Nếu bot đang chạy bằng tiến trình cũ, dừng rồi khởi động lại để nạp mã mới.
