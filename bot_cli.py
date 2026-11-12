"""Magic Survival AutoFarm - Pure CLI / Terminal Mode (No Tkinter GUI required).

Ideal for running directly inside Antigravity terminal, VS Code terminal, or Git Bash.
Full background automation via ADB (LDPlayer) or DirectInput.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time


import botcore
from adb_controller import ADBCommandError
from game_actions import (ActionCancelled, FrameCaptureError, GuardedController, capture_frame,
                          select_attribute, select_combination, select_card, remember_card, finish_match,
                          select_character, dismiss_death, close_ad, back_from_ad, move_from_frame, select_chest_artifact)
from data_recorder import DataRecorder
from learning_engine import get_adaptive_learner


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

    # 1. Nhận diện chế độ qua tham số dòng lệnh (CLI args)
    # Hỗ trợ: python bot_cli.py 1, python bot_cli.py ld, python bot_cli.py 2, python bot_cli.py google
    selected_mode = None
    args = [a.lower().strip() for a in sys.argv[1:]]
    for arg in args:
        if arg in ("1", "ld", "ldplayer", "--ld", "--ldplayer", "-ld"):
            selected_mode = "adb"
            break
        elif arg in ("2", "google", "gplay", "googleplay", "pc", "windows", "desktop", "--google", "--gplay", "--pc"):
            selected_mode = "desktop"
            break

    current_mode = config.get("control_mode", "desktop")
    default_choice = "1" if current_mode == "adb" else "2"

    # 2. Nếu không có tham số dòng lệnh, mở menu chọn tương tác trong terminal
    if selected_mode is None:
        is_interactive = False
        try:
            is_interactive = bool(sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty())
        except Exception:
            is_interactive = False

        if is_interactive:
            print("\n" + "=" * 60)
            print("  CHỌN NỀN TẢNG ĐIỀU KHIỂN:")
            print("=" * 60)
            tag_1 = " [Đang lưu mặc định]" if default_choice == "1" else ""
            tag_2 = " [Đang lưu mặc định]" if default_choice == "2" else ""
            print(f"  [1] 📱 LDPlayer (Chạy ngầm qua ADB, không chiếm chuột/phím){tag_1}")
            print(f"  [2] 🖥️ Google Play Games PC (Chạy cửa sổ Windows, phím WASD){tag_2}")
            print("=" * 60)
            try:
                user_input = input(f"👉 Chọn nền tảng [1 hoặc 2] (Bấm Enter để dùng [{default_choice}]): ").strip().lower()
                if user_input in ("1", "ld", "ldplayer"):
                    selected_mode = "adb"
                elif user_input in ("2", "google", "gplay", "pc", "windows", "desktop"):
                    selected_mode = "desktop"
                elif user_input == "":
                    selected_mode = "adb" if default_choice == "1" else "desktop"
                else:
                    print(f"[*] Lựa chọn không hợp lệ; dùng mặc định: {'LDPlayer' if default_choice == '1' else 'Google Play Games PC'}")
                    selected_mode = "adb" if default_choice == "1" else "desktop"
            except (EOFError, KeyboardInterrupt):
                print("\n[!] Đã hủy thao tác.")
                return
        else:
            selected_mode = current_mode

    control_mode = selected_mode
    config["control_mode"] = control_mode
    if control_mode == "desktop":
        config["input_mode"] = "keyboard"
    else:
        config["input_mode"] = "touch"

    # Tự động lưu cấu hình lựa chọn để lần sau Enter là xong
    try:
        if hasattr(CONFIG_PATH, "write_text"):
            CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    adb_path = config.get("adb_path", r"D:\LDPlayer\LDPlayer9\adb.exe")
    controller = None

    if control_mode == "adb":
        print(f"\n[*] Chế độ điều khiển: ADB NGẦM (LDPlayer)")
        print(f"[*] Đường dẫn adb: {adb_path}")
        try:
            from adb_controller import ADBController
            controller = ADBController(adb_path=adb_path)
            if controller.device:
                print(f"[+] Đã kết nối thành công với LDPlayer! (Device: {controller.device})")
                print(f"[+] Kích thước màn hình: {controller.screen_width}x{controller.screen_height}")
                print("[+] Chuột và bàn phím của bạn sẽ KHÔNG BỊ CHIẾM khi bot chạy!")
            else:
                print("[!] Chưa tìm thấy thiết bị ADB; dừng để kiểm tra kết nối.")
                return
        except Exception as e:
            print(f"[!] Không khởi tạo được ADB: {e}")
            return
    else:
        print("\n[*] Chế độ điều khiển: DirectInput (Google Play Games PC / Windows)")
        import main
        controller = main.Controller()
        h_init = main.locate_game(config.get("window_title", "Magic Survival"))
        if h_init:
            import win32gui
            t_init = win32gui.GetWindowText(h_init)
            print(f"[+] Đã tìm thấy cửa sổ game: '{t_init}' (HWND: {h_init})")
            print("[+] Hãy click chuột vào cửa sổ Magic Survival để bot bắt đầu tự động chơi!")
        else:
            print("[!] Chưa tìm thấy cửa sổ Magic Survival. Hãy mở game trên Google Play Games!")

    recorder = DataRecorder(enabled=bool(config.get("record_gameplay_data", True)), max_runs=int(config.get("max_data_runs", 50)))
    learner = get_adaptive_learner()

    rules = []
    if RULES_PATH.is_file():
        try:
            rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    is_adb = hasattr(controller, "screen_width")
    rect = {"left": 0, "top": 0, "width": getattr(controller, "screen_width", 1080), "height": getattr(controller, "screen_height", 1920)}

    hwnd = None
    controller = GuardedController(
        controller, lambda: is_adb or (hwnd is not None and main.is_game_or_popup_active(hwnd)[0]),
    )
    capture = lambda: capture_frame(controller, rect, main.screenshot if not is_adb else None)
    session_start = time.monotonic()

    print("\n>>> BOT ĐANG BẮT ĐẦU CHẠY TỰ ĐỘNG! <<<")
    print(">>> Nhấn Ctrl+C trong cửa sổ này để dừng bất kỳ lúc nào.\n")

    active_skills: set[str] = set()
    skill_levels: dict[str, int] = {}
    maxed_skills: set[str] = set()
    match_start_time = 0.0
    match_running = False
    last_auto_action_time = 0.0
    last_combination_attempt = 0.0
    last_level_up_time = 0.0
    last_die_time = 0.0
    last_confirm_time = 0.0
    last_shop_time = 0.0
    last_chest_modal_time = 0.0
    last_chest_pos = None
    last_chest_type = "treasure_chest"
    last_chest_weight = 24.0
    last_chest_hunt_time = 0.0
    last_chest_log_time = 0.0
    last_logged_chest_pos = None
    last_learn_time = 0.0
    last_monolith_pos = None
    last_monolith_time = 0.0
    previous_direction = None
    in_shop = False
    last_shop_label = ""
    step_count = 0
    last_known_game_timer_sec = 0.0
    last_timer_scan_time = 0.0
    rule_streak_name = ""
    rule_streak = 0
    last_rule_click = {}
    last_boss_alert_time = 0.0
    last_focus_warning = 0.0
    last_lobby_gold: Optional[int] = None
    last_lobby_gems: Optional[int] = None

    try:
        while True:
            try:
                time.sleep(0.02)
                now = time.monotonic()
                if now - session_start >= 60 * float(config.get("max_session_minutes", 120)):
                    print("Đã hết giới hạn thời gian phiên chơi.")
                    break

                if is_adb:
                    # Tự phục hồi: Nếu game bị văng ra màn hình chính LDPlayer hoặc mở Play Store / Chrome -> tự động đóng & mở lại
                    if hasattr(controller, "is_game_foreground") and not controller.is_game_foreground():
                        controller.release()
                        match_running = False
                        previous_direction = None

                        # Kiểm tra xem có bị nhảy sang Chrome hoặc Google Play Store sau khi bấm X không
                        if hasattr(controller, "get_foreground_package"):
                            fg_pkg = controller.get_foreground_package() or ""
                            if any(p in fg_pkg.lower() for p in ("chrome", "browser", "vending")):
                                print(f"🌐 [Trình duyệt] Phát hiện {fg_pkg} mở sau khi bấm quảng cáo -> Đang tự động tắt Chrome và đưa game về màn hình chính...")
                                if hasattr(controller, "close_external_browsers"):
                                    controller.close_external_browsers()
                                if hasattr(controller, "launch_game"):
                                    controller.launch_game()
                                time.sleep(1.2)
                                last_auto_action_time = now
                                continue

                        # An ad/store overlay can own focus without the game crashing.
                        # Look for its actual dismiss control before reopening the game.
                        if config.get("auto_close_ads", True):
                            try:
                                overlay = capture()
                            except FrameCaptureError:
                                time.sleep(0.5)
                                continue
                            close = botcore.detect_close_button(overlay)
                            if close is not None:
                                if close_ad(controller, rect, capture) is not None:
                                    print("[Quảng cáo] Đã bấm nút đóng; đọc lại màn hình trước thao tác tiếp theo.")
                                time.sleep(0.6)
                                continue
                        if controller.is_game_foreground():
                            continue
                        if config.get("auto_close_ads", True):
                            controller.press_esc()
                            time.sleep(0.5)
                        if config.get("auto_restart", True) and not controller.is_game_foreground():
                            print("🔄 [Tự phục hồi] Game bị chuyển sang ứng dụng khác -> Đang tự động mở lại Magic Survival...")
                            controller.launch_game()
                            time.sleep(2.0)
                            last_auto_action_time = now
                        continue
                else:
                    import main
                    hwnd = main.locate_game(config.get("window_title", "Magic Survival"))
                    if not hwnd:
                        if now - last_focus_warning >= 5.0:
                            last_focus_warning = now
                            print("[!] Chưa tìm thấy cửa sổ game Magic Survival; đang chờ game mở...")
                        controller.release()
                        time.sleep(0.5)
                        continue
                    active, _ = main.is_game_or_popup_active(hwnd)
                    if not active:
                        if now - last_focus_warning >= 5.0:
                            last_focus_warning = now
                            print("[⏸️] Cửa sổ Magic Survival đang không có tiêu điểm (focus). Hãy click chuột vào cửa sổ game để bot chạy tiếp!")
                        controller.release()
                        time.sleep(0.4)
                        continue
                    rect = main.game_rectangle(hwnd, config)

                try:
                    frame = botcore.prepare_analysis_frame(capture())
                    captured_at = time.perf_counter()
                except FrameCaptureError:
                    time.sleep(0.5)
                    continue

                h, w = frame.shape[:2]
                found_rule = botcore.find_rule(frame, rules, str(BASE_DIR)) if rules else None
                if found_rule:
                    controller.release()
                    name = found_rule["name"]
                    rule_streak = rule_streak + 1 if name == rule_streak_name else 1
                    rule_streak_name = name
                    if rule_streak >= 2 and now - last_rule_click.get(name, 0.0) >= 3.2:
                        controller.tap(found_rule["target"], rect)
                        last_rule_click[name] = now
                    continue
                rule_streak_name, rule_streak = "", 0

                fast_combat = botcore.is_fast_combat_frame(frame)
                if not fast_combat:
                    controller.release()
                    restore_pos = botcore.detect_restore_gold(frame)
                    if restore_pos:
                        controller.release()
                        if now - last_confirm_time >= 2.0:
                            controller.tap(list(restore_pos), rect)
                            last_confirm_time = now
                            if recorder.current_run_id:
                                recorder.finish_run()
                            match_running = False
                            match_start_time = last_known_game_timer_sec = 0.0
                            active_skills.clear()
                            skill_levels.clear()
                            maxed_skills.clear()
                            previous_direction = last_chest_pos = last_monolith_pos = None
                            print("[Restore Gold] Đã bấm Confirm nhận lại vàng sau crash.")
                        continue

                    # 1. Phát hiện màn hình chết -> Bấm DIE
                    die_pos = botcore.detect_die_button(frame)
                    if die_pos:
                        controller.release()
                        match_running = False
                        t_die = botcore.detect_game_timer(frame)
                        if t_die and t_die[2] >= last_known_game_timer_sec:
                            last_known_game_timer_sec = float(t_die[2])
                        if now - last_die_time >= 1.5:
                            last_die_time = now
                            if dismiss_death(controller, rect, capture):
                                print("[Tử trận] Đã xác nhận Die, chuyển sang nhận thưởng.")
                            else:
                                print("[Tử trận] Chưa xác nhận được Die; đọc lại, không đoán vị trí gần Revive.")
                            time.sleep(0.8)
                        continue

                    # 2. Phát hiện bảng kết quả -> Bấm CONFIRM & Ghi nhận học hỏi AI
                    confirm_pos = botcore.detect_confirm_button(frame)
                    if confirm_pos:
                        controller.release()
                        match_running = False
                        if now - last_confirm_time >= 2.0:
                            last_confirm_time = now
                            if match_start_time > 0.0 or recorder.current_run_id or last_known_game_timer_sec > 0.0:
                                t_final = botcore.detect_game_timer(frame) or botcore.detect_results_survival_time(frame)
                                if t_final:
                                    last_known_game_timer_sec = max(last_known_game_timer_sec, float(t_final[2]))
                                time_mult = 1.24 if str(config.get("game_map", "depth")).lower().strip() == "depth" else 1.0
                                if last_known_game_timer_sec <= 0.0 and match_start_time > 0.0:
                                    last_known_game_timer_sec = max(0.0, (now - match_start_time) * time_mult)
                                stats = botcore.detect_results_stats(frame)
                                rep = finish_match(
                                    recorder, learner, frame, last_known_game_timer_sec,
                                    active_skills, config.get("skill_priority", []),
                                    skill_levels=skill_levels,
                                    character=config.get("character", "summoner"),
                                    game_map=config.get("game_map", "depth"),
                                    gold=stats.get("gold", 0),
                                    gems=stats.get("gems", 0),
                                    kills=stats.get("kills", 0),
                                )
                                if rep and isinstance(rep, dict) and "summary_text" in rep:
                                    print(rep["summary_text"])
                                else:
                                    g_val = stats.get("gold", 0)
                                    gm_val = stats.get("gems", 0)
                                    k_val = stats.get("kills", 0)
                                    print(f"💰 [Phần thưởng ván] +{g_val:,} Vàng | 💎 +{gm_val:,} Gem | ⚔️ {k_val:,} Quái")
                            match_start_time = 0.0
                            active_skills.clear()
                            skill_levels.clear()
                            maxed_skills.clear()
                            last_monolith_pos = None
                            last_chest_pos = None
                            previous_direction = None
                            last_known_game_timer_sec = 0.0
                            last_timer_scan_time = 0.0
                            last_boss_alert_time = 0.0
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

                    # 4-6. Màn hình sảnh & bắt đầu trận (chỉ kiểm tra khi ngoài trận đấu)
                    if not match_running:
                        # 4. Màn hình chính -> Bấm "Start Game"
                        sg_pos = botcore.detect_start_game(frame)
                        if sg_pos:
                            controller.release()
                            if not config.get("auto_restart", True):
                                continue
                            match_running = False
                            active_skills.clear()
                            skill_levels.clear()
                            maxed_skills.clear()
                            match_start_time = 0.0
                            currencies = botcore.detect_main_screen_currencies(frame)
                            gold = currencies.get("gold")
                            gems = currencies.get("gems")
                            cur_info = ""
                            if gold is not None or gems is not None:
                                g_s = f"{gold:,} Vàng" if gold is not None else "---"
                                gem_s = f"{gems:,} Gem" if gems is not None else "---"
                                cur_info = f" [💰 {g_s} | 💎 {gem_s}]"
                                if last_lobby_gold is not None and gold is not None and gold >= last_lobby_gold:
                                    diff_g = gold - last_lobby_gold
                                    diff_gm = (gems - last_lobby_gems) if (gems is not None and last_lobby_gems is not None and gems >= last_lobby_gems) else 0
                                    if diff_g > 0 or diff_gm > 0:
                                        print(f"🎉 [Tổng kết sau trận] Vừa cộng: +{diff_g:,} Vàng | 💎 +{diff_gm:,} Gem (Tổng: {g_s} | {gem_s})")
                                last_lobby_gold = gold
                                last_lobby_gems = gems
                            if now - last_auto_action_time >= 1.5:
                                last_auto_action_time = now
                                controller.tap(list(sg_pos), rect)
                                print(f"🎮 [Sảnh chính]{cur_info} Tự động bấm 'Start Game'!")
                                time.sleep(1.2)
                            continue

                        # 5. Màn hình chọn nhân vật -> Bấm "Selected"
                        sel_pos = botcore.detect_selected(frame)
                        if sel_pos:
                            controller.release()
                            if not config.get("auto_restart", True):
                                continue
                            match_running = False
                            if now - last_auto_action_time >= 1.5:
                                last_auto_action_time = now
                                character = config.get("character", "summoner")
                                if select_character(controller, rect, frame, capture, character):
                                    print(f"[Chọn nhân vật] Đã chọn {character.title()} và xác nhận Selected.")
                                else:
                                    print(f"[Chọn nhân vật] Chưa xác nhận được {character}; sẽ đọc lại màn hình.")
                                time.sleep(1.2)
                            continue

                        # 6. Màn hình chọn map -> Bấm "Enter Area" bắt đầu trận mới
                        ea_pos = botcore.detect_enter_area(frame)
                        if ea_pos:
                            controller.release()
                            if not config.get("auto_restart", True):
                                continue
                            match_running = False
                            currencies = botcore.detect_main_screen_currencies(frame)
                            gold = currencies.get("gold")
                            gems = currencies.get("gems")
                            cur_header = ""
                            if gold is not None or gems is not None:
                                g_s = f"{gold:,} Vàng" if gold is not None else "---"
                                gem_s = f"{gems:,} Gem" if gems is not None else "---"
                                cur_header = f"💰 Tài nguyên hiện tại: {g_s} | 💎 {gem_s}"
                            if now - last_auto_action_time >= 1.5:
                                last_auto_action_time = now
                                if match_start_time == 0.0:
                                    recorder.start_new_run()
                                    match_start_time = now
                                run_id = recorder.current_run_id or "recording_disabled"
                                last_known_game_timer_sec = 0.0
                                last_timer_scan_time = 0.0
                                step_count = 0
                                last_monolith_pos = None
                                last_chest_pos = None
                                previous_direction = None
                                controller.tap(list(ea_pos), rect)
                                print("\n" + "-" * 60)
                                print(f"🔥 [TRẬN ĐẤU MỚI BẮT ĐẦU!] Mã ván: {run_id}")
                                if cur_header:
                                    print(f"   {cur_header}")
                                print("   Bot đang tự động né quái và cày vàng...")
                                print("-" * 60 + "\n")
                                time.sleep(1.2)
                            continue

                    # 7. MÀN HÌNH CHỌN THUỘC TÍNH (Level 4/7 Trait / Select Attribute - Có nút Learn)
                    if botcore.is_attribute_screen(frame) or botcore.detect_learn_button(frame) is not None:
                        controller.release()
                        match_running = True
                        if not config.get("auto_levelup", True):
                            continue
                        if now - last_learn_time >= 1.2:
                            last_learn_time = now
                            learned = select_attribute(controller, rect, capture)
                            if learned:
                                if learned.key:
                                    active_skills.add(learned.key)
                                recorder.record_decision(frame, "attribute", f"circle_{learned.index}",
                                                         metadata={"chosen_attribute": learned.label, "parent_skill": learned.key})
                                print(f"[Thuộc tính] Đã xác nhận học: {learned.label}")
                            else:
                                print("[Thuộc tính] Chưa xác nhận được Learn; đọc lại màn hình.")
                        continue

                    # 8. MÀN HÌNH LÊN CẤP (Level Up)
                    lvl_res = botcore.is_level_up_screen(frame)
                    if lvl_res:
                        controller.release()
                        if not config.get("auto_levelup", True):
                            continue
                        match_running = True
                        if now - last_timer_scan_time >= 1.5:
                            last_timer_scan_time = now
                            t_lvl = botcore.detect_game_timer(frame)
                            if t_lvl and t_lvl[2] >= last_known_game_timer_sec:
                                last_known_game_timer_sec = float(t_lvl[2])
                        if now - last_level_up_time >= 1.2:
                            last_level_up_time = now

                            # 8.1 Kiểm tra xem có mở khóa Phép Kết Hợp Fusion (ngôi sao đỏ góc trên-phải) không
                            combo_star_pos = botcore.detect_combination_star(frame)
                            if combo_star_pos and now - last_combination_attempt >= 10.0:
                                last_combination_attempt = time.monotonic()
                                learned = select_combination(controller, rect, frame, capture, config.get("skill_priority"))
                                if learned:
                                    active_skills.add(learned.key)
                                    maxed_skills.add(learned.key)
                                    recorder.record_decision(frame, "combination_magic", learned.key,
                                                             metadata={"combo_label": learned.label})
                                    print(f"[Combination] Đã xác nhận học: {learned.label}")
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
                                learner=learner,
                                skill_levels=skill_levels,
                                level_count=botcore.detect_player_level(frame) or step_count + 2,
                                early_priority_skills=config.get("early_priority_skills"),
                            )
                            card_idx, target = choice_res
                            choice_label = getattr(choice_res, "label", f"Thẻ {card_idx}")
                            if select_card(controller, rect, frame, choice_res, capture):
                                step_count += 1
                                remember_card(choice_res, active_skills, skill_levels, maxed_skills)
                                recorder.record_decision(frame, "level_up", f"card_{card_idx}",
                                                         metadata={"skill_key": choice_res.skill_key,
                                                                   "offered_level": choice_res.offered_level,
                                                                   "active_skills": sorted(active_skills)})
                                print(f"[Cấp #{step_count}] Đã xác nhận Thẻ {card_idx}: {choice_label}")
                        continue

                    # 9. MÀN HÌNH RƯƠNG CỔ VẬT (Obtain button)
                    obtain_pos = botcore.detect_obtain_button(frame)
                    if obtain_pos or botcore.is_chest_screen(frame):
                        controller.release()
                        if not config.get("auto_levelup", True) or not obtain_pos:
                            continue
                        match_running = True
                        if now - last_timer_scan_time >= 1.5:
                            last_timer_scan_time = now
                            t_ch = botcore.detect_game_timer(frame)
                            if t_ch and t_ch[2] >= last_known_game_timer_sec:
                                last_known_game_timer_sec = float(t_ch[2])
                        if now - last_chest_modal_time >= 1.2:
                            last_chest_modal_time = now
                            chosen = select_chest_artifact(
                                controller, rect, capture, active_skills=set(active_skills),
                                prefer_cc=config.get("prefer_crit_and_cooldown", True),
                            )
                            if chosen:
                                recorder.record_decision(
                                    frame, "chest", f"slot_{chosen.index}",
                                    metadata={"chosen_artifact": chosen.label, "active_skills": sorted(active_skills)},
                                )
                                print(f"[Rương] Đã xác nhận nhận cổ vật: {chosen.label} (ô {chosen.index})")
                                last_chest_pos = None
                            else:
                                print("[Rương] Chưa xác nhận nhận cổ vật; đọc lại màn hình.")
                        continue

                    # 11. MÀN HÌNH CỬA HÀNG THƯƠNG NHÂN (Merchant Shop)
                    shop_buy = botcore.detect_buy_button(frame)
                    if shop_buy:
                        controller.release()
                        if not config.get("auto_levelup", True):
                            continue
                        match_running = True
                        if now - last_shop_time >= 1.5:
                            last_shop_time = now
                            mana_val = botcore.detect_mana_orb_currency(frame)
                            mana_str = f" ({mana_val} Mana)" if mana_val is not None else ""
                            print(f"\n🛒 [Cửa hàng] Mở cửa hàng Thương nhân{mana_str}! Đang duyệt full 8 món đồ...")

                            shop_targets = botcore.get_shop_item_targets()
                            build_skills = set(active_skills)

                            best_buy_slot = None
                            best_buy_score = -1
                            best_buy_label = ""

                            shop_lost = False
                            for idx, s_pos in enumerate(shop_targets, 1):
                                controller.tap(list(s_pos), rect)
                                time.sleep(0.24)
                                f_item = capture()
                                shop_buy = botcore.detect_buy_button(f_item)
                                if shop_buy is None:
                                    shop_lost = True
                                    break

                                # Kiểm tra xem món này có đủ Mana mua không (nút Buy sáng trắng)
                                is_affordable = botcore.is_shop_buy_enabled(f_item, buy_pos=shop_buy)
                                s_score, s_lbl = botcore.evaluate_selected_shop_artifact(
                                    f_item,
                                    prefer_crit_and_cooldown=config.get("prefer_crit_and_cooldown", True),
                                    active_skills=build_skills,
                                )

                                # Kiểm tra xem món đồ có thực sự đáng mua không (hợp build hoặc Tier cao/Toy Castle)
                                is_worth = botcore.is_shop_artifact_worth_buying(s_score, s_lbl)

                                if is_affordable and is_worth:
                                    syn_tag = " [HỢP BUILD ⭐]" if ("Build:" in s_lbl or "★" in s_lbl or "Special" in s_lbl or "Legendary" in s_lbl) else ""
                                    print(f"   - Ô {idx}/8: [{s_lbl}] -> 🟢 ĐỦ MANA & ĐÁNG MUA (Điểm: {s_score}){syn_tag}")
                                    effective_score = s_score + (2000 if "Build:" in s_lbl else 0)
                                    if effective_score > best_buy_score:
                                        best_buy_score = effective_score
                                        best_buy_slot = s_pos
                                        best_buy_label = s_lbl
                                elif is_affordable:
                                    print(f"   - Ô {idx}/8: [{s_lbl}] -> 🟡 BỎ QUA (Không hợp build/không đáng tốn Mana)")
                                else:
                                    print(f"   - Ô {idx}/8: [{s_lbl}] -> 🔴 Chưa đủ Mana")

                            if shop_lost:
                                continue

                            # Quyết định mua hoặc đóng cửa hàng
                            if best_buy_slot and best_buy_score > 0 and botcore.is_shop_artifact_worth_buying(best_buy_score, best_buy_label):
                                controller.tap(list(best_buy_slot), rect)
                                time.sleep(0.25)
                                selected_item = capture()
                                fresh_buy = botcore.detect_buy_button(selected_item)
                                if not fresh_buy or not botcore.is_shop_buy_enabled(selected_item, fresh_buy):
                                    continue
                                controller.tap(list(fresh_buy), rect)
                                print(f"💰 [Cửa hàng] Đã mua thành công vật phẩm giá trị: [{best_buy_label}]!")
                                time.sleep(0.65)
                                f_after = capture()
                                x_pos = botcore.detect_shop_x_button(f_after)
                                if x_pos:
                                    controller.tap(list(x_pos), rect)
                                time.sleep(0.4)
                            else:
                                x_pos = botcore.detect_shop_x_button(capture())
                                if x_pos:
                                    controller.tap(list(x_pos), rect)
                                print(f"🛒 [Cửa hàng] Không có món phù hợp với build -> Giữ Mana, bấm 'X' đóng shop farm tiếp!")
                                time.sleep(0.5)
                        continue

                # 12. GIAI ĐOẠN CHIẾN ĐẤU TÍCH CỰC (In Active Combat)
                # Khi nút Pause (||) xuất hiện trên thanh HUD -> Nhân vật đang sống và chiến đấu trực tiếp!
                pause_pos = botcore.detect_pause_button(frame)
                if pause_pos and fast_combat:
                    match_running = True
                    if match_start_time == 0.0:
                        match_start_time = now

                    # Quét đồng hồ thời gian sống thực tế trên thanh HUD mỗi ~1.0 giây
                    if now - last_timer_scan_time >= 1.0:
                        last_timer_scan_time = now
                        t_live = botcore.detect_game_timer(frame)
                        if t_live and (t_live[2] >= last_known_game_timer_sec or last_known_game_timer_sec == 0.0):
                            last_known_game_timer_sec = float(t_live[2])

                    player_coords = tuple(config.get("player_position", [0.5, 0.5]))
                    px = int(w * player_coords[0])
                    py = int(h * player_coords[1])

                    # Phân tích thực địa: Quái vật, Đá/Tháp qua màn, Rương cổ vật, Mana Orbs
                    vision = botcore.inspect_game(
                        frame,
                        player=player_coords,
                        known_monolith=last_monolith_pos,
                        known_chest=last_chest_pos,
                    )

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

                    if not config.get("auto_chest", True):
                        vision.chest = None
                        last_chest_pos = None

                    # Theo dõi Rương cổ vật / Chỉ dẫn rương liên tục kèm bù trừ vector di chuyển
                    if getattr(vision, "chest", None) is not None:
                        raw_c = vision.chest
                        last_chest_pos = (int(raw_c[0]), int(raw_c[1]))
                        last_chest_hunt_time = now
                        c_type = getattr(vision, "chest_type", "treasure_chest")
                        last_chest_type = c_type
                        last_chest_weight = vision.chest_weight
                        if (
                            last_logged_chest_pos is None
                            or math.hypot(last_chest_pos[0] - last_logged_chest_pos[0], last_chest_pos[1] - last_logged_chest_pos[1]) > 50
                            or (now - last_chest_log_time >= 3.0)
                        ):
                            print(f"📦 [Săn Rương] ƯU TIÊN CAO: Phát hiện {c_type} tại {last_chest_pos}! Đang dũng mãnh lao tới nhặt...")
                            last_logged_chest_pos = last_chest_pos
                            last_chest_log_time = now
                    elif last_chest_pos is not None and (now - last_chest_hunt_time <= 3.0):
                        if previous_direction:
                            est_cx = int(round(last_chest_pos[0] - 12.0 * previous_direction[0]))
                            est_cy = int(round(last_chest_pos[1] - 12.0 * previous_direction[1]))
                            last_chest_pos = (est_cx, est_cy)
                        if (
                            -80 <= last_chest_pos[0] < w + 80
                            and -80 <= last_chest_pos[1] < h + 80
                            and math.hypot(last_chest_pos[0] - px, last_chest_pos[1] - py) > 8
                        ):
                            vision.chest = last_chest_pos
                            vision.chest_type = last_chest_type
                            vision.chest_weight = last_chest_weight
                        else:
                            last_chest_pos = None
                    else:
                        last_chest_pos = None

                    # Điều khiển né quái thông minh bằng thuật toán trường tiềm năng (Potential Field)
                    if getattr(vision, "bosses", None) and (now - last_boss_alert_time) >= 4.0:
                        last_boss_alert_time = now
                        print(f"⚠️ [Cảnh báo] Phát hiện {len(vision.bosses)} quái to (Elite/Boss) có thanh máu đỏ! Kích hoạt né tránh khẩn cấp!")

                    time_mult = 1.24 if str(config.get("game_map", "depth")).lower().strip() == "depth" else 1.0
                    mv_policy = getattr(learner, "get_movement_policy", lambda: {})()
                    if not isinstance(mv_policy, dict):
                        mv_policy = {}
                    enable_weave = bool(config.get("enable_human_weave", True))
                    raw_freq = mv_policy.get("weave_frequency", 3.2)
                    raw_amp = mv_policy.get("weave_amplitude", 0.28)
                    weave_freq = float(raw_freq) if isinstance(raw_freq, (int, float)) else 3.2
                    weave_amp = float(raw_amp) if isinstance(raw_amp, (int, float)) else 0.28
                    dir_x, dir_y = botcore.choose_direction(
                        vision,
                        elapsed=last_known_game_timer_sec if last_known_game_timer_sec > 0.0 else ((now - match_start_time) * time_mult),
                        player=player_coords,
                        previous=previous_direction,
                        active_skills=active_skills,
                        nearest_target_skills=config.get("nearest_target_skills"),
                        enable_weave=enable_weave,
                        weave_freq=weave_freq,
                        weave_amp=weave_amp,
                    )
                    if move_from_frame(controller, rect, config, (dir_x, dir_y), captured_at):
                        previous_direction = (dir_x, dir_y)
                    else:
                        previous_direction = None
                    continue

                # 13. TỰ ĐỘNG TIẾP TỤC NẾU BỊ TẠM DỪNG (Pause Menu Auto-Resume)
                resume_pos = botcore.detect_resume_button(frame)
                if resume_pos:
                    controller.release()
                    match_running = True
                    if now - last_auto_action_time >= 1.0:
                        last_auto_action_time = now
                        print(f"▶️ [Tự phục hồi] Phát hiện menu Tạm dừng -> Bấm 'Resume' tại {resume_pos} để tiếp tục chơi!")
                        controller.tap(list(resume_pos), rect)
                        time.sleep(0.4)
                    continue

                # 14. PHÁT HIỆN QUẢNG CÁO NGOÀI TRẬN ĐẤU (Video, Playable ad, AdMob) -> Bấm X hoặc Close tắt
                ad_x = botcore.detect_close_button(frame) if config.get("auto_close_ads", True) else None
                if ad_x:
                    controller.release()
                    match_running = False
                    if now - last_auto_action_time >= 1.2:
                        last_auto_action_time = now
                        if close_ad(controller, rect, capture) is not None:
                            print("[Quảng cáo] Đã bấm nút đóng tìm được trên ảnh mới.")
                        time.sleep(1.2)
                    continue
                elif config.get("auto_close_ads", True) and botcore.is_ad_screen(frame):
                    controller.release()
                    match_running = False
                    if now - last_auto_action_time >= 3.0:
                        last_auto_action_time = now
                        if back_from_ad(controller, rect, capture):
                            print("[Quảng cáo] Đã xác nhận còn quảng cáo trên ảnh mới rồi bấm Back.")
                        time.sleep(1.0)
                    continue

                controller.release()
                previous_direction = None
            except (ADBCommandError, FrameCaptureError) as error:
                controller.release()
                previous_direction = None
                last_chest_pos = last_monolith_pos = None
                rule_streak_name, rule_streak = "", 0
                print(f"[ADB] Tạm ngắt input: {error}. Sẽ chụp ảnh mới trước khi tiếp tục.")
                time.sleep(0.5)
            except ActionCancelled:
                controller.release()
                previous_direction = None
                if now - last_focus_warning >= 5.0:
                    last_focus_warning = now
                    print("[⏸️] Cửa sổ game tạm mất focus. Tạm dừng thao tác, chờ bạn quay lại cửa sổ game...")
                time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[!] Đã nhận lệnh dừng từ bàn phím. Đang giải phóng bộ điều khiển...")
        if controller:
            controller.release()
        print("[+] Bot đã dừng an toàn. Hẹn gặp lại bạn!\n")
    finally:
        controller.release()
        shutdown = getattr(controller, "close", None)
        if shutdown is not None:
            shutdown()


if __name__ == "__main__":
    run_cli_bot()
