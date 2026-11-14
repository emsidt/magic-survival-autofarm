# 🤖 Magic Survival AutoFarm & Adaptive AI Bot

Hệ thống **tự động hóa hoàn toàn (Full Auto-Play) và Học máy thích ứng (Adaptive AI)** cho tựa game **Magic Survival**, hỗ trợ chạy song song trên **giả lập Android LDPlayer (qua ADB ngầm 100%)** và **Google Play Games PC (cửa sổ Windows)**.

Bot hoạt động thuần túy bằng **Thị giác máy tính (OpenCV + Windows OCR)** và **Điều khiển ngoại vi / ADB** — tuyệt đối **không can thiệp bộ nhớ (memory hack), không sửa gói tin mạng, không chỉnh sửa file game**.

---

## 🌟 Tính năng nổi bật

### 1. Hai chế độ điều khiển linh hoạt
* **Chế độ 1 — LDPlayer / Android ADB (`control_mode: "adb"`)**:
  * Chụp màn hình trực tiếp từ nhân Android qua `adb exec-out screencap -p`.
  * Gửi thao tác chạm (`tap`) và kéo giữ joystick (`swipe`) trực tiếp vào giả lập.
  * **Chạy ngầm hoàn toàn**: Không chiếm chuột hay bàn phím máy tính; bạn có thể vừa treo bot vừa làm việc khác.
* **Chế độ 2 — Google Play Games PC (`control_mode: "desktop"`)**:
  * Chụp vùng cửa sổ game tốc độ cao bằng thư viện `mss`.
  * Điều khiển di chuyển bằng bàn phím (`WASD`) hoặc kéo chuột ảo (`pydirectinput`).

### 2. Hai giao diện vận hành (CLI & GUI)
* **Terminal CLI Mode ([`bot_cli.py`](bot_cli.py))**: Siêu nhẹ, tốn ít tài nguyên CPU/RAM, hiển thị nhật ký trạng thái thời gian thực (vàng, đá quý, thời gian sống, cấp độ, phép đã học, rương, tháp qua màn).
* **Tkinter GUI Mode ([`main.py`](main.py))**: Giao diện trực quan có khung xem trước ảnh (Live Preview), vẽ mũi tên vector hướng di chuyển, thống kê bộ đếm hành động, chỉnh sửa cấu hình trực tiếp và công cụ dạy quy tắc bằng chuột (`F8` / `F9` / `F10`).

### 3. Thị giác máy tính & Điều hướng chiến thuật ([`botcore.py`](botcore.py))
* **Né quái & Vùng tối sát thương (Hazard / Void Avoidance)**:
  * Phân tích mật độ quái vật (bóng đen & lõi đỏ), Boss khổng lồ và vùng tối thu hẹp bản đồ (`detect_wave_darkness`).
  * Sử dụng **Bản đồ khoảng cách (Distance Transform)** kết hợp **32 tia phóng chiếu (Ray-casting)** và **Quán tính hướng (Momentum)** để không bị kẹt hoặc giật lắc hướng (`W ↔ S`) khi bị bao vây.
* **Kỹ thuật "Lắc tay" (Human Weave)**:
  * Tạo dao động hình sin vi mô khi di chuyển giúp gom quái và lách khe đạn tự nhiên như người chơi thật; tự động tắt khi đang lao thẳng vào nhặt rương hoặc chạm tháp qua màn.
* **Thứ tự ưu tiên mục tiêu thông minh (Strict Target Hierarchy)**:
  1. **Tháp qua màn (Monolith / Obelisk)** — *Ưu tiên tuyệt đối số 1*:
     * Nhận diện đa tỷ lệ kết hợp bộ lọc **Vết nứt Rune đỏ thẫm nguyên bản (`Pure Crimson`: `R >= 80, G <= 75, B <= 75`)** và **Thân đá xám trung tính (`|B - G| <= 6`)**.
     * Hoạt động chính xác trên mọi màu nền bản đồ (kể cả map đất đỏ/nâu như *Depths*, *Magma*) và nhận diện được ngay cả khi tháp mới chỉ ló một nửa thân ở sát mép màn hình.
     * **Thuật toán Quét xoắn ốc hình hộp nở rộng (Expanding Box Spiral Sweep)**: Khi đã dẹp xong đợt quái (Wave Cleared) mà chưa thấy tháp trên màn hình, bot tự động ngừng đi vòng tròn nhỏ và chuyển sang chạy tuần tra mở rộng theo 4 hướng Đông – Tây – Nam – Bắc (2.6s → 5.0s → 7.4s → 9.8s...) để mở rộng tầm nhìn camera đi tìm tháp.
  2. **Rương cổ vật (Treasure Chest / Reliquary / Opulence)**:
     * Nhận diện cả rương nằm trên mặt đất lẫn biểu tượng mũi tên chỉ hướng rương ở rìa màn hình.
  3. **Hạt kinh nghiệm & Vàng (Mana Orbs & Gold)**:
     * Phân loại hạt theo màu sắc/giá trị (Xanh lam, Vàng, Tím/Hồng) và chỉ lao tới nhặt khi hành lang di chuyển an toàn.

### 4. Tự động chọn Kỹ năng, Nhánh Lv.7 & Phép kết hợp (Magic Combination)
* **Nhận diện bài bằng Windows OCR (`winocr`) + Template Matching**:
  * Tự động đọc tên kỹ năng ở màn hình lên cấp (`Learn`), màn hình cường hóa (`Strengthen Magic`), màn hình chọn nhánh tiến hóa cấp 7 (`Select Attribute`), và màn hình ghép phép (`Combination` nút sao đỏ).
* **Tối ưu hóa nhánh cấp 7 (Mastery Level 7) phục vụ ghép phép**:
  * **Spirit Lv.7** → Tự động chọn **`Magic Blade`** + **Electric Shock Lv.7 (`Chain Lightning`)** $\rightarrow$ Ghép thành **`Telekinetic Sword`**.
  * **Cyclone Lv.7** → Tự động chọn **`Void`** + **Satellite Lv.7 (`Antigravity`)** $\rightarrow$ Ghép thành **`Black Hole`**.
  * Hỗ trợ đầy đủ cơ sở dữ liệu tri thức trong [`game_knowledge.json`](game_knowledge.json) cho các phép kết hợp mạnh nhất: *Superconductivity, Current Overload, Vortex, Neutron Generation, Perpetual Engine, Overmind, Demon Equation, Frenzy, Prism Spree...*
* **Đánh giá & Chọn Cổ vật trong Rương (Artifact Evaluator)**:
  * Tự động duyệt qua từng cổ vật trong rương thường (3 món) và rương Opulence (tối đa 6 món).
  * Chấm điểm tự động dựa trên bậc hiếm (**Legendary > Special > Synergy > Rare > Common**) và chỉ số ưu tiên (**Giảm hồi chiêu `Cooldown`, Chí mạng `Crit Rate / Crit Damage`, Sát thương phép**), sau đó chọn cổ vật điểm cao nhất và bấm **Obtain**.

### 5. Tự động hóa vòng đời trận đấu & Tắt mọi loại Quảng cáo
* **Vòng lặp tự động khép kín 100%**:
  * Sảnh chính (Đọc số Vàng & Gem hiện có) $\rightarrow$ Chọn nhân vật (**Summoner**) $\rightarrow$ **Selected** $\rightarrow$ **Enter Area** $\rightarrow$ **Start Game** $\rightarrow$ Chiến đấu $\rightarrow$ Khi kết thúc trận đọc thời gian sống sót & số mạng hạ gục $\rightarrow$ Bấm **Confirm / OK** $\rightarrow$ Tự quay lại sảnh và bắt đầu ván mới.
  * Tự động nhận diện popup **Restore Gold** (khôi phục vàng sau khi văng game) và bấm **Confirm**.
* **Hệ thống đóng quảng cáo đa tầng (Multi-Layer Ad Dismissal)**:
  * **Màn hình "No Ads - Tap to Continue"**: Tự động nhận diện màn hình đen khi hết video quảng cáo và bấm *"Tap to Continue"* ngay lập tức.
  * **Quét nút chữ đa ngôn ngữ (Full Frame + 1.5x Zoom Top/Bottom Action Bars)**: Nhận diện chính xác các nút `"Đóng"`, `"Đóng | ✔"`, `"Close"`, `"Skip"`, `"Skip reward"`, `"Bỏ qua"`, `"Chạm để bỏ qua"`, `"Thoát video"`, `"No thanks"`, `"Không cảm ơn"`, `"Hủy"`, `"Cancel"`, `"Quay lại"`, `"Back"`, `"Claim"`, `"Nhận thưởng"`, kể cả nút xám mờ ở góc dưới bên trái hoặc nút có kèm icon.
  * **Xử lý hộp thoại xác nhận (Confirmation Dialogs)**: Khi gặp bảng hỏi *"Đóng quảng cáo?"* hoặc *"Đóng video?"*, bot tự động bỏ qua dòng tiêu đề câu hỏi (có dấu `?`) và bấm chính xác vào nút xác nhận **`ĐÓNG`** / **`ĐÓNG VIDEO`**.
  * **Nhận diện biểu tượng góc**: Quét ký tự đơn (`X`, `✕`, `✖`, `×`, `>`, `>>`, `<`, `<<`) và khớp mẫu biểu tượng nút X tròn, chữ thập, mũi tên tua nhanh ở cả chế độ sáng trên nền tối và tối trên nền sáng (có cơ chế bảo vệ chống bấm nhầm nút X đóng cửa sổ LDPlayer trên thanh tiêu đề Windows).
  * **Dự phòng phím Back Android**: Nếu màn hình vẫn là quảng cáo sau 2 giây mà ẩn nút đóng, bot tự động gửi phím `Back` (`ESC`) để thoát.

### 6. Bộ não Học máy Thích ứng (Adaptive AI) & Học từ Chuyên gia
* **Học tăng cường sau mỗi trận ([`learning_engine.py`](learning_engine.py))**:
  * Sau mỗi ván đấu, `AdaptiveLearner` đối chiếu thời gian sống sót thực tế với thời gian sống trung bình lịch sử (`average_survival_sec`).
  * Những bộ kỹ năng (`skill_weights`) và cặp phối hợp (`synergy_weights`) giúp sống lâu hơn trung bình sẽ được cộng điểm thưởng vào [`data/learned_policy.json`](data/learned_policy.json), giúp bot ngày càng ưu tiên các build mạnh hơn ở những ván tiếp theo.
* **Chế độ Ghi hình Chuyên gia ([`record_human_play.py`](record_human_play.py) / [`record_human.bat`](record_human.bat))**:
  * Cho phép bạn tự tay chơi 100%, trong khi bot chạy ngầm quan sát và ghi lại mọi lựa chọn kỹ năng, nhánh Lv.7, cổ vật và thời gian sống sót của bạn để nạp trực tiếp kinh nghiệm chuyên gia vào não AI.
* **Ghi dữ liệu huấn luyện có cấu trúc ([`data_recorder.py`](data_recorder.py))**:
  * Lưu ảnh chụp màn hình và thông tin quyết định từng bước vào `data/runs/<run_id>/decisions.jsonl` (tự động dọn dẹp và giữ lại tối đa 50 ván gần nhất).

---

## 📂 Cấu trúc thư mục dự án

```text
d:\magic-survival-autofarm\
├── botcore.py                 # Trái tim xử lý thị giác (OpenCV, OCR), nhận diện UI/Tháp/Rương/Quái & thuật toán điều hướng
├── bot_cli.py                 # Chế độ chạy Terminal CLI tự động hoàn toàn (hỗ trợ cả ADB và Desktop)
├── main.py                    # Giao diện người dùng Tkinter GUI, xem trước trực tiếp & quản lý quy tắc
├── game_actions.py            # Các thao tác tương tác game cấp cao có khóa bảo vệ trạng thái (GuardedController)
├── adb_controller.py          # Giao tiếp ADB với giả lập LDPlayer (chụp ảnh screencap, tap, swipe ngầm)
├── learning_engine.py         # Bộ máy AI học thích ứng trọng số kỹ năng & synergy qua từng ván đấu
├── data_recorder.py           # Ghi nhật ký quyết định (JSONL + ảnh) theo từng ván chơi
├── record_human_play.py       # Công cụ quan sát người chơi thật để dạy chiến thuật cho AI
├── storage.py                 # Ghi file JSON nguyên tử (atomic write) chống hỏng dữ liệu khi tắt đột ngột
├── config.json                # Cấu hình trung tâm của toàn bộ hệ thống
├── game_knowledge.json        # Cơ sở dữ liệu tri thức về kỹ năng, nhánh Lv.7, phép kết hợp (Combination) & cổ vật
├── rules.json                 # Các quy tắc nhận diện hình ảnh tùy chỉnh do người dùng dạy
├── requirements.txt           # Danh sách thư viện Python cần thiết
├── setup.bat                  # Script khởi tạo môi trường ảo (.venv) và cài đặt thư viện
├── chay_bot_ldplayer.bat      # Chạy nhanh bot ở Chế độ 1: LDPlayer (ADB)
├── chay_bot_google_play.bat   # Chạy nhanh bot ở Chế độ 2: Google Play Games PC
├── run_cli.bat                # Mở menu chọn chế độ chạy trên Terminal CLI
├── run.bat                    # Mở giao diện đồ họa Tkinter GUI
├── record_human.bat           # Chạy chế độ ghi hình học từ người chơi thật
├── assets/                    # Ảnh mẫu chuẩn (nhân vật, tháp monolith, rương, biểu tượng phép, nút quảng cáo...)
│   ├── characters/            # Mẫu biểu tượng nhân vật (summoner.png...)
│   └── chests/                # Mẫu các loại rương & mũi tên chỉ hướng rương
├── data/                      # Dữ liệu AI đã học và lịch sử các ván đấu
│   ├── learned_policy.json    # Trọng số kỹ năng & synergy do AI đúc kết
│   ├── learning_history.json  # Lịch sử chi tiết 100 ván đấu gần nhất
│   └── runs/                  # Ảnh chụp và log quyết định từng bước của 50 ván gần nhất
└── tests/                     # Hơn 230 bài kiểm thử tự động (Unit & Integration Tests)
```

---

## 🛠️ Yêu cầu hệ thống & Cài đặt

### Yêu cầu
* **Hệ điều hành**: Windows 10 hoặc Windows 11 (bắt buộc để sử dụng tính năng nhận diện chữ `winocr` tích hợp của Windows).
* **Ngôn ngữ**: Python 3.10 trở lên (khuyến nghị Python 3.11 hoặc 3.12).
* **Môi trường chạy game**:
  * **LDPlayer 9** (khuyến nghị bật *ADB Debugging* trong Cài đặt giả lập, độ phân giải dọc `900x1600` hoặc `1080x1920`), **HOẶC**
  * **Google Play Games PC**.

### Các bước cài đặt lần đầu
1. Mở thư mục dự án tại `D:\magic-survival-autofarm`.
2. Nhấp đúp vào **`setup.bat`** (hoặc chạy trong PowerShell) để tự động tạo môi trường ảo `.venv` và cài đặt các thư viện cần thiết:
   ```powershell
   cd D:\magic-survival-autofarm
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Đảm bảo Windows đã cài gói ngôn ngữ nhận diện chữ **English (United States)** trong *Windows Settings → Time & language → Language & region* để `winocr` hoạt động.

---

## 🚀 Hướng dẫn sử dụng

### Cách 1: Chạy bằng Terminal CLI (Khuyên dùng — Nhẹ và ổn định nhất)
* **Dành cho giả lập LDPlayer (ADB chạy ngầm)**:
  1. Mở LDPlayer và vào game **Magic Survival**.
  2. Kiểm tra đường dẫn `adb_path` trong [`config.json`](config.json) (mặc định: `"D:\\LDPlayer\\LDPlayer9\\adb.exe"`).
  3. Nhấp đúp file **`chay_bot_ldplayer.bat`** (hoặc chạy `python bot_cli.py 1`).
* **Dành cho Google Play Games PC**:
  1. Mở cửa sổ game Magic Survival trên màn hình (không thu nhỏ cửa sổ).
  2. Nhấp đúp file **`chay_bot_google_play.bat`** (hoặc chạy `python bot_cli.py 2`).
* **Dừng bot trên CLI**: Nhấn tổ hợp phím **`Ctrl + C`** tại cửa sổ Terminal, bot sẽ tự động nhả toàn bộ thao tác điều khiển ngay lập tức.

### Cách 2: Chạy bằng Giao diện đồ họa GUI
1. Nhấp đúp file **`run.bat`** (hoặc chạy `.\.venv\Scripts\python.exe main.py`).
2. Sử dụng các phím tắt toàn cục:

| Phím tắt | Chức năng |
| :---: | :--- |
| **F8** | Bắt đầu chạy bot / Tạm dừng bot |
| **F9** | Dừng khẩn cấp và nhả toàn bộ phím/chuột/cảm ứng ngay lập tức |
| **F10** | Dừng và chụp màn hình hiện tại để thêm quy tắc nhận diện mới |

### Cách 3: Tự tay chơi để dạy AI (Human Expert Recorder)
1. Mở game trên LDPlayer hoặc Google Play Games PC.
2. Nhấp đúp file **`record_human.bat`**.
3. Tự tay chơi một ván thật xuất sắc (ví dụ sống trên 20–45 phút). Công cụ sẽ âm thầm ghi lại thứ tự lên cấp phép, cách bạn chọn nhánh Lv.7, cách chọn rương và nạp thẳng trọng số ưu tiên vào [`data/learned_policy.json`](data/learned_policy.json).

---

## ⚙️ Cấu hình chi tiết (`config.json`)

Bạn có thể chỉnh sửa trực tiếp file [`config.json`](config.json) để tùy biến hành vi của bot:

| Tham số | Kiểu | Giá trị mặc định | Mô tả chi tiết |
| :--- | :---: | :---: | :--- |
| `window_title` | `string` | `"Magic Survival"` | Tên tiêu đề cửa sổ game khi dùng chế độ Desktop. |
| `control_mode` | `string` | `"adb"` | `"adb"` (điều khiển giả lập LDPlayer ngầm) hoặc `"desktop"` (cửa sổ PC). |
| `adb_path` | `string` | `"D:\\LDPlayer\\LDPlayer9\\adb.exe"` | Đường dẫn tới file `adb.exe` của giả lập Android. |
| `input_mode` | `string` | `"touch"` | `"touch"` (ADB), `"keyboard"` (phím WASD), hoặc `"mouse"` (kéo chuột). |
| `crop_left_px`, `crop_top_px`, `crop_right_px`, `crop_bottom_px` | `int` | `0` | Số pixel cắt bỏ ở 4 mép cửa sổ khi dùng chế độ Desktop (ví dụ bỏ thanh bên 65px của Google Play Games). |
| `player_position` | `[float, float]` | `[0.5, 0.5]` | Tọa độ chuẩn hóa `(x, y)` của nhân vật trên màn hình (chính giữa là `0.5, 0.5`). |
| `joystick_position` | `[float, float]` | `[0.5, 0.8]` | Tâm đặt ngón tay/chuột để kéo joystick. |
| `joystick_radius_px` | `int` | `180` | Bán kính kéo joystick tính bằng pixel. |
| `fps` | `int` | `30` | Tần suất vòng lặp quét tối đa mỗi giây. |
| `max_session_minutes` | `float` | `0` | Thời gian chạy tối đa (phút). Đặt `0` để chạy vô hạn. |
| `auto_levelup` | `bool` | `true` | Tự động chọn bài khi lên cấp, chọn nhánh Lv.7 và ghép phép Combination. |
| `auto_chest` | `bool` | `true` | Tự động đánh giá và nhận cổ vật khi mở rương. |
| `auto_close_ads` | `bool` | `true` | Tự động tắt quảng cáo, bấm *Tap to Continue* và thoát về sảnh. |
| `auto_restart` | `bool` | `true` | Tự động chọn nhân vật và vào ván mới khi kết thúc trận. |
| `character` | `string` | `"summoner"` | Tên nhân vật tự động chọn trước khi vào trận (`assets/characters/<name>.png`). |
| `game_map` | `string` | `"depth"` | Tên bản đồ đang cày (hỗ trợ hệ số thời gian thực tế cho map `depth`). |
| `enable_human_weave` | `bool` | `true` | Bật kỹ thuật lắc tay vi mô khi di chuyển né quái. |
| `early_priority_skills` | `object` | `{"electric_zone": {"target_level": 4, "max_player_level": 10}}` | Ép ưu tiên lấy kỹ năng bảo vệ vòng ngoài (như *Electric Zone* lên cấp 4) trong 10 cấp đầu tiên để trụ vững đầu trận. |
| `nearest_target_skills` | `list[str]` | `["telekinetic_sword"]` | Danh sách kỹ năng tự nhắm quái gần nhất cho phép bot chủ động áp sát nhặt đồ nếu chỉ có quái đơn lẻ. |
| `skill_priority` | `list[str]` | `[...]` | Danh sách thứ tự ưu tiên kỹ năng gốc của người dùng (kết hợp cùng điểm AI học được). |
| `prefer_freeze_traits` | `bool` | `true` | Ưu tiên các nhánh làm chậm/đóng băng (*Blizzard, Frost Nova, Tsunami*). |
| `prefer_crit_and_cooldown`| `bool` | `true` | Ưu tiên chọn cổ vật và thuộc tính giảm hồi chiêu & tăng chí mạng. |
| `record_gameplay_data` | `bool` | `true` | Ghi lại hình ảnh và quyết định mỗi ván vào thư mục `data/runs/`. |
| `max_data_runs` | `int` | `50` | Số lượng thư mục ván đấu tối đa lưu giữ trên ổ đĩa (tự động xóa ván cũ nhất). |

---

## 🧪 Kiểm thử tự động (Automated Testing)

Dự án đi kèm bộ **230+ bài kiểm thử (Unit Tests & Integration Tests)** bao phủ toàn bộ thuật toán thị giác, điều hướng, chọn phép, nhận diện tháp/rương, tắt quảng cáo và học máy.

Để chạy toàn bộ bộ kiểm thử:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Hoặc chạy riêng từng nhóm kiểm thử:
```powershell
# Kiểm thử nhận diện và tắt quảng cáo (Đóng, Skip, X, No Ads...)
.\.venv\Scripts\python.exe -m unittest tests.test_ad_close_text

# Kiểm thử nhận diện tháp Monolith, rương, né quái và chọn kỹ năng
.\.venv\Scripts\python.exe -m unittest tests.test_botcore

# Kiểm thử di chuyển nhặt đồ và lao vào tháp qua màn
.\.venv\Scripts\python.exe -m unittest tests.test_pickup_movement

# Kiểm thử bộ máy AI học thích ứng
.\.venv\Scripts\python.exe -m unittest tests.test_learning_engine
```

---

## 🔧 Xử lý sự cố thường gặp (Troubleshooting)

1. **Lỗi không kết nối được ADB trên LDPlayer**:
   * Mở **LDPlayer Settings (Cài đặt)** $\rightarrow$ **Other settings (Cài đặt khác)** $\rightarrow$ Bật **ADB debugging: Open local connection**.
   * Kiểm tra đường dẫn `adb_path` trong `config.json` đã trỏ đúng tới file `adb.exe` trong thư mục cài đặt LDPlayer chưa.
2. **OCR không đọc được chữ trên màn hình nâng cấp / quảng cáo**:
   * Đảm bảo Windows 10/11 đã cài đặt gói ngôn ngữ **English (US)** có hỗ trợ *Optical Character Recognition (OCR)*.
   * Không thu nhỏ độ phân giải giả lập xuống quá thấp (khuyến nghị chiều rộng từ `540px` đến `1080px`).
3. **Chế độ Google Play Games PC không nhận phím WASD**:
   * Nhấn `Shift + Tab` trong Google Play Games để mở *Controls Editor*, đặt biểu tượng Joystick vào giữa vùng điều khiển và gán phím `W/A/S/D`, hoặc chuyển sang chế độ LDPlayer ADB để ổn định hơn.
   * Đảm bảo cửa sổ game không bị thu nhỏ (Minimize) hoặc bị che khuất bởi cửa sổ khác khi dùng chế độ Desktop.

---

## ⚠️ Lưu ý & Miễn trừ trách nhiệm

* Công cụ này được phát triển cho mục đích nghiên cứu **Thị giác máy tính (Computer Vision)**, **Tự động hóa giao diện (UI Automation)** và **Học tăng cường thích ứng (Adaptive Reinforcement Learning)**.
* Không dạy các quy tắc tùy chỉnh (`rules.json`) bấm vào các nút giao dịch cửa hàng bằng tiền thật.
* Người dùng tự chịu trách nhiệm tuân thủ điều khoản dịch vụ của trò chơi khi sử dụng công cụ tự động hóa.
