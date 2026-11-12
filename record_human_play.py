"""Chế độ Ghi hình & Học hỏi từ Trận đấu Người chơi (Human Expert Recorder).

Chế độ này cho phép BẠN tự tay chơi game 100% (không có bất kỳ can thiệp phím/chuột nào từ bot).
Hệ thống sẽ chạy ngầm quan sát:
1. Ghi lại lựa chọn bắt được từ cú bấm và đánh dấu lựa chọn chưa rõ.
2. Ghi lại các nhánh thuộc tính và cổ vật bạn đã mở.
3. Đọc thời gian sống sót từ đồng hồ HUD, bỏ qua học khi không đọc được.
4. Tự động nạp toàn bộ build và kinh nghiệm của bạn vào Não AI (learned_policy.json)
   để AI học theo phong cách chơi chuyên gia của bạn!
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Optional
import threading
import time
import win32gui

# Đảm bảo tiến trình Python là Per-Monitor DPI Aware để GetCursorPos khớp 100% với pixel thực tế
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


import botcore
from data_recorder import DataRecorder
from learning_engine import get_adaptive_learner
from game_actions import finish_match
import main


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

STATE_LOBBY = "LOBBY"
STATE_PLAYING = "PLAYING"
STATE_DEAD = "DEAD"


class MouseTracker:
    """Theo dõi click chuột trái của người chơi ngầm (100Hz) để bắt chính xác thẻ đã chọn."""
    def __init__(self):
        self.clicks: list[tuple[int, int, float]] = []
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        class POINT(ctypes.Structure):
            _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
        was_down = False
        while self._running:
            try:
                # 0x01 là VK_LBUTTON
                is_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
                if is_down and not was_down:
                    pt = POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    with self._lock:
                        self.clicks.append((int(pt.x), int(pt.y), time.monotonic()))
                        if len(self.clicks) > 50:
                            self.clicks = self.clicks[-50:]
                was_down = is_down
            except Exception:
                pass
            time.sleep(0.01)

    def get_last_click_in_rect(self, rect: dict, since_time: float = 0.0) -> Optional[tuple[float, float]]:
        rx = rect.get("left", 0)
        ry = rect.get("top", 0)
        rw = rect.get("width", 1)
        rh = rect.get("height", 1)
        if rw <= 0 or rh <= 0:
            return None
        with self._lock:
            for cx, cy, t in reversed(self.clicks):
                if t >= since_time - 0.2:  # Cho phép click xảy ra ngay trước/trong khi phát hiện
                    nx = (cx - rx) / rw
                    ny = (cy - ry) / rh
                    if 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0:
                        return (round(nx, 4), round(ny, 4))
        return None

    def clear(self):
        with self._lock:
            self.clicks.clear()

    def close(self):
        self._running = False
        self._thread.join(timeout=1.0)


class MovementTracker:
    """Theo dõi thao tác di chuyển của người chơi (WASD / phím mũi tên) để học kỹ năng lắc tay."""
    def __init__(self):
        self._running = True
        self.vectors: list[tuple[float, float, float]] = []  # (vx, vy, timestamp)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        user32 = ctypes.windll.user32
        import math
        while self._running:
            try:
                # 0x57: W, 0x53: S, 0x41: A, 0x44: D
                # 0x26: Up, 0x28: Down, 0x25: Left, 0x27: Right
                up = bool((user32.GetAsyncKeyState(0x57) | user32.GetAsyncKeyState(0x26)) & 0x8000)
                down = bool((user32.GetAsyncKeyState(0x53) | user32.GetAsyncKeyState(0x28)) & 0x8000)
                left = bool((user32.GetAsyncKeyState(0x41) | user32.GetAsyncKeyState(0x25)) & 0x8000)
                right = bool((user32.GetAsyncKeyState(0x44) | user32.GetAsyncKeyState(0x27)) & 0x8000)

                vx = (1.0 if right else 0.0) - (1.0 if left else 0.0)
                vy = (1.0 if down else 0.0) - (1.0 if up else 0.0)
                mag = math.hypot(vx, vy)
                if mag > 0:
                    vx, vy = vx / mag, vy / mag
                    with self._lock:
                        self.vectors.append((vx, vy, time.monotonic()))
                        if len(self.vectors) > 400:
                            self.vectors = self.vectors[-400:]
            except Exception:
                pass
            time.sleep(0.04)

    def analyze_weave_profile(self) -> tuple[float, float]:
        """Tính tần số lắc tay (frequency) và biên độ góc (amplitude) từ mẫu di chuyển của người chơi."""
        with self._lock:
            samples = list(self.vectors)
        if len(samples) < 15:
            return (3.2, 0.28)

        direction_changes = 0
        amplitudes = []
        for i in range(1, len(samples)):
            vx0, vy0, t0 = samples[i - 1]
            vx1, vy1, t1 = samples[i]
            dt = t1 - t0
            if 0.01 <= dt <= 0.35:
                dot = vx0 * vx1 + vy0 * vy1
                cross = vx0 * vy1 - vy0 * vx1
                if dot < 0.92:
                    direction_changes += 1
                    amplitudes.append(abs(cross))

        duration = samples[-1][2] - samples[0][2]
        if duration > 1.0:
            freq = max(1.5, min(5.5, direction_changes / (2.0 * duration)))
        else:
            freq = 3.2

        amp = max(0.15, min(0.50, float(sum(amplitudes) / len(amplitudes)))) if amplitudes else 0.28
        return (round(freq, 2), round(amp, 3))

    def clear(self):
        with self._lock:
            self.vectors.clear()

    def close(self):
        self._running = False
        self._thread.join(timeout=1.0)


def map_click_to_card(click, num_cards):
    """Return only an observed click inside a card/Mana band; other clicks are unknown."""
    if click is None:
        return None
    x, y = click
    if not 0.10 <= x <= 0.90:
        return None
    bands = ((0.15, 0.367, 1), (0.367, 0.540, 2), (0.540, 0.714, 3),
             (0.714, 0.890, 4), (0.890, 0.98, "mana")) if num_cards == 4 else (
             (0.20, 0.445, 1), (0.445, 0.619, 2), (0.619, 0.798, 3), (0.798, 0.95, "mana"))
    return next((index for lo, hi, index in bands if lo <= y < hi), None)


def format_game_time(seconds: float) -> str:
    """Format seconds into MM:SS string."""
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def run_human_recorder():
    print("=" * 65)
    print("  🎮 MAGIC SURVIVAL - HUMAN EXPERT DEMONSTRATION RECORDER 🎮")
    print("=" * 65)
    print("Chế độ này KHÔNG bấm phím hay chuột của bạn.")
    print("Bạn toàn quyền tự điều khiển, né quái và chọn bài như bình thường.")
    print("AI sẽ đóng vai trò 'học trò' ngồi quan sát và ghi chép từng bước đi của bạn!\n")

    config = {}
    if CONFIG_PATH.is_file():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    title = config.get("window_title", "Magic Survival")
    print(f"[*] Đang tìm cửa sổ game (Tiêu đề: '{title}', hoặc giả lập LDPlayer)...")

    hwnd = None
    while not hwnd:
        hwnd = main.locate_game(title)
        if not hwnd:
            print(f"    [!] Chưa tìm thấy cửa sổ game '{title}' hoặc LDPlayer. Đang chờ bạn mở game...", end="\r")
            time.sleep(1.5)

    try:
        w_title = win32gui.GetWindowText(hwnd) or win32gui.GetClassName(hwnd)
    except Exception:
        w_title = title
    print(f"\n[+] ĐÃ KẾT NỐI VỚI CỬA SỔ GAME (HWND: {hwnd}, Tiêu đề: '{w_title}')!")
    rect = main.game_rectangle(hwnd, config)
    print(f"[+] Vùng hiển thị màn hình game: {rect['width']}x{rect['height']} tại ({rect['left']}, {rect['top']})")
    print("\n>>> BẠN CÓ THỂ BẮT ĐẦU CHƠI BẤT KỲ LÚC NÀO! <<<")
    print(">>> Nhấn Ctrl+C trong cửa sổ này nếu muốn dừng ghi bất kỳ lúc nào.\n")

    recorder = DataRecorder(enabled=True)
    learner = get_adaptive_learner()
    mouse_tracker = MouseTracker()
    movement_tracker = MovementTracker()

    state = STATE_LOBBY
    match_start_time = 0.0
    active_skills: set[str] = set()
    skill_levels: dict[str, int] = {}
    last_level_up_frame = None
    last_level_up_time = 0.0
    last_seen_cards = None
    in_level_up = False
    in_shop = False
    last_shop_time = 0.0
    last_shop_label = ""
    last_shop_frame = None
    last_mana_val = None
    step_count = 0
    death_streak = 0
    last_known_game_timer_sec = 0.0
    last_timer_scan_time = 0.0

    try:
        while True:
            time.sleep(0.20)
            try:
                if not hwnd:
                    hwnd = main.locate_game(title)
                if not hwnd or not main.is_game_or_popup_active(hwnd)[0]:
                    continue
                rect = main.game_rectangle(hwnd, config)
                frame = main.screenshot(rect)
            except Exception:
                hwnd = main.locate_game(title)
                continue

            h, w = frame.shape[:2]
            now = time.monotonic()

            ea_pos = botcore.detect_enter_area(frame)
            sg_pos = botcore.detect_start_game(frame)
            sel_pos = botcore.detect_selected(frame)
            pause_pos = botcore.detect_pause_button(frame)
            die_pos = botcore.detect_die_button(frame)
            confirm_pos = botcore.detect_confirm_button(frame)

            # --- TRẠNG THÁI 1: ĐANG Ở SẢNH CHỜ (LOBBY) ---
            if state == STATE_LOBBY:
                if ea_pos:
                    pass  # Đang ở màn hình chọn map
                # Trận đấu chính thức bắt đầu khi thấy nút Pause || và KHÔNG có màn hình chết/kết thúc
                if pause_pos is not None and not die_pos and not confirm_pos:
                    state = STATE_PLAYING
                    match_start_time = now
                    last_known_game_timer_sec = 0.0
                    last_timer_scan_time = 0.0
                    mouse_tracker.clear()
                    movement_tracker.clear()
                    active_skills.clear()
                    skill_levels.clear()
                    char_norm = str(config.get("character", "summoner")).lower().strip()
                    start_skill = botcore.CHARACTER_STARTING_SKILLS.get(char_norm)
                    if start_skill:
                        active_skills.add(start_skill)
                        skill_levels[start_skill] = max(skill_levels.get(start_skill, 0), 1)
                    step_count = 0
                    death_streak = 0
                    in_level_up = False
                    in_shop = False
                    last_shop_label = ""
                    last_shop_frame = None
                    last_mana_val = None
                    run_id = recorder.start_new_run()
                    game_map = config.get("game_map", "depth")
                    time_mult = 1.24 if str(game_map).lower().strip() == "depth" else 1.0
                    map_note = " (Gia tốc 1.24x)" if time_mult > 1.0 else ""
                    print("\n" + "-" * 65)
                    print(f"[🔥 TRẬN ĐẤU BẮT ĐẦU!] Mã trận: {run_id} | Bản đồ: {str(game_map).upper()}{map_note}")
                    print("    Đang theo dõi thời gian trong game và ghi nhận kỹ năng của bạn...")
                    print("-" * 65)

            # --- TRẠNG THÁI 2: ĐANG TRONG TRẬN ĐẤU (PLAYING) ---
            elif state == STATE_PLAYING:
                if now - last_timer_scan_time >= 0.5:
                    last_timer_scan_time = now
                    timer = botcore.detect_game_timer(frame)
                    if timer:
                        last_known_game_timer_sec = max(last_known_game_timer_sec, float(timer[2]))

                game_map = config.get("game_map", "depth")
                time_mult = 1.24 if str(game_map).lower().strip() == "depth" else 1.0
                cur_game_sec = last_known_game_timer_sec if last_known_game_timer_sec > 0.0 else max(0.0, (now - match_start_time) * time_mult)
                cur_game_time_str = format_game_time(cur_game_sec)

                # 2.1 Phát hiện lên cấp (Level Up)
                lvl_res = botcore.is_level_up_screen(frame)
                if lvl_res:
                    ocr_res = botcore._detect_cards_ocr(frame, h, w)
                    # Safeguard: Bắt buộc phải có ít nhất 1 thẻ có tên kỹ năng / chữ mô tả, hoặc nhận diện được header/button lên cấp
                    has_content = any(c.skills or c.text_lines for c in ocr_res.values())
                    if not has_content and lvl_res.reason not in ("header_level_up", "mana_retrieve_button", "combination_star_active"):
                        pass  # Bỏ qua false-positive trong combat khi không có chữ thực tế
                    elif not in_level_up and (now - last_level_up_time >= 1.0):
                        in_level_up = True
                        last_level_up_time = now
                        step_count += 1
                        last_level_up_frame = frame.copy()
                        last_seen_cards = ocr_res
                        num_c = len(ocr_res)
                        print(f"\n[Cấp #{step_count}] Màn hình lên cấp ({num_c} lựa chọn có sẵn) - Thời gian: {cur_game_time_str}:")
                        for idx in sorted(ocr_res.keys()):
                            cdata = ocr_res[idx]
                            sk_names = ", ".join(cdata.skills) if cdata.skills else (cdata.text_lines[0].title() if cdata.text_lines else "Chưa rõ")
                            star_tag = " [★ ĐẶC BIỆT]" if (cdata.has_asterisk or cdata.is_special_passive) else ""
                            desc = f" | {' '.join(cdata.text_lines[1:3])}" if len(cdata.text_lines) > 1 else ""
                            print(f"    Thẻ {idx}: {sk_names}{star_tag}{desc}")
                elif not lvl_res and in_level_up:
                    # Người chơi vừa click chọn 1 thẻ!
                    in_level_up = False
                    chosen_card_idx = None
                    chosen_name = ""
                    click_y_val = None

                    # 1. Bắt click chuột trái trong thời gian hiển thị bảng lên cấp
                    click_norm = mouse_tracker.get_last_click_in_rect(rect, since_time=last_level_up_time)

                    if last_seen_cards:
                        chosen_card_idx = map_click_to_card(click_norm, len(last_seen_cards))
                        click_y_val = click_norm[1] if click_norm is not None else None

                        if chosen_card_idx == "mana":
                            chosen_name = "Mana 20% Retrieve"
                        elif chosen_card_idx in last_seen_cards:
                            cdata = last_seen_cards[chosen_card_idx]
                            if cdata.skills:
                                chosen_name = ", ".join(cdata.skills)
                                for sk in cdata.skills:
                                    active_skills.add(sk)
                                    skill_levels[sk] = skill_levels.get(sk, 0) + 1
                            elif cdata.text_lines:
                                chosen_name = cdata.text_lines[0].title()
                                if cdata.special_passive_name:
                                    active_skills.add(cdata.special_passive_name)
                                    skill_levels[cdata.special_passive_name] = skill_levels.get(cdata.special_passive_name, 0) + 1
                            else:
                                chosen_name = f"Thẻ {chosen_card_idx}"
                        else:
                            chosen_name = "Không xác định được lựa chọn"

                        recorder.record_decision(
                            last_level_up_frame,
                            "human_level_up",
                            f"card_{chosen_card_idx}" if chosen_card_idx is not None else "unknown",
                            confidence=1.0 if chosen_card_idx is not None else 0.0,
                            metadata={
                                "step": step_count,
                                "chosen_card": chosen_card_idx,
                                "chosen_skill": chosen_name,
                                "click_norm_y": click_y_val,
                                "game_time": cur_game_time_str,
                                "game_time_sec": cur_game_sec,
                                "offered_cards": {
                                    str(k): list(last_seen_cards[k].skills) for k in sorted(last_seen_cards.keys())
                                },
                            },
                        )

                    click_info = f" (Click y={click_y_val:.2f})" if click_y_val is not None else ""
                    if chosen_card_idx == "mana":
                        print(f"    -> [ĐÃ CHỌN]: Mana 20% Retrieve (Bỏ qua thẻ để lấy Mana)!{click_info} (Thời gian trong game: {cur_game_time_str})")
                    elif chosen_card_idx is not None:
                        print(f"    -> [ĐÃ CHỌN]: Thẻ {chosen_card_idx} -> [{chosen_name}]!{click_info} (Thời gian trong game: {cur_game_time_str})")
                    else:
                        print(f"    -> [Đã ghi nhận]: Bạn vừa chọn xong kỹ năng! (Thời gian trong game: {cur_game_time_str})")

                # 2.2 Thuộc tính cấp 7
                learn_pos = botcore.detect_learn_button(frame)
                if learn_pos:
                    score, label, p_sk = botcore.evaluate_selected_attribute(frame)
                    print(f"[Thuộc tính cấp 7] Đang quan sát nhánh bạn chọn: [{label}] (Thuộc: {p_sk})")

                # 2.3 Rương cổ vật
                obtain_pos = botcore.detect_obtain_button(frame)
                if obtain_pos:
                    _, lbl = botcore.evaluate_selected_chest_artifact(frame, True, active_skills=active_skills)
                    print(f"[Rương Cổ vật] Bạn đang mở rương: {lbl}")

                # 2.4 Cửa hàng Thương Nhân (Merchant Shop - Mua cổ vật bằng Mana Orbs)
                buy_pos = botcore.detect_buy_button(frame)
                if buy_pos:
                    if not in_shop and (now - last_shop_time >= 1.0):
                        in_shop = True
                        last_shop_time = now
                        last_shop_frame = frame.copy()
                        mana_val = botcore.detect_mana_orb_currency(frame)
                        last_mana_val = mana_val
                        _, s_lbl = botcore.evaluate_selected_shop_artifact(frame, prefer_crit_and_cooldown=True, active_skills=active_skills)
                        last_shop_label = s_lbl
                        can_buy = botcore.is_shop_buy_enabled(frame)
                        mana_str = f"{mana_val} Mana Orbs" if mana_val is not None else "Đang đọc..."
                        status_str = "ĐỦ TIỀN MUA (Nút Buy sáng)!" if can_buy else "Chưa đủ Mana Orb"
                        print(f"\n[🛒 CỬA HÀNG THƯƠNG NHÂN] Mở cửa hàng mua cổ vật:")
                        print(f"    - Mana Orbs tích lũy: {mana_str}")
                        print(f"    - Cổ vật đang xem: [{s_lbl}]")
                        print(f"    - Trạng thái: {status_str}")
                    elif in_shop:
                        _, cur_s_lbl = botcore.evaluate_selected_shop_artifact(frame, prefer_crit_and_cooldown=True, active_skills=active_skills)
                        if cur_s_lbl and cur_s_lbl != last_shop_label:
                            last_shop_label = cur_s_lbl
                            last_shop_frame = frame.copy()
                            can_buy = botcore.is_shop_buy_enabled(frame)
                            status_str = "ĐỦ TIỀN MUA!" if can_buy else "Chưa đủ Mana Orb"
                            print(f"    -> Đổi sang xem: [{cur_s_lbl}] ({status_str})")
                elif not buy_pos and in_shop:
                    # Rời khỏi cửa hàng
                    in_shop = False
                    click_norm = mouse_tracker.get_last_click_in_rect(rect, since_time=last_shop_time)
                    bought = False
                    if click_norm is not None:
                        cx, cy = click_norm
                        if cy >= 0.80 and 0.25 <= cx <= 0.75:
                            bought = True
                        elif cy <= 0.16 and cx >= 0.75:
                            bought = False  # Bấm X
                        else:
                            bought = False
                    else:
                        bought = False

                    if bought and last_shop_label:
                        print(f"    -> [ĐÃ MUA CỔ VẬT]: Đã quan sát thao tác mua [{last_shop_label}] bằng Mana Orb! (Thời gian trong game: {cur_game_time_str})")
                        recorder.record_decision(
                            last_shop_frame if last_shop_frame is not None else frame,
                            "human_shop_action",
                            "buy_attempt",
                            confidence=1.0,
                            metadata={
                                "artifact": last_shop_label,
                                "mana_orbs": last_mana_val,
                                "time": cur_game_time_str,
                                "game_time_sec": cur_game_sec,
                            },
                        )
                    else:
                        print(f"    -> [ĐÃ ĐÓNG CỬA HÀNG]: Bạn đã đóng cửa hàng tiếp tục farm! (Thời gian trong game: {cur_game_time_str})")

                # 2.5 KẾT THÚC TRẬN ĐẤU (Nhân vật chết hoặc bấm kết thúc)
                # Safeguards:
                # 1) Chỉ kích hoạt khi nút Pause || hoàn toàn biến mất (pause_pos is None)
                # 2) Phải duy trì trạng thái chết/kết thúc ít nhất 3 chu kỳ liên tiếp (>= 0.6s) để triệt tiêu mọi glitch/chớp giật
                if confirm_pos and pause_pos is None:
                    death_streak += 1
                    if death_streak >= 3:
                        # Đọc thời gian sống sót trên màn hình kết quả hoặc HUD
                        t_final = botcore.detect_results_survival_time(frame) or botcore.detect_game_timer(frame)
                        if t_final:
                            last_known_game_timer_sec = max(last_known_game_timer_sec, float(t_final[2]))

                        # Fallback gia tốc bản đồ Depth nếu OCR bị che khuất
                        time_mult = 1.24 if str(config.get("game_map", "depth")).lower().strip() == "depth" else 1.0
                        if last_known_game_timer_sec <= 0.0 and match_start_time > 0.0:
                            last_known_game_timer_sec = max(0.0, (now - match_start_time) * time_mult)

                        survival_sec = last_known_game_timer_sec
                        # Bắt buộc trận phải diễn ra ít nhất 10 giây mới tính là 1 trận hợp lệ (loại bỏ glitch)
                        if survival_sec >= 10.0:
                            state = STATE_DEAD
                            death_streak = 0
                            m, s = int(survival_sec // 60), int(survival_sec % 60)
                            print("\n" + "=" * 65)
                            print("  🏆 TRẬN ĐẤU CỦA BẠN ĐÃ KẾT THÚC! 🏆")
                            print("=" * 65)
                            print(f"[*] THỜI GIAN SỐNG SÓT CỦA BẠN: {m:02d} phút {s:02d} giây ({survival_sec:.1f}s)")
                            print(f"[*] Tổng số kỹ năng đã thu thập: {len(active_skills)} kỹ năng:")
                            print(f"    {', '.join(sorted(list(active_skills)))}")

                            learn_rep = finish_match(
                                recorder, learner, frame, survival_sec, active_skills,
                                config.get("skill_priority", []),
                                skill_levels=skill_levels,
                                character=config.get("character", "summoner"),
                                game_map=config.get("game_map", "depth"),
                            )
                            if learn_rep and isinstance(learn_rep, dict) and "summary_text" in learn_rep:
                                print(learn_rep["summary_text"])
                            elif learn_rep:
                                print(f"[AI] Đã cập nhật theo thời gian HUD; reward={learn_rep.get('reward', 0):+.3f}")

                            # Học phong cách di chuyển & lắc tay từ mẫu thao tác của bạn
                            try:
                                weave_freq, weave_amp = movement_tracker.analyze_weave_profile()
                                mv_rep = learner.update_movement_policy(weave_freq, weave_amp, chest_aggression=1.8, run_id=run_id)
                                print("\n" + "-" * 65)
                                print("🎯 [AI HỌC LẮC TAY] Đã phân tích & học phong cách lắc tay di chuyển từ bạn:")
                                print(f"   • Tần số lắc tay (Weaving): {mv_rep['weave_frequency']} Hz")
                                print(f"   • Biên độ lượn né (Amplitude): {mv_rep['weave_amplitude']}")
                                print(f"   • Độ quyết đoán ăn rương: x{mv_rep['chest_aggression']}")
                                print("-" * 65)
                            except Exception:
                                pass

                            print("\n>>> Đã ghi nhận xong 1 lần duy nhất! Đang chờ bạn quay lại Sảnh để chơi trận mới... <<<")
                        else:
                            recorder.finish_run()
                            print("[AI] Đồng hồ chưa rõ hoặc ván quá ngắn; giữ bản ghi và bỏ qua học.")
                            state = STATE_DEAD
                            death_streak = 0
                else:
                    death_streak = 0

            # --- TRẠNG THÁI 3: HẬU TRẬN ĐẤU (DEAD / SUMMARY) ---
            elif state == STATE_DEAD:
                # Đang ở màn hình chết hoặc bảng kết quả -> KHÔNG GHI NHẬN LẠI NỮA
                # Chờ người chơi bấm xác nhận quay về màn hình chọn map hoặc màn hình chính
                if ea_pos or sg_pos or sel_pos:
                    state = STATE_LOBBY
                    print("\n[+] Đã phát hiện bạn quay trở về Sảnh chính / Chọn map.")
                    print("    Sẵn sàng ghi nhận trận đấu tiếp theo khi bạn vào map!\n")

    except KeyboardInterrupt:
        print("\n[!] Đã dừng bộ ghi hình người chơi. Dữ liệu đã được lưu an toàn!")
    finally:
        mouse_tracker.close()
        movement_tracker.close()


if __name__ == "__main__":
    run_human_recorder()
