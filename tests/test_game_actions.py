import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from botcore import CardChoice
from game_actions import (ActionCancelled, FrameCaptureError, GuardedController,
                          capture_frame, finish_match, remember_card,
                          select_attribute, select_card, select_combination)


class TestGameActions(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 100, 3), dtype=np.uint8)
        self.controller = Mock(spec=["tap", "release", "press_esc", "move", "lock"])
        self.controller.lock = threading.RLock()

    def test_adb_failure_never_falls_back_to_desktop(self):
        adb = Mock(screen_width=1080)
        adb.screenshot.return_value = None
        desktop = Mock(return_value=self.frame)
        with self.assertRaises(FrameCaptureError):
            capture_frame(adb, {}, desktop)
        desktop.assert_not_called()
        adb.release.assert_called_once()

    def test_desktop_capture_reads_a_new_frame_each_time(self):
        next_frame = self.frame + 1
        desktop = Mock(side_effect=[self.frame, next_frame])
        self.assertIs(capture_frame(self.controller, {}, desktop), self.frame)
        self.assertIs(capture_frame(self.controller, {}, desktop), next_frame)
        self.assertEqual(desktop.call_count, 2)

    def test_stop_between_actions_blocks_next_click(self):
        running = threading.Event()
        running.set()
        guarded = GuardedController(self.controller, running.is_set)
        guarded.tap([0.5, 0.5], {})
        running.clear()
        with self.assertRaises(ActionCancelled):
            guarded.tap([0.9, 0.1], {})
        self.assertEqual(self.controller.tap.call_count, 1)

    @patch("game_actions.botcore.detect_combination_star", return_value=None)
    def test_inactive_star_sends_no_input(self, _):
        self.assertIsNone(select_combination(self.controller, {}, self.frame, Mock()))
        self.controller.tap.assert_not_called()

    @patch("game_actions.botcore.is_learn_button_active", return_value=False)
    @patch("game_actions.botcore.detect_learn_button", return_value=(0.5, 0.88))
    @patch("game_actions.botcore.find_best_combination_option", return_value=((0.5, 0.4), "Fusion", "vortex"))
    @patch("game_actions.botcore.detect_combination_star", return_value=(0.9, 0.14))
    def test_disabled_learn_does_not_claim_fusion(self, *_):
        result = select_combination(self.controller, {}, self.frame, Mock(return_value=self.frame), sleep=lambda _: None)
        self.assertIsNone(result)
        self.assertEqual(self.controller.tap.call_count, 2)  # Star, then option; never Learn.
        self.controller.press_esc.assert_called_once()

    @patch("game_actions._returned_to_game", return_value=False)
    @patch("game_actions.botcore.is_learn_button_active", return_value=True)
    @patch("game_actions.botcore.detect_learn_button", return_value=(0.5, 0.88))
    @patch("game_actions.botcore.find_best_combination_option", return_value=((0.5, 0.4), "Fusion", "vortex"))
    @patch("game_actions.botcore.detect_combination_star", return_value=(0.9, 0.14))
    def test_failed_transition_does_not_claim_fusion(self, *_):
        self.assertIsNone(select_combination(self.controller, {}, self.frame, Mock(return_value=self.frame), sleep=lambda _: None))

    @patch("game_actions._returned_to_game", return_value=True)
    @patch("game_actions.botcore.is_learn_button_active", return_value=True)
    @patch("game_actions.botcore.detect_learn_button", return_value=(0.5, 0.88))
    @patch("game_actions.botcore.is_attribute_screen", return_value=True)
    @patch("game_actions.botcore.evaluate_selected_attribute", side_effect=[(100, "A", "spirit"), (500, "B", "spirit"), (100, "C", "spirit")])
    def test_attribute_reselects_best_before_learn(self, *_):
        selected = select_attribute(self.controller, {}, Mock(return_value=self.frame), sleep=lambda _: None)
        self.assertEqual(selected.index, 2)
        self.assertEqual(self.controller.tap.call_args_list[-2].args[0], [0.31, 0.44])
        self.assertEqual(self.controller.tap.call_args_list[-1].args[0], [0.5, 0.88])

    @patch("game_actions.botcore.is_level_up_screen", return_value=True)
    @patch("game_actions.botcore.is_attribute_screen", return_value=False)
    def test_same_card_screen_does_not_increment_levels(self, *_):
        choice = CardChoice(1, (0.5, 0.38), skill_key="spirit")
        self.assertFalse(select_card(self.controller, {}, self.frame, choice, Mock(return_value=self.frame), sleep=lambda _: None))

    def test_level_four_and_unknown_level_do_not_mark_maxed(self):
        active, levels, maxed = set(), {}, set()
        choice = CardChoice(1, (0.5, 0.38), skill_key="spirit")
        for _ in range(10):
            remember_card(choice, active, levels, maxed)
        self.assertNotIn("spirit", maxed)
        choice.offered_level = 4
        remember_card(choice, active, levels, maxed)
        self.assertEqual(levels["spirit"], 4)
        self.assertNotIn("spirit", maxed)
        choice.offered_level = 7
        remember_card(choice, active, levels, maxed)
        self.assertIn("spirit", maxed)

    def test_finish_preserves_id_and_skips_unknown_timer(self):
        recorder = Mock(current_run_id="run_actual")
        recorder.finish_run.side_effect = lambda **_: setattr(recorder, "current_run_id", None)
        learner = Mock()
        finish_match(recorder, learner, self.frame, 120, {"spirit"}, [])
        self.assertEqual(learner.evaluate_and_learn_run.call_args.kwargs["run_id"], "run_actual")
        recorder.finish_run.assert_called_once_with(survival_time="02:00")
        learner.reset_mock()
        finish_match(recorder, learner, self.frame, 0, {"spirit"}, [])
        learner.evaluate_and_learn_run.assert_not_called()
