"""Magic Survival AutoFarm - Pure CLI / Terminal Mode (No Tkinter GUI required).

Ideal for running directly inside Antigravity terminal, VS Code terminal, or Git Bash.
Full background automation via ADB (LDPlayer) or DirectInput.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

import botcore
from data_recorder import DataRecorder
from learning_engine import AdaptiveLearner


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
RULES_PATH = BASE_DIR / "rules.json"


def run_cli_bot():
    print("=" * 65)
    print("  🤖 MAGIC SURVIVAL AUTOFARM - TERMINAL MODE (CLI) 🤖")
    print("=" * 65)

    config = {}
    if CONFIG_PATH.is_file():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    control_mode = config.get("control_mode", "adb")
    adb_path = config.get("adb_path", r"D:\LDPlayer\LDPlayer9\adb.exe")

    controller = None
    if control_mode == "adb":
        print(f"[*] Chế độ điều khiển: ADB NGẦM (LDPlayer)")
        print(f"[*] Đường dẫn adb: {adb_path}")
        try:
            from adb_controller import ADBController
            controller = ADBController(adb_path=adb_path)
            if controller.device:
                print(f"[+] Đã kết nối thành công với LDPlayer! (Device: {controller.device})")
                print(f"[+] Kích thước màn hình: {controller.screen_width}x{controller.screen_height}")
                print("[+] Chuột và bàn phím của bạn sẽ KHÔNG BỊ CHIẾM khi bot chạy!")
            else:
                print("[!] Chưa tìm thấy cổng ADB của LDPlayer. Đang chuyển sang DirectInput...")
                import main
                controller = main.Controller()
        except Exception as e:
            print(f"[!] Lỗi khởi tạo ADB ({e}). Chuyển sang DirectInput...")
            import main
            controller = main.Controller()
    else:
        print("[*] Chế độ điều khiển: DirectInput (Windows)")
        import main
        controller = main.Controller()

    recorder = DataRecorder(enabled=bool(config.get("record_gameplay_data", True)))
    learner = AdaptiveLearner()

    rules = []
    if RULES_PATH.is_file():
        try:
            rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    is_adb = hasattr(controller, "screen_width")
    rect = {"left": 0, "top": 0, "width": getattr(controller, "screen_width", 1080), "height": getattr(controller, "screen_height", 1920)}

    print("\n>>> BOT ĐANG BẮT ĐẦU CHẠY TỰ ĐỘNG! <<<")
    print(">>> Nhấn Ctrl+C trong cửa sổ này để dừng bất kỳ lúc nào.\n")

    active_skills: set[str] = set()
    skill_levels: dict[str, int] = {}
    maxed_skills: set[str] = set()
    match_start_time = 0.0
    match_running = False
    last_auto_action_time = 0.0
    last_level_up_time = 0.0
    last_die_time = 0.0
    last_confirm_time = 0.0
    last_shop_time = 0.0
    last_chest_time = 0.0
    last_learn_time = 0.0
    in_shop = False
    last_shop_label = ""
    step_count = 0

    try:
        while True:
            time.sleep(0.12)
            now = time.monotonic()

            if is_adb:
                frame = controller.screenshot()
            else:
                import main
                hwnd = main.locate_game(config.get("window_title", "Magic Survival"))
                if not hwnd:
                    time.sleep(1.0)
                    continue
                rect = main.game_rectangle(hwnd, config)
                frame = main.screenshot(rect)

            if frame is None or frame.size == 0:
                continue

            h, w = frame.shape[:2]

            # 1. Phát hiện màn hình chết -> Bấm DIE
            die_pos = botcore.detect_die_button(frame)
            if die_pos:
                controller.release()
                match_running = False
                if now - last_die_time >= 1.5:
                    last_die_time = now
                    controller.tap(list(die_pos), rect)
                    print(f"💀 [Tử trận] Tự động bấm 'Die' bỏ qua quảng cáo!")
                    time.sleep(0.8)
                continue

            # 2. Phát hiện bảng kết quả -> Bấm CONFIRM & Ghi nhận học hỏi AI
            confirm_pos = botcore.detect_confirm_button(frame)
            if confirm_pos:
                controller.release()
                match_running = False
                if now - last_confirm_time >= 2.0:
                    last_confirm_time = now
                    recorder.record_decision(frame, "endgame", "confirm")
                    recorder.finish_run()
                    if match_start_time > 0.0:
                        survival_sec = now - match_start_time
                        match_start_time = 0.0
                        m, s = int(survival_sec // 60), int(survival_sec % 60)
                        rep = learner.evaluate_and_learn_run(
                            run_id=recorder.current_run_id or "run",
                            survival_seconds=survival_sec,
                            active_skills=set(active_skills),
                            core_skills=set(config.get("skill_priority", [])),
                        )
                        print("\n" + "=" * 60)
                        print(f"🏆 [KẾT QUẢ VÁN]: Sống sót {m:02d}p {s:02d}s | Điểm thưởng: {rep.get('reward', 0):+.2f}")
                        print(f"   Đã cập nhật {len(rep.get('skills_updated', []))} kỹ năng vào Não AI!")
                        print("=" * 60 + "\n")
                    active_skills.clear()
                    skill_levels.clear()
                    maxed_skills.clear()
                    controller.tap(list(confirm_pos), rect)
                    print(f"📋 [Kết quả] Tự động bấm 'Confirm' quay về sảnh!")
                    time.sleep(1.5)
                continue

            # 3. Màn hình Cài đặt mở nhầm -> Bấm Back/ESC đóng
            if botcore.detect_settings_dialog(frame):
                controller.press_esc()
                time.sleep(0.5)
                continue

            # 4. Màn hình chính -> Bấm "Start Game"
            sg_pos = botcore.detect_start_game(frame)
            if sg_pos:
                match_running = False
                active_skills.clear()
                skill_levels.clear()
                maxed_skills.clear()
                match_start_time = 0.0
                if now - last_auto_action_time >= 1.5:
                    last_auto_action_time = now
                    controller.tap(list(sg_pos), rect)
                    print("🎮 [Sảnh chính] Tự động bấm 'Start Game'!")
                    time.sleep(1.2)
                continue

            # 5. Màn hình chọn nhân vật -> Bấm "Selected"
            sel_pos = botcore.detect_selected(frame)
            if sel_pos:
                match_running = False
                if now - last_auto_action_time >= 1.5:
                    last_auto_action_time = now
                    controller.tap(list(sel_pos), rect)
                    print("🧙 [Chọn nhân vật] Tự động bấm 'Selected'!")
                    time.sleep(1.2)
                continue

            # 6. Màn hình chọn map -> Bấm "Enter Area" bắt đầu trận mới
            ea_pos = botcore.detect_enter_area(frame)
            if ea_pos:
                match_running = False
                if now - last_auto_action_time >= 1.5:
                    last_auto_action_time = now
                    run_id = recorder.start_new_run()
                    match_start_time = now
                    step_count = 0
                    controller.tap(list(ea_pos), rect)
                    print("\n" + "-" * 60)
                    print(f"🔥 [TRẬN ĐẤU MỚI BẮT ĐẦU!] Mã ván: {run_id}")
                    print("   Bot đang tự động né quái và cày vàng...")
                    print("-" * 60 + "\n")
                    time.sleep(1.2)
                continue

            # 7. Phát hiện quảng cáo có nút X -> Bấm X tắt
            ad_x = botcore.detect_close_button(frame)
            if ad_x:
                controller.release()
                if now - last_auto_action_time >= 1.5:
                    last_auto_action_time = now
                    controller.tap(list(ad_x), rect)
                    print("📺 [Quảng cáo] Đã tự động bấm nút 'X' đóng quảng cáo!")
                    time.sleep(1.0)
                continue

            # 8. MÀN HÌNH LÊN CẤP (Level Up)
            lvl_res = botcore.is_level_up_screen(frame)
            if lvl_res:
                controller.release()
                match_running = True
                if now - last_level_up_time >= 1.2:
                    last_level_up_time = now
                    step_count += 1

                    # 8.1 Kiểm tra xem có mở khóa Phép Kết Hợp Fusion (ngôi sao đỏ góc trên-phải) không
                    combo_star_pos = botcore.detect_combination_star(frame)
                    if combo_star_pos:
                        controller.tap(list(combo_star_pos), rect)
                        time.sleep(0.45)
                        f_combo = controller.screenshot() if is_adb else frame
                        combo_choice = botcore.find_best_combination_option(f_combo, config.get("skill_priority"))
                        if combo_choice:
                            combo_target, combo_label, combo_key = combo_choice
                            controller.tap(list(combo_target), rect)
                            time.sleep(0.35)
                            f_conf = controller.screenshot() if is_adb else frame
                            btn_learn = botcore.detect_learn_button(f_conf)
                            if btn_learn:
                                controller.tap(list(btn_learn), rect)
                                active_skills.add(combo_key)
                                maxed_skills.add(combo_key)
                                if combo_key in botcore.COMBINATION_COMPONENTS:
                                    for comp in botcore.COMBINATION_COMPONENTS[combo_key]:
                                        active_skills.add(comp)
                                        skill_levels[comp] = 7
                                        maxed_skills.add(comp)
                                        print(f"🏆 [MAX FUSION] Kỹ năng thành phần [{comp}] đã hợp thể tối đa vào [{combo_label}]!")
                                print(f"✨ [Phép kết hợp Fusion] Đã mở khóa: [{combo_label}] ({combo_key})!")
                                time.sleep(0.65)
                                continue

                    # 8.2 Chọn thẻ kỹ năng tối ưu
                    choice = config.get("card_choice", 1)
                    choice_res = botcore.choose_best_artifact_or_card(
                        frame,
                        default_choice=choice,
                        skill_priority=config.get("skill_priority"),
                        prefer_crit_and_cooldown=config.get("prefer_crit_and_cooldown", True),
                        prefer_freeze_traits=config.get("prefer_freeze_traits", True),
                        active_skills=active_skills,
                        maxed_skills=maxed_skills,
                    )
                    card_idx, target = choice_res
                    choice_label = getattr(choice_res, "label", f"Thẻ {card_idx}")
                    if target:
                        controller.tap(list(target), rect)
                        sk_key = getattr(choice_res, "skill_key", None)
                        if sk_key:
                            active_skills.add(sk_key)
                            skill_levels[sk_key] = skill_levels.get(sk_key, 0) + 1
                            max_lvl = botcore.SKILL_MAX_LEVELS.get(sk_key, 1 if sk_key in botcore.SPECIAL_STAR_PASSIVES else 7)
                            if skill_levels[sk_key] >= max_lvl:
                                maxed_skills.add(sk_key)
                                print(f"🏆 [MAX LEVEL] Kỹ năng [{sk_key}] đã đạt cấp tối đa ({max_lvl})!")
                        print(f"⭐ [Cấp #{step_count}] Đã chọn Thẻ {card_idx}: [{choice_label}]")
                        time.sleep(0.65)
                continue

            # 9. MÀN HÌNH CHỌN THUỘC TÍNH LEVEL 7 (Learn button)
            learn_pos = botcore.detect_learn_button(frame)
            if learn_pos:
                controller.release()
                match_running = True
                if now - last_learn_time >= 1.5:
                    last_learn_time = now
                    s_att, l_att, p_sk = botcore.evaluate_selected_attribute(frame)
                    circles = botcore.get_attribute_circle_targets()
                    if circles:
                        controller.tap(list(circles[0]), rect)
                        time.sleep(0.2)
                    controller.tap(list(learn_pos), rect)
                    if p_sk:
                        active_skills.add(p_sk)
                        skill_levels[p_sk] = 7
                        maxed_skills.add(p_sk)
                        print(f"🏆 [MAX LEVEL] Kỹ năng [{p_sk}] đã hoàn thành nhánh Cấp 7 (MAX)!")
                    print(f"🌀 [Thuộc tính Cấp 7] Đã học nhánh: [{l_att}] (Thuộc: {p_sk})")
                    time.sleep(0.65)
                continue

            # 10. MÀN HÌNH RƯƠNG CỔ VẬT (Obtain button)
            obtain_pos = botcore.detect_obtain_button(frame)
            if obtain_pos:
                controller.release()
                match_running = True
                if now - last_chest_time >= 1.2:
                    last_chest_time = now
                    _, c_lbl = botcore.evaluate_selected_chest_artifact(frame, True, active_skills=active_skills)
                    controller.tap(list(obtain_pos), rect)
                    print(f"📦 [Rương Cổ vật] Đã nhận: [{c_lbl}]!")
                    time.sleep(0.65)
                continue

            # 11. MÀN HÌNH CỬA HÀNG THƯƠNG NHÂN (Merchant Shop)
            shop_buy = botcore.detect_buy_button(frame)
            if shop_buy:
                controller.release()
                match_running = True
                if now - last_shop_time >= 1.5:
                    last_shop_time = now
                    mana_val = botcore.detect_mana_orb_currency(frame)
                    mana_str = f" (Mana: {mana_val})" if mana_val is not None else ""
                    if botcore.is_shop_buy_enabled(frame):
                        _, s_lbl = botcore.evaluate_selected_shop_artifact(frame, True, active_skills=active_skills)
                        controller.tap(list(shop_buy), rect)
                        print(f"🛒 [Cửa hàng] Đủ Mana mua [{s_lbl}]{mana_str} -> Đã bấm Buy!")
                        time.sleep(0.65)
                    else:
                        x_pos = botcore.detect_shop_x_button(frame) or (0.936, 0.079)
                        controller.tap(list(x_pos), rect)
                        print(f"🛒 [Cửa hàng] Chưa đủ Mana mua đồ{mana_str} -> Bấm 'X' đóng shop farm tiếp!")
                        time.sleep(0.65)
                continue

            # 12. GIAI ĐOẠN CHIẾN ĐẤU TÍCH CỰC (In Active Combat)
            pause_pos = botcore.detect_pause_button(frame)
            if pause_pos:
                match_running = True
                if match_start_time == 0.0:
                    match_start_time = now

                # Điều khiển né quái thông minh bằng thuật toán trường tiềm năng (Potential Field)
                vision = botcore.inspect_game(frame, player=tuple(config.get("player_position", [0.5, 0.5])))
                dir_x, dir_y = botcore.choose_direction(vision, elapsed=now - match_start_time, player=tuple(config.get("player_position", [0.5, 0.5])))
                controller.move((dir_x, dir_y), rect, config)

    except KeyboardInterrupt:
        print("\n[!] Đã nhận lệnh dừng từ bàn phím. Đang giải phóng bộ điều khiển...")
        if controller:
            controller.release()
        print("[+] Bot đã dừng an toàn. Hẹn gặp lại bạn!\n")


if __name__ == "__main__":
    run_cli_bot()
