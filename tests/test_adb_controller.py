import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from adb_controller import ADBController


class TestADBController(unittest.TestCase):
    def setUp(self):
        self.ctrl = ADBController(screen_size=(1080, 1920))

    def test_tap_normalized_coordinates(self):
        """Test normalized coords [0.5, 0.5] scale to [540, 960] and run input tap."""
        with patch.object(self.ctrl, "_run_adb") as mock_run:
            self.ctrl.tap([0.5, 0.5])
            mock_run.assert_called_once_with(["shell", "input", "tap", "540", "960"], timeout=2.0)

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


if __name__ == "__main__":
    unittest.main()
