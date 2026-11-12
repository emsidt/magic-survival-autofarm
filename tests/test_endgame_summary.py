import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import botcore
from game_actions import finish_match, format_match_summary, remember_card
from learning_engine import AdaptiveLearner


class TestEndgameSummary(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.learner = AdaptiveLearner(data_dir=self.test_dir)
        self.frame = np.zeros((200, 200, 3), dtype=np.uint8)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_readable_skill_name(self):
        self.assertEqual(botcore.get_readable_skill_name("electric_zone"), "Electric Zone")
        self.assertEqual(botcore.get_readable_skill_name("spirit"), "Spirit")
        self.assertEqual(botcore.get_readable_skill_name("telekinetic_sword"), "Telekinetic Sword [Hợp thể]")
        self.assertEqual(botcore.get_readable_skill_name("unknown_magic"), "Unknown Magic")

    def test_format_match_summary_with_report(self):
        report = {
            "reward": 0.425,
            "diff_sec": 65.5,
            "prev_avg_sec": 240.0,
            "new_avg_survival": 265.0,
            "total_runs": 12,
            "skill_deltas": {
                "electric_zone": 0.170,
                "spirit": 0.085,
            },
            "skills_updated": {
                "electric_zone": 2.450,
                "spirit": 1.200,
            },
        }
        active_skills = {"electric_zone", "spirit"}
        skill_levels = {"electric_zone": 4, "spirit": 2}

        summary_block, status_line = format_match_summary(
            survival_seconds=305.5,
            active_skills=active_skills,
            skill_levels=skill_levels,
            report=report,
        )

        # Check that survival time, skills with levels, and delta scores are in summary
        self.assertIn("05:05 (305s)", summary_block)
        self.assertIn("+65.5s so với mốc TB 04:00", summary_block)
        self.assertIn("+0.425 điểm", summary_block)
        self.assertIn("Electric Zone (Lv.4)", summary_block)
        self.assertIn("Spirit (Lv.2)", summary_block)
        self.assertIn("+0.170", summary_block)
        self.assertIn("+0.085", summary_block)

        # Check status line
        self.assertIn("05:05", status_line)
        self.assertIn("+0.425", status_line)
        self.assertIn("Electric Zone (Lv.4)", status_line)

    def test_finish_match_integration_with_real_learner(self):
        recorder = Mock(current_run_id="run_test_summary_01")
        recorder.finish_run.side_effect = lambda **_: setattr(recorder, "current_run_id", None)

        report = finish_match(
            recorder=recorder,
            learner=self.learner,
            frame=self.frame,
            survival_seconds=360.0,
            active_skills={"electric_zone", "spirit"},
            core_skills=["electric_zone"],
            skill_levels={"electric_zone": 4, "spirit": 2},
            character="electromancer",
        )

        self.assertIsNotNone(report)
        self.assertIn("summary_text", report)
        self.assertIn("status_line", report)
        self.assertIn("skill_deltas", report)
        self.assertIn("electric_zone", report["skill_deltas"])
        self.assertIn("Electric Zone (Lv.4)", report["summary_text"])
        self.assertIn("06:00", report["summary_text"])

        # Verify saved in history with skill_levels
        history = self.learner.history
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["skill_levels"]["electric_zone"], 4)
        self.assertEqual(history[0]["skill_levels"]["spirit"], 2)

    def test_detect_main_screen_currencies(self):
        import cv2
        self.assertEqual(botcore.detect_main_screen_currencies(None), {"gold": None, "gems": None})
        self.assertEqual(botcore.detect_main_screen_currencies(np.zeros((10, 10, 3), np.uint8)), {"gold": None, "gems": None})

        img_path = Path("captures/current_live_check_now.png")
        if img_path.is_file():
            img = cv2.imread(str(img_path))
            cur = botcore.detect_main_screen_currencies(img)
            self.assertEqual(cur["gold"], 9684)
            self.assertEqual(cur["gems"], 156)

        img_path_small = Path("captures/live_debug_small.png")
        if img_path_small.is_file():
            img_small = cv2.imread(str(img_path_small))
            cur_small = botcore.detect_main_screen_currencies(img_small)
            self.assertEqual(cur_small["gold"], 9684)
            self.assertEqual(cur_small["gems"], 156)


if __name__ == "__main__":
    unittest.main()
