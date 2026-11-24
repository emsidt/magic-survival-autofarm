"""ADB-based Background Controller for Android Emulators (LDPlayer, MuMu, BlueStacks, Nox).

Allows full automated gameplay and screen capture purely inside the Android VM.
Zero interference with Windows mouse cursor or keyboard.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import struct
import subprocess
import threading
import time
from typing import Optional
import zlib

import cv2
import numpy as np


DEFAULT_LDPLAYER_ADB = r"D:\LDPlayer\LDPlayer9\adb.exe"


def _parse_touch_device_from_getevent(output: str) -> Optional[tuple[str, int, int]]:
    """Parse `getevent -p` output and return (device_path, max_x, max_y) for the multitouch screen."""
    if not output:
        return None
    blocks = re.split(r"(?=add device \d+:)", output)
    for block in blocks:
        dev_match = re.match(r"add device \d+:\s*(/dev/input/event\d+)", block.strip())
        if not dev_match:
            continue
        if "INPUT_PROP_DIRECT" not in block:
            continue
        if not re.search(r"\b002f\b", block) or not re.search(r"\b0039\b", block):
            continue
        mx = re.search(r"\b0035\b[^\n]*?\bmax\s+(\d+)", block)
        my = re.search(r"\b0036\b[^\n]*?\bmax\s+(\d+)", block)
        if mx and my:
            max_x = int(mx.group(1))
            max_y = int(my.group(1))
            if max_x > 0 and max_y > 0:
                return dev_match.group(1), max_x, max_y
    return None


def _decode_screenshot_bytes(data: bytes) -> Optional[np.ndarray]:
    """Decode PNG, gzipped raw RGBA, or raw Android screencap RGBA bytes into a BGR ndarray."""
    if not data:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        img_arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if data[:2] == b"\x1f\x8b":
        try:
            data = zlib.decompress(data, 16 + zlib.MAX_WBITS)
        except zlib.error:
            return None
    if len(data) < 16:
        return None
    w, h, fmt = struct.unpack_from("<III", data, 0)
    if w <= 0 or h <= 0 or w > 8192 or h > 8192 or fmt != 1:
        return None
    header_size = len(data) - (w * h * 4)
    if header_size not in (12, 16):
        return None
    rgba = np.frombuffer(data, dtype=np.uint8, offset=header_size).reshape((h, w, 4))
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)


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
        self._touch_lock = threading.Lock()
        self.last_move_time = 0.0
        self.last_direction_time = 0.0
        self.is_moving = False
        self.current_direction: Optional[tuple[float, float]] = None
        self.current_config: Optional[dict] = None
        self._move_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._movement_error = None
        self._touch_device: Optional[str] = None
        self._touch_max_x: int = 0
        self._touch_max_y: int = 0
        self._touch_proc: Optional[subprocess.Popen] = None
        self._touch_down: bool = False
        self._touch_tracking_id: int = 1
        self._last_touch_xy: Optional[tuple[int, int]] = None
        self._capture_mode: str = "png"
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

    def _detect_touch_device(self):
        """Probe Android input device and raw multitouch ranges for zero-stutter persistent touch."""
        try:
            res = self._run_adb(["shell", "getevent", "-p"], timeout=2.0)
            out = res.stdout.decode("utf-8", errors="ignore")
            parsed = _parse_touch_device_from_getevent(out)
            if parsed is None:
                return
            dev_path, max_x, max_y = parsed

            in_res = self._run_adb(["shell", "dumpsys", "input"], timeout=2.0)
            in_out = in_res.stdout.decode("utf-8", errors="ignore")
            orient_match = re.search(
                r"Touch Input Mapper \(mode - direct\).*?SurfaceOrientation:\s*(\d+)",
                in_out,
                re.DOTALL,
            )
            if orient_match is not None and orient_match.group(1) != "0":
                return

            self._touch_device = dev_path
            self._touch_max_x = max_x
            self._touch_max_y = max_y
        except Exception:
            self._touch_device = None
            self._touch_max_x = 0
            self._touch_max_y = 0

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
                self._capture_mode = "gzip"
                self._detect_touch_device()
        except Exception as error:
            raise ConnectionError(f"Không kết nối được ADB: {error}") from error

    def _scale_touch_xy(self, sx: int, sy: int) -> tuple[int, int]:
        """Scale screen pixel coordinates [0, screen_w-1] x [0, screen_h-1] to raw touch axis range."""
        max_sx = max(1, self.screen_width - 1)
        max_sy = max(1, self.screen_height - 1)
        tx = int(round(max(0, min(max_sx, sx)) * self._touch_max_x / max_sx))
        ty = int(round(max(0, min(max_sy, sy)) * self._touch_max_y / max_sy))
        return (
            max(0, min(self._touch_max_x, tx)),
            max(0, min(self._touch_max_y, ty)),
        )

    def _ensure_touch_shell(self) -> Optional[subprocess.Popen]:
        """Start or reuse persistent `adb shell` pipe for low-latency sendevent injection."""
        proc = self._touch_proc
        if proc is not None:
            if proc.poll() is None and proc.stdin is not None:
                return proc
            self._touch_proc = None
            self._touch_down = False
            self._last_touch_xy = None
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.append("shell")
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._touch_proc = proc
            return proc
        except OSError:
            self._touch_proc = None
            return None

    def _write_touch_cmd(self, cmd: str) -> bool:
        """Write one shell command line to the persistent ADB shell stdin pipe."""
        proc = self._ensure_touch_shell()
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write((cmd + "\n").encode("ascii"))
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.terminate()
            except OSError:
                pass
            self._touch_proc = None
            self._touch_down = False
            self._last_touch_xy = None
            return False

    def _touch_move_joystick(self, cx: int, cy: int, tx: int, ty: int) -> bool:
        """Keep slot 0 continuously held DOWN and stream MOVE updates without lifting."""
        with self._touch_lock:
            dev = self._touch_device
            if not dev or self._touch_max_x <= 0 or self._touch_max_y <= 0:
                return False
            rcx, rcy = self._scale_touch_xy(cx, cy)
            rtx, rty = self._scale_touch_xy(tx, ty)
            if not self._touch_down:
                self._touch_tracking_id = (self._touch_tracking_id % 60000) + 1
                tid = self._touch_tracking_id
                down_cmd = (
                    f"sendevent {dev} 3 47 0; "
                    f"sendevent {dev} 3 57 {tid}; "
                    f"sendevent {dev} 1 330 1; "
                    f"sendevent {dev} 3 53 {rcx}; "
                    f"sendevent {dev} 3 54 {rcy}; "
                    f"sendevent {dev} 3 58 1; "
                    f"sendevent {dev} 0 0 0"
                )
                if not self._write_touch_cmd(down_cmd):
                    return False
                time.sleep(0.015)
                move_cmd = (
                    f"sendevent {dev} 3 53 {rtx}; "
                    f"sendevent {dev} 3 54 {rty}; "
                    f"sendevent {dev} 0 0 0"
                )
                if not self._write_touch_cmd(move_cmd):
                    return False
                self._touch_down = True
                self._last_touch_xy = (rtx, rty)
                return True

            if (rtx, rty) != self._last_touch_xy:
                move_cmd = (
                    f"sendevent {dev} 3 53 {rtx}; "
                    f"sendevent {dev} 3 54 {rty}; "
                    f"sendevent {dev} 0 0 0"
                )
                if not self._write_touch_cmd(move_cmd):
                    return False
                self._last_touch_xy = (rtx, rty)
            return True

    def _touch_up(self):
        """Release persistent slot 0 touch if currently held down."""
        with self._touch_lock:
            dev = self._touch_device
            if not self._touch_down or not dev:
                return
            up_cmd = (
                f"sendevent {dev} 3 47 0; "
                f"sendevent {dev} 3 57 -1; "
                f"sendevent {dev} 1 330 0; "
                f"sendevent {dev} 0 0 0"
            )
            self._write_touch_cmd(up_cmd)
            self._touch_down = False
            self._last_touch_xy = None

    def _close_touch_shell(self):
        """Release any held touch and close the persistent ADB shell subprocess."""
        self._touch_up()
        with self._touch_lock:
            proc = self._touch_proc
            self._touch_proc = None
            self._touch_down = False
            self._last_touch_xy = None
            if proc is not None:
                if proc.stdin is not None:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                try:
                    proc.terminate()
                except OSError:
                    pass

    def release(self):
        """Release movement / touches."""
        with self.lock:
            self.is_moving = False
            self.current_direction = None
            self._touch_up()

    def close(self):
        """Stop the movement daemon and close persistent shell when its runner exits."""
        self.release()
        self._stop_event.set()
        worker = self._move_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        self._close_touch_shell()

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
            time.sleep(0.01 if self.is_moving else 0.03)
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
                if self._touch_device:
                    continue
                direction = self.current_direction
                config = self.current_config
                swipe_ms = max(80, min(600, int((config or {}).get("swipe_duration_ms", 350))))
                cx, cy, tx, ty = self._calc_joystick_coords(direction, config)
                if not self._swipe_lock.acquire(blocking=False):
                    continue
                self.last_move_time = time.monotonic()
            failure = None
            try:
                self._run_adb(["shell", "input", "swipe", str(cx), str(cy), str(tx), str(ty), str(swipe_ms)], timeout=1.5)
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

        async_move = bool((config or {}).get("async_move", False))
        swipe_ms = max(80, min(600, int((config or {}).get("swipe_duration_ms", 350))))
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
            if self._touch_device:
                cx, cy, tx, ty = self._calc_joystick_coords(direction, config)
                if self._touch_move_joystick(cx, cy, tx, ty):
                    self.last_move_time = time.monotonic()
                    return
                self._touch_device = None
                self._close_touch_shell()
        if async_move:
            return

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
                    self._run_adb(["shell", "input", "swipe", str(cx), str(cy), str(tx), str(ty), str(swipe_ms)], timeout=1.5)
                except Exception:
                    self.release()
                    raise
                finally:
                    self._swipe_lock.release()

    def tap(self, target: list[float], rect: Optional[dict] = None):
        """Tap normalized coordinates [nx, ny] (0.0..1.0) inside Android VM."""
        with self.lock:
            was_down = self._touch_down
            self.release()
            with self._swipe_lock:
                if was_down:
                    time.sleep(0.02)
                nx, ny = target[0], target[1]
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in (nx, ny)):
                    raise ValueError("Tap coordinates must be normalized")
                x = min(self.screen_width - 1, int(round(nx * self.screen_width)))
                y = min(self.screen_height - 1, int(round(ny * self.screen_height)))
                self._run_adb(["shell", "input", "tap", str(x), str(y)], timeout=2.0)

    def press_esc(self):
        """Send Back keyevent to dismiss dialogs/settings."""
        with self.lock:
            was_down = self._touch_down
            self.release()
            with self._swipe_lock:
                if was_down:
                    time.sleep(0.02)
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

    def restart_game(self, package_name: str = "com.vkslrzm.Zombie"):
        """Force-stop the game (clearing stuck ad/WebView activities) and relaunch it."""
        self.close_external_browsers()
        with self.lock:
            try:
                self._run_adb(["shell", "am", "force-stop", package_name], timeout=3.0)
            except Exception:
                pass
            time.sleep(1.0)
            self._run_adb(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"], timeout=3.0)

    def get_foreground_package(self) -> Optional[str]:
        """Return the package name of the currently focused Android window, if any."""
        try:
            res = self._run_adb(["shell", "dumpsys", "window"], timeout=2.0)
            out = res.stdout.decode("utf-8", errors="ignore")
            for line in out.splitlines():
                if "mCurrentFocus" in line and "Window{" in line:
                    m = re.search(r"u\d+\s+([^/]+)/", line)
                    if m:
                        return m.group(1).strip()
        except Exception:
            pass
        return None

    def close_external_browsers(self):
        """Force-stop external browsers and app stores that hijack clicks (Chrome, Play Store, Android Browser)."""
        unwanted_packages = (
            "com.android.chrome",
            "com.android.browser",
            "com.android.vending",
            "org.chromium.chrome",
            "com.google.android.apps.chrome",
        )
        self.release()
        with self.lock:
            for pkg in unwanted_packages:
                try:
                    self._run_adb(["shell", "am", "force-stop", pkg], timeout=2.0)
                except Exception:
                    pass

    def screenshot(self) -> Optional[np.ndarray]:
        """Capture Android screen directly from framebuffer pipe in background without window focus."""
        modes = ("gzip", "png") if self._capture_mode == "gzip" else ("png",)
        for mode in modes:
            try:
                cmd = ["exec-out", "screencap | gzip -1"] if mode == "gzip" else ["exec-out", "screencap", "-p"]
                res = self._run_adb(cmd, timeout=4.0)
                if res.returncode == 0 and res.stdout:
                    img = _decode_screenshot_bytes(res.stdout)
                    if img is not None:
                        # Update screen resolution dynamically if changed
                        self.screen_height, self.screen_width = img.shape[:2]
                        return img
            except Exception:
                pass
        return None
