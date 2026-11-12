from contextlib import ExitStack, redirect_stdout
import io
import itertools
import json
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

import bot_cli
import botcore


class TestCLIFlow(unittest.TestCase):
    def run_frames(self, frames, overrides=None, config=None, controller_effects=None):
        controller = Mock(spec=["device", "screen_width", "screen_height", "lock", "release",
                                "screenshot", "is_game_foreground", "tap", "move", "press_esc", "close", "launch_game",
                                "get_foreground_package", "close_external_browsers"])
        controller.device = "emulator-test"
        controller.screen_width, controller.screen_height = 100, 200
        controller.lock = threading.RLock()
        controller.is_game_foreground.return_value = True
        controller.get_foreground_package.return_value = "com.vkslrzm.Zombie"
        controller.screenshot.side_effect = list(frames) + [KeyboardInterrupt()]
        for name, effect in (controller_effects or {}).items():
            getattr(controller, name).side_effect = effect
        recorder = Mock(current_run_id="run_exact")
        recorder.finish_run.side_effect = lambda **_: setattr(recorder, "current_run_id", None)
        learner = Mock()
        settings = {"control_mode": "adb", "auto_close_ads": False, **(config or {})}
        cfg = Mock()
        cfg.is_file.return_value = True
        cfg.read_text.return_value = json.dumps(settings)
        detectors = {name: None for name in ("detect_die_button", "detect_confirm_button", "detect_start_game",
                    "detect_selected", "detect_enter_area", "detect_learn_button", "detect_obtain_button",
                    "detect_buy_button", "detect_pause_button", "detect_resume_button", "detect_combination_star",
                    "detect_restore_gold", "detect_player_level", "detect_close_button")}
        detectors.update({name: False for name in ("detect_settings_dialog", "is_attribute_screen",
                                                  "is_level_up_screen", "is_chest_screen", "is_fast_combat_frame", "is_ad_screen")})
        detectors.update({"detect_game_timer": (2, 0, 120), "choose_direction": (1, 0)})
        distance = np.full((200, 100), 100, np.float32)
        detectors["inspect_game"] = botcore.Vision(np.zeros((200, 100), np.uint8), distance, [], True, 1)
        with ExitStack() as stack:
            stack.enter_context(patch("bot_cli.CONFIG_PATH", cfg))
            stack.enter_context(patch("bot_cli.RULES_PATH", Mock(is_file=Mock(return_value=False))))
            stack.enter_context(patch("adb_controller.ADBController", return_value=controller))
            stack.enter_context(patch("bot_cli.DataRecorder", return_value=recorder))
            stack.enter_context(patch("bot_cli.get_adaptive_learner", return_value=learner))
            stack.enter_context(patch("bot_cli.time.sleep"))
            stack.enter_context(patch("bot_cli.time.monotonic", side_effect=itertools.count(100, 5)))
            for name, value in detectors.items():
                kwargs = {"side_effect": overrides[name]} if overrides and name in overrides else {"return_value": value}
                stack.enter_context(patch.object(botcore, name, **kwargs))
            stack.enter_context(redirect_stdout(io.StringIO()))
            bot_cli.run_cli_bot()
        return controller, recorder, learner

    def test_results_screen_staying_open_is_learned_once(self):
        playing = np.zeros((200, 100, 3), np.uint8)
        results = playing + 1
        controller, recorder, learner = self.run_frames(
            [playing, results, results],
            overrides={"detect_pause_button": lambda f: (0.9, 0.04) if f is playing else None,
                       "is_fast_combat_frame": lambda f: f is playing,
                       "detect_confirm_button": lambda f: (0.5, 0.85) if f is results else None},
        )
        learner.evaluate_and_learn_run.assert_called_once()
        self.assertEqual(learner.evaluate_and_learn_run.call_args.kwargs["run_id"], "run_exact")
        recorder.finish_run.assert_called_once()
        self.assertGreater(controller.release.call_count, 0)

    def test_auto_restart_off_never_taps_start(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        controller, _, learner = self.run_frames([frame], {"detect_start_game": lambda _: (0.5, 0.8)}, {"auto_restart": False})
        controller.tap.assert_not_called()
        learner.evaluate_and_learn_run.assert_not_called()

    def test_movement_timeout_recovers_on_a_new_frame_without_exiting(self):
        first = np.full((200, 100, 3), 100, np.uint8)
        second = first + 1
        controller, _, learner = self.run_frames(
            [first, second],
            {"is_fast_combat_frame": lambda _: True, "detect_pause_button": lambda _: (0.9, 0.04)},
            controller_effects={"move": [bot_cli.ADBCommandError("timeout"), None]},
        )
        self.assertEqual(controller.move.call_count, 2)
        self.assertEqual(controller.screenshot.call_count, 3)
        learner.evaluate_and_learn_run.assert_not_called()

    def test_tap_timeout_does_not_replay_button_on_next_gameplay_frame(self):
        menu = np.zeros((200, 100, 3), np.uint8)
        playing = menu + 100
        controller, _, _ = self.run_frames(
            [menu, playing],
            {"detect_start_game": lambda f: (0.5, 0.8) if f is menu else None,
             "is_fast_combat_frame": lambda f: f is playing,
             "detect_pause_button": lambda f: (0.9, 0.04) if f is playing else None},
            controller_effects={"tap": bot_cli.ADBCommandError("timeout")},
        )
        controller.tap.assert_called_once()
        controller.move.assert_called_once()

    def test_death_requires_fresh_verified_die_action(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        with patch("bot_cli.dismiss_death", return_value=False) as dismiss:
            controller, _, learner = self.run_frames([frame], {"detect_die_button": lambda _: (0.5, 0.73)})
        dismiss.assert_called_once()
        controller.tap.assert_not_called()
        learner.evaluate_and_learn_run.assert_not_called()

    def test_restore_gold_confirms_without_training_a_completed_run(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        controller, recorder, learner = self.run_frames(
            [frame], {"detect_restore_gold": lambda _: (0.5, 0.67)},
        )
        controller.tap.assert_called_once_with([0.5, 0.67], unittest.mock.ANY)
        recorder.finish_run.assert_called_once_with()
        learner.evaluate_and_learn_run.assert_not_called()

    def test_fast_combat_bypasses_expensive_menu_scans(self):
        frame = np.full((200, 100, 3), 100, np.uint8)
        def unexpected(*args):
            self.fail("Combat must not wait for a full menu scan")
        controller, _, _ = self.run_frames([frame], {
            "is_fast_combat_frame": lambda _: True,
            "detect_pause_button": lambda _: (0.9, 0.04),
            "detect_die_button": unexpected,
            "is_level_up_screen": unexpected,
            "detect_restore_gold": unexpected,
        })
        controller.move.assert_called_once()

    def test_pause_hud_on_unknown_menu_never_moves(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        controller, _, _ = self.run_frames([frame], {"detect_pause_button": lambda _: (0.9, 0.04)})
        controller.move.assert_not_called()

    def test_capture_loss_during_card_selection_recovers_on_new_frame(self):
        menu = np.zeros((200, 100, 3), np.uint8)
        playing = menu + 100
        with patch("botcore.choose_best_artifact_or_card", return_value=botcore.CardChoice(1, (0.5, 0.4), skill_key="spirit")):
            controller, recorder, _ = self.run_frames(
                [menu, None, playing],
                {"is_level_up_screen": lambda f: f is menu, "is_fast_combat_frame": lambda f: f is playing,
                 "detect_pause_button": lambda f: (0.9, 0.04) if f is playing else None},
            )
        controller.tap.assert_called_once()
        controller.move.assert_called_once()
        self.assertFalse(any(c.args[1] == "level_up" for c in recorder.record_decision.call_args_list))

    def test_failed_card_attempt_does_not_advance_player_level_counter(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        with patch("bot_cli.select_card", side_effect=[False, True, True]), \
                patch("botcore.choose_best_artifact_or_card", return_value=botcore.CardChoice(1, (0.5, 0.4))) as choose:
            self.run_frames([frame] * 3, {"is_level_up_screen": lambda _: True})
        self.assertEqual([c.kwargs["level_count"] for c in choose.call_args_list], [2, 2, 3])

    def test_attaching_to_existing_run_uses_level_read_from_screen(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        with patch("bot_cli.select_card", return_value=True), \
                patch("botcore.choose_best_artifact_or_card", return_value=botcore.CardChoice(1, (0.5, 0.4))) as choose:
            self.run_frames([frame], {"is_level_up_screen": lambda _: True, "detect_player_level": lambda _: 32})
        self.assertEqual(choose.call_args.kwargs["level_count"], 32)

    def test_external_ad_close_does_not_send_back_or_relaunch_game(self):
        ad = np.zeros((200, 100, 3), np.uint8)
        playing = ad + 100
        controller, _, _ = self.run_frames(
            [ad, ad, playing],
            {"detect_close_button": lambda f: (0.11, 0.06) if f is ad else None,
             "is_fast_combat_frame": lambda f: f is playing,
             "detect_pause_button": lambda f: (0.9, 0.04) if f is playing else None},
            config={"auto_close_ads": True},
            controller_effects={"is_game_foreground": [False, True, True]},
        )
        controller.tap.assert_called_once()
        controller.press_esc.assert_not_called()
        controller.launch_game.assert_not_called()
        controller.move.assert_called_once()
        controller.close.assert_called_once()

    def test_chrome_browser_takeover_is_closed_and_game_relaunched(self):
        chrome = np.zeros((200, 100, 3), np.uint8)
        playing = chrome + 100
        controller, _, _ = self.run_frames(
            [chrome, playing],
            {"is_fast_combat_frame": lambda f: f is playing,
             "detect_pause_button": lambda f: (0.9, 0.04) if f is playing else None},
            controller_effects={
                "is_game_foreground": [False, True, True, True],
                "get_foreground_package": ["com.android.chrome", "com.vkslrzm.Zombie", "com.vkslrzm.Zombie"],
            },
        )
        controller.close_external_browsers.assert_called_once()
        controller.launch_game.assert_called_once()

    def test_selected_menu_uses_summoner_selection_flow(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        with patch("bot_cli.select_character", return_value=True) as select:
            controller, _, _ = self.run_frames([frame], {"detect_selected": lambda _: (0.5, 0.93)})
        select.assert_called_once()
        self.assertEqual(select.call_args.args[4], "summoner")
        controller.tap.assert_not_called()  # No old direct Selected tap in the runner.

    def test_auto_restart_off_does_not_select_character(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        with patch("bot_cli.select_character") as select:
            controller, _, _ = self.run_frames(
                [frame], {"detect_selected": lambda _: (0.5, 0.93)}, {"auto_restart": False},
            )
        select.assert_not_called()
        controller.tap.assert_not_called()

    def test_auto_levelup_off_never_taps_card(self):
        frame = np.zeros((200, 100, 3), np.uint8)
        controller, _, _ = self.run_frames([frame], {"is_level_up_screen": lambda _: True}, {"auto_levelup": False})
        controller.tap.assert_not_called()

    def test_movement_receives_only_confirmed_fusion_and_targeting_config(self):
        levelup = np.zeros((200, 100, 3), np.uint8)
        playing = levelup + 1
        for learned in (None, Mock(key="telekinetic_sword", label="Telekinetic Sword")):
            with self.subTest(confirmed=learned is not None):
                observed = []

                def move_direction(*args, **kwargs):
                    observed.append((set(kwargs["active_skills"]), kwargs["nearest_target_skills"]))
                    return (1, 0)

                with patch("bot_cli.select_combination", return_value=learned):
                    self.run_frames(
                        [levelup, playing],
                        overrides={
                            "is_level_up_screen": lambda f: f is levelup,
                            "detect_combination_star": lambda f: (0.9, 0.1) if f is levelup else None,
                            "detect_pause_button": lambda f: (0.9, 0.04) if f is playing else None,
                            "is_fast_combat_frame": lambda f: f is playing,
                            "choose_direction": move_direction,
                        },
                        config={"nearest_target_skills": ["telekinetic_sword"],
                                "skill_priority": ["telekinetic_sword", "spirit"]},
                    )
                expected = {"telekinetic_sword"} if learned else set()
                self.assertEqual(observed, [(expected, ["telekinetic_sword"])])
