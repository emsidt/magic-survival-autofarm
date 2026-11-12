import unittest
from unittest.mock import AsyncMock, Mock, patch

import cv2
import numpy as np

import botcore
from game_actions import dismiss_death


def ocr_line(text, y=70):
    words = [Mock(text=word, bounding_rect=Mock(x=70, y=y, width=35, height=14)) for word in text.split()]
    return Mock(text=text, words=words)


class CrashProtectionTests(unittest.TestCase):
    def test_revive_and_death_title_never_guess_die_coordinates(self):
        frame = np.zeros((800, 450, 3), np.uint8)
        for text in ("Revive", "Life or Death", "Death"):
            result = Mock(lines=[ocr_line(text)])
            with patch("winocr.recognize_pil", new=AsyncMock(return_value=result)):
                self.assertIsNone(botcore.detect_die_button(frame, min_confidence=2.0))
                self.assertIsNone(botcore.detect_verified_die_text(frame))

    def test_revive_line_before_die_does_not_short_circuit_detection(self):
        frame = np.zeros((800, 450, 3), np.uint8)
        result = Mock(lines=[ocr_line("Revive", 30), ocr_line("Die", 100)])
        with patch("winocr.recognize_pil", new=AsyncMock(return_value=result)):
            target = botcore.detect_die_button(frame, min_confidence=2.0)
            self.assertIsNotNone(target)
            self.assertGreater(target[1], 0.65)

    def test_real_die_font_is_verified_at_multiple_sizes(self):
        template = cv2.imread("assets/die_button.png")
        for scale, w, h in [(0.52, 600, 1000), (1, 600, 1000), (2, 1080, 1920)]:
            with self.subTest(scale=scale):
                frame = np.zeros((h, w, 3), np.uint8)
                th, tw = template.shape[:2]
                image = cv2.resize(template, (round(tw * scale), round(th * scale)))
                x, y = int(w * 0.38), int(h * 0.65)
                frame[y:y+image.shape[0], x:x+image.shape[1]] = image
                target = botcore.detect_verified_die_text(frame)
                self.assertIsNotNone(target)
                # The lower Die row, never the upper Revive row.
                self.assertGreater(target[1] * h, y + image.shape[0] * 0.6)

    def test_unverified_death_sends_no_input(self):
        controller = Mock()
        capture = Mock(return_value=np.zeros((800, 450, 3), np.uint8))
        with patch("botcore.detect_die_button", return_value=(0.5, 0.73)), \
                patch("botcore.detect_verified_die_text", return_value=None):
            self.assertFalse(dismiss_death(controller, {}, capture, sleep=Mock()))
        controller.tap.assert_not_called()

    def test_fresh_verified_word_is_used_instead_of_old_template_position(self):
        controller, capture = Mock(), Mock()
        with patch("botcore.detect_die_button", return_value=(0.5, 0.73)), \
                patch("botcore.detect_verified_die_text", return_value=(0.52, 0.79)), \
                patch("botcore.detect_confirm_button", return_value=(0.5, 0.9)):
            self.assertTrue(dismiss_death(controller, {}, capture, sleep=Mock()))
        controller.tap.assert_called_once_with([0.52, 0.79], {})
        self.assertEqual(capture.call_count, 2)

    def test_changed_screen_never_taps_old_death_position(self):
        controller = Mock()
        with patch("botcore.detect_die_button", return_value=None):
            self.assertFalse(dismiss_death(controller, {}, Mock(), sleep=Mock()))
        controller.tap.assert_not_called()
