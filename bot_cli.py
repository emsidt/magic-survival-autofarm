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
    last_monolith_pos = None
    last_monolith_time = 0.0
    previous_direction = None
    in_shop = False
    last_shop_label = ""
    step_count = 0

    try:
        while True:
            time.sleep(0.12)
            now = time.monotonic()

            if is_adb:
                # Tự phục hồi: Nếu game bị văng ra màn hình chính LDPlayer (AdMob Crash) -> tự động mở lại
                if hasattr(controller, "is_game_foreground") and not controller.is_game_foreground():
                    print("🔄 [Tự phục hồi] Phát hiện game bị thoát/văng ra ngoài màn hình chính -> Đang tự động mở lại Magic Survival...")
                    controller.launch_game()
                    time.sleep(3.5)
                    last_auto_action_time = now
                    continue
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
                    last_monolith_pos = None
                    previous_direction = None
                    controller.tap(list(confirm_pos), rect)
                    last_auto_action_time = now
                    print(f"📋 [Kết quả] Tự động bấm 'Confirm' quay về sảnh!")
                    time.sleep(2.0)
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
                    last_monolith_pos = None
                    previous_direction = None
                    controller.tap(list(ea_pos), rect)
                    print("\n" + "-" * 60)
                    print(f"🔥 [TRẬN ĐẤU MỚI BẮT ĐẦU!] Mã ván: {run_id}")
                    print("   Bot đang tự động né quái và cày vàng...")
                    print("-" * 60 + "\n")
                    time.sleep(1.2)
                continue

            # 7. MÀN HÌNH CHỌN THUỘC TÍNH (Level 4/7 Trait / Select Attribute - Có nút Learn)
            if botcore.is_attribute_screen(frame) or botcore.detect_learn_button(frame) is not None:
                controller.release()
                match_running = True
                if now - last_learn_time >= 1.2:
                    last_learn_time = now
                    circles = botcore.get_attribute_circle_targets()
                    
                    # Duyệt và đánh giá 3 nhánh thuộc tính (1: Top, 2: Bottom-Left, 3: Bottom-Right)
                    best_c_idx = 1
                    best_c_score = -1
                    best_c_label = ""
                    best_c_parent = ""

                    for c_idx in (1, 2, 3):
                        controller.tap(list(circles[c_idx]), rect)
                        time.sleep(0.35)
                        f_snap = controller.screenshot() if is_adb else frame
                        s_att, l_att, p_sk = botcore.evaluate_selected_attribute(f_snap)
                        if s_att > best_c_score:
                            best_c_score = s_att
                            best_c_idx = c_idx
                            best_c_label = l_att
                            if p_sk:
                                best_c_parent = p_sk
                        # Nếu gặp nhánh Hợp thể tối thượng (score >= 500), chốt ngay lập tức
                        if best_c_score >= 500:
                            break

                    # Tự động chọn nhánh tối ưu nhất
                    controller.tap(list(circles[best_c_idx]), rect)
                    time.sleep(0.25)

                    # Bấm nút "Learn" xác nhận
                    f_learn = controller.screenshot() if is_adb else frame
                    learn_target = botcore.detect_learn_button(f_learn) or (0.50, 0.8786)
                    controller.tap(list(learn_target), rect)

                    if best_c_parent:
                        active_skills.add(best_c_parent)
                        skill_levels[best_c_parent] = 7
                        maxed_skills.add(best_c_parent)
                        print(f"🏆 [MAX LEVEL] Kỹ năng [{best_c_parent}] đã hoàn thành nhánh Cấp 7 (MAX)!")
                    print(f"🌀 [Thuộc tính Cấp 7] Đã học nhánh: [{best_c_label}] (Kỹ năng: {best_c_parent or 'Unknown'})")
                    time.sleep(0.8)
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

            # 9. MÀN HÌNH RƯƠNG CỔ VẬT (Obtain button)
            obtain_pos = botcore.detect_obtain_button(frame)
            if obtain_pos:
                controller.release()
                match_running = True
                if now - last_chest_time >= 1.2:
                    last_chest_time = now
                    obtain_x, obtain_y = obtain_pos
                    prefer_cc = config.get("prefer_crit_and_cooldown", True)

                    build_skills = set(active_skills)
                    for p_sk in config.get("skill_priority", []):
                        clean_sk = str(p_sk).lower().strip().replace("-", "_").replace(" ", "_")
                        build_skills.add(clean_sk)

                    print(f"\n📦 [Rương Cổ vật] Mở Rương! Đang duyệt 3 cổ vật (Ô 1, Ô 2, Ô 3)...")
                    candidates = {}

                    # 1. Đọc Thẻ 1 (Mặc định đang được chọn khi mở rương)
                    s1, lbl1 = botcore.evaluate_selected_chest_artifact(frame, prefer_cc, active_skills=build_skills)
                    candidates[1] = (s1, lbl1)
                    print(f"   - Thẻ 1/3: [{lbl1}] (Điểm: {s1})")

                    # 2. Bấm xem Thẻ 2
                    slot2 = botcore.get_chest_card_target(2, obtain_x)
                    controller.tap(list(slot2), rect)
                    time.sleep(0.30)
                    f2 = controller.screenshot() if is_adb else frame
                    s2, lbl2 = botcore.evaluate_selected_chest_artifact(f2, prefer_cc, active_skills=build_skills)
                    candidates[2] = (s2, lbl2)
                    print(f"   - Thẻ 2/3: [{lbl2}] (Điểm: {s2})")

                    # 3. Bấm xem Thẻ 3
                    slot3 = botcore.get_chest_card_target(3, obtain_x)
                    controller.tap(list(slot3), rect)
                    time.sleep(0.30)
                    f3 = controller.screenshot() if is_adb else frame
                    s3, lbl3 = botcore.evaluate_selected_chest_artifact(f3, prefer_cc, active_skills=build_skills)
                    candidates[3] = (s3, lbl3)
                    print(f"   - Thẻ 3/3: [{lbl3}] (Điểm: {s3})")

                    # Chọn thẻ có điểm cao nhất (ưu tiên Build Synergy, S-Tier, Special, Legendary)
                    best_idx = max(candidates, key=lambda k: candidates[k][0])
                    best_score, best_label = candidates[best_idx]

                    # Nếu thẻ tốt nhất không phải là Thẻ 3 (thẻ đang chọn), bấm chọn lại thẻ đó
                    if best_idx != 3:
                        best_slot = botcore.get_chest_card_target(best_idx, obtain_x)
                        controller.tap(list(best_slot), rect)
                        time.sleep(0.25)

                    # Bấm Obtain để nhận cổ vật
                    controller.tap([obtain_x, obtain_y], rect)
                    print(f"📦 [Rương Cổ vật] 🎉 ĐÃ CHỌN CỔ VẬT TỐT NHẤT: Thẻ {best_idx} -> [{best_label}]!")
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
                    mana_str = f" ({mana_val} Mana)" if mana_val is not None else ""
                    print(f"\n🛒 [Cửa hàng] Mở cửa hàng Thương nhân{mana_str}! Đang duyệt full 8 món đồ...")

                    shop_targets = botcore.get_shop_item_targets()
                    build_skills = set(active_skills)
                    for p_sk in config.get("skill_priority", []):
                        clean_sk = str(p_sk).lower().strip().replace("-", "_").replace(" ", "_")
                        build_skills.add(clean_sk)

                    best_buy_slot = None
                    best_buy_score = -1
                    best_buy_label = ""

                    for idx, s_pos in enumerate(shop_targets, 1):
                        controller.tap(list(s_pos), rect)
                        time.sleep(0.24)
                        f_item = controller.screenshot() if is_adb else frame
                        if f_item is None or f_item.size == 0:
                            continue

                        # Kiểm tra xem món này có đủ Mana mua không (nút Buy sáng trắng)
                        is_affordable = botcore.is_shop_buy_enabled(f_item, buy_pos=shop_buy)
                        s_score, s_lbl = botcore.evaluate_selected_shop_artifact(
                            f_item,
                            prefer_crit_and_cooldown=config.get("prefer_crit_and_cooldown", True),
                            active_skills=build_skills,
                        )

                        # Kiểm tra xem món đồ có khớp với build hiện tại hoặc độ hiếm cao không
                        has_synergy = ("Build:" in s_lbl) or ("★" in s_lbl) or ("S-Tier" in s_lbl) or ("Special" in s_lbl) or ("Legendary" in s_lbl)

                        if is_affordable:
                            syn_tag = " [HỢP BUILD ⭐]" if has_synergy else ""
                            print(f"   - Ô {idx}/8: [{s_lbl}] -> 🟢 ĐỦ MANA (Điểm: {s_score}){syn_tag}")
                            # Ưu tiên vượt trội cho các món đồ hợp build hoặc Tier cao
                            effective_score = s_score + (1000 if has_synergy else 0)
                            if effective_score > best_buy_score:
                                best_buy_score = effective_score
                                best_buy_slot = s_pos
                                best_buy_label = s_lbl
                        else:
                            print(f"   - Ô {idx}/8: [{s_lbl}] -> 🔴 Chưa đủ Mana")

                    # Quyết định mua hoặc đóng cửa hàng
                    if best_buy_slot and best_buy_score > 0:
                        controller.tap(list(best_buy_slot), rect)
                        time.sleep(0.25)
                        controller.tap(list(shop_buy), rect)
                        print(f"🛒 [Cửa hàng] 🎉 ĐÃ MUA MÓN TỐT NHẤT HỢP BUILD: [{best_buy_label}]!")
                        time.sleep(0.65)
                        f_after = controller.screenshot() if is_adb else frame
                        x_pos = botcore.detect_shop_x_button(f_after) or (0.943, 0.079)
                        controller.tap(list(x_pos), rect)
                        time.sleep(0.4)
                    else:
                        x_pos = botcore.detect_shop_x_button(frame) or (0.943, 0.079)
                        controller.tap(list(x_pos), rect)
                        print(f"🛒 [Cửa hàng] Đã duyệt xong 8 món: Không có món phù hợp hoặc chưa đủ Mana -> Bấm 'X' đóng shop farm tiếp!")
                        time.sleep(0.5)
                continue

            # 12. Phát hiện quảng cáo có nút X -> Bấm X tắt
            ad_x = botcore.detect_close_button(frame)
            if ad_x:
                controller.release()
                if now - last_auto_action_time >= 1.5:
                    last_auto_action_time = now
                    controller.tap(list(ad_x), rect)
                    print("📺 [Quảng cáo] Đã tự động bấm nút 'X' đóng quảng cáo!")
                    time.sleep(1.0)
                continue

            # 13. GIAI ĐOẠN CHIẾN ĐẤU TÍCH CỰC (In Active Combat)
            pause_pos = botcore.detect_pause_button(frame)
            if pause_pos:
                match_running = True
                if match_start_time == 0.0:
                    match_start_time = now

                player_coords = tuple(config.get("player_position", [0.5, 0.5]))
                px = int(w * player_coords[0])
                py = int(h * player_coords[1])

                # Phân tích thực địa: Quái vật, Đá/Tháp qua màn, Rương cổ vật, Mana Orbs
                vision = botcore.inspect_game(frame, player=player_coords)

                # Theo dõi Tháp qua màn (Monolith) liên tục kèm bù trừ vector di chuyển
                if getattr(vision, "monolith", None) is not None:
                    last_monolith_pos = vision.monolith
                    last_monolith_time = now
                    print(f"🏛️ [Tháp qua màn] ƯU TIÊN TUYỆT ĐỐI: Phát hiện Tháp tại {vision.monolith}! Đang lao thẳng vào để chạm Tháp nhận Cổ vật Huyền thoại!")
                elif last_monolith_pos is not None and (now - last_monolith_time <= 3.0):
                    if previous_direction:
                        est_mx = int(round(last_monolith_pos[0] - 12.0 * previous_direction[0]))
                        est_my = int(round(last_monolith_pos[1] - 12.0 * previous_direction[1]))
                        last_monolith_pos = (est_mx, est_my)
                    if (
                        -80 <= last_monolith_pos[0] < w + 80
                        and -80 <= last_monolith_pos[1] < h + 80
                        and math.hypot(last_monolith_pos[0] - px, last_monolith_pos[1] - py) > 8
                    ):
                        vision.monolith = last_monolith_pos
                    else:
                        last_monolith_pos = None
                else:
                    last_monolith_pos = None

                # Điều khiển né quái thông minh bằng thuật toán trường tiềm năng (Potential Field)
                dir_x, dir_y = botcore.choose_direction(
                    vision,
                    elapsed=now - match_start_time,
                    player=player_coords,
                    previous=previous_direction,
                )
                previous_direction = (dir_x, dir_y)
                controller.move((dir_x, dir_y), rect, config)

    except KeyboardInterrupt:
        print("\n[!] Đã nhận lệnh dừng từ bàn phím. Đang giải phóng bộ điều khiển...")
        if controller:
            controller.release()
        print("[+] Bot đã dừng an toàn. Hẹn gặp lại bạn!\n")


if __name__ == "__main__":
    run_cli_bot()
