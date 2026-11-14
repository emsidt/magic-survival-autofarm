# 🧠 Kế hoạch & Kiến trúc Hệ thống AI Học từ Dữ liệu Chơi

Tài liệu này mô tả kiến trúc, lộ trình triển khai và trạng thái hoàn thiện của hệ thống **AI Học máy Thích ứng (Adaptive AI Learning)** tích hợp trong **Magic Survival AutoFarm**.

---

## 1. Mục tiêu và Phạm vi Kiến trúc

Hệ thống kết hợp hai tầng xử lý:
1. **Tầng Thị giác & Điều khiển Thời gian thực ([`botcore.py`](botcore.py), [`game_actions.py`](game_actions.py), [`bot_cli.py`](bot_cli.py), [`main.py`](main.py))**:
   * Nhận diện trạng thái màn hình bằng OpenCV & Windows OCR (`winocr`).
   * Điều hướng né quái, thoát vùng tối sát thương, ưu tiên lao vào **Tháp qua màn (Monolith)** $\rightarrow$ **Rương cổ vật (Chest)** $\rightarrow$ **Hạt kinh nghiệm (Mana Orbs)**.
2. **Tầng Học máy Thích ứng & Ghi nhận Tri thức ([`learning_engine.py`](learning_engine.py), [`data_recorder.py`](data_recorder.py), [`record_human_play.py`](record_human_play.py))**:
   * Ghi nhận toàn bộ quyết định chọn kỹ năng, nhánh tiến hóa Lv.7, phép kết hợp (Combination) và cổ vật trong từng ván đấu.
   * Tự động đánh giá hiệu quả sinh tồn sau mỗi ván và cập nhật bảng trọng số kỹ năng (`skill_weights`) cũng như điểm cộng hưởng cặp kỹ năng (`synergy_weights`).

---

## 2. Trạng thái Triển khai theo Giai đoạn

### Bước 0 — Dọn dẹp và Chuẩn hóa Dữ liệu Ảnh Mẫu
- [x] Chuyển toàn bộ ảnh chụp thử nghiệm vào `captures/` và phân loại tự động qua [`scripts/inspect_captures.py`](scripts/inspect_captures.py) (lưu tại `captures/manifest.json`).
- [x] Chuẩn hóa thư mục `assets/` cho toàn bộ mẫu nhận diện cốt lõi (nhân vật, tháp Monolith, rương thường, rương Reliquary, rương Opulence, mũi tên chỉ hướng, nút đóng quảng cáo).
- [x] Tách biệt thư mục `rules/` cho các quy tắc tùy chỉnh của người dùng.

### Bước 1 — Chốt Bài toán, Tri thức Gốc & Công thức Phép Kết hợp
- [x] Xây dựng cơ sở dữ liệu tri thức toàn diện trong [`game_knowledge.json`](game_knowledge.json) bao gồm:
  * Toàn bộ kỹ năng chủ động, kỹ năng bị động và nhánh tiến hóa cấp 7 (Mastery Level 7).
  * Công thức ghép phép (**Magic Combination**):
    * **Telekinetic Sword** = `Spirit (Magic Blade)` + `Electric Shock (Chain Lightning)`
    * **Black Hole** = `Cyclone (Void)` + `Satellite (Antigravity)`
    * Cùng các công thức cấp cao: *Superconductivity, Current Overload, Vortex, Neutron Generation, Perpetual Engine, Overmind, Demon Equation, Frenzy, Prism Spree...*
  * Hệ thống chấm điểm cổ vật (**Artifact Scoring**) theo bậc hiếm (*Legendary, Special, Synergy, Rare, Common*) và từ khóa chỉ số (*Cooldown, Crit Rate, Crit Dmg, All Magic Damage...*).

### Bước 2 — Thu thập Dữ liệu có Cấu trúc ([`data_recorder.py`](data_recorder.py))
- [x] Triển khai `DataRecorder` ghi log tự động theo từng quyết định trong trận:
  * Lưu ảnh chụp màn hình tại thời điểm quyết định (`step_XXXX_<screen_type>.png`).
  * Ghi thông tin chi tiết vào `data/runs/<run_id>/decisions.jsonl` (bước, thời gian, loại màn hình, kỹ năng chọn, độ tin cậy, metadata).
  * Tổng kết cuối trận vào `data/runs/<run_id>/summary.json` (thời gian sống, số kill, vàng nhận được, danh sách kỹ năng và cấp độ đạt được).
- [x] Cơ chế tự động xoay vòng dữ liệu (`max_data_runs: 50`), tự động xóa các ván cũ nhất để không làm đầy ổ cứng.

### Bước 3 — Học từ Chuyên gia Con người ([`record_human_play.py`](record_human_play.py))
- [x] Xây dựng công cụ **Human Expert Demonstration Recorder** ([`record_human.bat`](record_human.bat)):
  * Chạy ngầm quan sát người chơi thật điều khiển 100%.
  * Tự động phát hiện thời điểm người chơi mở bảng chọn phép, chọn nhánh Lv.7, ghép Combination hoặc mở rương.
  * Xác định chính xác lá bài người chơi vừa chọn và nạp trực tiếp trọng số ưu tiên cao vào não AI khi kết thúc ván chơi.

### Bước 4 — Bộ máy Học Tăng cường Thích ứng ([`learning_engine.py`](learning_engine.py))
- [x] Triển khai lớp `AdaptiveLearner` quản lý chính sách học tại [`data/learned_policy.json`](data/learned_policy.json) và lịch sử tại [`data/learning_history.json`](data/learning_history.json).
- [x] **Hàm thưởng sinh tồn (Survival Reward Function)**:
  * So sánh thời gian sống sót thực tế của ván đấu (`survival_seconds`) với mức trung bình lịch sử (`average_survival_sec`).
  * **Ván vượt mốc trung bình hoặc ván chuyên gia ($\ge 20$ phút)**: Cộng điểm thưởng dương cho các kỹ năng đã học (ưu tiên kỹ năng đạt cấp 7 và kỹ năng trụ cột) cùng toàn bộ các cặp kỹ năng phối hợp (`synergy_weights`).
  * **Ván dưới mức trung bình**: Điều chỉnh giảm nhẹ đối với các kỹ năng phụ, đồng thời bảo vệ các kỹ năng cốt lõi (Core Skills) không bị tụt điểm oan khi chết sớm do địa hình.
- [x] Lưu trữ an toàn bằng cơ chế ghi nguyên tử ([`storage.py`](storage.py) - `write_json_atomic`) đảm bảo không bao giờ hỏng file JSON ngay cả khi mất điện hay tắt ngang.

### Bước 5 — Bộ Kiểm thử Offline & Chống Hồi quy (`tests/`)
- [x] Xây dựng hơn **230 bài kiểm thử tự động** kiểm tra độc lập từng thành phần:
  * [`tests/test_botcore.py`](tests/test_botcore.py): Kiểm thử nhận diện màn hình, chọn kỹ năng, nhánh Lv.7, nhận diện tháp Monolith trên mọi màu nền map và góc khuất mép màn hình.
  * [`tests/test_pickup_movement.py`](tests/test_pickup_movement.py) & [`tests/test_combat_flow.py`](tests/test_combat_flow.py): Kiểm thử điều hướng né quái, nhặt rương, ưu tiên lao thẳng vào tháp và quét xoắn ốc mở rộng khi sạch quái.
  * [`tests/test_ad_close_text.py`](tests/test_ad_close_text.py): Kiểm thử nhận diện mọi biến thể nút đóng quảng cáo (Đóng, Đóng | ✔, Skip, Bỏ qua, Hủy, X, mũi tên tua nhanh, No Ads - Tap to Continue).
  * [`tests/test_learning_engine.py`](tests/test_learning_engine.py) & [`tests/test_data_recorder.py`](tests/test_data_recorder.py): Kiểm thử tính toàn vẹn của thuật toán học máy và bộ ghi dữ liệu.

---

## 3. Cấu trúc Dữ liệu Lưu trữ (`data/`)

* [`data/learned_policy.json`](data/learned_policy.json):
  * `total_runs_analyzed`: Tổng số ván đấu AI đã phân tích.
  * `average_survival_sec`: Thời gian sống trung bình động (EMA) tính bằng giây.
  * `skill_weights`: Điểm thưởng ưu tiên của từng kỹ năng (trong khoảng `[-5.0, +8.0]`).
  * `synergy_weights`: Điểm cộng hưởng giữa các cặp kỹ năng `"skill_a+skill_b"` (trong khoảng `[-2.5, +5.0]`).
* [`data/learning_history.json`](data/learning_history.json):
  * Lưu 100 bản ghi kết quả ván đấu gần nhất (mã ván, thời gian sống, số mạng hạ gục, phần thưởng AI, kỹ năng và cấp độ đạt được).
* `data/runs/<run_id>/`:
  * Chứa toàn bộ ảnh chụp từng bước quyết định và file `decisions.jsonl` + `summary.json` của 50 ván gần nhất.
