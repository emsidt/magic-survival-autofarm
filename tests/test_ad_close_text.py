import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import botcore


class AdCloseTextTests(unittest.TestCase):
    def recognize(self, text, y=40):
        words = []
        x = 25
        for token in text.split():
            width = len(token) * 8
            words.append(Mock(text=token, bounding_rect=Mock(x=x, y=y, width=width, height=18)))
            x += width + 6
        return Mock(lines=[Mock(text=text, words=words)])

    def test_vietnamese_and_english_close_labels(self):
        frame = np.zeros((900, 500, 3), np.uint8)
        for text in ("Đóng", "Dong", "Đóng lại", "Close", "Close ad", "Bỏ qua", "Bo qua", "Skip ad", "No, thanks"):
            with self.subTest(text=text), patch("winocr.recognize_pil", new=AsyncMock(return_value=self.recognize(text))):
                point = botcore.detect_ad_close_text(frame)
                self.assertIsNotNone(point)
                self.assertAlmostEqual(point[1], 49 / 900)

    def test_bottom_text_button_is_not_excluded(self):
        frame = np.zeros((900, 500, 3), np.uint8)
        with patch("winocr.recognize_pil", new=AsyncMock(return_value=self.recognize("Close", 860))):
            self.assertGreater(botcore.detect_ad_close_text(frame)[1], 0.95)

    def test_install_countdown_and_descriptions_are_not_close_buttons(self):
        frame = np.zeros((900, 500, 3), np.uint8)
        for text in ("Cài đặt", "Install", "Skip in 5", "Skip 5", "Close combat", "Close the enemy", "Đóng góp", "Skip to install"):
            with self.subTest(text=text), patch("winocr.recognize_pil", new=AsyncMock(return_value=self.recognize(text))):
                self.assertIsNone(botcore.detect_ad_close_text(frame))

    def test_text_button_wins_before_decorative_cross_templates(self):
        names = ("detect_start_game", "detect_enter_area", "detect_selected", "detect_confirm_button",
                 "detect_die_button", "detect_pause_button", "detect_obtain_button", "is_chest_screen",
                 "detect_buy_button", "detect_learn_button", "is_attribute_screen", "detect_settings_gear")
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(botcore, name, return_value=None))
            stack.enter_context(patch("botcore.detect_ad_close_text", return_value=(0.12, 0.05)))
            match = stack.enter_context(patch("botcore.cv2.matchTemplate", side_effect=AssertionError("text already found")))
            self.assertEqual(botcore.detect_close_button(np.zeros((900, 500, 3), np.uint8)), (0.12, 0.05))
            match.assert_not_called()

    def test_pill_dong_button_and_ad_screen_on_real_image(self):
        import cv2
        from pathlib import Path
        img_path = Path(__file__).parent / "fixtures/ads/dong_button.jpg"
        self.assertTrue(img_path.is_file())
        frame = cv2.imread(str(img_path))
        btn = botcore.detect_close_button(frame)
        self.assertIsNotNone(btn)
        # 'Đóng' pill button is at top-left: x ~ 0.11, y ~ 0.06
        self.assertAlmostEqual(btn[0], 0.11, delta=0.05)
        self.assertAlmostEqual(btn[1], 0.06, delta=0.04)

        # Ad screen must NEVER be marked as combat gameplay
        vis = botcore.inspect_game(frame)
        self.assertFalse(vis.gameplay)
        self.assertTrue(vis.modal)
        self.assertTrue(botcore.is_ad_screen(frame))
        small = botcore.prepare_analysis_frame(frame)
        small_btn = botcore.detect_close_button(small)
        self.assertAlmostEqual(small_btn[0], btn[0], delta=0.02)
        self.assertAlmostEqual(small_btn[1], btn[1], delta=0.02)

    def test_dark_pill_dong_button_on_real_image(self):
        import cv2
        from pathlib import Path
        img_path = Path(__file__).parent / "fixtures/ads/dong_pill_dark.jpg"
        self.assertTrue(img_path.is_file())
        frame = cv2.imread(str(img_path))
        btn = botcore.detect_close_button(frame)
        self.assertIsNotNone(btn)
        # Dark 'Đóng' pill button is at top-left: x ~ 0.11, y ~ 0.07
        self.assertAlmostEqual(btn[0], 0.11, delta=0.04)
        self.assertAlmostEqual(btn[1], 0.07, delta=0.04)

        # Must also detect correctly at native 1080x1920 emulator resolution where OCR reads 'D6ng'
        up_btn = botcore.detect_close_button(cv2.resize(frame, (1080, 1920)))
        self.assertIsNotNone(up_btn)
        self.assertAlmostEqual(up_btn[0], 0.11, delta=0.04)
        self.assertAlmostEqual(up_btn[1], 0.07, delta=0.04)

        vis = botcore.inspect_game(frame)
        self.assertFalse(vis.gameplay)
        self.assertTrue(vis.modal)
        self.assertTrue(botcore.is_ad_screen(frame))

    def test_confirmation_dialog_dong_button_selected_over_question(self):
        import cv2
        from pathlib import Path
        img_path = Path(__file__).parent / "fixtures/ads/dong_confirmation.png"
        self.assertTrue(img_path.is_file())
        frame = cv2.imread(str(img_path))
        btn = botcore.detect_close_button(frame)
        self.assertIsNotNone(btn)
        # The dialog has title 'Đóng quảng cáo?' and button 'ĐÓNG' at center x ~ 0.51, y ~ 0.57.
        # Must choose the button 'ĐÓNG', NOT the title question!
        self.assertAlmostEqual(btn[0], 0.51, delta=0.04)
        self.assertAlmostEqual(btn[1], 0.57, delta=0.04)

        vis = botcore.inspect_game(frame)
        self.assertFalse(vis.gameplay)
        self.assertTrue(vis.modal)
        self.assertTrue(botcore.is_ad_screen(frame))
        small = botcore.prepare_analysis_frame(frame)
        small_btn = botcore.detect_close_button(small)
        self.assertAlmostEqual(small_btn[0], btn[0], delta=0.02)
        self.assertAlmostEqual(small_btn[1], btn[1], delta=0.02)

    def test_confirmation_dialog_dong_video_selected_over_question(self):
        import cv2
        from pathlib import Path
        img_path = Path(__file__).parent / "fixtures/ads/dong_video_confirmation.jpg"
        self.assertTrue(img_path.is_file())
        frame = cv2.imread(str(img_path))
        btn = botcore.detect_close_button(frame)
        self.assertIsNotNone(btn)
        # The dialog has title 'Đóng video?' and button 'ĐÓNG VIDEO' at center x ~ 0.36, y ~ 0.58.
        # Must choose the button 'ĐÓNG VIDEO', NOT the title question!
        self.assertAlmostEqual(btn[0], 0.36, delta=0.04)
        self.assertAlmostEqual(btn[1], 0.58, delta=0.04)

        # Must also detect correctly at native 1080x1920 emulator resolution
        up_btn = botcore.detect_close_button(cv2.resize(frame, (1080, 1920)))
        self.assertIsNotNone(up_btn)
        self.assertAlmostEqual(up_btn[0], 0.36, delta=0.04)
        self.assertAlmostEqual(up_btn[1], 0.58, delta=0.04)

        vis = botcore.inspect_game(frame)
        self.assertFalse(vis.gameplay)
        self.assertTrue(vis.modal)
        self.assertTrue(botcore.is_ad_screen(frame))
