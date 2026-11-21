# Magic Survival AutoFarm

Bot tự động chơi game **Magic Survival** bằng thị giác máy tính (OpenCV + Windows OCR) và điều khiển ngoại vi/ADB. Không đụng bộ nhớ game, không sửa gói tin.

- **LDPlayer (ADB, khuyên dùng)**: chạy ngầm, không chiếm chuột/bàn phím.
- **Google Play Games PC**: chụp cửa sổ bằng `mss`, điều khiển bằng WASD/chuột.
- Có **AI học thích ứng**: tự điều chỉnh điểm ưu tiên kỹ năng sau mỗi ván dựa trên thời gian sống.

## Cài đặt & chạy

```powershell
setup.bat                      # tạo .venv + cài requirements.txt
chay_bot_ldplayer.bat          # CLI + LDPlayer, tự restart khi lỗi (giáo án mặc định: vortex)
chay_bot_aura_blade.bat        # CLI + giáo án Aura Blade (DEM) - đang thử nghiệm
chay_bot_google_play.bat       # CLI + Google Play Games PC
run.bat                        # GUI Tkinter (main.py)
run_cli.bat [tham số]          # CLI tuỳ chọn tham số
test_ldplayer.bat              # kiểm tra luồng ADB với LDPlayer
record_human.bat               # ghi lại ván người chơi để AI học
```

Yêu cầu: Windows 10/11 (có gói OCR English-US), Python 3.11, LDPlayer bật *ADB debugging: Open local connection*, `adb_path` trong `config.json` trỏ đúng `adb.exe`.

### Tham số `bot_cli.py`

| Tham số | Ý nghĩa |
|---|---|
| `1` / `ld` | LDPlayer (ADB) |
| `2` / `google` / `pc` | Google Play Games PC |
| `--build aura_blade` / `--aura` | Giáo án Aura Blade – DEM |
| `--build vortex` / `--classic` | Giáo án Vortex/Black Hole (mặc định) |
| `--runs N` | Số ván tối đa (0 = vô hạn) |
| `--hibernate` | Hibernate máy khi hết giới hạn phiên (`max_session_minutes`) |

Ví dụ: `python bot_cli.py 1 --build aura_blade --runs 5`

## Cấu trúc project

| File / thư mục | Vai trò |
|---|---|
| [bot_cli.py](bot_cli.py) | Vòng lặp chính chế độ terminal: nhận diện màn hình, chọn thẻ, chạy ván, tổng kết, hibernate |
| [main.py](main.py) | GUI Tkinter (preview, chỉnh config, dạy quy tắc bằng chuột F8/F9/F10) |
| [botcore.py](botcore.py) | Lõi thị giác + chính sách: nhận diện thẻ/kỹ năng (OCR + template), né quái/vùng tối, tìm tháp & rương, `BUILD_PRESETS`, chấm điểm thẻ |
| [game_actions.py](game_actions.py) | Thao tác menu dùng chung: chọn nhân vật/map, bắt đầu ván, đóng quảng cáo, nhận thưởng |
| [adb_controller.py](adb_controller.py) | Điều khiển giả lập qua ADB (screencap, tap, swipe joystick) |
| [learning_engine.py](learning_engine.py) | `AdaptiveLearner`: cập nhật `skill_weights` / `synergy_weights` sau mỗi ván |
| [data_recorder.py](data_recorder.py) | Ghi quyết định + ảnh từng ván vào `data/runs/` (tự xoay vòng `max_data_runs`) |
| [record_human_play.py](record_human_play.py) | Quan sát người chơi thật và nạp lựa chọn vào AI |
| [storage.py](storage.py) | Ghi JSON nguyên tử (không hỏng file khi tắt ngang) |
| [game_knowledge.json](game_knowledge.json) | Cơ sở tri thức: 181 cổ vật, **60 phép kết hợp** (kèm trait nguyên liệu), **35 synergy cổ vật**, **25 Subject**, công thức chỉ số (ATK × Amplify × All Magic Damage × Crit; CDR/Damage Reduction nhân dồn), nguồn nhận cổ vật (nguồn: wiki Magic Survival) |
| [knowledge.py](knowledge.py) | Truy cập tri thức: tra fusion/Subject, nhận diện nhóm chỉ số, theo dõi cổ vật đã nhặt trong ván và cộng điểm khi cổ vật giúp hoàn thành synergy (đủ bộ +2500, mỗi mảnh đã có +400) |
| [config.json](config.json) | Cấu hình chạy (xem bên dưới) |
| [rules.json](rules.json) / `rules/` | Quy tắc bấm tuỳ chỉnh do người dùng dạy (GUI) |
| `assets/` | Ảnh mẫu nhận diện (nút, tháp, rương, nhân vật, kỹ năng) |
| `data/` | `learned_policy.json`, `learning_history.json` (giữ lại), `runs/` (ghi hình, bị git bỏ qua) |
| `scripts/` | `inspect_captures.py` (phân loại `captures/`), `test_ldplayer_stream.py` |
| `tests/` | 231 unit/integration test |

## Cơ chế hoạt động

**Thứ tự ưu tiên mục tiêu khi chiến đấu:** Tháp qua màn (Monolith) → Rương cổ vật → Hạt kinh nghiệm. Né quái bằng distance transform + ray-casting + quán tính hướng; "lắc tay" (human weave) để gom quái, tự tắt khi lao vào tháp/rương. Hết quái mà chưa thấy tháp thì quét xoắn ốc mở rộng.

**Chọn thẻ khi lên cấp** (`choose_best_artifact_or_card`):
1. Kỹ năng trong `early_priority_skills` (mặc định `electric_zone` lên Lv4 trong 10 cấp đầu cho dễ sống).
2. Nhánh tiến hóa Lv.7 / phép kết hợp (dấu ★) / passive đặc biệt mạnh.
3. Kỹ năng trong `skill_priority`: mỗi bậc 25 điểm, cộng bonus học được `clamp(bonus*0.5, -12, 12)`.
4. Cổ vật/passive chấm theo bậc hiếm, crit, cooldown, synergy với kỹ năng đang có.

Hiện **không có epsilon-greedy**: giáo án là chính, AI chỉ tinh chỉnh ±12 điểm.

**AI học:** sau mỗi ván so thời gian sống với trung bình động. Hơn trung bình/ván người chơi ≥ 20 phút → thưởng (lr 0.20); thấp hơn → phạt nhẹ (lr 0.06). Trọng số kỹ năng trong [-1.5, 8], synergy trong [-1, 5] (chi tiết ở mục "Hệ thống AI học").

## Hệ thống AI học (chi tiết)

Hai tầng: (1) **thị giác & điều khiển thời gian thực** (`botcore.py`, `game_actions.py`, `bot_cli.py`, `main.py`); (2) **học thích ứng & ghi tri thức** (`learning_engine.py`, `data_recorder.py`, `record_human_play.py`).

**Ghi dữ liệu** (`DataRecorder`): mỗi quyết định lưu ảnh `step_XXXX_<screen>.png` + dòng trong `data/runs/<run_id>/decisions.jsonl`; cuối ván ghi `summary.json` (thời gian sống, quái, vàng, kỹ năng/cấp). Tự xoá ván cũ nhất khi vượt `max_data_runs` (mặc định 50).

**Học từ người chơi** (`record_human.bat`): quan sát người chơi thật, phát hiện lúc chọn thẻ/nhánh Lv.7/Combination/mở rương, rồi nạp lựa chọn vào trọng số khi hết ván. Ván người ≥ 20 phút luôn được thưởng và **không** kéo lệch mốc trung bình của bot.

**Hàm thưởng** (`AdaptiveLearner.evaluate_and_learn_run`, lưu nguyên tử qua `storage.write_json_atomic`):
- `diff = thời gian sống − average_survival_sec` (EMA, tối đa 12 mẫu).
- Ván ≥ 20 phút hoặc `diff ≥ 0`: `reward = clamp(diff / max(0.7·avg, 120), 0..1.5)` (ván người tối thiểu 1.0), `lr = 0.20`.
- Ván thấp hơn TB: `reward = max(-0.30, diff / max(2.5·avg, 360))`, `lr = 0.06` (phạt chậm để không phá build tốt khi chết do di chuyển).
- **Chia công theo "lợi thế" (v2):** kỹ năng dùng trong ván: `+= lr·reward·2·(1 − p)`, kỹ năng đã biết nhưng không dùng: `+= lr·reward·2·(−p)·0.5`, với `p` = tần suất dùng thường lệ (EMA, `skill_usage`). Cặp: `+= lr·reward·1.5·(1 − p_a·p_b)`. Kỹ năng ván nào cũng có (Spirit) nhận ~0 thay vì leo lên trần 8.0 như luật v1 (từng làm 23/43 kỹ năng chạm trần). Mỗi ván mọi trọng số co về 0 thêm 1% để điểm cũ phai dần.
- Policy cũ (v1) tự được dựng lại từ `learning_history.json` khi nạp lần đầu; bản gốc lưu ở `data/learned_policy.v1.bak.json`.
- Giới hạn: `skill_weights` ∈ [-1.5, 8] (kỹ năng lõi sàn 0), `synergy_weights` ∈ [-1, 5].
- Chống học trùng theo `run_id`; chỉ học khi có thời gian sống hợp lệ đọc từ HUD/màn kết quả.

**Dữ liệu `data/`:** `learned_policy.json` (`total_runs_analyzed`, `average_survival_sec`, `skill_weights`, `synergy_weights`, `skill_usage`, `movement_policy`, `recent_run_ids`, `version`), `learning_history.json` (100 ván gần nhất: thời gian, quái, reward, kỹ năng, delta), `runs/<run_id>/`.

**Tri thức gốc** (`game_knowledge.json`): kỹ năng, nhánh Lv.7, công thức Magic Combination (Telekinetic Sword = Spirit + Electric Shock; Black Hole = Cyclone + Satellite; Superconductivity, Current Overload, Vortex, Overmind...), điểm cổ vật theo bậc hiếm và chỉ số (Cooldown, Crit...).

**Giới hạn hiện tại (đánh giá thẳng):** tín hiệu học chỉ là thời gian sống (nhiễu cao, khó quy cho từng kỹ năng); mức chỉnh tối đa ±12 điểm so với giáo án; chưa có thống kê so sánh giữa các build. Hiệu quả thực chủ yếu đến từ giáo án viết tay và độ chính xác của vision. Cần tích luỹ nhiều ván để so `vortex` với `aura_blade` bằng số liệu.

**Log khi chạy:** mỗi ván in khối tổng kết (thời gian sống, reward AI, vàng/gem/quái, kỹ năng và delta); khi dừng bot in thêm **Tổng kết phiên** (số ván, sống TB/tốt nhất/tệ nhất, tổng vàng/gem/quái).

## Giáo án (build)

Chọn bằng `build_mode` trong `config.json` hoặc `--build`:

- **`vortex`** (mặc định): Cyclone + Satellite → Vortex / Black Hole, kèm Blizzard/Frost Nova, Shield, Cloaking.
- **`aura_blade`** (thử nghiệm, tách riêng): Summoner; Spirit + Electric Shock → Telekinetic Sword (Aura Blade) → Magic Circle + Intelligence Lv5 → Overmind → max toàn bộ passive để mở Deus Ex Machina. Mục tiêu crit ≥ 80%, nhiều kiếm, cooldown thấp.

Thêm giáo án mới: khai báo trong `BUILD_PRESETS` ở `botcore.py` (`skill_priority`, `early_priority_skills`, `nearest_target_skills`, ...).

## Các khoá `config.json` chính

| Khoá | Ý nghĩa |
|---|---|
| `control_mode` | `adb` hoặc `desktop` |
| `adb_path` | Đường dẫn `adb.exe` của LDPlayer |
| `character`, `game_map` | Nhân vật, bản đồ khi bắt đầu ván (`summoner`, `depth`) |
| `build_mode`, `skill_priority`, `early_priority_skills`, `nearest_target_skills` | Giáo án |
| `prefer_crit_and_cooldown`, `prefer_freeze_traits` | Thiên hướng chấm cổ vật |
| `auto_levelup`, `auto_chest`, `auto_close_ads`, `auto_restart` | Tự động hoá |
| `enable_human_weave` | Bật lắc tay |
| `max_session_minutes`, `auto_hibernate`, `max_matches` | Giới hạn phiên (270 phút), hibernate, số ván (0 = vô hạn) |
| `record_gameplay_data`, `max_data_runs` | Ghi dữ liệu ván |
| `auto_clear_terminal`, `clear_terminal_interval_sec` | Dọn terminal định kỳ |

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Sự cố thường gặp

- **Không kết nối ADB**: bật ADB local connection trong LDPlayer; kiểm tra `adb_path`.
- **OCR không đọc được**: cài gói ngôn ngữ English (US) có OCR; độ rộng giả lập 540–1080px.
- **Google Play Games không nhận WASD**: `Shift+Tab` → Controls Editor gán joystick W/A/S/D, hoặc dùng LDPlayer; đừng minimize cửa sổ game.

## Lưu ý

Dự án phục vụ nghiên cứu Computer Vision / UI automation. Đừng dạy quy tắc bấm vào nút mua bằng tiền thật. Người dùng tự chịu trách nhiệm về điều khoản dịch vụ của game.
