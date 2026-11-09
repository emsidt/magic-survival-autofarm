# Magic Survival AutoFarm (Google Play Games PC)

Bot hỗ trợ **tự chơi Magic Survival trên Windows** dựa trên ảnh màn hình: né các vùng quái tối, nhặt orb kinh nghiệm màu xanh và tự bấm những màn nâng cấp / kết thúc / chơi lại mà bạn đã dạy. Mục tiêu là hỗ trợ chơi lặp lại để tích lũy vàng và đá xanh nhận được từ trò chơi; bot **không sửa số dư, không can thiệp bộ nhớ, không bỏ qua điều kiện nhận thưởng**.

> **Bản thử nghiệm.** Được thiết kế dựa trên giao diện trong ảnh bạn gửi, chưa được chạy kiểm chứng trực tiếp trên Google Play Games của máy bạn. Không cam kết sống sót lâu, tự nhận đúng mọi nút hoặc kiếm được mức tài nguyên cụ thể. Tự kiểm tra quy định của trò chơi về automation trước khi sử dụng.

## 1. Cài đặt

Máy cần Windows 10/11, Python 3.12 (của bạn đã có), Google Play Games PC và game Magic Survival.

1. Giải nén thư mục này, ví dụ `D:\magic-survival-autofarm`.
2. Chạy **`setup.bat`** một lần để cài thư viện (numpy, OpenCV, mss, Pillow, pywin32, pydirectinput, pynput).
3. Chạy **`run.bat`**. Giao diện tool mở trong một cửa sổ riêng.

Nếu dùng PowerShell thay vì file `.bat`:

```powershell
cd D:\magic-survival-autofarm
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 2. Gán điều khiển trong Google Play Games

1. Mở Magic Survival rồi vào một trận.
2. Thử **W/A/S/D**. Nếu nhân vật di chuyển bình thường, để chế độ `WASD` của bot.
3. Nếu không, nhấn **Shift + Tab** trong Google Play Games → **Remap controls / Controls Editor** → thêm điều khiển **Joystick**, đặt tại vùng joystick của game và gán W/A/S/D. Sau đó thử lại bằng tay.
4. Trường hợp game vẫn không nhận phím, đổi bot sang **Kéo joystick bằng chuột**. Cần chỉnh `joystick_position` và `joystick_radius_px` trong `config.json` nếu tâm joystick của bạn nằm khác vị trí mẫu. Tọa độ là tỉ lệ `(x, y)` **trong vùng game đã cắt**, ví dụ `[0.08, 0.12]`.

**Quan trọng:** bot chỉ gửi phím khi cửa sổ **Magic Survival** nằm ở phía trước. Không thu nhỏ, che cửa sổ hoặc thay đổi độ phân giải trong lúc bot chạy.

## 3. Chạy bot lần đầu

1. Giữ cửa sổ game ở đúng kích thước như ảnh mẫu, không bật chế độ fullscreen vội.
2. Chọn `WASD`, để `Bỏ thanh bên = 65` px (ảnh của bạn có thanh Google Play Games bên trái rộng khoảng 65 px).
3. Vào một trận, nhấn **F8** để bắt đầu. Tool sẽ chọn hướng chạy và vẽ mũi tên xanh trên ảnh xem trước.
4. **F8** lần nữa để tạm dừng; **F9** dừng ngay việc gửi input; **F10** chụp game để dạy màn hình.
5. Quan sát vài phút: nếu nhân vật di chuyển ngược hướng, đứng yên hoặc ảnh cắt bị lệch, hãy dừng, sửa cấu hình rồi thử lại.

| Phím | Tác dụng |
|---|---|
| F8 | Bắt đầu / tạm dừng |
| F9 | Dừng ngay, nhả mọi phím và chuột |
| F10 | Dừng và chụp ảnh màn game để thiết lập quy tắc |

**Để dừng an toàn, dùng F9 trước khi chuyển sang cửa sổ khác.** Tool tự nhả phím khi game không còn là cửa sổ đang được chọn.

## 4. Dạy bot tự lên cấp và chơi lại

Quy tắc có hai thành phần:

- **Vùng nhận diện (anchor):** một khung chứa chữ/biểu tượng **ổn định, có nhiều chi tiết riêng** trên màn hình đó, ví dụ tiêu đề của màn chọn nâng cấp. Không khoanh nền trơn hoặc nội dung thay đổi liên tục.
- **Nút cần bấm (target):** tọa độ nút bạn muốn bot nhấp khi nhận thấy vùng đó.

Làm với từng màn hình:

1. Khi game xuất hiện màn **chọn phép nâng cấp**, nhấn **F10**. Bot sẽ dừng, chụp và hiển thị ảnh trong giao diện tool.
2. Bấm **`+ Thêm quy tắc`**, kéo chuột khoanh chữ/biểu tượng nhận diện màn nâng cấp.
3. Nhập tên không dấu, ví dụ `nang_cap`.
4. Nhấp vào vị trí **thẻ nâng cấp** bạn muốn chọn.
5. Nếu sau đó hiện một nút `Xác nhận`, chụp màn mới và thêm quy tắc `xac_nhan`.
6. Lặp lại cho **màn hình kết quả** (nút nhận thưởng / tiếp tục), **màn hình chọn khu vực**, **nút bắt đầu lượt chơi** và các popup xuất hiện trong vòng lặp.

Các quy tắc được lưu trong `rules.json`, ảnh nhận diện nằm trong `rules/`. Muốn đổi nút, tạo lại quy tắc với cùng tên. Bot chỉ bấm một nút sau khi ảnh khớp **hai lần liên tiếp** và có thời gian nghỉ giữa các lần bấm.

**Đặc biệt lưu ý:** không dạy quy tắc nào có thể bấm vào nút **mua bằng tiền thật, thanh toán, chi tiêu đá xanh, hay xác nhận xóa dữ liệu**. Bot không biết ý nghĩa giao dịch của những nút này.

## 5. Tinh chỉnh

Mở `config.json` bằng VS Code, sửa khi bot đã dừng:

| Trường | Ý nghĩa | Giá trị mẫu |
|---|---|---|
| `window_title` | Một phần tiêu đề cửa sổ game | `Magic Survival` |
| `input_mode` | `keyboard` hoặc `mouse` | `keyboard` |
| `crop_left_px` | Bỏ thanh công cụ phía trái | `65` |
| `crop_top_px`, `crop_right_px`, `crop_bottom_px` | Bỏ mép/công cụ thừa | `0` |
| `player_position` | Tâm nhân vật trên hình game `[x,y]`, 0–1 | `[0.5,0.5]` |
| `joystick_position` | Điểm kéo joystick cho mouse mode | `[0.08,0.12]` |
| `joystick_radius_px` | Quãng kéo chuột | `65` |
| `fps` | Lần đánh giá mỗi giây | `6` |
| `max_session_minutes` | Thời gian tối đa trước khi dừng | `120` |

Tọa độ đi từ **0 (trái/trên)** đến **1 (phải/dưới)** tính trên phần ảnh game được chụp, không tính thanh tiêu đề Windows và thanh Google Play Games phía trái.

## 6. Xử lý lỗi thường gặp

- **Bot không chạy:** kiểm tra game đang ở cửa sổ trước mặt, tiêu đề chứa `Magic Survival`, nhập `F8` (không phải F9).
- **Game không nhận WASD:** tự nhấn WASD thử; kiểm tra gán joystick trong Controls Editor, hoặc chuyển sang chế độ chuột.
- **Ảnh bên phải/trái bị lệch:** điều chỉnh `crop_left_px` và các mép khác trong `config.json`.
- **Nhân vật không ở giữa:** đo vị trí nhân vật trên ảnh xem trước rồi sửa `player_position`.
- **Bot coi menu là gameplay:** thêm quy tắc với một anchor đặc trưng của menu đó; nếu chưa thể dạy, nhấn F9 để tránh click nhầm.
- **Bot không thấy game / ảnh đen:** thử chế độ cửa sổ, để game hiển thị không bị che. `mss` chụp desktop Windows nên một số kiểu render được tăng tốc bằng GPU có thể không tương thích.
- **Nhận sai quy tắc:** chọn vùng anchor đặc trưng hơn, lớn hơn một chút, hoặc tăng `threshold` trong `rules.json` (ví dụ `0.92`).
- **Windows bật quyền admin cho game:** tool có thể cần chạy cùng mức quyền mới gửi được input. Không nên chạy bằng admin khi không cần.

## 7. Giới hạn hiện tại và hướng phát triển

- AI di chuyển hiện dùng **heuristic thị giác**, không phải mô hình đã được huấn luyện trên gameplay Magic Survival. Những hiệu ứng mới, tông màu map mới, quái không có màu tối hoặc vật thể che chắn có thể gây nhận diện sai.
- Mặc định mỗi lần nâng cấp sẽ bấm một vị trí bạn đã dạy; chưa đánh giá tên phép/độ mạnh build theo ngữ cảnh. Có thể dạy thêm từng anchor nhận diện thẻ phép cụ thể nếu chúng ổn định trên màn hình.
- Chưa có OCR để đọc chính xác vàng/đá xanh. Số lần bot bấm quy tắc **không tương đương** tài nguyên thu được.
- Chưa xác minh game cho phép tự động hóa. Công cụ không có chức năng né phát hiện hoặc vượt qua cơ chế bảo vệ.
- Vùng game mẫu có nền xám và quái đen theo ảnh của bạn. Với bản đồ khác, `botcore.py` cần tinh chỉnh ngưỡng màu.

Bạn có thể chạy thử logic xử lý ảnh bằng `python -m unittest discover -s tests -v` (nếu đã cài requirements).
