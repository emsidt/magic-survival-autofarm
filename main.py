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
from pathlib import Path
from typing import Optional
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

import botcore
from game_actions import (ActionCancelled, GuardedController, capture_frame,
                          select_attribute, select_combination, select_card, remember_card, finish_match,
                          select_character, dismiss_death, close_ad, back_from_ad, move_from_frame, select_chest_artifact)

from botcore import (
    choose_best_artifact_or_card,
    choose_direction,
    detect_buy_button,
    detect_close_button,
    detect_combination_star,
    detect_confirm_button,
    detect_die_button,
    detect_enter_area,
    detect_learn_button,
    detect_mana_orb_currency,
    detect_obtain_button,
    detect_selected,
    detect_settings_dialog,
    detect_start_game,
    detect_shop_x_button,
    evaluate_selected_chest_artifact,
    evaluate_selected_shop_artifact,
    find_rule,
    get_chest_card_target,
    get_shop_item_targets,
    inspect_game,
    is_attribute_screen,
    is_level_up_screen,
    is_shop_buy_enabled,
    is_three_card_chest,
)
from data_recorder import DataRecorder
from learning_engine import get_adaptive_learner
from storage import write_json_atomic


BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
RULES_PATH = BASE / "rules.json"
RULE_IMAGE_DIR = BASE / "rules"
DEFAULTS = {
    "window_title": "Magic Survival",
    "control_mode": "directinput",
    "adb_path": r"D:\LDPlayer\LDPlayer9\adb.exe",
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
    "character": "summoner",
    "auto_chest": True,
    "nearest_target_skills": ["telekinetic_sword"],
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
    write_json_atomic(path, value)


def locate_game(title: str = "Magic Survival"):
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

    candidates_exact = []
    candidates_ldplayer = []
    candidates_emulator = []

    # Windows to exclude: code editors, terminals, browsers, dev tools
    EXCLUDE_KEYWORDS = (
        "autofarm", "visual studio", "antigravity", "cursor", "sublime", "pycharm",
        "google chrome", "microsoft edge", "firefox", "brave", "github", "powershell", "cmd.exe"
    )
    EXCLUDE_CLASSES = (
        "chrome_widgetwin", "hwndwrapper", "mozillawindowclass", "consolewindowclass"
    )

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        w_text = win32gui.GetWindowText(hwnd).strip()
        c_text = win32gui.GetClassName(hwnd).strip()
        w_low = w_text.lower()
        c_low = c_text.lower()

        # Exclude dev tools / browsers / editors
        if any(k in w_low for k in EXCLUDE_KEYWORDS) or any(c_low.startswith(k) for k in EXCLUDE_CLASSES):
            return

        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            if (right - left) < 200 or (bottom - top) < 300:
                return
        except Exception:
            return

        # 1. LDPlayer detection (class LDPlayerMainFrame or title containing ldplayer/dnplayer)
        if c_low == "ldplayermainframe" or "ldplayer" in w_low or "dnplayer" in w_low:
            candidates_ldplayer.append(hwnd)
            return

        # 2. Window title contains the specified title (e.g. Magic Survival)
        if title.lower() in w_low:
            candidates_exact.append(hwnd)
            return

        # 3. Other known Android emulators (Nox, BlueStacks, MuMu)
        if any(emu in w_low or emu in c_low for emu in ("bluestacks", "nox", "mumu", "nemu")):
            candidates_emulator.append(hwnd)
            return

    win32gui.EnumWindows(visit, None)

    # Priority selection:
    # If the user specifically set title to something custom, exact match takes precedence.
    if title.lower() not in ("magic survival", "magic-survival") and candidates_exact:
        selected = candidates_exact[0]
    elif candidates_ldplayer:
        selected = candidates_ldplayer[0]
    elif candidates_exact:
        selected = candidates_exact[0]
    elif candidates_emulator:
        selected = candidates_emulator[0]
    else:
        selected = None

    if selected and win32gui.IsIconic(selected):
        try:
            win32gui.ShowWindow(selected, 9)  # SW_RESTORE
        except Exception:
            pass

    return selected


def find_game_child_window(hwnd: int) -> Optional[int]:
    """Auto-detect emulator renderer child window (LDPlayer RenderWindow, GPG crosvm, MuMu, BlueStacks)."""
    children: list[int] = []

    def _find(child_hwnd, _):
        try:
            w_text = win32gui.GetWindowText(child_hwnd).lower()
            c_text = win32gui.GetClassName(child_hwnd).lower()
            if any(k in c_text or k in w_text for k in ("renderwindow", "crosvm", "subwin", "nemu")):
                children.append(child_hwnd)
        except Exception:
            pass

    try:
        win32gui.EnumChildWindows(hwnd, _find, None)
    except Exception:
        pass

    if children:
        best = None
        max_area = 0
        for ch in children:
            try:
                cl, ct, cr, cb = win32gui.GetClientRect(ch)
                area = (cr - cl) * (cb - ct)
                if area > max_area and (cr - cl) >= 200 and (cb - ct) >= 300:
                    max_area = area
                    best = ch
            except Exception:
                pass
        return best or children[0]
    return None


def game_rectangle(hwnd: int, config: dict) -> dict:
    # 1. Auto-detect emulator renderer child window (LDPlayer RenderWindow, GPG crosvm, etc.)
    child = find_game_child_window(hwnd)
    target = child if child is not None else hwnd

    is_render_child = (child is not None)
    try:
        c_name = win32gui.GetClassName(target).lower()
        if "renderwindow" in c_name or "crosvm" in c_name:
            is_render_child = True
    except Exception:
        pass

    if is_render_child:
        cl, ct, cr, cb = win32gui.GetClientRect(target)
        ox, oy = win32gui.ClientToScreen(target, (cl, ct))
        width = cr - cl
        height = cb - ct
        if width >= 200 and height >= 300:
            return {"left": ox, "top": oy, "width": width, "height": height}

    # 2. Fallback to standard window with config crops
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
    if win32gui.IsChild(fg, hwnd):
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

    return False, hwnd


_GRABBERS = threading.local()


def get_grabber() -> mss.mss:
    if not hasattr(_GRABBERS, "instance"):
        _GRABBERS.instance = mss.mss()
    return _GRABBERS.instance


def screenshot(rect: dict) -> np.ndarray:
    try:
        shot = np.asarray(get_grabber().grab(rect))
    except Exception:
        old = getattr(_GRABBERS, "instance", None)
        if old is not None:
            old.close()
        _GRABBERS.instance = mss.mss()
        shot = np.asarray(_GRABBERS.instance.grab(rect))
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
            if not all(math.isfinite(v) for v in (dx, dy)):
                raise ValueError("Movement must be finite")
            if config["input_mode"] != "keyboard" and abs(dx) < 0.12 and abs(dy) < 0.12:
                self.release()
                return
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
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in target[:2]):
                raise ValueError("Tap coordinates must be normalized")
            x = rect["left"] + min(rect["width"] - 1, int(round(target[0] * rect["width"])))
            y = rect["top"] + min(rect["height"] - 1, int(round(target[1] * rect["height"])))
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
                return
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
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after_idle(self.root.attributes, "-topmost", False)
            self.root.focus_force()
        except Exception:
            pass
        print("=" * 65)
        print("  🎮 BẢNG ĐIỀU KHIỂN GIAO DIỆN (GUI) ĐÃ KHỞI ĐỘNG 🎮")
        print("=" * 65)
        print("[+] Cửa sổ giao diện đang hiển thị trên màn hình.")
        print("[+] Nhấn F8 để Bắt đầu/Tạm dừng; F9 để Dừng.")
        print("[*] (Gợi ý: Bạn cũng có thể chạy chế độ dòng lệnh trực tiếp: python bot_cli.py)\n")
        self.autostart = autostart
        self.config = {**DEFAULTS, **read_json(CONFIG_PATH, {})}
        self.rules = read_json(RULES_PATH, [])
        self.events = queue.Queue(maxsize=30)
        self.hotkey_events = queue.SimpleQueue()
        if self.config.get("control_mode") == "adb":
            try:
                from adb_controller import ADBController
                self.controller = ADBController(adb_path=self.config.get("adb_path", r"D:\LDPlayer\LDPlayer9\adb.exe"))
            except Exception as error:
                raise RuntimeError(f"Không khởi tạo được ADB: {error}") from error
        else:
            self.controller = Controller()
        self.running = threading.Event()
        self.ending = threading.Event()
        self.input_generation = 0
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
        self.learner = get_adaptive_learner()
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
        ttk.Checkbutton(tools, text="Tự đóng quảng cáo (Đóng / Close / X)", variable=self.auto_close_ads).pack(anchor="w", pady=1)
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
        self.input_generation += 1
        self.controller.release()
        self.previous_direction = None
        self.status.set("Đã dừng input. Nhấn F8 để chạy lại.")

    def _key_down(self, key):
        if key in (keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10) and key not in self.pressed_hotkeys:
            self.pressed_hotkeys.add(key)
            if key == keyboard.Key.f9:
                self.running.clear()
                self.input_generation += 1
                self.controller.release()
            self.hotkey_events.put(key)

    def _key_up(self, key):
        self.pressed_hotkeys.discard(key)

    def _push(self, kind, value):
        if kind == "status":
            print(f"[*] {value}")
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
        hwnd = None
        input_generation = self.input_generation
        controller = GuardedController(
            self.controller,
            lambda: self.running.is_set() and not self.ending.is_set()
            and input_generation == self.input_generation
            and (hasattr(self.controller, "screen_width")
                 or (hwnd is not None and is_game_or_popup_active(hwnd)[0])),
        )
        capture = lambda: capture_frame(controller, rect, screenshot)
        streak_name = ""
        streak = 0
        last_click: dict[str, float] = {}
        next_preview = 0.0
        last_gameplay_time = 0.0
        last_ad_close_time = 0.0
        last_auto_action_time = 0.0
        last_combination_attempt = 0.0
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
        skill_levels: dict[str, int] = {}
        maxed_skills: set[str] = set()
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
        last_known_game_timer_sec: float = 0.0
        last_timer_scan_time: float = 0.0
        while not self.ending.is_set():
            try:
                while not self.ending.is_set():
                    if not self.running.is_set():
                        controller.release()
                        time.sleep(0.12)
                        continue

                    start_tick = time.monotonic()
                    input_generation = self.input_generation
                    if self.session_start and start_tick - self.session_start > 60 * self.config["max_session_minutes"]:
                        self.running.clear()
                        controller.release()
                        self._push("status", "Đã dừng vì hết giới hạn thời gian.")
                        continue

                    is_adb = hasattr(controller, "screen_width")
                    if is_adb:
                        rect = {"left": 0, "top": 0, "width": controller.screen_width, "height": controller.screen_height}
                        if hasattr(controller, "is_game_foreground") and not controller.is_game_foreground():
                            controller.release()
                            self.previous_direction = None
                            match_running = False
                            if self.config.get("auto_close_ads", True):
                                close = close_ad(controller, rect, capture)
                                if close is not None:
                                    self.rule_counts["tat_quang_cao"] = self.rule_counts.get("tat_quang_cao", 0) + 1
                                    self._push("status", f"[Quảng cáo] Đã bấm nút đóng ({close[0]:.2f}, {close[1]:.2f}) trên màn hình Cửa hàng / Quảng cáo!")
                                    time.sleep(0.6)
                                    continue
                            if controller.is_game_foreground():
                                continue
                            if self.config.get("auto_close_ads", True):
                                controller.press_esc()
                                time.sleep(0.5)
                            if self.config.get("auto_restart", True) and not controller.is_game_foreground():
                                self._push("status", "🔄 [Tự phục hồi] Game bị chuyển sang ứng dụng khác -> Đang mở lại Magic Survival...")
                                controller.launch_game()
                                time.sleep(1.5)
                            continue
                    else:
                        hwnd = locate_game(self.config["window_title"])
                        if not hwnd:
                            controller.release()
                            self._push("status", "Không tìm thấy cửa sổ Magic Survival.")
                            time.sleep(1.0)
                            continue

                        is_active, active_wnd = is_game_or_popup_active(hwnd, post_death_phase)
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

                    frame = botcore.prepare_analysis_frame(capture())
                    captured_at = time.perf_counter()
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

                        fast_combat = botcore.is_fast_combat_frame(frame)
                        if not fast_combat:
                            controller.release()
                            restore_pos = botcore.detect_restore_gold(frame)
                            if restore_pos:
                                controller.release()
                                if start_tick - last_confirm_click_time >= 2.0:
                                    controller.tap(list(restore_pos), rect)
                                    last_confirm_click_time = start_tick
                                    if self.recorder.current_run_id:
                                        self.recorder.finish_run()
                                    match_running = post_death_phase = False
                                    match_start_time = last_known_game_timer_sec = 0.0
                                    active_skills.clear()
                                    skill_levels.clear()
                                    maxed_skills.clear()
                                    self.previous_direction = last_chest_pos = last_monolith_pos = None
                                    self._push("status", "[Restore Gold] Đã bấm Confirm nhận lại vàng sau crash.")
                                continue

                            # 0. MÀN HÌNH CHẾT "Life or Death" -> BẤM "DIE" NGAY LẬP TỨC (bỏ qua xem quảng cáo Revive)
                            die_pos = detect_die_button(frame)
                            if die_pos:
                                controller.release()
                                self.previous_direction = None
                                match_running = False
                                post_death_phase = True
                                final_timer = botcore.detect_game_timer(frame)
                                if final_timer:
                                    last_known_game_timer_sec = max(last_known_game_timer_sec, float(final_timer[2]))
                                if start_tick - last_die_click_time >= 1.2:
                                    last_die_click_time = start_tick
                                    last_auto_action_time = start_tick
                                    if dismiss_death(controller, rect, capture):
                                        self.rule_counts["bam_die"] = self.rule_counts.get("bam_die", 0) + 1
                                        self._push("status", "Đã xác nhận Die, chuyển sang nhận thưởng.")
                                    else:
                                        self._push("status", "Chưa xác nhận được Die; không đoán vị trí gần Revive.")
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
                                    if match_start_time > 0.0 or last_known_game_timer_sec > 0.0 or self.recorder.current_run_id:
                                        t_fin = botcore.detect_game_timer(frame) or botcore.detect_results_survival_time(frame)
                                        if t_fin:
                                            last_known_game_timer_sec = max(last_known_game_timer_sec, float(t_fin[2]))
                                        if last_known_game_timer_sec <= 0.0 and match_start_time > 0.0:
                                            last_known_game_timer_sec = max(0.0, start_tick - match_start_time)
                                        report = finish_match(
                                            self.recorder, self.learner, frame, last_known_game_timer_sec,
                                            active_skills, self.config.get("skill_priority", []),
                                            skill_levels=skill_levels,
                                            character=self.config.get("character", "summoner"),
                                        )
                                        if report and isinstance(report, dict) and "summary_text" in report:
                                            print(report["summary_text"])
                                            self._push("status", report.get("status_line", "[AI] Đã ghi kết quả ván."))
                                        else:
                                            self._push("status", "[AI] Đã ghi kết quả ván." if report else "[AI] Chưa đọc được đồng hồ game; bỏ qua cập nhật trọng số.")
                                    match_start_time = 0.0
                                    last_known_game_timer_sec = 0.0
                                    last_timer_scan_time = 0.0
                                    active_skills.clear()
                                    skill_levels.clear()
                                    maxed_skills.clear()
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

                            # A1-A3: Màn hình sảnh & bắt đầu trận (chỉ kiểm tra khi không trong trận)
                            if not match_running:
                                # A1. ƯU TIÊN MÀN HÌNH CHÍNH (TITLE SCREEN): Bấm "Start Game"
                                sg_pos = detect_start_game(frame)
                                if sg_pos:
                                    match_running = False
                                    post_death_phase = False
                                    active_skills.clear()
                                    skill_levels.clear()
                                    maxed_skills.clear()
                                    ad_wait_start_time = 0.0
                                    match_start_time = 0.0
                                    currencies = botcore.detect_main_screen_currencies(frame)
                                    gold = currencies.get("gold")
                                    gems = currencies.get("gems")
                                    cur_txt = ""
                                    if gold is not None or gems is not None:
                                        g_s = f"{gold:,} Vàng" if gold is not None else "---"
                                        gem_s = f"{gems:,} Gem" if gems is not None else "---"
                                        cur_txt = f" [Tài nguyên: 💰 {g_s} | 💎 {gem_s}]"
                                    if self.config.get("auto_restart", True) and (start_tick - last_auto_action_time >= 1.5):
                                        controller.tap(list(sg_pos), rect)
                                        last_auto_action_time = start_tick
                                        self.rule_counts["start_game"] = self.rule_counts.get("start_game", 0) + 1
                                        self._push("status", f"Phát hiện màn hình chính{cur_txt}: Tự động bấm 'Start Game' tại ({sg_pos[0]:.2f}, {sg_pos[1]:.2f}) - Tuyệt đối không bấm Cài đặt!")
                                        auto_action_done = True
                                        time.sleep(1.2)
                                    continue

                                # A2. MÀN HÌNH CHỌN NHÂN VẬT (CLASS SCREEN): Bấm "Selected"
                                sel_pos = detect_selected(frame)
                                if sel_pos:
                                    match_running = False
                                    post_death_phase = False
                                    active_skills.clear()
                                    skill_levels.clear()
                                    maxed_skills.clear()
                                    ad_wait_start_time = 0.0
                                    match_start_time = 0.0
                                    if self.config.get("auto_restart", True) and (start_tick - last_auto_action_time >= 1.5):
                                        last_auto_action_time = start_tick
                                        character = self.config.get("character", "summoner")
                                        if select_character(controller, rect, frame, capture, character):
                                            self.rule_counts["selected"] = self.rule_counts.get("selected", 0) + 1
                                            self._push("status", f"Đã chọn {character.title()} và xác nhận Selected.")
                                        else:
                                            self._push("status", f"Chưa xác nhận được {character}; sẽ đọc lại màn chọn nhân vật.")
                                        auto_action_done = True
                                        time.sleep(1.2)
                                    continue

                                # A3. MÀN HÌNH SẢNH / CHỌN MAP (ENTER AREA SCREEN): Bấm "Enter Area"
                                ea_pos = detect_enter_area(frame)
                                if ea_pos:
                                    match_running = False
                                    post_death_phase = False
                                    active_skills.clear()
                                    skill_levels.clear()
                                    maxed_skills.clear()
                                    ad_wait_start_time = 0.0
                                    currencies = botcore.detect_main_screen_currencies(frame)
                                    gold = currencies.get("gold")
                                    gems = currencies.get("gems")
                                    cur_txt = ""
                                    if gold is not None or gems is not None:
                                        g_s = f"{gold:,} Vàng" if gold is not None else "---"
                                        gem_s = f"{gems:,} Gem" if gems is not None else "---"
                                        cur_txt = f" [Tài nguyên: 💰 {g_s} | 💎 {gem_s}]"
                                    if self.config.get("auto_restart", True) and (start_tick - last_auto_action_time >= 1.5):
                                        if match_start_time == 0.0:
                                            self.recorder.start_new_run()
                                            match_start_time = time.monotonic()
                                        last_chest_pos = None
                                        last_monolith_pos = None
                                        self.previous_direction = None
                                        last_known_game_timer_sec = 0.0
                                        last_timer_scan_time = 0.0
                                        level_up_clicks = 0
                                        controller.tap(list(ea_pos), rect)
                                        last_auto_action_time = start_tick
                                        self.rule_counts["enter_area"] = self.rule_counts.get("enter_area", 0) + 1
                                        self._push("status", f"Chuẩn bị vào trận mới{cur_txt}: Tự động bấm 'Enter Area'!")
                                        auto_action_done = True
                                        time.sleep(1.2)
                                    continue

                            # A4. POPUP QUẢNG CÁO (AdMob, Play Store overlay, Unity Ads):
                            if post_death_phase and botcore.detect_pause_button(frame):
                                post_death_phase = False
                                match_running = True
                                ad_wait_start_time = 0.0
                            if self.config.get("auto_close_ads", True):
                                close_pos = detect_close_button(frame)
                                if close_pos and (start_tick - last_ad_close_time >= 1.0):
                                    controller.release()
                                    self.previous_direction = None
                                    match_running = False
                                    if close_ad(controller, rect, capture) is None:
                                        continue
                                    now_tick = time.monotonic()
                                    last_ad_close_time = now_tick
                                    last_auto_action_time = now_tick
                                    ad_wait_start_time = 0.0
                                    self.rule_counts["tat_quang_cao"] = self.rule_counts.get("tat_quang_cao", 0) + 1
                                    self._push("status", "[Quảng cáo] Đã bấm nút đóng; đọc lại màn hình.")
                                    auto_action_done = True
                                    time.sleep(0.8)
                                    continue
                                elif botcore.is_ad_screen(frame) and (start_tick - last_ad_close_time >= 3.0):
                                    controller.release()
                                    self.previous_direction = None
                                    match_running = False
                                    last_ad_close_time = start_tick
                                    last_auto_action_time = start_tick
                                    auto_action_done = back_from_ad(controller, rect, capture)
                                    if auto_action_done:
                                        self._push("status", "[Quảng cáo] Đã xác nhận còn quảng cáo trên ảnh mới rồi bấm Back.")
                                    time.sleep(0.8)
                                    continue

                            # C. KẾT THÚC VÁN (HẬU CHẾT): Xử lý quảng cáo và quay lại sảnh
                            if post_death_phase:
                                now_tick = time.monotonic()
                                elapsed_ad = now_tick - ad_wait_start_time if ad_wait_start_time > 0 else 999.0

                                # 1. Tìm & bấm nút X / Close / Skip quảng cáo nếu đã phát hiện vị trí
                                close_pos = detect_close_button(frame) if self.config.get("auto_close_ads", True) else None
                                if close_pos and (now_tick - last_ad_close_time >= 1.2):
                                    if close_ad(controller, rect, capture) is None:
                                        continue
                                    last_ad_close_time = now_tick
                                    last_auto_action_time = now_tick
                                    ad_wait_start_time = 0.0
                                    self.rule_counts["tat_quang_cao"] = self.rule_counts.get("tat_quang_cao", 0) + 1
                                    self._push("status", "[Quảng cáo] Đã bấm nút đóng; đọc lại màn hình.")
                                    auto_action_done = True
                                    time.sleep(1.0)
                                    continue

                                # 2. Đang trong 4 giây đầu xem video quảng cáo (chờ video tải/chạy):
                                if ad_wait_start_time > 0 and elapsed_ad < 4.0:
                                    self._push("status", f"[Quảng cáo] Đang chờ video quảng cáo ({elapsed_ad:.0f}s)...")
                                    auto_action_done = True
                                    time.sleep(1.0)
                                    continue

                                controller.release()
                                self._push("status", "Đang chờ nút đóng quảng cáo hoặc màn hình sảnh...")
                                time.sleep(0.5)
                                continue

                            # B0. MÀN HÌNH MỞ RƯƠNG (Treasure Chest / Reliquary có nút "Obtain" ở dưới)
                            obtain_pos = detect_obtain_button(frame)
                            if obtain_pos:
                                controller.release()
                                self.previous_direction = None
                                last_monolith_pos = None
                                last_chest_pos = None
                                uncertain_since = 0.0
                                match_running = True
                                post_death_phase = False
                                if self.config.get("auto_levelup", True) and (start_tick - last_chest_obtain_time >= 1.1):
                                    last_chest_obtain_time = time.monotonic()
                                    chosen = select_chest_artifact(
                                        controller, rect, capture, active_skills=set(active_skills),
                                        prefer_cc=self.config.get("prefer_crit_and_cooldown", True),
                                    )
                                    last_auto_action_time = time.monotonic()
                                    if chosen:
                                        self.recorder.record_decision(
                                            frame, "chest", f"slot_{chosen.index}",
                                            metadata={"chosen_artifact": chosen.label,
                                                      "active_skills": sorted(active_skills)},
                                        )
                                        last_chest_scan_time = last_auto_action_time
                                        self.rule_counts["nang_cap"] = self.rule_counts.get("nang_cap", 0) + 1
                                        self._push("status", f"Đã xác nhận nhận cổ vật: {chosen.label} (ô {chosen.index})")
                                        auto_action_done = True
                                    else:
                                        self._push("status", "Chưa xác nhận nhận cổ vật; đọc lại màn hình.")
                                continue

                            # B0.1 MÀN HÌNH CỬA HÀNG (Merchant Shop có nút "Buy" ở dưới và "X" ở góc trên-phải)
                            shop_buy_pos = detect_buy_button(frame)
                            if shop_buy_pos:
                                controller.release()
                                self.previous_direction = None
                                uncertain_since = 0.0
                                match_running = True
                                post_death_phase = False
                                if not self.config.get("auto_levelup", True):
                                    continue
                                if start_tick - last_shop_action_time >= 1.2:
                                    prefer_cc = self.config.get("prefer_crit_and_cooldown", True)
                                    shop_items = get_shop_item_targets()
                                    best_buy_slot = None
                                    best_buy_score = -1
                                    best_buy_label = ""
                                    current_mana = detect_mana_orb_currency(frame)
                                    mana_info = f" ({current_mana} Mana)" if current_mana is not None else ""
                                    self._push("status", f"[Cửa hàng] Mở Thương nhân{mana_info}! Đang duyệt full 8 món...")

                                    build_skills = set(active_skills)

                                    # Duyệt qua toàn bộ 8 ô vật phẩm trong cửa hàng
                                    shop_lost = False
                                    for idx, s_target in enumerate(shop_items, 1):
                                        controller.tap(list(s_target), rect)
                                        time.sleep(0.24)
                                        f_item = capture()
                                        shop_buy_pos = detect_buy_button(f_item)
                                        if shop_buy_pos is None:
                                            shop_lost = True
                                            break

                                        is_affordable = is_shop_buy_enabled(f_item, buy_pos=shop_buy_pos)
                                        s_item, l_item = evaluate_selected_shop_artifact(f_item, prefer_cc, active_skills=build_skills)
                                        has_synergy = ("Build:" in l_item) or ("★" in l_item) or ("S-Tier" in l_item) or ("Special" in l_item) or ("Legendary" in l_item)

                                        if is_affordable:
                                            effective_score = s_item + (1000 if has_synergy else 0)
                                            if effective_score > best_buy_score:
                                                best_buy_score = effective_score
                                                best_buy_slot = s_target
                                                best_buy_label = l_item

                                    if shop_lost:
                                        last_shop_action_time = time.monotonic()
                                        continue

                                    # Nếu có món đủ tiền mua -> chọn và bấm BUY!
                                    if best_buy_slot and best_buy_score > 0:
                                        controller.tap(list(best_buy_slot), rect)
                                        time.sleep(0.25)
                                        selected_item = capture()
                                        fresh_buy = detect_buy_button(selected_item)
                                        if not fresh_buy or not is_shop_buy_enabled(selected_item, fresh_buy):
                                            last_shop_action_time = time.monotonic()
                                            continue
                                        controller.tap(list(fresh_buy), rect)
                                        now_tick = time.monotonic()
                                        last_shop_action_time = now_tick
                                        last_auto_action_time = now_tick
                                        self.rule_counts["mua_do"] = self.rule_counts.get("mua_do", 0) + 1
                                        self._push("status", f"[Cửa hàng] Đã bấm Buy cho món: [{best_buy_label}]!")
                                        auto_action_done = True
                                        time.sleep(0.65)
                                        f_after = capture()
                                        shop_x_pos = detect_shop_x_button(f_after)
                                        if shop_x_pos:
                                            controller.tap(list(shop_x_pos), rect)
                                        time.sleep(0.4)
                                    else:
                                        # Không đủ mana mua món nào hoặc không có món hợp build -> Bấm nút 'X' đóng cửa hàng
                                        shop_x_pos = detect_shop_x_button(capture())
                                        if shop_x_pos:
                                            controller.tap(list(shop_x_pos), rect)
                                        now_tick = time.monotonic()
                                        last_shop_action_time = now_tick
                                        last_auto_action_time = now_tick
                                        self.rule_counts["dong_cua_hang"] = self.rule_counts.get("dong_cua_hang", 0) + 1
                                        self._push("status", f"[Cửa hàng] Đã duyệt 8 món: Chưa đủ Mana hoặc không có món hợp build -> Đóng shop!")
                                        auto_action_done = True
                                        time.sleep(0.8)
                                continue

                            # B0.2 MÀN HÌNH CHỌN THUỘC TÍNH LEVEL 7 (Select Attribute có nút "Learn" ở dưới)
                            if is_attribute_screen(frame) or detect_learn_button(frame) is not None:
                                learn_pos = detect_learn_button(frame) or (0.50, 0.8786)
                                controller.release()
                                self.previous_direction = None
                                uncertain_since = 0.0
                                match_running = True
                                post_death_phase = False
                                if self.config.get("auto_levelup", True) and (start_tick - last_learn_click_time >= 1.2):
                                    last_learn_click_time = time.monotonic()
                                    learned = select_attribute(controller, rect, capture)
                                    if learned:
                                        if learned.key:
                                            active_skills.add(learned.key)
                                        self.recorder.record_decision(
                                            frame, "attribute", f"circle_{learned.index}",
                                            metadata={"chosen_attribute": learned.label, "parent_skill": learned.key},
                                        )
                                        self.rule_counts["chon_thuoc_tinh"] = self.rule_counts.get("chon_thuoc_tinh", 0) + 1
                                        self._push("status", f"Đã xác nhận học thuộc tính: {learned.label}")
                                    else:
                                        self._push("status", "Chưa xác nhận được Learn; sẽ đọc lại màn hình.")
                                    last_auto_action_time = time.monotonic()
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
                                if (combo_star_pos and self.config.get("auto_levelup", True)
                                        and start_tick - last_auto_action_time >= 0.8
                                        and start_tick - last_combination_attempt >= 10.0):
                                    last_combination_attempt = time.monotonic()
                                    learned = select_combination(controller, rect, frame, capture, self.config.get("skill_priority"))
                                    last_auto_action_time = time.monotonic()
                                    if learned:
                                        active_skills.add(learned.key)
                                        maxed_skills.add(learned.key)
                                        self.recorder.record_decision(frame, "combination_magic", learned.key,
                                                                      metadata={"combo_label": learned.label})
                                        self.rule_counts["magic_combination"] = self.rule_counts.get("magic_combination", 0) + 1
                                        self._push("status", f"Đã xác nhận học combination: {learned.label}")
                                    continue

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
                                        maxed_skills=maxed_skills,
                                        learner=self.learner,
                                        skill_levels=skill_levels,
                                        level_count=botcore.detect_player_level(frame) or level_up_clicks + 2,
                                        early_priority_skills=self.config.get("early_priority_skills"),
                                    )
                                    card_idx, target = choice_res
                                    choice_label = getattr(choice_res, "label", f"Thẻ {card_idx}")
                                    if select_card(controller, rect, frame, choice_res, capture):
                                        remember_card(choice_res, active_skills, skill_levels, maxed_skills)
                                        self.recorder.record_decision(
                                            frame, "level_up", f"card_{card_idx}",
                                            metadata={"chosen_card": card_idx, "chosen_label": choice_label,
                                                      "skill_key": choice_res.skill_key,
                                                      "offered_level": choice_res.offered_level,
                                                      "active_skills": sorted(active_skills)},
                                        )
                                    else:
                                        last_auto_action_time = time.monotonic()
                                        self._push("status", "Chưa xác nhận được chọn thẻ; đọc lại màn hình.")
                                        continue
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
                        if vision.gameplay and fast_combat:
                            match_running = True
                            if match_start_time == 0.0:
                                match_start_time = time.monotonic()

                            if start_tick - last_timer_scan_time >= 1.0:
                                last_timer_scan_time = start_tick
                                t_live = botcore.detect_game_timer(frame)
                                if t_live and (t_live[2] >= last_known_game_timer_sec or last_known_game_timer_sec == 0.0):
                                    last_known_game_timer_sec = float(t_live[2])

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
                            match_running = True
                            post_death_phase = False
                            direction = choose_direction(
                                vision,
                                last_known_game_timer_sec if last_known_game_timer_sec > 0.0 else (start_tick - match_start_time),
                                self.previous_direction,
                                tuple(self.config["player_position"]),
                                active_skills=active_skills,
                                nearest_target_skills=self.config.get("nearest_target_skills"),
                            )
                            if move_from_frame(controller, rect, self.config, direction, captured_at):
                                self.previous_direction = direction
                            else:
                                self.previous_direction = None
                            if getattr(vision, "monolith", None):
                                self._push("status", f"[Tháp qua màn] ƯU TIÊN TUYỆT ĐỐI: Đang lao thẳng vào Tháp tại ({vision.monolith[0]}, {vision.monolith[1]}) để nhận Legendary Artifact!")
                            elif vision.chest:
                                chest_type_name = getattr(vision, "chest_type", "treasure_chest").replace("_", " ").title()
                                self._push("status", f"[Rương Artifact] Ưu tiên chạy tới RƯƠNG [{chest_type_name}] tại ({vision.chest[0]}, {vision.chest[1]})")
                        else:
                            # Khung hình tối / quái dày đặc giữa trận -> vẫn tiếp tục né & di chuyển
                            moved_uncertain = False
                            if fast_combat and match_running and not post_death_phase and not vision.modal and start_tick - last_gameplay_time <= 1.5:
                                if uncertain_since == 0.0:
                                    uncertain_since = start_tick
                                direction = choose_direction(
                                    vision, start_tick, self.previous_direction,
                                    tuple(self.config["player_position"]),
                                    active_skills=active_skills,
                                    nearest_target_skills=self.config.get("nearest_target_skills"),
                                )
                                moved_uncertain = move_from_frame(controller, rect, self.config, direction, captured_at)
                                self.previous_direction = direction if moved_uncertain else None
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
            except ActionCancelled:
                controller.release()
                self.previous_direction = None
            except Exception as error:
                # Never let one transient error (window resize, OCR hiccup, screenshot failure)
                # kill the bot thread and leave the character standing still.
                controller.release()
                self.previous_direction = None
                self._push("status", f"Lỗi tạm thời ({type(error).__name__}: {error}) - tự phục hồi sau 1 giây...")
                time.sleep(1.0)
        controller.release()

    def _poll_events(self):
        while not self.hotkey_events.empty():
            key = self.hotkey_events.get_nowait()
            if key == keyboard.Key.f8:
                self.toggle()
            elif key == keyboard.Key.f9:
                self.stop()
            elif key == keyboard.Key.f10:
                self.take_snapshot()
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
        try:
            rect = None
            if not hasattr(self.controller, "screen_width"):
                hwnd = locate_game(self.config["window_title"])
                if not hwnd:
                    messagebox.showwarning("Không thấy game", "Hãy mở Magic Survival trước.")
                    return
                rect = game_rectangle(hwnd, self.config)
            self.frame_snapshot = capture_frame(self.controller, rect, screenshot)
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
        shutdown = getattr(self.controller, "close", None)
        if shutdown is not None:
            shutdown()
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
