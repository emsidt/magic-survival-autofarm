"""Chế độ Ghi hình & Học hỏi từ Trận đấu Người chơi (Human Expert Recorder).

Chế độ này cho phép BẠN tự tay chơi game 100% (không có bất kỳ can thiệp phím/chuột nào từ bot).
Hệ thống sẽ chạy ngầm quan sát:
1. Ghi lại toàn bộ kỹ năng bạn đã chọn ở từng cấp độ.
2. Ghi lại các nhánh thuộc tính và cổ vật bạn đã mở.
3. Ghi lại thời gian sống sót thực tế (ví dụ: 45 phút).
4. Tự động nạp toàn bộ build và kinh nghiệm của bạn vào Não AI (learned_policy.json)
   để AI học theo phong cách chơi chuyên gia của bạn!
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys
import threading
import time

# Đảm bảo tiến trình Python là Per-Monitor DPI Aware để GetCursorPos khớp 100% với pixel thực tế
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import numpy as np

import botcore
from data_recorder import DataRecorder
from learning_engine import AdaptiveLearner
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

    title = config.get("game_window_title", "Magic Survival")
    print(f"[*] Đang tìm cửa sổ game '{title}'...")

    hwnd = None
    while not hwnd:
        hwnd = main.locate_game(title)
        if not hwnd:
            print(f"    [!] Chưa tìm thấy cửa sổ game '{title}'. Đang chờ bạn mở game...", end="\r")
            time.sleep(1.5)

    print(f"\n[+] ĐÃ KẾT NỐI VỚI GAME (HWND: {hwnd})!")
    rect = main.game_rectangle(hwnd, config)
    print(f"[+] Kích thước khung hình theo dõi: {rect['width']}x{rect['height']}")
    print("\n>>> BẠN CÓ THỂ BẮT ĐẦU CHƠI BẤT KỲ LÚC NÀO! <<<")
    print(">>> Nhấn Ctrl+C trong cửa sổ này nếu muốn dừng ghi bất kỳ lúc nào.\n")

    recorder = DataRecorder(enabled=True)
    learner = AdaptiveLearner()
    mouse_tracker = MouseTracker()

    state = STATE_LOBBY
    match_start_time = 0.0
    active_skills: set[str] = set()
    last_level_up_frame = None
    last_level_up_time = 0.0
    last_seen_cards = None
    in_level_up = False
    step_count = 0
    death_streak = 0

    try:
        while True:
            time.sleep(0.20)
            try:
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
                    active_skills.clear()
                    step_count = 0
                    death_streak = 0
                    in_level_up = False
                    run_id = recorder.start_new_run()
                    print("\n" + "-" * 65)
                    print(f"[🔥 TRẬN ĐẤU BẮT ĐẦU!] Mã trận: {run_id}")
                    print("    Đang đếm thời gian và quan sát lựa chọn kỹ năng của bạn...")
                    print("-" * 65)

            # --- TRẠNG THÁI 2: ĐANG TRONG TRẬN ĐẤU (PLAYING) ---
            elif state == STATE_PLAYING:
                # 2.1 Phát hiện lên cấp (Level Up)
                lvl_res = botcore.is_level_up_screen(frame)
                if lvl_res:
                    if not in_level_up and (now - last_level_up_time >= 1.0):
                        in_level_up = True
                        last_level_up_time = now
                        step_count += 1
                        last_level_up_frame = frame.copy()
                        ocr_res = botcore._detect_cards_ocr(frame, h, w)
                        last_seen_cards = ocr_res
                        num_c = len(ocr_res)
                        print(f"\n[Cấp #{step_count}] Màn hình lên cấp ({num_c} lựa chọn có sẵn):")
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

                    # 2. Dự phòng: Nếu chuột tap quá nhanh, lấy vị trí con trỏ chuột hiện tại (người chơi vừa bấm xong chuột vẫn đang nằm trên thẻ)
                    if click_norm is None:
                        class _PT(ctypes.Structure):
                            _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
                        cur_pt = _PT()
                        ctypes.windll.user32.GetCursorPos(ctypes.byref(cur_pt))
                        rx = rect.get("left", 0)
                        ry = rect.get("top", 0)
                        rw = rect.get("width", 1)
                        rh = rect.get("height", 1)
                        if rw > 0 and rh > 0:
                            nx = (cur_pt.x - rx) / rw
                            ny = (cur_pt.y - ry) / rh
                            if 0.0 <= nx <= 1.0 and 0.15 <= ny <= 0.98:
                                click_norm = (round(nx, 4), round(ny, 4))

                    if last_seen_cards:
                        num_c = len(last_seen_cards)
                        if click_norm is not None:
                            norm_x, norm_y = click_norm
                            click_y_val = norm_y
                            if num_c == 4:
                                centers_4 = {1: 0.28, 2: 0.45, 3: 0.62, 4: 0.80, "mana": 0.93}
                                if 0.15 <= norm_y < 0.367:
                                    chosen_card_idx = 1
                                elif 0.367 <= norm_y < 0.540:
                                    chosen_card_idx = 2
                                elif 0.540 <= norm_y < 0.714:
                                    chosen_card_idx = 3
                                elif 0.714 <= norm_y < 0.890:
                                    chosen_card_idx = 4
                                elif 0.890 <= norm_y < 0.98:
                                    chosen_card_idx = "mana"
                                else:
                                    chosen_card_idx = min(centers_4.keys(), key=lambda k: abs(norm_y - centers_4[k]))
                            else:
                                centers_3 = {1: 0.36, 2: 0.53, 3: 0.70, "mana": 0.85}
                                if 0.20 <= norm_y < 0.445:
                                    chosen_card_idx = 1
                                elif 0.445 <= norm_y < 0.619:
                                    chosen_card_idx = 2
                                elif 0.619 <= norm_y < 0.798:
                                    chosen_card_idx = 3
                                elif 0.798 <= norm_y < 0.95:
                                    chosen_card_idx = "mana"
                                else:
                                    chosen_card_idx = min(centers_3.keys(), key=lambda k: abs(norm_y - centers_3[k]))

                        if chosen_card_idx == "mana":
                            chosen_name = "Mana 20% Retrieve"
                        elif chosen_card_idx in last_seen_cards:
                            cdata = last_seen_cards[chosen_card_idx]
                            if cdata.skills:
                                chosen_name = ", ".join(cdata.skills)
                                for sk in cdata.skills:
                                    active_skills.add(sk)
                            elif cdata.text_lines:
                                chosen_name = cdata.text_lines[0].title()
                                if cdata.special_passive_name:
                                    active_skills.add(cdata.special_passive_name)
                            else:
                                chosen_name = f"Thẻ {chosen_card_idx}"
                        else:
                            # Fallback nếu không xác định được tọa độ click
                            chosen_card_idx = 1
                            cdata = last_seen_cards.get(1)
                            if cdata and cdata.skills:
                                chosen_name = ", ".join(cdata.skills)
                                active_skills.add(cdata.skills[0])
                            elif cdata and cdata.text_lines:
                                chosen_name = cdata.text_lines[0].title()
                            else:
                                chosen_name = "Kỹ năng vừa chọn"

                        recorder.record_decision(
                            last_level_up_frame,
                            "human_level_up",
                            f"card_{chosen_card_idx}",
                            confidence=1.0,
                            metadata={
                                "step": step_count,
                                "chosen_card": chosen_card_idx,
                                "chosen_skill": chosen_name,
                                "click_norm_y": click_y_val,
                                "offered_cards": {
                                    str(k): list(last_seen_cards[k].skills) for k in sorted(last_seen_cards.keys())
                                },
                            },
                        )

                    elapsed_m = int((now - match_start_time) // 60)
                    elapsed_s = int((now - match_start_time) % 60)
                    click_info = f" (Click y={click_y_val:.2f})" if click_y_val is not None else ""
                    if chosen_card_idx == "mana":
                        print(f"    -> [ĐÃ CHỌN]: Mana 20% Retrieve (Bỏ qua thẻ để lấy Mana)!{click_info} (Thời gian: {elapsed_m:02d}:{elapsed_s:02d})")
                    elif chosen_card_idx is not None:
                        print(f"    -> [ĐÃ CHỌN]: Thẻ {chosen_card_idx} -> [{chosen_name}]!{click_info} (Thời gian: {elapsed_m:02d}:{elapsed_s:02d})")
                    else:
                        print(f"    -> [Đã ghi nhận]: Bạn vừa chọn xong kỹ năng! (Thời gian: {elapsed_m:02d}:{elapsed_s:02d})")

                # 2.2 Thuộc tính cấp 7
                learn_pos = botcore.detect_learn_button(frame)
                if learn_pos:
                    score, label, p_sk = botcore.evaluate_selected_attribute(frame)
                    if p_sk:
                        active_skills.add(p_sk)
                    print(f"[Thuộc tính cấp 7] Đang quan sát nhánh bạn chọn: [{label}] (Thuộc: {p_sk})")

                # 2.3 Rương cổ vật
                obtain_pos = botcore.detect_obtain_button(frame)
                if obtain_pos:
                    _, lbl = botcore.evaluate_selected_chest_artifact(frame, True, active_skills=active_skills)
                    print(f"[Rương Cổ vật] Bạn đang mở rương: {lbl}")

                # 2.4 KẾT THÚC TRẬN ĐẤU (Nhân vật chết hoặc bấm kết thúc)
                # Safeguards:
                # 1) Chỉ kích hoạt khi nút Pause || hoàn toàn biến mất (pause_pos is None)
                # 2) Phải duy trì trạng thái chết/kết thúc ít nhất 3 chu kỳ liên tiếp (>= 0.6s) để triệt tiêu mọi glitch/chớp giật
                if (die_pos or confirm_pos) and pause_pos is None:
                    death_streak += 1
                    if death_streak >= 3:
                        survival_sec = now - match_start_time
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

                            recorder.finish_run(survival_time=f"{m:02d}:{s:02d}")

                            core_prio = set(config.get("skill_priority", []))
                            learn_rep = learner.evaluate_and_learn_run(
                                run_id=recorder.current_run_id or f"human_expert_{int(now)}",
                                survival_seconds=survival_sec,
                                active_skills=active_skills,
                                core_skills=core_prio,
                            )

                            print("\n🧠 [KẾT QUẢ AI HỌC HỎI TỪ BẠN]:")
                            print(f"    - Điểm thưởng chuyên gia (Reward): {learn_rep.get('reward', 1.5):+.3f}")
                            new_avg = learn_rep.get('new_avg_survival', survival_sec)
                            print(f"    - Mức chuẩn trung bình mới được nâng lên: {int(new_avg // 60)}m {int(new_avg % 60)}s")
                            print("    - Toàn bộ kỹ năng và cặp kết hợp (synergy) của bạn đã được gia tăng trọng số ưu tiên!")
                            print("    - Đã lưu vào data/learned_policy.json thành công!")
                            print("\n>>> Đã ghi nhận xong 1 lần duy nhất! Đang chờ bạn quay lại Sảnh để chơi trận mới... <<<")
                        else:
                            # Thời gian quá ngắn (<10s) -> bỏ qua không ghi nhận
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


if __name__ == "__main__":
    run_human_recorder()
