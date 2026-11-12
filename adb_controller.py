"""ADB-based Background Controller for Android Emulators (LDPlayer, MuMu, BlueStacks, Nox).

Allows full automated gameplay and screen capture purely inside the Android VM.
Zero interference with Windows mouse cursor or keyboard.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Optional

import cv2
import numpy as np


DEFAULT_LDPLAYER_ADB = r"D:\LDPlayer\LDPlayer9\adb.exe"


class ADBCommandError(RuntimeError):
    """A transient transport/input failure; callers must obtain a new frame."""


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
        self._swipe_lock = threading.Lock()
        self.last_move_time = 0.0
        self.last_direction_time = 0.0
        self.is_moving = False
        self.current_direction: Optional[tuple[float, float]] = None
        self.current_config: Optional[dict] = None
        self._move_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._movement_error = None
        self._find_device_and_resolution(screen_size)

    def _run_adb(self, args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(args)
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (subprocess.TimeoutExpired, OSError) as error:
            raise ADBCommandError(f"ADB không hoàn tất lệnh {' '.join(args[:3])}: {error}") from error
        if result.returncode != 0:
            raise ADBCommandError(result.stderr.decode("utf-8", errors="replace").strip() or "ADB command failed")
        return result

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
                for port in ("5555", "5556", "5558"):
                    try:
                        self._run_adb(["connect", f"127.0.0.1:{port}"], timeout=2.0)
                    except (subprocess.TimeoutExpired, RuntimeError):
                        continue
                res = self._run_adb(["devices"])
                out = res.stdout.decode("utf-8", errors="ignore")
                for line in out.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[1] == "device":
                        devices.append(parts[0])

            if not devices or (self.device and self.device not in devices):
                raise ConnectionError("Không tìm thấy thiết bị ADB đã chọn")
            if devices:
                self.device = self.device or devices[0]
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
        except Exception as error:
            raise ConnectionError(f"Không kết nối được ADB: {error}") from error

    def release(self):
        """Release movement / touches."""
        with self.lock:
            self.is_moving = False
            self.current_direction = None

    def close(self):
        """Stop the movement daemon when its runner exits."""
        self.release()
        self._stop_event.set()
        worker = self._move_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.0)

    def _calc_joystick_coords(
        self,
        direction: tuple[float, float],
        config: Optional[dict] = None,
    ) -> tuple[int, int, int, int]:
        dx, dy = direction
        jx_ratio = 0.50
        jy_ratio = 0.65
        radius_px = int(self.screen_width * 0.18)

        if config and "joystick_position" in config:
            pos = config["joystick_position"]
            if len(pos) >= 2 and pos[1] >= 0.25:
                jx_ratio, jy_ratio = pos[0], pos[1]
        if config and "joystick_radius_px" in config:
            r = int(config["joystick_radius_px"])
            if r >= 80:
                radius_px = r

        cx = max(0, min(self.screen_width - 1, int(self.screen_width * jx_ratio)))
        cy = max(0, min(self.screen_height - 1, int(self.screen_height * jy_ratio)))
        tx = max(0, min(self.screen_width - 1, int(cx + dx * radius_px)))
        ty = max(0, min(self.screen_height - 1, int(cy + dy * radius_px)))
        return cx, cy, tx, ty

    def _ensure_move_worker(self):
        with self.lock:
            if self._move_thread is None or not self._move_thread.is_alive():
                self._stop_event.clear()
                self._move_thread = threading.Thread(target=self._movement_worker_loop, daemon=True)
                self._move_thread.start()

    def _movement_worker_loop(self):
        """Background thread that continuously sustains joystick movement while vision captures/analyzes."""
        while not self._stop_event.is_set():
            time.sleep(0.03)
            if not self.is_moving:
                continue
            # Take the state lock before the swipe lock, matching GuardedController.
            # Never wait for state while owning swipe: a guarded tap owns state
            # while waiting for the previous swipe to finish.
            with self.lock:
                if not self.is_moving or not self.current_direction:
                    continue
                if time.monotonic() - self.last_direction_time > 1.0:
                    self.release()
                    continue
                direction = self.current_direction
                config = self.current_config
                cx, cy, tx, ty = self._calc_joystick_coords(direction, config)
                if not self._swipe_lock.acquire(blocking=False):
                    continue
                self.last_move_time = time.monotonic()
            failure = None
            try:
                self._run_adb(["shell", "input", "swipe", str(cx), str(cy), str(tx), str(ty), "350"], timeout=1.5)
            except Exception as error:
                failure = error
            finally:
                self._swipe_lock.release()
            if failure is not None:
                # Release swipe lock before state lock (a guarded tap may be waiting).
                with self.lock:
                    self.release()
                    self._movement_error = failure

    def move(self, direction: tuple[float, float], rect: Optional[dict] = None, config: Optional[dict] = None):
        """Send virtual swipe/joystick vector without touching Windows mouse or keyboard."""
        dx, dy = direction
        if not all(math.isfinite(v) for v in (dx, dy)):
            raise ValueError("Movement must be finite")
        if abs(dx) < 0.12 and abs(dy) < 0.12:
            self.release()
            return

        with self.lock:
            if self._movement_error is not None:
                error, self._movement_error = self._movement_error, None
                self.release()
                raise ADBCommandError(f"Lệnh di chuyển nền thất bại: {error}") from error
            self.current_direction = direction
            age = float((config or {}).get("_movement_frame_age", 0.0))
            if not math.isfinite(age) or age >= 1.0:
                self.release()
                return
            age = max(0.0, age)
            self.last_direction_time = time.monotonic() - age
            self.current_config = dict(config or {})
            self.is_moving = True
            self._ensure_move_worker()

        # If swipe lock is free (e.g. initial start, or worker between cycles), execute swipe immediately.
        # If another swipe is currently in-flight, return immediately to keep vision capture fast and non-blocking;
        # the background worker will sustain the new direction as soon as the active swipe completes.
        with self.lock:
            if self._swipe_lock.acquire(blocking=False):
                try:
                    if not self.is_moving or not self.current_direction:
                        return
                    cx, cy, tx, ty = self._calc_joystick_coords(direction, config)
                    self.last_move_time = time.monotonic()
                    self._run_adb(["shell", "input", "swipe", str(cx), str(cy), str(tx), str(ty), "350"], timeout=1.5)
                except Exception:
                    self.release()
                    raise
                finally:
                    self._swipe_lock.release()

    def tap(self, target: list[float], rect: Optional[dict] = None):
        """Tap normalized coordinates [nx, ny] (0.0..1.0) inside Android VM."""
        with self.lock:
            self.release()
            with self._swipe_lock:
                nx, ny = target[0], target[1]
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in (nx, ny)):
                    raise ValueError("Tap coordinates must be normalized")
                x = min(self.screen_width - 1, int(round(nx * self.screen_width)))
                y = min(self.screen_height - 1, int(round(ny * self.screen_height)))
                self._run_adb(["shell", "input", "tap", str(x), str(y)], timeout=2.0)

    def press_esc(self):
        """Send Back keyevent to dismiss dialogs/settings."""
        with self.lock:
            self.release()
            with self._swipe_lock:
                self._run_adb(["shell", "input", "keyevent", "4"], timeout=2.0)

    def is_game_foreground(self, package_name: str = "com.vkslrzm.Zombie") -> bool:
        """Check if Magic Survival is currently the active foreground window."""
        try:
            res = self._run_adb(["shell", "dumpsys", "window"], timeout=2.0)
            out = res.stdout.decode("utf-8", errors="ignore")
            for line in out.splitlines():
                if "mCurrentFocus" in line:
                    if "Window{" in line:
                        return package_name in line
            raise ADBCommandError("Chưa xác định được cửa sổ Android đang có focus")
        except ADBCommandError:
            self.release()
            raise

    def launch_game(self, package_name: str = "com.vkslrzm.Zombie"):
        """Bring or launch the game back to foreground if closed/crashed."""
        self.release()
        with self.lock:
            self._run_adb(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"], timeout=3.0)

    def screenshot(self) -> Optional[np.ndarray]:
        """Capture Android screen directly from framebuffer pipe in background without window focus."""
        try:
            res = self._run_adb(["exec-out", "screencap", "-p"], timeout=4.0)
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
