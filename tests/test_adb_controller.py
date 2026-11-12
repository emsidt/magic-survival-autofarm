import unittest
import subprocess
from unittest.mock import patch, MagicMock
import numpy as np

from adb_controller import ADBController, ADBCommandError


class TestADBController(unittest.TestCase):
    def setUp(self):
        self.ctrl = ADBController(screen_size=(1080, 1920))
        # Unit tests must never leave a daemon sending real ADB input after mocks exit.
        patcher = patch.object(self.ctrl, "_ensure_move_worker")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_worker_drops_stale_direction(self):
        self.ctrl.is_moving = True
        self.ctrl.current_direction = (1, 0)
        self.ctrl.last_direction_time = 0
        with patch.object(self.ctrl, "_run_adb") as run, \
                patch.object(self.ctrl._stop_event, "is_set", side_effect=[False, True]), \
                patch("adb_controller.time.monotonic", return_value=2), \
                patch("adb_controller.time.sleep"):
            self.ctrl._movement_worker_loop()
        run.assert_not_called()
        self.assertFalse(self.ctrl.is_moving)

    def test_worker_sustains_fresh_direction(self):
        self.ctrl.is_moving = True
        self.ctrl.current_direction = (1, 0)
        self.ctrl.last_direction_time = 2
        with patch.object(self.ctrl, "_run_adb") as run, \
                patch.object(self.ctrl._stop_event, "is_set", side_effect=[False, True]), \
                patch("adb_controller.time.monotonic", return_value=2.2), \
                patch("adb_controller.time.sleep"):
            self.ctrl._movement_worker_loop()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1], "350")

    def test_frame_age_expires_motion_from_capture_not_last_move_call(self):
        with patch.object(self.ctrl, "_run_adb") as run, patch("adb_controller.time.monotonic", return_value=5):
            self.ctrl.move((1, 0), config={"_movement_frame_age": 0.75})
            run.assert_called_once()
        with patch.object(self.ctrl, "_run_adb") as run, \
                patch.object(self.ctrl._stop_event, "is_set", side_effect=[False, True]), \
                patch("adb_controller.time.monotonic", return_value=5.3), patch("adb_controller.time.sleep"):
            self.ctrl._movement_worker_loop()
        run.assert_not_called()
        self.assertFalse(self.ctrl.is_moving)

    def test_stale_or_invalid_frame_age_sends_no_swipe(self):
        for age in (1.1, float("nan"), float("inf")):
            with self.subTest(age=age), patch.object(self.ctrl, "_run_adb") as run:
                self.ctrl.move((1, 0), config={"_movement_frame_age": age})
                run.assert_not_called()
                self.assertFalse(self.ctrl.is_moving)

    def test_focus_query_failure_never_assumes_game_is_ready(self):
        with patch.object(self.ctrl, "_run_adb", side_effect=ADBCommandError("timeout")):
            with self.assertRaises(ADBCommandError):
                self.ctrl.is_game_foreground()
        with patch.object(self.ctrl, "_run_adb", return_value=MagicMock(stdout=b"mCurrentFocus=null")):
            with self.assertRaises(ADBCommandError):
                self.ctrl.is_game_foreground()

    def test_close_stops_and_joins_background_worker(self):
        self.ctrl._move_thread = MagicMock()
        self.ctrl.close()
        self.assertTrue(self.ctrl._stop_event.is_set())
        self.ctrl._move_thread.join.assert_called_once_with(timeout=2.0)

    def test_tap_normalized_coordinates(self):
        """Test normalized coords [0.5, 0.5] scale to [540, 960] and run input tap."""
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.tap([0.5, 0.5])
            mock_run.assert_called_once_with(["shell", "input", "tap", "540", "960"], timeout=2.0)

    def test_subprocess_timeout_becomes_recoverable_adb_error(self):
        with patch("adb_controller.subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 1.5)) as run:
            with self.assertRaises(ADBCommandError):
                self.ctrl._run_adb(["shell", "input", "swipe"], timeout=1.5)
        run.assert_called_once()  # Never replay a command whose outcome is unknown.

    def test_move_failure_clears_direction_and_unlocks_swipe(self):
        with patch.object(self.ctrl, "_run_adb", side_effect=ADBCommandError("timeout")):
            with self.assertRaises(ADBCommandError):
                self.ctrl.move((1, 0))
        self.assertFalse(self.ctrl.is_moving)
        self.assertIsNone(self.ctrl.current_direction)
        self.assertTrue(self.ctrl._swipe_lock.acquire(blocking=False))
        self.ctrl._swipe_lock.release()

    def test_worker_failure_stops_and_is_reported_once(self):
        self.ctrl.is_moving = True
        self.ctrl.current_direction = (1, 0)
        self.ctrl.last_direction_time = 2
        with patch.object(self.ctrl, "_run_adb", side_effect=ADBCommandError("timeout")), \
                patch.object(self.ctrl._stop_event, "is_set", side_effect=[False, True]), \
                patch("adb_controller.time.monotonic", return_value=2.2), \
                patch("adb_controller.time.sleep"):
            self.ctrl._movement_worker_loop()
        self.assertFalse(self.ctrl.is_moving)
        with patch.object(self.ctrl, "_run_adb") as run:
            with self.assertRaises(ADBCommandError):
                self.ctrl.move((0, 1))
            run.assert_not_called()
            self.ctrl.move((0, -1))
            run.assert_called_once()

    def test_tap_at_edge_stays_inside_frame(self):
        with patch.object(self.ctrl, "_run_adb") as run:
            self.ctrl.tap([1, 1])
            run.assert_called_once_with(["shell", "input", "tap", "1079", "1919"], timeout=2.0)

    def test_explicit_device_is_not_replaced_by_first_device(self):
        response = MagicMock(stdout=b"List of devices attached\nfirst\tdevice\nchosen\tdevice\n")
        with patch.object(ADBController, "_run_adb", return_value=response), patch.object(ADBController, "screenshot", return_value=np.zeros((200, 100, 3), np.uint8)):
            ctrl = ADBController(device="chosen")
        self.assertEqual(ctrl.device, "chosen")

    def test_failed_tap_is_reported_to_caller(self):
        with patch.object(self.ctrl, "_run_adb", side_effect=RuntimeError("device offline")):
            with self.assertRaises(RuntimeError):
                self.ctrl.tap([0.5, 0.5])

    def test_move_swipe_joystick(self):
        """Test movement direction sends input swipe with duration."""
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            # Move East (dx=1.0, dy=0.0)
            self.ctrl.move((1.0, 0.0), config={"joystick_position": [0.5, 0.65], "joystick_radius_px": 200})
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[:3], ["shell", "input", "swipe"])
            cx, cy = int(args[3]), int(args[4])
            tx, ty = int(args[5]), int(args[6])
            self.assertEqual(cx, 540)
            self.assertEqual(cy, 1248)
            self.assertEqual(tx, 740)  # cx + dx * radius (540 + 200)
            self.assertEqual(ty, 1248)

    def test_press_esc(self):
        """Test press_esc sends Android back keyevent 4."""
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.press_esc()
            mock_run.assert_called_once_with(["shell", "input", "keyevent", "4"], timeout=2.0)

    def test_screenshot_buffer_decoding(self):
        """Test screenshot method decodes PNG byte stream into numpy BGR frame."""
        import cv2
        fake_img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, png_bytes = cv2.imencode(".png", fake_img)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = png_bytes.tobytes()

        with patch("subprocess.run", return_value=mock_proc):
            frame = self.ctrl.screenshot()
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, (100, 100, 3))

    def test_is_game_foreground_and_launch(self):
        """Test foreground check via dumpsys window and game launch via monkey."""
        mock_res = MagicMock()
        mock_res.stdout = b"mCurrentFocus=Window{bbc8fda u0 com.vkslrzm.Zombie/com.unity3d.player.UnityPlayerActivity}\n"
        with patch.object(self.ctrl, "_run_adb", return_value=mock_res):
            self.assertTrue(self.ctrl.is_game_foreground())

        mock_launcher = MagicMock()
        mock_launcher.stdout = b"mCurrentFocus=Window{123 u0 com.ldmnq.launcher3}\n"
        with patch.object(self.ctrl, "_run_adb", return_value=mock_launcher):
            self.assertFalse(self.ctrl.is_game_foreground())

        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.launch_game()
            mock_run.assert_called_once_with(
                ["shell", "monkey", "-p", "com.vkslrzm.Zombie", "-c", "android.intent.category.LAUNCHER", "1"],
                timeout=3.0,
            )

    def test_get_foreground_package_and_close_external_browsers(self):
        """Test reading focused package and killing unwanted browser/store apps."""
        mock_res = MagicMock()
        mock_res.stdout = b"mCurrentFocus=Window{ceef773 u0 com.android.chrome/com.google.android.apps.chrome.Main}\n"
        with patch.object(self.ctrl, "_run_adb", return_value=mock_res):
            self.assertEqual(self.ctrl.get_foreground_package(), "com.android.chrome")

        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.close_external_browsers()
            calls = [c.args[0] for c in mock_run.call_args_list]
            self.assertIn(["shell", "am", "force-stop", "com.android.chrome"], calls)
            self.assertIn(["shell", "am", "force-stop", "com.android.vending"], calls)

    def test_continuous_movement_sustains_and_stops_on_release(self):
        """Test continuous movement keeps sending swipes until release() is called."""
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.move((1.0, 0.0), config={"joystick_position": [0.5, 0.65], "joystick_radius_px": 200})
            self.assertTrue(self.ctrl.is_moving)
            self.assertEqual(self.ctrl.current_direction, (1.0, 0.0))
            self.ctrl.release()
            self.assertFalse(self.ctrl.is_moving)
            self.assertIsNone(self.ctrl.current_direction)

    def test_swipe_lock_prevents_concurrent_swipes(self):
        """When a swipe is already executing, move() updates direction without executing concurrent swipe."""
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            # Simulate an in-flight swipe by acquiring _swipe_lock
            acquired = self.ctrl._swipe_lock.acquire(blocking=False)
            self.assertTrue(acquired)
            try:
                self.ctrl.move((0.0, 1.0), config={"joystick_position": [0.5, 0.65], "joystick_radius_px": 200})
                # No new swipe was sent because lock was busy
                mock_run.assert_not_called()
                # But current_direction was safely updated for the worker thread
                self.assertEqual(self.ctrl.current_direction, (0.0, 1.0))
            finally:
                self.ctrl._swipe_lock.release()

    def test_tap_acquires_swipe_lock_and_releases_movement(self):
        """Tap stops movement and executes under swipe lock."""
        self.ctrl.is_moving = True
        self.ctrl.current_direction = (1.0, 0.0)
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.tap([0.5, 0.5])
            self.assertFalse(self.ctrl.is_moving)
            self.assertIsNone(self.ctrl.current_direction)
            mock_run.assert_called_once_with(["shell", "input", "tap", "540", "960"], timeout=2.0)


if __name__ == "__main__":
    unittest.main()
