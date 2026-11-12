# Crash khi mở quảng cáo hồi sinh

Log đọc trực tiếp từ `adb logcat -d -b crash` của `emulator-5554`, gói game `com.vkslrzm.Zombie`, phiên bản 0.9941 (612), ghi nhiều lần `FATAL EXCEPTION` trong `UnityRewardedAd.show` / Google Mobile Ads 23.6.0. Nguyên nhân trong stack trace là `TransactionTooLargeException`, với parcel khoảng 1,47–1,52 MB khi mở Activity quảng cáo. Bản log được lưu cùng thư mục tại `crash_log_2026-11-11.txt`.

Mã bot có nhánh OCR đọc thấy `Revive`, `Life or Death` hoặc `Death` rồi trả về tọa độ cố định `(0.50, 0.73)` thay cho nút Die. Nhánh này có thể chạm nhầm vùng quảng cáo. Log không ghi tọa độ input nên chưa chứng minh được từng crash đều do nhánh này gây ra.

Đã bỏ tọa độ đoán. GUI và CLI dùng chung `dismiss_death`: nhả di chuyển, chụp ảnh mới, kiểm tra màn Die, đọc chính xác chữ Die và bấm tâm chữ đó. OCR không xác nhận được thì không bấm. Có thử OCR ở hai kích thước để đọc font cách điệu. Chỉ báo thành công khi ảnh sau cú bấm có nút Confirm của màn kết quả. Khi mở lại game, ADB cũng nhả hướng di chuyển trước.

Đây là sửa luồng input của bot để tránh kích hoạt nhầm quảng cáo hồi sinh. Không sửa APK hoặc SDK quảng cáo của game, không xóa dữ liệu game. Chưa chạy thử trọn ván sau sửa; cần khởi động lại bot để tiến trình đang chạy nạp mã mới.
