from contextlib import ExitStack
from types import SimpleNamespace
import sys
import queue
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import cv2
import numpy as np

import botcore


class TestVisionRegressions(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((1000, 800, 3), dtype=np.uint8)

    def test_artifact_scoring_survives_unavailable_ocr(self):
        with patch.dict(sys.modules, {"winocr": None}):
            for evaluate in (botcore.evaluate_selected_chest_artifact, botcore.evaluate_selected_shop_artifact):
                score, label = evaluate(self.frame)
                self.assertGreaterEqual(score, 0)
                self.assertIn("Artifact", label)

    def test_red_ring_is_not_a_combination_star(self):
        cv2.circle(self.frame, (715, 140), 36, (30, 30, 220), 6)
        with patch("botcore.is_attribute_screen", return_value=False), patch("botcore.is_chest_screen", return_value=False), patch("botcore.detect_die_button", return_value=None):
            self.assertIsNone(botcore.detect_combination_star(self.frame))

    def test_maxed_slots_are_excluded_from_every_selection_branch(self):
        cards = {
            1: botcore.CardSlotData(1, skills=["adrenaline"], is_special_passive=True,
                                   special_passive_name="adrenaline", has_asterisk=True),
            2: botcore.CardSlotData(2, freeze_traits=["absolute zero"], is_maxed=True),
            3: botcore.CardSlotData(3, text_lines=["Unknown choice"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards), patch("botcore._detect_skills_templates", return_value={}):
            result = botcore.choose_best_artifact_or_card(self.frame, default_choice=1, maxed_skills={"adrenaline"})
            self.assertEqual(result.idx, 3)
            self.assertEqual(cards[1].skills, ["adrenaline"])  # OCR is not mutated.
            cards[3].is_maxed = True
            self.assertIsNone(botcore.choose_best_artifact_or_card(self.frame, maxed_skills={"adrenaline"}).target)

    def test_mana_skill_and_offered_level_are_retained(self):
        line = SimpleNamespace(text="Mana Factory Lv 1", words=[SimpleNamespace(
            bounding_rect=SimpleNamespace(x=100, y=250, width=140, height=20))])
        ocr = SimpleNamespace(recognize_pil=AsyncMock(return_value=SimpleNamespace(lines=[line])))
        with patch.dict(sys.modules, {"winocr": ocr}):
            cards = botcore._detect_cards_ocr(self.frame, 1000, 800)
        self.assertIn("mana_factory", cards[1].skills)
        self.assertEqual(cards[1].offered_level, 1)

    def test_combo_requires_its_menu_header(self):
        line = SimpleNamespace(text="Telekinetic Sword", words=[SimpleNamespace(
            bounding_rect=SimpleNamespace(x=100, y=350, width=140, height=20))])
        ocr = SimpleNamespace(recognize_pil=AsyncMock(return_value=SimpleNamespace(lines=[line])))
        with patch.dict(sys.modules, {"winocr": ocr}):
            self.assertIsNone(botcore.find_best_combination_option(self.frame))

    def test_enter_area_does_not_match_spell_description(self):
        line = SimpleNamespace(text="Increase area by 20%", words=[SimpleNamespace(
            bounding_rect=SimpleNamespace(x=100, y=50, width=140, height=20))])
        ocr = SimpleNamespace(recognize_pil=AsyncMock(return_value=SimpleNamespace(lines=[line])))
        with patch.dict(sys.modules, {"winocr": ocr}):
            self.assertIsNone(botcore.detect_enter_area(self.frame))

    def test_hundred_minute_timer_is_not_truncated(self):
        self.assertEqual(botcore.parse_timer_text("100:05"), (100, 5, 6005))
        self.assertIsNone(botcore.parse_timer_text("180:05"))

    def test_nearby_chest_cannot_pull_through_immediate_wall(self):
        distance = np.full((300, 300), 100.0, dtype=np.float32)
        distance[:, 160:185] = 0
        vision = botcore.Vision(np.zeros((300, 300), np.uint8), distance, [], True, 1.0,
                                chest=(210, 150), chest_weight=280.0)
        dx, dy = botcore.choose_direction(vision, 0)
        self.assertLess(dx, 0.7)


class TestControllerRegressions(unittest.TestCase):
    def test_f9_is_not_dropped_by_a_full_preview_queue(self):
        import main
        app = main.FarmApp.__new__(main.FarmApp)
        app.pressed_hotkeys = set()
        app.running = threading.Event()
        app.input_generation = 0
        app.running.set()
        app.controller = Mock()
        app.events = queue.Queue(maxsize=1)
        app.events.put(("preview", None))
        app.hotkey_events = queue.SimpleQueue()
        app._key_down(main.keyboard.Key.f9)
        self.assertFalse(app.running.is_set())
        app.controller.release.assert_called_once()
        self.assertEqual(app.hotkey_events.get_nowait(), main.keyboard.Key.f9)

    @patch("main.win32api")
    @patch("main.pydirectinput")
    def test_escape_is_sent_once(self, pdi, winapi):
        from main import Controller
        Controller().press_esc()
        pdi.press.assert_called_once_with("esc")
        winapi.keybd_event.assert_not_called()

    @patch("main.pydirectinput")
    def test_mouse_zero_vector_releases_drag(self, pdi):
        from main import Controller
        ctrl = Controller()
        ctrl.mouse_held = True
        ctrl.move((0, 0), {}, {"input_mode": "mouse"})
        pdi.mouseUp.assert_called_once()
        self.assertFalse(ctrl.mouse_held)

    def test_unrelated_window_overlap_is_not_game_focus(self):
        import main
        with ExitStack() as stack:
            for name, value in [("GetForegroundWindow", 2), ("IsChild", False), ("GetAncestor", 2),
                                ("GetWindowRect", (0, 0, 500, 600))]:
                stack.enter_context(patch.object(main.win32gui, name, return_value=value))
            stack.enter_context(patch.object(main.win32process, "GetWindowThreadProcessId", side_effect=[(1, 10), (2, 20)]))
            self.assertEqual(main.is_game_or_popup_active(1, post_death_phase=True), (False, 1))
