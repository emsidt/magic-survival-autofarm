"""Magic Survival screen-based farm helper for Windows / Google Play Games PC.

Run `python main.py`. Start/pause with F8 and stop input with F9.
This program never interacts with game files, memory, payments, or networking.
"""

from __future__ import annotations

import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import json
import math
import os
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import cv2
import mss
import numpy as np
from PIL import Image, ImageTk
import pydirectinput
from pynput import keyboard
import win32api, win32gui, win32process, win32con
pydirectinput.FAILSAFE = False

from botcore import (
    choose_best_artifact_or_card,
    choose_direction,
    detect_buy_button,
    detect_chest,
    detect_close_button,
    detect_combination_star,
    detect_confirm_button,
    detect_die_button,
    detect_enter_area,
    detect_learn_button,
    detect_monolith,
    detect_obtain_button,
    detect_selected,
    detect_settings_dialog,
    detect_settings_gear,
    detect_start_game,
    detect_shop_x_button,
    evaluate_selected_attribute,
    evaluate_selected_chest_artifact,
    evaluate_selected_shop_artifact,
    find_best_combination_option,
    find_rule,
    get_attribute_circle_targets,
    get_chest_card_target,
    get_shop_item_targets,
    get_upgrade_target,
    inspect_game,
    is_level_up_screen,
    is_shop_buy_enabled,
    is_three_card_chest,
)
from data_recorder import DataRecorder
from learning_engine import AdaptiveLearner


BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
RULES_PATH = BASE / "rules.json"
RULE_IMAGE_DIR = BASE / "rules"
DEFAULTS = {
    "window_title": "Magic Survival",
    "input_mode": "keyboard",
    "crop_left_px": 65,
    "crop_top_px": 0,
    "crop_right_px": 0,
    "crop_bottom_px": 0,
    "player_position": [0.5, 0.5],
    "joystick_position": [0.08, 0.12],
    "joystick_radius_px": 65,
    "fps": 30,
    "max_session_minutes": 120,
    "auto_levelup": True,
    "card_choice": 1,
    "auto_close_ads": True,
    "auto_restart": True,
    "auto_chest": True,
    "skill_priority": [
        "telekinetic_sword",
        "superconductivity",
        "current_overload",
        "spirit",
        "electric_shock",
        "vortex",
        "black_hole",
        "neutron_generation",
        "cyclone",
        "satellite",
        "blizzard",
        "frost_nova",
        "tsunami",
        "flash_shock",
        "perpetual_engine",
        "overmind",
        "demon_equation",
        "frenzy",
        "prism_spree",
        "magic_circle",
        "shield",
        "cloaking",
        "armageddon",
        "electric_zone",
        "arcane_ray",
        "fast_casting",
        "haste",
        "snipe",
        "vitality",
        "intelligence",
        "arcane_effuse",
        "concentration",
        "explorer",
    ],
    "prefer_freeze_traits": True,
    "prefer_crit_and_cooldown": True,
}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def save_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def locate_game(title: str):
    try:
        user32 = ctypes.windll.user32
        hwinsta0 = user32.OpenWindowStationW("WinSta0", False, 0x0000037F)
        if hwinsta0:
            user32.SetProcessWindowStation(hwinsta0)
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
    except Exception:
        pass

    candidates = []

    def visit(hwnd, _):
        window_text = win32gui.GetWindowText(hwnd).lower()
        if (win32gui.IsWindowVisible(hwnd) and title.lower() in window_text
                and "autofarm" not in window_text):
            if win32gui.IsIconic(hwnd):
                try:
                    win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                except Exception:
                    pass
            try:
                left, top, right, bottom = win32gui.GetClientRect(hwnd)
                # Must be a real gameplay window, not a tiny splash/launcher dialog
                if (right - left) >= 300 and (bottom - top) >= 400:
                    candidates.append(hwnd)
            except Exception:
                pass

    win32gui.EnumWindows(visit, None)
    return candidates[0] if candidates else None


def game_rectangle(hwnd: int, config: dict) -> dict:
    # Auto-detect Google Play Games PC renderer child window if available
    crosvm_child: list[int] = []

    def _find_crosvm(child_hwnd, _):
        try:
            w_text = win32gui.GetWindowText(child_hwnd).lower()
            c_text = win32gui.GetClassName(child_hwnd).lower()
            if "crosvm" in w_text or "crosvm" in c_text:
                crosvm_child.append(child_hwnd)
        except Exception:
            pass

    try:
        win32gui.EnumChildWindows(hwnd, _find_crosvm, None)
    except Exception:
        pass

    if crosvm_child:
        cl, ct, cr, cb = win32gui.GetClientRect(crosvm_child[0])
        ox, oy = win32gui.ClientToScreen(crosvm_child[0], (cl, ct))
        width = cr - cl
        height = cb - ct
        if width >= 250 and height >= 350:
            return {"left": ox, "top": oy, "width": width, "height": height}

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    origin_x, origin_y = win32gui.ClientToScreen(hwnd, (left, top))
    x = origin_x + int(config.get("crop_left_px", 0))
    y = origin_y + int(config.get("crop_top_px", 0))
    width = right - left - int(config.get("crop_left_px", 0)) - int(config.get("crop_right_px", 0))
    height = bottom - top - int(config.get("crop_top_px", 0)) - int(config.get("crop_bottom_px", 0))
    if width < 180 or height < 250:
        raise ValueError("Game crop quá nhỏ; kiểm tra 4 giá trị crop trong config.json")
    return {"left": x, "top": y, "width": width, "height": height}


def is_game_or_popup_active(hwnd: int, post_death_phase: bool = False) -> tuple[bool, int]:
    """Check if the active foreground window is the game window, a child, or an ad popup.
    Returns (is_active, target_hwnd).
    """
    fg = win32gui.GetForegroundWindow()
    if not fg:
        return False, hwnd
    if fg == hwnd:
        return True, hwnd
    if win32gui.IsChild(hwnd, fg):
        return True, hwnd
    try:
        root = win32gui.GetAncestor(fg, win32con.GA_ROOT)
        if root == hwnd:
            return True, hwnd
        root_owner = win32gui.GetAncestor(fg, win32con.GA_ROOTOWNER)
        if root_owner == hwnd:
            return True, hwnd
    except Exception:
        pass

    try:
        _, game_pid = win32process.GetWindowThreadProcessId(hwnd)
        _, fg_pid = win32process.GetWindowThreadProcessId(fg)
        if game_pid != 0 and game_pid == fg_pid:
            return True, fg
    except Exception:
        pass

    # During post-death phase (waiting/closing ads), an ad popup may be created
    # by Google Play Games overlay or an in-game browser window
    if post_death_phase:
        try:
            gl, gt, gr, gb = win32gui.GetWindowRect(hwnd)
            fl, ft, fr, fb = win32gui.GetWindowRect(fg)
            # Check overlap between game window and foreground window
            if not (fr <= gl or fl >= gr or fb <= gt or ft >= gb):
                fw = fr - fl
                fh = fb - ft
                if fw >= 150 and fh >= 150:
                    return True, fg
        except Exception:
            pass

    return False, hwnd


_GRABBER: Optional[mss.mss] = None


def get_grabber() -> mss.mss:
    global _GRABBER
    if _GRABBER is None:
        _GRABBER = mss.mss()
    return _GRABBER


def screenshot(rect: dict) -> np.ndarray:
    global _GRABBER
    try:
        grabber = get_grabber()
        shot = np.asarray(grabber.grab(rect))
        return np.ascontiguousarray(shot[:, :, :3])
    except Exception:
        # Recreate GDI context cleanly if Windows desktop surface changes
        try:
            if _GRABBER:
                _GRABBER.close()
        except Exception:
            pass
        _GRABBER = mss.mss()
        shot = np.asarray(_GRABBER.grab(rect))
        return np.ascontiguousarray(shot[:, :, :3])


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.keys: set[str] = set()
        self.mouse_held = False
        self.last_key_refresh = 0.0
        pydirectinput.PAUSE = 0.0

    def release(self):
        with self.lock:
            # Explicitly release all movement keys to guarantee no keys remain stuck in Windows OS
            for key in ("w", "a", "s", "d"):
                try:
                    pydirectinput.keyUp(key)
                except Exception:
                    pass
            self.keys.clear()
            if self.mouse_held:
                try:
                    pydirectinput.mouseUp()
                except Exception:
                    pass
                self.mouse_held = False

    def move(self, direction: tuple[float, float], rect: dict, config: dict):
        with self.lock:
            dx, dy = direction
            if config["input_mode"] == "keyboard":
                if self.mouse_held:
                    pydirectinput.mouseUp()
                    self.mouse_held = False
                desired = set()
                th_on = 0.28
                th_off = 0.16

                # Y axis (w / s) with hysteresis to eliminate stutter/key chatter
                if "w" in self.keys:
                    if dy < -th_off:
                        desired.add("w")
                else:
                    if dy < -th_on:
                        desired.add("w")

                if "s" in self.keys:
                    if dy > th_off:
                        desired.add("s")
                else:
                    if dy > th_on:
                        desired.add("s")

                # X axis (a / d) with hysteresis
                if "a" in self.keys:
                    if dx < -th_off:
                        desired.add("a")
                else:
                    if dx < -th_on:
                        desired.add("a")

                if "d" in self.keys:
                    if dx > th_off:
                        desired.add("d")
                else:
                    if dx > th_on:
                        desired.add("d")

                for key in self.keys - desired:
                    pydirectinput.keyUp(key)
                for key in desired - self.keys:
                    pydirectinput.keyDown(key)

                # Re-assert held keys only occasionally (2.5s) instead of 0.35s to prevent emulator stutter
                now = time.monotonic()
                if now - self.last_key_refresh >= 2.5:
                    for key in desired & self.keys:
                        pydirectinput.keyDown(key)
                    self.last_key_refresh = now
                self.keys = desired
            else:
                for key in tuple(self.keys):
                    pydirectinput.keyUp(key)
                self.keys.clear()
                jx, jy = config["joystick_position"]
                base_x = int(rect["left"] + rect["width"] * jx)
                base_y = int(rect["top"] + rect["height"] * jy)
                radius = int(config["joystick_radius_px"])
                if not self.mouse_held:
                    pydirectinput.moveTo(base_x, base_y)
                    pydirectinput.mouseDown()
                    self.mouse_held = True
                pydirectinput.moveTo(base_x + int(dx * radius), base_y + int(dy * radius))

    def tap(self, target: list[float], rect: dict):
        with self.lock:
            self.release()
            x = int(round(rect["left"] + target[0] * rect["width"]))
            y = int(round(rect["top"] + target[1] * rect["height"]))
            clicked = False
            try:
                win32api.SetCursorPos((x, y))
                time.sleep(0.04)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.06)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                clicked = True
            except Exception:
                pass
            if not clicked:
                try:
                    pydirectinput.moveTo(x, y)
                    time.sleep(0.04)
                    pydirectinput.mouseDown()
                    time.sleep(0.06)
                    pydirectinput.mouseUp()
                except Exception:
                    pass

    def press_esc(self):
        with self.lock:
            self.release()
            try:
                pydirectinput.press("esc")
            except Exception:
                pass
            try:
                win32api.keybd_event(win32con.VK_ESCAPE, 0, 0, 0)
                time.sleep(0.04)
                win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass


class FarmApp:
    def __init__(self, autostart: bool = False):
        self.root = tk.Tk()
        self.root.title("Magic Survival AutoFarm – PC")
        self.root.geometry("760x860")
        self.root.minsize(700, 780)
        self.autostart = autostart
        self.config = {**DEFAULTS, **read_json(CONFIG_PATH, {})}
        self.rules = read_json(RULES_PATH, [])
        self.events = queue.Queue(maxsize=30)
        self.controller = Controller()
        self.running = threading.Event()
        self.ending = threading.Event()
        self.input_mode = tk.StringVar(value=self.config["input_mode"])
        self.crop_left = tk.StringVar(value=str(self.config["crop_left_px"]))
        self.limit_mins = tk.StringVar(value=str(self.config["max_session_minutes"]))
        self.auto_levelup = tk.BooleanVar(value=bool(self.config.get("auto_levelup", True)))
        self.card_choice = tk.IntVar(value=int(self.config.get("card_choice", 1)))
        self.auto_close_ads = tk.BooleanVar(value=bool(self.config.get("auto_close_ads", True)))
        self.auto_restart = tk.BooleanVar(value=bool(self.config.get("auto_restart", True)))
        self.auto_chest = tk.BooleanVar(value=bool(self.config.get("auto_chest", True)))
        self.recorder = DataRecorder(
            enabled=bool(self.config.get("record_gameplay_data", True)),
            max_runs=int(self.config.get("max_data_runs", 50)),
        )
        self.learner = AdaptiveLearner()
        self.status = tk.StringVar(value="Sẵn sàng. F8 bắt đầu / tạm dừng; F9 dừng.")
        self.metrics = tk.StringVar(value="Chưa chạy")
        self.frame_snapshot = None
        self.render_photo = None
        self.canvas_scale = 1.0
        self.anchor_start = None
        self.anchor_box = None
        self.rule_name = None
        self.calibration_mode = None
        self.previous_direction = None
        self.pressed_hotkeys: set = set()
        self.session_start = None
        self.rule_counts: dict[str, int] = {}
        self._layout()
        self._refresh_rules()
        self.root.after(30, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker = threading.Thread(target=self._bot_loop, daemon=True)
        self.worker.start()
        self.hotkeys = keyboard.Listener(on_press=self._key_down, on_release=self._key_up)
        self.hotkeys.start()
        if self.autostart:
            self.root.after(600, self.toggle)

    def _layout(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, width=345, height=640, bg="#20232a", highlightthickness=1)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.canvas.bind("<ButtonPress-1>", self._mouse_down)
        self.canvas.bind("<B1-Motion>", self._mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_up)
        self.canvas.create_text(172, 270, text="Chụp màn hình để xem game", fill="#e5e7eb")

        tools = ttk.Frame(outer)
        tools.grid(row=0, column=1, sticky="nsew")
        ttk.Label(tools, text="Magic Survival AutoFarm", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(tools, text="Điều khiển", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Radiobutton(tools, text="WASD (Google Play keymap)", variable=self.input_mode,
                        value="keyboard").pack(anchor="w")
        ttk.Radiobutton(tools, text="Kéo joystick bằng chuột", variable=self.input_mode,
                        value="mouse").pack(anchor="w")

        row = ttk.Frame(tools)
        row.pack(fill="x", pady=(6, 2))
        ttk.Label(row, text="Bỏ thanh bên (px):").pack(side="left")
        ttk.Entry(row, width=5, textvariable=self.crop_left).pack(side="right")
        row = ttk.Frame(tools)
        row.pack(fill="x", pady=(2, 7))
        ttk.Label(row, text="Giới hạn (phút):").pack(side="left")
        ttk.Entry(row, width=5, textvariable=self.limit_mins).pack(side="right")

        ttk.Button(tools, text="▶ Bắt đầu / Tạm dừng (F8)", command=self.toggle).pack(fill="x", pady=3)
        ttk.Button(tools, text="■ Dừng (F9)", command=self.stop).pack(fill="x", pady=3)
        ttk.Button(tools, text="📷 Chụp game (F10)", command=self.take_snapshot).pack(fill="x", pady=3)

        ttk.Separator(tools).pack(fill="x", pady=8)
        ttk.Label(tools, text="Tự động thông minh (Auto-Pilot)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Checkbutton(tools, text="Tự tắt quảng cáo khi chết (Nút X)", variable=self.auto_close_ads).pack(anchor="w", pady=1)
        ttk.Checkbutton(tools, text="Tự chạy đến rương item (Chest)", variable=self.auto_chest).pack(anchor="w", pady=1)
        ttk.Checkbutton(tools, text="Tự chọn nâng cấp (Level Up)", variable=self.auto_levelup).pack(anchor="w", pady=1)

        card_row = ttk.Frame(tools)
        card_row.pack(fill="x", padx=16, pady=1)
        ttk.Label(card_row, text="Ưu tiên thẻ:").pack(side="left")
        ttk.Radiobutton(card_row, text="1", variable=self.card_choice, value=1).pack(side="left", padx=2)
        ttk.Radiobutton(card_row, text="2", variable=self.card_choice, value=2).pack(side="left", padx=2)
        ttk.Radiobutton(card_row, text="3", variable=self.card_choice, value=3).pack(side="left", padx=2)

        ttk.Checkbutton(tools, text="Tự chơi lại khi chết (Auto Restart)", variable=self.auto_restart).pack(anchor="w", pady=1)

        ttk.Separator(tools).pack(fill="x", pady=8)
        ttk.Label(tools, text="Học nút thủ công (Tùy chọn)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(tools, text="Nếu muốn tự chọn nút riêng, bấm F10 rồi thêm quy tắc bên dưới.",
                  wraplength=300, justify="left").pack(anchor="w", pady=2)
        ttk.Button(tools, text="+ Thêm quy tắc", command=self.start_calibration).pack(fill="x", pady=2)
        ttk.Button(tools, text="Xóa quy tắc đã chọn", command=self.delete_rule).pack(fill="x", pady=2)
        self.rule_list = tk.Listbox(tools, height=4, exportselection=False)
        self.rule_list.pack(fill="x", pady=4)
        ttk.Separator(tools).pack(fill="x", pady=6)
        ttk.Label(tools, text="Ghi chú", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(tools, text="Đưa game ra trước khi chạy.\n"
                              "Không lưu và không can thiệp dữ liệu game.",
                  wraplength=300, justify="left").pack(anchor="w", pady=2)

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        footer = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        footer.pack(side="bottom", fill="x")
        ttk.Label(footer, textvariable=self.status, wraplength=700).pack(anchor="w")
        ttk.Label(footer, textvariable=self.metrics, foreground="#465e83").pack(anchor="w", pady=(2, 0))

    def _refresh_rules(self):
        self.rule_list.delete(0, tk.END)
        for rule in self.rules:
            self.rule_list.insert(tk.END, f"{rule['name']} → bấm {rule['target'][0]:.2f}, {rule['target'][1]:.2f}")

    def _save_config(self):
        try:
            self.config["input_mode"] = self.input_mode.get()
            self.config["crop_left_px"] = int(self.crop_left.get())
            self.config["max_session_minutes"] = int(self.limit_mins.get())
            self.config["auto_levelup"] = bool(self.auto_levelup.get())
            self.config["card_choice"] = int(self.card_choice.get())
            self.config["auto_close_ads"] = bool(self.auto_close_ads.get())
            self.config["auto_restart"] = bool(self.auto_restart.get())
            self.config["auto_chest"] = bool(self.auto_chest.get())
            if not 0 <= self.config["crop_left_px"] <= 250:
                raise ValueError("crop cần từ 0 đến 250")
            if not 1 <= self.config["max_session_minutes"] <= 1440:
                raise ValueError("phút phải từ 1 đến 1440")
            save_json(CONFIG_PATH, self.config)
            return True
        except ValueError as error:
            messagebox.showerror("Cấu hình không hợp lệ", str(error))
            return False

    def toggle(self):
        if self.running.is_set():
            self.stop()
        else:
            if not self._save_config():
                return
            self.running.set()
            self.session_start = time.monotonic()
            self.status.set("Đang chờ cửa sổ Magic Survival được đưa ra trước...")

    def stop(self):
        self.running.clear()
        self.controller.release()
        self.previous_direction = None
        self.status.set("Đã dừng input. Nhấn F8 để chạy lại.")

    def _key_down(self, key):
        if key in (keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10) and key not in self.pressed_hotkeys:
            self.pressed_hotkeys.add(key)
            try:
                self.events.put_nowait(("hotkey", key))
            except queue.Full:
                pass

    def _key_up(self, key):
        self.pressed_hotkeys.discard(key)

    def _push(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            if kind != "preview":
                try:
                    self.events.get_nowait()
                    self.events.put_nowait((kind, value))
                except Exception:
                    pass

    def _bot_loop(self):
        controller = self.controller
        streak_name = ""
        streak = 0
        last_click: dict[str, float] = {}
        next_preview = 0.0
        last_gameplay_time = 0.0
        last_ad_close_time = 0.0
        last_auto_action_time = 0.0
        last_die_click_time = 0.0
        last_chest_obtain_time = 0.0
        last_chest_scan_time = 0.0
        last_shop_action_time = 0.0
        last_shop_scan_time = 0.0
        last_learn_click_time = 0.0
        last_attribute_scan_time = 0.0
        last_confirm_click_time = 0.0
        ad_wait_start_time = 0.0
        active_skills: set[str] = set()
        uncertain_since = 0.0
        level_up_clicks = 0
        match_running = False
        post_death_phase = False
        last_chest_pos: Optional[tuple[int, int]] = None
        last_chest_type: str = "treasure_chest"
        last_chest_weight: float = 24.0
        last_chest_time: float = 0.0
        last_monolith_pos: Optional[tuple[int, int]] = None
        last_monolith_time: float = 0.0
        match_start_time: float = 0.0
        while not self.ending.is_set():
            try:
                while not self.ending.is_set():
                    if not self.running.is_set():
                        controller.release()
                        time.sleep(0.12)
                        continue

                    start_tick = time.monotonic()
                    if self.session_start and start_tick - self.session_start > 60 * self.config["max_session_minutes"]:
                        self.running.clear()
                        controller.release()
                        self._push("status", "Đã dừng vì hết giới hạn thời gian.")
                        continue

                    hwnd = locate_game(self.config["window_title"])
                    if not hwnd:
                        controller.release()
                        self._push("status", "Không tìm thấy cửa sổ Magic Survival.")
                        time.sleep(1.0)
                        continue

                    is_active, active_wnd = is_game_or_popup_active(hwnd, post_death_phase)
                    if not is_active:
                        if hwnd and not post_death_phase:
                            try:
                                win32gui.SetForegroundWindow(hwnd)
                                time.sleep(0.25)
                                is_active, active_wnd = is_game_or_popup_active(hwnd, post_death_phase)
                            except Exception:
                                pass
                    if not is_active:
                        controller.release()
                        self._push("status", "Đang chờ: hãy nhấp cửa sổ game để điều khiển an toàn.")
                        time.sleep(0.4)
                        continue

                    # Luôn quét chính xác kích thước khung hình chuẩn của game (Client viewport, không dính thanh tiêu đề/viền)
                    rect = game_rectangle(hwnd, self.config)
                    # Nếu có cửa sổ popup độc lập hoàn toàn ngoài cây cửa sổ game:
                    if active_wnd and active_wnd != hwnd and post_death_phase:
                        try:
                            # Tuyệt đối không dùng GetWindowRect vì dính thanh tiêu đề/viền làm lệch tọa độ
                            # Chỉ dùng nếu active_wnd là cửa sổ độc lập (không phải child hay root của game)
                            if not win32gui.IsChild(hwnd, active_wnd) and win32gui.GetAncestor(active_wnd, win32con.GA_ROOT) != hwnd:
                                cl, ct, cr, cb = win32gui.GetClientRect(active_wnd)
                                ox, oy = win32gui.ClientToScreen(active_wnd, (cl, ct))
                                pw, ph = cr - cl, cb - ct
                                if pw >= 150 and ph >= 150:
                                    rect = {"left": ox, "top": oy, "width": pw, "height": ph}
                        except Exception:
                            pass

                    frame = screenshot(rect)
                    found = find_rule(frame, self.rules, str(BASE))
                    direction = None
                    current_vision = None
                    scene = found["name"] if found else ""
                    if scene:
                        controller.release()
                        if scene == streak_name:
                            streak += 1
                        else:
                            streak_name, streak = scene, 1
                        if streak >= 2 and start_tick - last_click.get(scene, 0.0) >= 3.2:
                            controller.tap(found["target"], rect)
                            last_click[scene] = start_tick
                            self.rule_counts[scene] = self.rule_counts.get(scene, 0) + 1
                            self._push("status", f"Đã bấm quy tắc: {scene}")
                            time.sleep(0.65)
                    else:
                        streak_name, streak = "", 0
                        auto_action_done = False

                        # 0. MÀN HÌNH CHẾT "Life or Death" -> BẤM "DIE" NGAY LẬP TỨC (bỏ qua xem quảng cáo Revive)
                        die_pos = detect_die_button(frame)
                        if die_pos:
                            controller.release()
                            self.previous_direction = None
                            match_running = False
                            post_death_phase = True
                            if start_tick - last_die_click_time >= 1.2:
                                controller.tap(list(die_pos), rect)
                                last_die_click_time = start_tick
                                last_auto_action_time = start_tick
                                self.rule_counts["bam_die"] = self.rule_counts.get("bam_die", 0) + 1
                                self._push("status", f"Nhân vật đã chết: Tự động bấm 'Die' tại ({die_pos[0]:.2f}, {die_pos[1]:.2f})!")
                                auto_action_done = True
                                time.sleep(0.8)
                            continue

                        # 0.1 MÀN HÌNH KẾT QUẢ "Experiment Failed" -> BẤM "CONFIRM"
                        confirm_pos = detect_confirm_button(frame)
                        if confirm_pos:
                            controller.release()
                            self.previous_direction = None
                            last_monolith_pos = None
                            match_running = False
                            post_death_phase = True
                            if start_tick - last_confirm_click_time >= 2.0:
                                self.recorder.record_decision(frame, "endgame", "confirm")
                                self.recorder.finish_run()
                                if match_start_time > 0.0:
                                    survival_seconds = time.monotonic() - match_start_time
                                    match_start_time = 0.0
                                    try:
                                        learn_rep = self.learner.evaluate_and_learn_run(
                                            run_id=self.recorder.current_run_id or "run",
                                            survival_seconds=survival_seconds,
                                            active_skills=set(active_skills),
                                            core_skills=set(self.config.get("skill_priority", [])),
                                        )
                                        m, s = int(survival_seconds // 60), int(survival_seconds % 60)
                                        avg_m, avg_s = int(learn_rep["new_avg_survival"] // 60), int(learn_rep["new_avg_survival"] % 60)
                                        diff_sec = learn_rep.get("diff_sec", 0.0)
                                        diff_m, diff_s = int(abs(diff_sec) // 60), int(abs(diff_sec) % 60)
                                        r_sign = "+" if learn_rep["reward"] >= 0 else ""
                                        comp_str = f"vượt TB +{diff_m:02d}:{diff_s:02d}" if diff_sec >= 0 else f"kém TB -{diff_m:02d}:{diff_s:02d}"
                                        self._push(
                                            "status",
                                            f"[AI Learning] Ván {m:02d}:{s:02d} ({comp_str}, TB: {avg_m:02d}:{avg_s:02d}) -> {r_sign}{learn_rep['reward']:.2f}đ, cập nhật {len(learn_rep['skills_updated'])} kỹ năng!",
                                        )
                                    except Exception:
                                        pass
                                active_skills.clear()
                                controller.tap(list(confirm_pos), rect)
                                now_tick = time.monotonic()
                                last_confirm_click_time = now_tick
                                ad_wait_start_time = now_tick
                                last_auto_action_time = now_tick
                                self.rule_counts["confirm_ket_qua"] = self.rule_counts.get("confirm_ket_qua", 0) + 1
                                self._push("status", f"[Endgame] Bấm 'Confirm' tại ({confirm_pos[0]:.2f}, {confirm_pos[1]:.2f}) -> Bắt đầu chờ quảng cáo (~10s)...")
                                auto_action_done = True
                                time.sleep(1.2)
                            continue

                        # A0. KIỂM TRA MENU CÀI ĐẶT (SETTINGS POPUP):
                        # Nếu lỡ bị mở menu Cài đặt, tự động nhấn phím ESC để thoát ngay lập tức!
                        if detect_settings_dialog(frame):
                            controller.press_esc()
                            self._push("status", "[Cài đặt] Phát hiện menu Cài đặt (Settings) đang mở -> Tự động bấm ESC để đóng và quay lại Start Game!")
                            time.sleep(0.5)
                            continue

                        # A1. ƯU TIÊN MÀN HÌNH CHÍNH (TITLE SCREEN): Bấm "Start Game"
                        # Luôn kiểm tra Start Game trước post_death_phase để TUYỆT ĐỐI KHÔNG BẤM VÀO CÀI ĐẶT
                        sg_pos = detect_start_game(frame)
                        if sg_pos:
                            match_running = False
                            post_death_phase = False
                            active_skills.clear()
                            ad_wait_start_time = 0.0
                            match_start_time = 0.0
                            if self.config.get("auto_restart", True) and (start_tick - last_auto_action_time >= 1.5):
                                controller.tap(list(sg_pos), rect)
                                last_auto_action_time = start_tick
                                self.rule_counts["start_game"] = self.rule_counts.get("start_game", 0) + 1
                                self._push("status", f"Phát hiện màn hình chính: Tự động bấm 'Start Game' tại ({sg_pos[0]:.2f}, {sg_pos[1]:.2f}) - Tuyệt đối không bấm Cài đặt!")
                                auto_action_done = True
                                time.sleep(1.2)
                            continue

                        # A2. MÀN HÌNH CHỌN NHÂN VẬT (CLASS SCREEN): Bấm "Selected"
                        sel_pos = detect_selected(frame)
                        if sel_pos:
                            match_running = False
                            post_death_phase = False
                            active_skills.clear()
                            ad_wait_start_time = 0.0
                            match_start_time = 0.0
                            if self.config.get("auto_restart", True) and (start_tick - last_auto_action_time >= 1.5):
                                controller.tap(list(sel_pos), rect)
                                last_auto_action_time = start_tick
                                self.rule_counts["selected"] = self.rule_counts.get("selected", 0) + 1
                                self._push("status", f"Phát hiện màn hình chọn nhân vật: Tự động bấm 'Selected' tại ({sel_pos[0]:.2f}, {sel_pos[1]:.2f})!")
                                auto_action_done = True
                                time.sleep(1.2)
                            continue

                        # A3. MÀN HÌNH SẢNH / CHỌN MAP (ENTER AREA SCREEN): Bấm "Enter Area"
                        ea_pos = detect_enter_area(frame)
                        if ea_pos:
                            match_running = False
                            post_death_phase = False
                            active_skills.clear()
                            ad_wait_start_time = 0.0
                            if self.config.get("auto_restart", True) and (start_tick - last_auto_action_time >= 1.5):
                                self.recorder.start_new_run()
                                match_start_time = time.monotonic()
                                controller.tap(list(ea_pos), rect)
                                last_auto_action_time = start_tick
                                self.rule_counts["enter_area"] = self.rule_counts.get("enter_area", 0) + 1
                                self._push("status", "Phát hiện màn hình chọn map: Tự động bấm 'Enter Area' vào trận mới!")
                                auto_action_done = True
                                time.sleep(1.2)
                            continue

                        # A4. POPUP QUẢNG CÁO HẬU TRẬN ĐẤU (TUYỆT ĐỐI KHÔNG CHẠY TRONG LÚC ĐANG GAMEPLAY):
                        if (post_death_phase or not match_running) and self.config.get("auto_close_ads", True):
                            close_pos = detect_close_button(frame)
                            if close_pos and (start_tick - last_ad_close_time >= 1.2):
                                controller.tap(list(close_pos), rect)
                                time.sleep(0.25)
                                controller.press_esc()
                                now_tick = time.monotonic()
                                last_ad_close_time = now_tick
                                last_auto_action_time = now_tick
                                ad_wait_start_time = 0.0
                                self.rule_counts["tat_quang_cao"] = self.rule_counts.get("tat_quang_cao", 0) + 1
                                self._push("status", f"[Quảng cáo] Phát hiện nút đóng: Đã bấm tại ({close_pos[0]:.2f}, {close_pos[1]:.2f}) & gửi ESC!")
                                auto_action_done = True
                                time.sleep(1.0)
                                continue

                        # C. KẾT THÚC VÁN (HẬU CHẾT): Xử lý quảng cáo và quay lại sảnh
                        if post_death_phase:
                            now_tick = time.monotonic()
                            elapsed_ad = now_tick - ad_wait_start_time if ad_wait_start_time > 0 else 999.0

                            # 1. Tìm & bấm nút X / Close / Skip quảng cáo nếu đã phát hiện vị trí
                            close_pos = detect_close_button(frame) if self.config.get("auto_close_ads", True) else None
                            if close_pos and (now_tick - last_ad_close_time >= 1.2):
                                controller.tap(list(close_pos), rect)
                                time.sleep(0.25)
                                controller.press_esc()
                                last_ad_close_time = now_tick
                                last_auto_action_time = now_tick
                                ad_wait_start_time = 0.0
                                self.rule_counts["tat_quang_cao"] = self.rule_counts.get("tat_quang_cao", 0) + 1
                                self._push("status", f"[Quảng cáo] Đã bấm nút X / Close tại ({close_pos[0]:.2f}, {close_pos[1]:.2f}) & gửi ESC!")
                                auto_action_done = True
                                time.sleep(1.0)
                                continue

                            # 2. Đang trong 4 giây đầu xem video quảng cáo (chờ video tải/chạy):
                            if ad_wait_start_time > 0 and elapsed_ad < 4.0:
                                self._push("status", f"[Quảng cáo] Đang chờ video quảng cáo ({elapsed_ad:.0f}s)...")
                                auto_action_done = True
                                time.sleep(1.0)
                                continue

                            # 3. Chuỗi hành động đóng quảng cáo toàn năng (Universal Ad Closer):
                            # Thực hiện định kỳ mỗi 1.8s khi đang kẹt ở màn hình quảng cáo:
                            # - Bấm nút X góc trên-phải chuẩn (Google AdMob / Unity Ads): (x=0.94, y=0.05)
                            # - Gửi ESC (Android Back) để bỏ qua/đóng quảng cáo
                            # - Bấm nút X góc trên-trái chuẩn: (x=0.06, y=0.05)
                            # - Gửi ESC lần 2
                            if self.config.get("auto_close_ads", True) and (now_tick - last_ad_close_time >= 1.6):
                                self._push("status", "[Quảng cáo] Đang tự động tắt quảng cáo: Bấm nút X & gửi ESC...")
                                # Bấm góc trên-phải chuẩn (thử cả tọa độ sát góc và góc chuẩn)
                                controller.tap([0.96, 0.035], rect)
                                time.sleep(0.15)
                                controller.tap([0.92, 0.045], rect)
                                time.sleep(0.18)
                                controller.press_esc()
                                time.sleep(0.20)
                                # Bấm góc trên-trái (vị trí X của một số quảng cáo Google Play / Unity)
                                controller.tap([0.04, 0.035], rect)
                                time.sleep(0.15)
                                controller.tap([0.08, 0.045], rect)
                                time.sleep(0.18)
                                controller.press_esc()
                                last_ad_close_time = now_tick
                                last_auto_action_time = now_tick
                                if elapsed_ad >= 10.0:
                                    ad_wait_start_time = 0.0
                                self.rule_counts["tat_quang_cao"] = self.rule_counts.get("tat_quang_cao", 0) + 1
                                auto_action_done = True
                                time.sleep(0.8)
                                continue

                            # 4. Bấm Tiếp tục tại vị trí nút Confirm chuẩn (CHỈ khi không xem quảng cáo và detect_confirm_button phát hiện)
                            if not auto_action_done and self.config.get("auto_restart", True) and ad_wait_start_time == 0.0:
                                cf_pos = detect_confirm_button(frame)
                                if cf_pos and (start_tick - last_auto_action_time >= 3.0):
                                    controller.tap(list(cf_pos), rect)
                                    last_auto_action_time = start_tick
                                    self.rule_counts["ket_qua"] = self.rule_counts.get("ket_qua", 0) + 1
                                    self._push("status", f"[Endgame] Bấm xác nhận kết quả (Confirm) tại ({cf_pos[0]:.2f}, {cf_pos[1]:.2f})...")
                                    auto_action_done = True
                                    time.sleep(1.0)
                                    continue

                        # B0. MÀN HÌNH MỞ RƯƠNG (Treasure Chest / Reliquary có nút "Obtain" ở dưới)
                        obtain_pos = detect_obtain_button(frame)
                        if obtain_pos:
                            controller.release()
                            self.previous_direction = None
                            last_monolith_pos = None
                            uncertain_since = 0.0
                            match_running = True
                            post_death_phase = False
                            if self.config.get("auto_levelup", True) and (start_tick - last_chest_obtain_time >= 1.1):
                                obtain_x, obtain_y = obtain_pos
                                prefer_cc = self.config.get("prefer_crit_and_cooldown", True)
                                if is_three_card_chest(frame, obtain_x) and (start_tick - last_chest_scan_time >= 3.0):
                                    # Đọc thẻ 1 (mặc định đang chọn), sau đó bấm xem thẻ 2 và thẻ 3 để so sánh điểm Meta + Build Synergy
                                    s1, lbl1 = evaluate_selected_chest_artifact(frame, prefer_cc, active_skills=active_skills)
                                    slot2 = get_chest_card_target(2, obtain_x)
                                    controller.tap(list(slot2), rect)
                                    time.sleep(0.32)
                                    frame2 = screenshot(rect)
                                    s2, lbl2 = evaluate_selected_chest_artifact(frame2, prefer_cc, active_skills=active_skills)
                                    slot3 = get_chest_card_target(3, obtain_x)
                                    controller.tap(list(slot3), rect)
                                    time.sleep(0.32)
                                    frame3 = screenshot(rect)
                                    s3, lbl3 = evaluate_selected_chest_artifact(frame3, prefer_cc, active_skills=active_skills)

                                    candidates = {1: (s1, lbl1), 2: (s2, lbl2), 3: (s3, lbl3)}
                                    best_idx = max(candidates, key=lambda k: candidates[k][0])
                                    _, best_label = candidates[best_idx]
                                    if best_idx != 3:
                                        best_slot = get_chest_card_target(best_idx, obtain_x)
                                        controller.tap(list(best_slot), rect)
                                        time.sleep(0.28)
                                    self.recorder.record_decision(
                                        frame,
                                        "chest",
                                        f"slot_{best_idx}",
                                        confidence=0.90,
                                        metadata={
                                            "chosen_artifact": best_label,
                                            "best_idx": best_idx,
                                            "active_skills": list(active_skills),
                                        },
                                    )
                                    controller.tap([obtain_x, obtain_y], rect)
                                    now_tick = time.monotonic()
                                    last_chest_scan_time = now_tick
                                    last_chest_obtain_time = now_tick
                                    last_auto_action_time = now_tick
                                    self.rule_counts["nang_cap"] = self.rule_counts.get("nang_cap", 0) + 1
                                    self._push("status", f"Mở Rương: Chọn {best_label} (Ô {best_idx}/3) & bấm Obtain!")
                                    auto_action_done = True
                                    time.sleep(0.55)
                                else:
                                    # Rương 1 vật phẩm (Reliquary) hoặc bấm bồi Obtain nếu lần bấm trước chưa đóng rương
                                    _, lbl = evaluate_selected_chest_artifact(frame, prefer_cc, active_skills=active_skills)
                                    self.recorder.record_decision(
                                        frame,
                                        "chest",
                                        "obtain",
                                        confidence=0.90,
                                        metadata={
                                            "chosen_artifact": lbl,
                                            "active_skills": list(active_skills),
                                        },
                                    )
                                    controller.tap([obtain_x, obtain_y], rect)
                                    now_tick = time.monotonic()
                                    last_chest_obtain_time = now_tick
                                    last_auto_action_time = now_tick
                                    self.rule_counts["nang_cap"] = self.rule_counts.get("nang_cap", 0) + 1
                                    self._push("status", f"Mở Rương: Nhận {lbl} -> Bấm Obtain!")
                                    auto_action_done = True
                                    time.sleep(0.55)
                            continue

                        # B0.1 MÀN HÌNH CỬA HÀNG (Merchant Shop có nút "Buy" ở dưới và "X" ở góc trên-phải)
                        shop_buy_pos = detect_buy_button(frame)
                        if shop_buy_pos:
                            controller.release()
                            self.previous_direction = None
                            uncertain_since = 0.0
                            match_running = True
                            post_death_phase = False
                            if start_tick - last_shop_action_time >= 1.2:
                                prefer_cc = self.config.get("prefer_crit_and_cooldown", True)
                                shop_items = get_shop_item_targets()
                                best_buy_slot = None
                                best_buy_score = -1
                                best_buy_label = ""
                                # 1. Kiểm tra món đang được chọn sẵn trên màn hình
                                if is_shop_buy_enabled(frame):
                                    s_cur, l_cur = evaluate_selected_shop_artifact(frame, prefer_cc, active_skills=active_skills)
                                    best_buy_slot = shop_items[0]
                                    best_buy_score = s_cur
                                    best_buy_label = l_cur

                                # 2. Duyệt qua các ô vật phẩm khác nếu chưa quét gần đây
                                if start_tick - last_shop_scan_time >= 5.0:
                                    for s_target in shop_items:
                                        controller.tap(list(s_target), rect)
                                        time.sleep(0.24)
                                        f_item = screenshot(rect)
                                        if is_shop_buy_enabled(f_item):
                                            s_item, l_item = evaluate_selected_shop_artifact(f_item, prefer_cc, active_skills=active_skills)
                                            if s_item > best_buy_score:
                                                best_buy_score = s_item
                                                best_buy_slot = s_target
                                                best_buy_label = l_item
                                    last_shop_scan_time = time.monotonic()

                                # Nếu có món đủ tiền mua -> chọn và bấm BUY!
                                if best_buy_slot and best_buy_score > 0:
                                    controller.tap(list(best_buy_slot), rect)
                                    time.sleep(0.25)
                                    controller.tap(list(shop_buy_pos), rect)
                                    now_tick = time.monotonic()
                                    last_shop_action_time = now_tick
                                    last_auto_action_time = now_tick
                                    self.rule_counts["mua_do"] = self.rule_counts.get("mua_do", 0) + 1
                                    self._push("status", f"Cửa hàng: Đã mua [{best_buy_label}] & bấm Buy!")
                                    auto_action_done = True
                                    time.sleep(0.6)
                                else:
                                    # Không đủ mana mua món nào hoặc đã mua xong -> Bấm nút 'X' đóng cửa hàng
                                    shop_x_pos = detect_shop_x_button(frame) or (0.936, 0.079)
                                    controller.tap(list(shop_x_pos), rect)
                                    now_tick = time.monotonic()
                                    last_shop_action_time = now_tick
                                    last_auto_action_time = now_tick
                                    self.rule_counts["dong_cua_hang"] = self.rule_counts.get("dong_cua_hang", 0) + 1
                                    self._push("status", "Cửa hàng: Không đủ mana mua đồ -> Bấm X đóng cửa hàng cày tiếp!")
                                    auto_action_done = True
                                    time.sleep(0.8)
                            continue

                        # B0.2 MÀN HÌNH CHỌN THUỘC TÍNH LEVEL 7 (Select Attribute có nút "Learn" ở dưới)
                        learn_pos = detect_learn_button(frame)
                        if learn_pos:
                            controller.release()
                            self.previous_direction = None
                            uncertain_since = 0.0
                            match_running = True
                            post_death_phase = False
                            if self.config.get("auto_levelup", True) and (start_tick - last_learn_click_time >= 1.2):
                                circles = get_attribute_circle_targets()
                                best_circle_idx = 2
                                best_circle_score, best_circle_label, parent_sk = evaluate_selected_attribute(frame)
                                if parent_sk:
                                    active_skills.add(parent_sk)

                                # Nếu thuộc tính hiện tại chưa phải là nhánh Hợp thể (score < 500), thử bấm xem các vòng tròn khác
                                if best_circle_score < 500 and (start_tick - last_attribute_scan_time >= 4.0):
                                    for c_idx in (1, 2, 3):
                                        controller.tap(list(circles[c_idx]), rect)
                                        time.sleep(0.25)
                                        f_c = screenshot(rect)
                                        s_c, l_c, p_c = evaluate_selected_attribute(f_c)
                                        if p_c:
                                            active_skills.add(p_c)
                                        if s_c > best_circle_score:
                                            best_circle_score = s_c
                                            best_circle_idx = c_idx
                                            best_circle_label = l_c
                                            if p_c:
                                                parent_sk = p_c
                                    last_attribute_scan_time = time.monotonic()
                                    controller.tap(list(circles[best_circle_idx]), rect)
                                    time.sleep(0.25)

                                self.recorder.record_decision(
                                    frame,
                                    "attribute",
                                    f"circle_{best_circle_idx}",
                                    confidence=0.90,
                                    metadata={
                                        "chosen_attribute": best_circle_label,
                                        "parent_skill": parent_sk,
                                        "active_skills": list(active_skills),
                                    },
                                )
                                # Bấm nút 'Learn' ở dưới đáy để học thuộc tính
                                controller.tap(list(learn_pos), rect)
                                now_tick = time.monotonic()
                                last_learn_click_time = now_tick
                                last_auto_action_time = now_tick
                                self.rule_counts["chon_thuoc_tinh"] = self.rule_counts.get("chon_thuoc_tinh", 0) + 1
                                self._push("status", f"Level 7 Attribute: Đã chọn [{best_circle_label}] & bấm Learn!")
                                auto_action_done = True
                                time.sleep(0.7)
                            continue

                        # B. MÀN HÌNH NÂNG CẤP KỸ NĂNG TRONG TRẬN (3 THẺ DỌC KHI LÊN CẤP)
                        lvl_res = is_level_up_screen(frame)
                        if lvl_res:
                            controller.release()
                            self.previous_direction = None
                            uncertain_since = 0.0
                            match_running = True
                            post_death_phase = False

                            # 1. KIỂM TRA NGÔI SAO HỢP THỂ (MÀU ĐỎ Ở GÓC TRÊN BÊN PHẢI)
                            combo_star_pos = detect_combination_star(frame)
                            if combo_star_pos and self.config.get("auto_levelup", True) and (start_tick - last_auto_action_time >= 0.8):
                                controller.tap(list(combo_star_pos), rect)
                                time.sleep(0.45)
                                f_combo = screenshot(rect)
                                combo_choice = find_best_combination_option(f_combo, self.config.get("skill_priority"))
                                if combo_choice:
                                    combo_target, combo_label, combo_key = combo_choice
                                    controller.tap(list(combo_target), rect)
                                    time.sleep(0.35)
                                    f_conf = screenshot(rect)
                                    btn_learn = detect_learn_button(f_conf)
                                    if btn_learn:
                                        controller.tap(list(btn_learn), rect)
                                        time.sleep(0.35)
                                    self.recorder.record_decision(
                                        f_combo,
                                        "combination_magic",
                                        combo_key,
                                        confidence=1.0,
                                        metadata={
                                            "combo_label": combo_label,
                                            "combo_key": combo_key,
                                            "active_skills": list(active_skills),
                                        },
                                    )
                                    active_skills.add(combo_key)
                                    now_tick = time.monotonic()
                                    last_auto_action_time = now_tick
                                    level_up_clicks += 1
                                    self.rule_counts["magic_combination"] = self.rule_counts.get("magic_combination", 0) + 1
                                    self._push("status", f"[Combination Magic] Đã bấm sao đỏ & chọn Hợp thể: [{combo_label}]!")
                                    auto_action_done = True
                                    time.sleep(0.6)
                                    continue
                                else:
                                    # Nếu menu mở ra nhưng chưa có combo mong muốn, bấm nút X ở góc trên-phải để quay về chọn thẻ
                                    close_btn = detect_shop_x_button(f_combo) or combo_star_pos
                                    controller.tap(list(close_btn), rect)
                                    time.sleep(0.35)

                            # 2. CHỌN THẺ KỸ NĂNG / THUỘC TÍNH BÌNH THƯỜNG
                            if self.config.get("auto_levelup", True) and (start_tick - last_auto_action_time >= 0.8):
                                choice = self.config.get("card_choice", 1)
                                choice_res = choose_best_artifact_or_card(
                                    frame,
                                    default_choice=choice,
                                    skill_priority=self.config.get("skill_priority"),
                                    prefer_crit_and_cooldown=self.config.get("prefer_crit_and_cooldown", True),
                                    prefer_freeze_traits=self.config.get("prefer_freeze_traits", True),
                                    active_skills=active_skills,
                                )
                                card_idx, target = choice_res
                                choice_label = getattr(choice_res, "label", f"Thẻ {card_idx}")
                                sk_key = getattr(choice_res, "skill_key", "")
                                if sk_key:
                                    active_skills.add(sk_key)
                                self.recorder.record_decision(
                                    frame,
                                    "level_up",
                                    f"card_{card_idx}",
                                    confidence=0.95,
                                    metadata={
                                        "chosen_card": card_idx,
                                        "chosen_label": choice_label,
                                        "skill_key": sk_key,
                                        "active_skills": list(active_skills),
                                        "has_combo_star": bool(combo_star_pos),
                                    },
                                )
                                controller.tap(list(target), rect)
                                now_tick = time.monotonic()
                                last_auto_action_time = now_tick
                                level_up_clicks += 1
                                self.rule_counts["nang_cap"] = self.rule_counts.get("nang_cap", 0) + 1
                                self._push("status", f"Tự động chọn: {choice_label} (Vị trí ô {card_idx})")
                                auto_action_done = True
                                time.sleep(0.4)
                            continue

                        # CHIẾN ĐẤU / GAMEPLAY TRONG TRẬN
                        vision = inspect_game(frame, tuple(self.config["player_position"]))
                        current_vision = vision
                        if vision.gameplay:
                            match_running = True
                            if match_start_time == 0.0:
                                match_start_time = time.monotonic()
                            fh, fw = frame.shape[:2]
                            px = int(fw * self.config["player_position"][0])
                            py = int(fh * self.config["player_position"][1])

                            # Monolith (Cột mốc qua màn / Legendary Artifact) tracking with movement compensation
                            if getattr(vision, "monolith", None) is not None:
                                last_monolith_pos = vision.monolith
                                last_monolith_time = start_tick
                            elif last_monolith_pos is not None and (start_tick - last_monolith_time <= 2.5):
                                if self.previous_direction:
                                    est_mx = int(round(last_monolith_pos[0] - 9.0 * self.previous_direction[0]))
                                    est_my = int(round(last_monolith_pos[1] - 9.0 * self.previous_direction[1]))
                                    last_monolith_pos = (est_mx, est_my)
                                if (
                                    -50 <= last_monolith_pos[0] < fw + 50
                                    and -50 <= last_monolith_pos[1] < fh + 50
                                    and math.hypot(last_monolith_pos[0] - px, last_monolith_pos[1] - py) > 8
                                ):
                                    vision.monolith = last_monolith_pos
                                else:
                                    last_monolith_pos = None
                            else:
                                last_monolith_pos = None

                            if not self.config.get("auto_chest", True):
                                vision.chest = None
                                last_chest_pos = None
                            else:
                                if vision.chest is not None:
                                    last_chest_pos = vision.chest
                                    last_chest_type = getattr(vision, "chest_type", "treasure_chest")
                                    last_chest_weight = getattr(vision, "chest_weight", 24.0)
                                    last_chest_time = start_tick
                                elif last_chest_pos is not None and (start_tick - last_chest_time <= 1.2):
                                    # Compensate chest screen coordinates as player moves toward it
                                    if self.previous_direction:
                                        est_x = int(round(last_chest_pos[0] - 9.0 * self.previous_direction[0]))
                                        est_y = int(round(last_chest_pos[1] - 9.0 * self.previous_direction[1]))
                                        last_chest_pos = (est_x, est_y)
                                    if (
                                        10 <= last_chest_pos[0] < fw - 10
                                        and 10 <= last_chest_pos[1] < fh - 10
                                        and math.hypot(last_chest_pos[0] - px, last_chest_pos[1] - py) > 12
                                    ):
                                        vision.chest = last_chest_pos
                                        vision.chest_type = last_chest_type
                                        vision.chest_weight = last_chest_weight
                                    else:
                                        last_chest_pos = None
                                else:
                                    last_chest_pos = None
                            last_gameplay_time = start_tick
                            uncertain_since = 0.0
                            level_up_clicks = 0
                            match_running = True
                            post_death_phase = False
                            direction = choose_direction(
                                vision, start_tick, self.previous_direction,
                                tuple(self.config["player_position"]),
                            )
                            controller.move(direction, rect, self.config)
                            self.previous_direction = direction
                            if getattr(vision, "monolith", None):
                                self._push("status", f"[Tháp qua màn] ƯU TIÊN TUYỆT ĐỐI: Đang lao thẳng vào Tháp tại ({vision.monolith[0]}, {vision.monolith[1]}) để nhận Legendary Artifact!")
                            elif vision.chest:
                                chest_type_name = getattr(vision, "chest_type", "treasure_chest").replace("_", " ").title()
                                self._push("status", f"[Rương Artifact] Ưu tiên chạy tới RƯƠNG [{chest_type_name}] tại ({vision.chest[0]}, {vision.chest[1]})")
                        else:
                            # Khung hình tối / quái dày đặc giữa trận -> vẫn tiếp tục né & di chuyển
                            moved_uncertain = False
                            if match_running and not post_death_phase and not vision.modal:
                                if uncertain_since == 0.0:
                                    uncertain_since = start_tick
                                direction = choose_direction(
                                    vision, start_tick, self.previous_direction,
                                    tuple(self.config["player_position"]),
                                )
                                controller.move(direction, rect, self.config)
                                self.previous_direction = direction
                                moved_uncertain = True
                                auto_action_done = True
                                self._push(
                                    "status",
                                    f"Màn hình tối/đông quái (nền={vision.background_fraction:.2f}) - vẫn né & di chuyển",
                                )
                            else:
                                uncertain_since = 0.0

                            if not moved_uncertain:
                                controller.release()
                                self.previous_direction = None

                        if not auto_action_done and not vision.gameplay:
                            self._push("status", "Đang chờ trận đấu hoặc quy tắc menu...")

                    if start_tick >= next_preview:
                        display = frame.copy()
                        if current_vision:
                            # Draw detected Mana orbs on preview so user sees active mana detection
                            for gx, gy in current_vision.gems[:25]:
                                cv2.circle(display, (gx, gy), 3, (255, 230, 0), -1)    # Cyan / Blue (S)
                            for gx, gy in current_vision.gold_gems[:15]:
                                cv2.circle(display, (gx, gy), 4, (0, 215, 255), -1)    # Gold (M)
                            for gx, gy in current_vision.purple_gems[:15]:
                                cv2.circle(display, (gx, gy), 5, (230, 60, 200), -1)   # Purple (L)
                        if direction:
                            hh, ww = frame.shape[:2]
                            cx, cy = int(ww * self.config["player_position"][0]), int(hh * self.config["player_position"][1])
                            endpoint = (int(cx + 95 * direction[0]), int(cy + 95 * direction[1]))
                            cv2.arrowedLine(display, (cx, cy), endpoint, (0, 230, 70), 3, tipLength=0.2)
                        if current_vision and getattr(current_vision, "monolith", None):
                            cv2.circle(display, current_vision.monolith, 28, (0, 0, 255), 3)
                            cv2.putText(display, "THAP QUA MAN (MONOLITH)", (current_vision.monolith[0] - 70, current_vision.monolith[1] - 32),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 255), 2)
                        if current_vision and current_vision.chest:
                            ctype = getattr(current_vision, "chest_type", "treasure_chest")
                            color = (0, 50, 255) if ctype == "black_box" else ((255, 100, 255) if ctype == "reliquary" else (0, 215, 255))
                            clabel = ctype.replace("_", " ").upper()
                            cv2.circle(display, current_vision.chest, 22, color, 3)
                            cv2.putText(display, clabel, (current_vision.chest[0] - 35, current_vision.chest[1] - 26),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2)
                        self._push("preview", display)
                        counts = ", ".join(f"{k}: {v}" for k, v in self.rule_counts.items()) or "chưa bấm quy tắc"
                        self._push("metrics", f"Tự động: {counts}")
                        next_preview = start_tick + 0.05
                    time.sleep(max(0.005, 1.0 / max(2, min(60, self.config["fps"])) - (time.monotonic() - start_tick)))
            except Exception as error:
                # Never let one transient error (window resize, OCR hiccup, screenshot failure)
                # kill the bot thread and leave the character standing still.
                controller.release()
                self.previous_direction = None
                self._push("status", f"Lỗi tạm thời ({type(error).__name__}: {error}) - tự phục hồi sau 1 giây...")
                time.sleep(1.0)
        controller.release()

    def _poll_events(self):
        try:
            for _ in range(15):
                kind, data = self.events.get_nowait()
                if kind == "hotkey":
                    if data == keyboard.Key.f8:
                        self.toggle()
                    elif data == keyboard.Key.f9:
                        self.stop()
                    elif data == keyboard.Key.f10:
                        self.take_snapshot()
                elif kind == "preview" and self.calibration_mode is None:
                    self._display(data)
                elif kind == "metrics":
                    self.metrics.set(data)
                elif kind == "status":
                    self.status.set(data)
                elif kind == "error":
                    self.status.set(data)
                    messagebox.showerror("Lỗi", data)
        except queue.Empty:
            pass
        if not self.ending.is_set():
            self.root.after(30, self._poll_events)

    def _display(self, frame: np.ndarray):
        height, width = frame.shape[:2]
        scale = min(345 / width, 650 / height)
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.render_photo = ImageTk.PhotoImage(Image.fromarray(rgb).resize(new_size))
        self.canvas.delete("all")
        self.canvas.config(width=new_size[0], height=new_size[1])
        self.canvas.create_image(0, 0, image=self.render_photo, anchor="nw")
        self.canvas_scale = scale

    def take_snapshot(self):
        self.stop()
        if not self._save_config():
            return
        hwnd = locate_game(self.config["window_title"])
        if not hwnd:
            messagebox.showwarning("Không thấy game", "Hãy mở Magic Survival trước.")
            return
        try:
            self.frame_snapshot = screenshot(game_rectangle(hwnd, self.config))
            self.calibration_mode = None
            self._display(self.frame_snapshot)
            self.status.set("Đã chụp. Bây giờ có thể thêm quy tắc.")
        except Exception as error:
            messagebox.showerror("Lỗi chụp", str(error))

    def start_calibration(self):
        self.stop()
        if self.frame_snapshot is None:
            messagebox.showinfo("Cần ảnh", "Nhấn 'Chụp game' khi màn hình cần tự bấm đang hiện.")
            return
        self.calibration_mode = "anchor"
        self._display(self.frame_snapshot)
        self.status.set("KÉO CHUỘT trên ảnh để khoanh tiêu đề/biểu tượng cố định của màn hình.")

    def _canvas_point(self, event):
        if self.frame_snapshot is None:
            return None
        h, w = self.frame_snapshot.shape[:2]
        return (min(w - 1, max(0, int(event.x / self.canvas_scale))),
                min(h - 1, max(0, int(event.y / self.canvas_scale))))

    def _mouse_down(self, event):
        if self.calibration_mode == "anchor":
            self.anchor_start = self._canvas_point(event)
        elif self.calibration_mode == "target":
            target = self._canvas_point(event)
            if target:
                self._complete_rule(target)

    def _mouse_drag(self, event):
        if self.calibration_mode == "anchor" and self.anchor_start:
            point = self._canvas_point(event)
            if point:
                self._display(self.frame_snapshot)
                x0, y0 = self.anchor_start
                x1, y1 = point
                sc = self.canvas_scale
                self.canvas.create_rectangle(x0 * sc, y0 * sc, x1 * sc, y1 * sc,
                                             outline="#00ec9d", width=3)

    def _mouse_up(self, event):
        if self.calibration_mode != "anchor" or not self.anchor_start:
            return
        pt = self._canvas_point(event)
        if pt is None:
            return
        x0, y0 = self.anchor_start
        x1, y1 = pt
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        self.anchor_start = None
        if x1 - x0 < 40 or y1 - y0 < 18:
            self.status.set("Khung quá nhỏ; hãy khoanh tối thiểu 40×18 pixel.")
            return
        crop = self.frame_snapshot[y0:y1, x0:x1]
        if np.std(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)) < 10:
            self.status.set("Vùng quá trơn. Chọn chữ hoặc biểu tượng có chi tiết rõ ràng.")
            return
        name = simpledialog.askstring("Tên quy tắc", "Tên màn hình (ví dụ: nang_cap / ket_qua / choi_lai):",
                                      parent=self.root)
        if not name:
            self.calibration_mode = None
            return
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")
        if not clean:
            messagebox.showerror("Tên sai", "Hãy dùng chữ, số, dấu _ hoặc -.")
            self.calibration_mode = None
            return
        if any(rule["name"] == clean for rule in self.rules):
            if not messagebox.askyesno("Ghi đè?", f"Quy tắc '{clean}' đã có. Thay thế?"):
                self.calibration_mode = None
                return
        self.rule_name = clean
        self.anchor_box = (x0, y0, x1, y1)
        self.calibration_mode = "target"
        self._display(self.frame_snapshot)
        sc = self.canvas_scale
        self.canvas.create_rectangle(x0 * sc, y0 * sc, x1 * sc, y1 * sc,
                                     outline="#00ec9d", width=3)
        self.status.set(f"QUY TẮC '{clean}': nhấp vào nút cần bấm khi nhận diện màn hình này.")

    def _complete_rule(self, target: tuple[int, int]):
        h, w = self.frame_snapshot.shape[:2]
        x0, y0, x1, y1 = self.anchor_box
        RULE_IMAGE_DIR.mkdir(exist_ok=True)
        image_path = RULE_IMAGE_DIR / f"{self.rule_name}.png"
        cv2.imwrite(str(image_path), self.frame_snapshot[y0:y1, x0:x1])
        rule = {
            "name": self.rule_name,
            "image": f"rules/{self.rule_name}.png",
            "anchor": [x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h],
            "target": [target[0] / w, target[1] / h],
            "threshold": 0.88,
        }
        self.rules = [r for r in self.rules if r["name"] != self.rule_name] + [rule]
        save_json(RULES_PATH, self.rules)
        self.calibration_mode = None
        self._refresh_rules()
        self._display(self.frame_snapshot)
        self.status.set(f"Đã lưu '{self.rule_name}'. Có thể chụp màn khác để dạy tiếp.")

    def delete_rule(self):
        choice = self.rule_list.curselection()
        if not choice:
            return
        rule = self.rules[choice[0]]
        if not messagebox.askyesno("Xóa quy tắc", f"Xóa '{rule['name']}'?"):
            return
        self.rules.pop(choice[0])
        save_json(RULES_PATH, self.rules)
        self._refresh_rules()
        image_path = BASE / rule["image"]
        if image_path.is_file():
            image_path.unlink()

    def close(self):
        self.running.clear()
        self.ending.set()
        self.controller.release()
        self.hotkeys.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    import sys
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except AttributeError:
        pass
    autostart = "--autostart" in sys.argv or "-a" in sys.argv
    FarmApp(autostart=autostart).run()
