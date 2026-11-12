from pathlib import Path
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import cv2
import numpy as np

import botcore
from game_actions import ActionCancelled, GuardedController, select_character


class CharacterVisionTests(unittest.TestCase):
    def test_summoner_icon_is_found_in_all_24_options_at_multiple_sizes(self):
        root = Path(__file__).resolve().parent / "fixtures" / "characters"
        for filename, y in [("summoner_selected.jpg", 0.517), ("electromancer_selected.png", 0.499)]:
            original = cv2.imread(str(root / filename))
            self.assertIsNotNone(original)
            for width in (300, 540, 1080):
                with self.subTest(filename=filename, width=width):
                    frame = cv2.resize(original, (width, round(original.shape[0] * width / original.shape[1])))
                    self.assertIsNotNone(botcore.detect_selected(frame))
                    target = botcore.detect_character_option(frame)
                    self.assertIsNotNone(target)
                    self.assertAlmostEqual(target[0], 0.35, delta=0.01)
                    self.assertAlmostEqual(target[1], y, delta=0.01)

    def test_blank_or_unknown_character_has_no_target(self):
        frame = np.zeros((800, 450, 3), np.uint8)
        self.assertIsNone(botcore.detect_character_option(frame))
        for character in ("unknown", "../summoner", None):
            self.assertIsNone(botcore.detect_character_option(frame, character))

    def test_header_requires_exact_name_and_survives_ocr_failure(self):
        frame = np.zeros((800, 450, 3), np.uint8)
        for text, expected in [("Summoner", True), ("Electromancer", False), ("Summoner Damage", False)]:
            with patch("winocr.recognize_pil", new=AsyncMock(return_value=Mock(lines=[Mock(text=text)]))):
                self.assertEqual(botcore.is_character_selected(frame), expected)
        with patch("winocr.recognize_pil", new=AsyncMock(side_effect=RuntimeError("OCR unavailable"))):
            self.assertFalse(botcore.is_character_selected(frame))


class CharacterActionTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 100, 3), np.uint8)
        self.controller = Mock()
        self.controller.lock = threading.RLock()
        self.capture = Mock(return_value=self.frame)
        self.sleep = Mock()
        for name, value in [("detect_selected", (0.5, 0.93)),
                            ("detect_character_option", (0.35, 0.50)),
                            ("is_character_selected", True),
                            ("detect_enter_area", (0.5, 0.91))]:
            patcher = patch.object(botcore, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def select(self):
        return select_character(self.controller, {}, self.frame, self.capture, sleep=self.sleep)

    def test_icon_then_fresh_selected_then_map(self):
        self.detect_selected.side_effect = [(0.5, 0.93), (0.51, 0.94)]
        self.assertTrue(self.select())
        taps = [call.args[0] for call in self.controller.tap.call_args_list]
        self.assertEqual(taps, [[0.35, 0.50], [0.51, 0.94]])
        self.assertEqual(self.capture.call_count, 2)

    def test_wrong_name_never_confirms_selected(self):
        self.is_character_selected.return_value = False
        self.assertFalse(self.select())
        self.controller.tap.assert_called_once_with([0.35, 0.50], {})
        self.assertEqual(self.capture.call_count, 3)

    def test_missing_icon_sends_no_tap(self):
        self.detect_character_option.return_value = None
        self.assertFalse(self.select())
        self.controller.tap.assert_not_called()

    def test_leaving_roster_never_uses_stale_selected(self):
        self.detect_selected.side_effect = [(0.5, 0.93), None]
        self.assertFalse(self.select())
        self.controller.tap.assert_called_once()

    def test_waits_for_name_and_map_transition(self):
        self.is_character_selected.side_effect = [False, True]
        self.detect_enter_area.side_effect = [None, (0.5, 0.91)]
        self.assertTrue(self.select())
        self.assertEqual(self.capture.call_count, 4)

    def test_missing_map_is_not_reported_as_success(self):
        self.detect_enter_area.return_value = None
        self.assertFalse(self.select())
        self.assertEqual(self.controller.tap.call_count, 2)

    def test_stop_after_icon_prevents_confirmation(self):
        running = threading.Event()
        running.set()
        guarded = GuardedController(self.controller, running.is_set)
        with self.assertRaises(ActionCancelled):
            select_character(guarded, {}, self.frame, self.capture, sleep=lambda _: running.clear())
        self.controller.tap.assert_called_once()
