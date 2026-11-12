# Rà soát logic bổ sung

Đợt này kiểm tra lại luồng GUI/CLI, các thao tác dùng chung, ADB chạy nền, nhận diện menu/quảng cáo, chọn thẻ, mở rương, cửa hàng, di chuyển và cách ghi nhận kết quả. Những sửa đổi dưới đây bổ sung cho báo cáo `RA_SOAT_LOGIC_2026-11-11.md`.

## Các lỗi đã sửa

| Lỗi | Cách xử lý |
|---|---|
| Bấm nút đóng quảng cáo rồi gửi thêm Back, có thể làm game vừa trở lại bị mở menu Pause | Chụp ảnh mới để tìm nút đóng, gửi đúng một thao tác rồi quay lại vòng nhận diện. Nhánh Back dự phòng cũng phải chụp lại và xác nhận vẫn còn quảng cáo, chưa có nút đóng. |
| Nhánh khôi phục GUI dùng biến ảnh trước khi chụp ảnh đầu tiên | Dùng hàm đóng quảng cáo tự chụp ảnh mới; không phụ thuộc biến ảnh của vòng trước. |
| Chỉ tìm X hoặc nhầm dòng “Đóng quảng cáo?” với nút đóng | Nhận diện nhãn Đóng/Close/Skip/Bỏ qua trước các mẫu X; loại dòng câu hỏi, đếm ngược, lời quảng cáo và nút cài đặt. Kiểm tra tọa độ cả trên ảnh gốc lẫn ảnh thu nhỏ. |
| CLI thoát khi mất ảnh ở giữa chuỗi chọn thẻ/rương | Bắt `FrameCaptureError` trong từng vòng chạy, nhả hướng, bỏ mục tiêu tạm và lấy ảnh mới; không phát lại cú bấm có kết quả chưa rõ. |
| Chỉ cần thấy Pause trên HUD là gửi di chuyển hoặc xác nhận đã học thẻ | Yêu cầu nhận diện cảnh chiến đấu; HUD vẫn có thể hiện phía sau menu. Màn không rõ trạng thái sẽ nhả di chuyển. |
| Hướng được tính từ ảnh cũ vẫn có thể khởi động lại vòng vuốt nền | Bỏ quyết định khi thời gian phân tích ảnh từ 1 giây trở lên. Thời hạn duy trì hướng tính cả thời gian phân tích, không bắt đầu lại từ lúc gọi `move()`. Một lệnh vuốt đã gửi vẫn có thể chạy hết 350 ms. |
| Các đường gửi input có thứ tự lấy khóa khác nhau | Thống nhất lấy khóa trạng thái trước khóa vuốt; worker nhả khóa vuốt trước khi báo lỗi. Dừng và thu hồi worker khi đóng bot. |
| Truy vấn focus lỗi vẫn có thể bị coi là game đang sẵn sàng | Lỗi ADB hoặc focus không xác định được sẽ ngắt input và chờ lần đọc mới. Lệnh mở lại game cũng chịu kiểm tra dừng/F9. |
| Bộ đếm cấp GUI bị đặt lại mỗi lần chiến đấu; CLI tăng cấp cả khi bấm thất bại | Chỉ tăng sau khi xác nhận chọn thẻ, đặt lại khi vào ván mới. Ưu tiên đọc `Current Level` trên màn hình, kể cả khi nối vào một ván đang chơi; khi không đọc được mới dùng số lần chọn thành công để ước lượng. |
| Rương duyệt các ô rồi bấm Obtain theo tọa độ cũ; ghi nhận nhận đồ trước khi biết kết quả | GUI và CLI dùng chung `select_chest_artifact()`: kiểm tra còn màn rương sau mỗi ô, đọc lại vị trí Obtain và chỉ ghi lựa chọn khi thấy chuyển về chiến đấu hoặc lên cấp. |
| Cửa hàng tiếp tục duyệt khi màn đã đổi hoặc nhận biểu tượng X của màn khác | Dừng chuỗi khi không còn Buy; kiểm tra lại Buy trước khi mua. Hàm tìm X của shop chỉ chạy trên màn có Buy. Log phân biệt đã bấm Buy với khẳng định mua thành công. |
| “Continue” của quảng cáo có thể bị nhầm là Resume game | Chỉ chấp nhận nhãn Resume chính xác; Continue cần đi cùng tiêu đề Pause/Paused. |

## Kiểm chứng

- `python -m unittest discover -s tests -q`: **188 kiểm thử đạt**. `compileall` cho các module, script và test, cùng `git diff --check`: đạt.
- Bộ kiểm thử có ảnh thật cho hai dạng nút Đóng, màn chiến đấu, màn lên cấp và chọn Summoner. Ảnh quảng cáo được lưu tại `tests/fixtures/ads/`, không phụ thuộc đường dẫn riêng ngoài dự án và không bị bỏ qua âm thầm.
- Các tình huống mới gồm: mất ảnh giữa chuỗi chọn thẻ, ADB lỗi/mất focus, quảng cáo tự kết thúc trước Back, F9 trước lệnh mở lại game, rương biến mất khi duyệt ô, Obtain đổi tọa độ, ảnh quá cũ, thẻ chưa chọn thành công và nối vào ván cấp cao.
- Đo offline trên `tests/fixtures/movement/combat.png`, thu nhỏ rộng 540 px: nhận diện chiến đấu, phân tích vùng nguy hiểm và chọn hướng có trung vị **0,295 giây** sau lượt đầu; lượt chậm nhất trong 6 lần là **0,538 giây**. Không gồm chụp màn hình, truyền ADB hoặc thời gian thực thi input; đây không phải FPS chơi thật.

## Phạm vi đã xác nhận

Đã kiểm tra bằng ảnh mẫu, điều khiển giả lập và bộ test. Chưa chạy trọn ván thật sau đợt sửa này, nên chưa có kết luận về thời gian sống, lượng vàng hay việc hết crash trong mọi trường hợp. Chẩn đoán crash của SDK quảng cáo vẫn được ghi riêng trong `CHAN_DOAN_CRASH_2026-11-11.md`; sửa các đường bấm nhầm không thay thế việc xác minh lỗi SDK khi chơi thật.

Di chuyển vẫn dựa trên nhận diện hình ảnh; cơ chế tránh vùng tối, chọn Die thay Revive và xác minh Summoner được giữ trong bộ kiểm thử. Việc ưu tiên cổ vật/kỹ năng tiếp tục dựa trên cấu hình và kỹ năng đã xác nhận sở hữu. Các số đếm cấp dự phòng chỉ là ước lượng nếu OCR không đọc được `Current Level`.
