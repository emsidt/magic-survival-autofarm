import unittest
from unittest.mock import patch
from main import Controller


class TestController(unittest.TestCase):
    @patch("main.pydirectinput")
    def test_keyboard_hysteresis(self, mock_pdi):
        c = Controller()
        rect = {"left": 0, "top": 0, "width": 800, "height": 600}
        config = {"input_mode": "keyboard"}

        # 1. Below threshold (dy = -0.20): should NOT engage 'w' initially (th_on is 0.28)
        c.move((0.0, -0.20), rect, config)
        self.assertNotIn("w", c.keys)
        mock_pdi.keyDown.assert_not_called()

        # 2. Exceeds threshold (dy = -0.30): engages 'w'
        c.move((0.0, -0.30), rect, config)
        self.assertIn("w", c.keys)
        mock_pdi.keyDown.assert_called_with("w")
        mock_pdi.keyDown.reset_mock()

        # 3. Drops to dy = -0.20: should STAY engaged because of hysteresis (th_off is 0.16)
        c.move((0.0, -0.20), rect, config)
        self.assertIn("w", c.keys)
        mock_pdi.keyUp.assert_not_called()
        mock_pdi.keyDown.assert_not_called()

        # 4. Drops below th_off (dy = -0.10): should release 'w'
        c.move((0.0, -0.10), rect, config)
        self.assertNotIn("w", c.keys)
        mock_pdi.keyUp.assert_called_with("w")


if __name__ == "__main__":
    unittest.main()

