from contextlib import ExitStack
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

import botcore
from game_actions import (ActionCancelled, GuardedController, back_from_ad, close_ad,
                          move_from_frame, select_card, select_chest_artifact, select_attribute)


class ActionTransitionTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((1000, 600, 3), np.uint8)
        self.controller = Mock(spec=["tap", "move", "press_esc", "release", "lock"])
        self.controller.lock = threading.RLock()

    def test_ad_close_is_one_input_without_back_after_return_to_game(self):
        capture = Mock(return_value=self.frame)
        with patch("botcore.detect_close_button", return_value=(0.11, 0.06)):
            self.assertEqual(close_ad(self.controller, {}, capture), (0.11, 0.06))
        capture.assert_called_once()
        self.controller.tap.assert_called_once_with([0.11, 0.06], {})
        self.controller.press_esc.assert_not_called()

    def test_disappeared_ad_close_sends_no_input(self):
        with patch("botcore.detect_close_button", return_value=None):
            self.assertIsNone(close_ad(self.controller, {}, Mock(return_value=self.frame)))
        self.controller.tap.assert_not_called()
        self.controller.press_esc.assert_not_called()

    def test_ad_ending_before_back_does_not_pause_the_game(self):
        with patch("botcore.detect_close_button", return_value=None), patch("botcore.is_ad_screen", return_value=False):
            self.assertFalse(back_from_ad(self.controller, {}, Mock(return_value=self.frame)))
        self.controller.press_esc.assert_not_called()

    def test_back_fallback_waits_for_visible_close_control(self):
        with patch("botcore.detect_close_button", return_value=(0.1, 0.06)), patch("botcore.is_ad_screen", return_value=True):
            self.assertFalse(back_from_ad(self.controller, {}, Mock(return_value=self.frame)))
        self.controller.press_esc.assert_not_called()

    def test_stop_blocks_delayed_game_relaunch(self):
        raw = Mock(lock=threading.RLock())
        guarded = GuardedController(raw, lambda: False)
        with self.assertRaises(ActionCancelled):
            guarded.launch_game()
        raw.launch_game.assert_not_called()

    def test_old_frame_cannot_restart_background_motion(self):
        with patch("game_actions.time.perf_counter", return_value=20):
            self.assertFalse(move_from_frame(self.controller, {}, {}, (1, 0), 18.9))
        self.controller.release.assert_called_once()
        self.controller.move.assert_not_called()

    def test_movement_lease_includes_analysis_time_without_mutating_config(self):
        config = {"joystick_radius_px": 150}
        with patch("game_actions.time.perf_counter", return_value=20):
            self.assertTrue(move_from_frame(self.controller, {}, config, (1, 0), 19.25))
        self.assertEqual(self.controller.move.call_args.args[2]["_movement_frame_age"], 0.75)
        self.assertEqual(config, {"joystick_radius_px": 150})

    def test_pause_icon_alone_does_not_confirm_card_learning(self):
        with ExitStack() as stack:
            for name, value in [("is_attribute_screen", False), ("is_level_up_screen", False),
                                ("detect_pause_button", (0.9, 0.04)), ("is_fast_combat_frame", False),
                                ("detect_obtain_button", None)]:
                stack.enter_context(patch.object(botcore, name, return_value=value))
            choice = botcore.CardChoice(1, (0.5, 0.38), skill_key="spirit")
            self.assertFalse(select_card(self.controller, {}, self.frame, choice,
                                         Mock(return_value=self.frame), sleep=lambda _: None))

    def test_attribute_does_not_click_if_screen_changed_before_first_action(self):
        with patch("botcore.is_attribute_screen", return_value=False):
            self.assertIsNone(select_attribute(self.controller, {}, Mock(return_value=self.frame)))
        self.controller.tap.assert_not_called()

    def test_chest_scan_aborts_when_first_slot_changes_screen(self):
        with patch("botcore.detect_obtain_button", side_effect=[(0.5, 0.8), None]), \
                patch("botcore.is_three_card_chest", return_value=True), \
                patch("botcore.evaluate_selected_chest_artifact") as score:
            result = select_chest_artifact(self.controller, {}, Mock(return_value=self.frame), sleep=lambda _: None)
        self.assertIsNone(result)
        self.controller.tap.assert_called_once()  # No second slot or old Obtain coordinate.
        score.assert_not_called()

    def test_chest_reselects_best_and_uses_fresh_obtain_coordinate(self):
        with patch("botcore.detect_obtain_button", side_effect=[(0.5, 0.8)] * 4 + [(0.6, 0.82), None]), \
                patch("botcore.is_three_card_chest", return_value=True), \
                patch("botcore.evaluate_selected_chest_artifact", side_effect=[(10, "A"), (90, "B"), (20, "C")]), \
                patch("botcore.is_fast_combat_frame", return_value=True):
            result = select_chest_artifact(self.controller, {}, Mock(return_value=self.frame), sleep=lambda _: None)
        self.assertEqual((result.index, result.label), (2, "B"))
        self.assertEqual(self.controller.tap.call_args_list[-2].args[0], list(botcore.get_chest_card_target(2, 0.5)))
        self.assertEqual(self.controller.tap.call_args_list[-1].args[0], [0.6, 0.82])

    def test_chest_still_open_is_not_recorded_as_obtained(self):
        with patch("botcore.detect_obtain_button", return_value=(0.5, 0.8)), \
                patch("botcore.is_three_card_chest", return_value=False), \
                patch("botcore.evaluate_selected_chest_artifact", return_value=(10, "A")):
            self.assertIsNone(select_chest_artifact(self.controller, {}, Mock(return_value=self.frame), sleep=lambda _: None))
        self.controller.tap.assert_called_once()

    def test_shop_x_shape_in_another_screen_is_not_clicked(self):
        with patch("botcore.detect_buy_button", return_value=None), \
                patch("botcore.cv2.matchTemplate", side_effect=AssertionError("Not a shop")):
            self.assertIsNone(botcore.detect_shop_x_button(self.frame))

    def test_player_level_reads_header_not_skill_level(self):
        for text, expected in [("Current Level : 27", 27), ("Current Level 2", 2),
                               ("Spirit Lv 7", None), ("Current Level 999", None)]:
            with self.subTest(text=text), patch("winocr.recognize_pil", new=AsyncMock(
                    return_value=Mock(lines=[Mock(text=text)]))):
                self.assertEqual(botcore.detect_player_level(self.frame), expected)

    def test_continue_ad_is_not_misread_as_game_resume(self):
        with ExitStack() as stack:
            for name in ("detect_pause_button", "detect_start_game", "detect_enter_area", "detect_selected",
                         "detect_confirm_button", "detect_die_button"):
                stack.enter_context(patch.object(botcore, name, return_value=None))
            word = Mock(text="Continue", bounding_rect=Mock(x=100, y=200, width=80, height=25))
            result = Mock(lines=[Mock(text="Continue", words=[word])])
            stack.enter_context(patch("winocr.recognize_pil", new=AsyncMock(return_value=result)))
            self.assertIsNone(botcore.detect_resume_button(self.frame))
            result.lines.insert(0, Mock(text="Paused", words=[]))
            self.assertIsNotNone(botcore.detect_resume_button(self.frame))
