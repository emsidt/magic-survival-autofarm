"""ADB-based Background Controller for Android Emulators (LDPlayer, MuMu, BlueStacks, Nox).

Allows full automated gameplay and screen capture purely inside the Android VM.
Zero interference with Windows mouse cursor or keyboard.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Optional

import cv2
import numpy as np


DEFAULT_LDPLAYER_ADB = r"D:\LDPlayer\LDPlayer9\adb.exe"


class ADBController:
    """Controls the game via Android Debug Bridge (ADB) without touching laptop mouse or keyboard."""

    def __init__(
        self,
        adb_path: str = DEFAULT_LDPLAYER_ADB,
        device: Optional[str] = None,
        screen_size: Optional[tuple[int, int]] = None,
    ):
        self.adb_path = str(Path(adb_path).resolve()) if Path(adb_path).is_file() else "adb"
        self.device = device
        self.screen_width = 1080
        self.screen_height = 1920
        self.lock = threading.RLock()
        self.last_move_time = 0.0
        self.is_moving = False
        self._find_device_and_resolution(screen_size)

    def _run_adb(self, args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(args)
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)

    def _find_device_and_resolution(self, screen_size: Optional[tuple[int, int]] = None):
        """Auto-detect running LDPlayer emulator via ADB and query its resolution."""
        if screen_size:
            self.screen_width, self.screen_height = screen_size
            return

        try:
            res = self._run_adb(["devices"])
            out = res.stdout.decode("utf-8", errors="ignore")
            devices = []
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])

            # If no device connected yet, try connecting to standard LDPlayer ports
            if not devices:
                for port in ("5555", "5554", "5556", "5558", "127.0.0.1:5555"):
                    self._run_adb(["connect", f"127.0.0.1:{port}"], timeout=2.0)
                res = self._run_adb(["devices"])
                out = res.stdout.decode("utf-8", errors="ignore")
                for line in out.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[1] == "device":
                        devices.append(parts[0])

            if devices:
                self.device = devices[0]
                # Query screen resolution (prefer active screencap dimensions)
                frame = self.screenshot()
                if frame is not None:
                    self.screen_height, self.screen_width = frame.shape[:2]
                else:
                    disp_res = self._run_adb(["shell", "dumpsys", "window", "displays"], timeout=3.0)
                    disp_out = disp_res.stdout.decode("utf-8", errors="ignore")
                    m_cur = re.search(r"cur=(\d+)x(\d+)", disp_out)
                    if m_cur:
                        self.screen_width = int(m_cur.group(1))
                        self.screen_height = int(m_cur.group(2))
                    else:
                        wm_res = self._run_adb(["shell", "wm", "size"], timeout=3.0)
                        wm_out = wm_res.stdout.decode("utf-8", errors="ignore")
                        m = re.search(r"Physical size:\s*(\d+)x(\d+)", wm_out) or re.search(r"(\d+)x(\d+)", wm_out)
                        if m:
                            self.screen_width = int(m.group(1))
                            self.screen_height = int(m.group(2))
        except Exception:
            pass

    def release(self):
        """Release movement / touches."""
        with self.lock:
            self.is_moving = False

    def move(self, direction: tuple[float, float], rect: Optional[dict] = None, config: Optional[dict] = None):
        """Send virtual swipe/joystick vector without touching Windows mouse or keyboard."""
        with self.lock:
            dx, dy = direction
            if abs(dx) < 0.12 and abs(dy) < 0.12:
                self.release()
                return

            now = time.monotonic()
            if now - self.last_move_time < 0.16:
                return
            self.last_move_time = now

            # Default joystick centered at bottom-half of mobile screen
            jx_ratio = 0.50
            jy_ratio = 0.65
            radius_px = int(self.screen_width * 0.18)

            if config and "joystick_position" in config:
                jx_ratio, jy_ratio = config["joystick_position"]
            if config and "joystick_radius_px" in config:
                radius_px = int(config["joystick_radius_px"])

            cx = int(self.screen_width * jx_ratio)
            cy = int(self.screen_height * jy_ratio)
            tx = int(cx + dx * radius_px)
            ty = int(cy + dy * radius_px)

            try:
                # Use swipe with short duration (220ms) to simulate continuous joystick hold
                self._run_adb(["shell", "input", "swipe", str(cx), str(cy), str(tx), str(ty), "220"], timeout=1.0)
                self.is_moving = True
            except Exception:
                pass

    def tap(self, target: list[float], rect: Optional[dict] = None):
        """Tap normalized coordinates [nx, ny] (0.0..1.0) inside Android VM."""
        with self.lock:
            self.release()
            nx, ny = target[0], target[1]
            x = int(round(nx * self.screen_width))
            y = int(round(ny * self.screen_height))
            try:
                self._run_adb(["shell", "input", "tap", str(x), str(y)], timeout=2.0)
            except Exception:
                pass

    def press_esc(self):
        """Send Back keyevent to dismiss dialogs/settings."""
        with self.lock:
            self.release()
            try:
                self._run_adb(["shell", "input", "keyevent", "4"], timeout=2.0)
            except Exception:
                pass

    def screenshot(self) -> Optional[np.ndarray]:
        """Capture Android screen directly from framebuffer pipe in background without window focus."""
        try:
            cmd = [self.adb_path]
            if self.device:
                cmd.extend(["-s", self.device])
            cmd.extend(["exec-out", "screencap", "-p"])
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4.0)
            if res.returncode == 0 and res.stdout:
                img_arr = np.frombuffer(res.stdout, dtype=np.uint8)
                img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
                if img is not None:
                    # Update screen resolution dynamically if changed
                    self.screen_height, self.screen_width = img.shape[:2]
                    return img
        except Exception:
            pass
        return None
