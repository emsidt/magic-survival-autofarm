import shutil
import tempfile
import unittest
from pathlib import Path

from learning_engine import AdaptiveLearner


class TestAdaptiveLearner(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.learner = AdaptiveLearner(data_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_state(self):
        self.assertEqual(self.learner.policy["total_runs_analyzed"], 0)
        self.assertEqual(self.learner.get_skill_bonus("spirit"), 0.0)

    def test_learn_from_above_average_run(self):
        # First run initializes average
        self.learner.evaluate_and_learn_run(
            run_id="run_test_01",
            survival_seconds=600.0,
            active_skills={"spirit", "satellite"},
        )
        # Second run survives 900s (better than 600s average)
        report2 = self.learner.evaluate_and_learn_run(
            run_id="run_test_02",
            survival_seconds=900.0,
            active_skills={"spirit", "satellite"},
            combos=["telekinetic_sword"],
        )
        self.assertGreater(report2["diff_sec"], 0)
        self.assertGreater(report2["reward"], 0.0)

        # Both skills have positive bonus
        bonus_spirit = self.learner.get_skill_bonus("spirit")
        self.assertGreater(bonus_spirit, 0.0)

        # Synergy bonus
        bonus_synergy = self.learner.get_skill_bonus("spirit", active_skills={"satellite"})
        self.assertGreater(bonus_synergy, bonus_spirit)

    def test_learn_from_below_average_run_is_gentle(self):
        # Average is 600s
        self.learner.evaluate_and_learn_run(
            run_id="run_test_01",
            survival_seconds=600.0,
            active_skills={"spirit"},
        )
        # Next run dies at 200s (below average)
        report = self.learner.evaluate_and_learn_run(
            run_id="run_test_02",
            survival_seconds=200.0,
            active_skills={"incineration"},
        )
        self.assertLess(report["diff_sec"], 0)
        # Penalty is gentle (between -0.30 and 0.0), NOT harsh!
        self.assertGreaterEqual(report["reward"], -0.30)
        self.assertLess(report["reward"], 0.0)

    def test_core_skills_protection(self):
        # Core skills defined in build priority should never drop below 0.0
        # even if bot dies at 30 seconds due to clumsy movement
        self.learner.evaluate_and_learn_run(
            run_id="run_die_early",
            survival_seconds=30.0,
            active_skills={"spirit"},
            core_skills={"spirit"},
        )
        bonus = self.learner.get_skill_bonus("spirit")
        self.assertGreaterEqual(bonus, 0.0)

    def test_duplicate_result_is_not_learned_twice(self):
        self.learner.evaluate_and_learn_run("one_run", 500, {"spirit"})
        again = AdaptiveLearner(self.test_dir)
        result = again.evaluate_and_learn_run("one_run", 500, {"spirit"})
        self.assertEqual(result["skipped"], "already_analyzed")
        self.assertEqual(again.policy["total_runs_analyzed"], 1)

    def test_invalid_duration_does_not_poison_policy(self):
        for seconds in (float("nan"), float("inf"), -1, 0):
            with self.assertRaises(ValueError):
                self.learner.evaluate_and_learn_run("bad", seconds, {"spirit"})
        self.assertEqual(self.learner.policy["total_runs_analyzed"], 0)

    def test_invalid_json_shape_falls_back_to_valid_defaults(self):
        (self.test_dir / "learned_policy.json").write_text("[]", encoding="utf-8")
        (self.test_dir / "learning_history.json").write_text("{}", encoding="utf-8")
        learner = AdaptiveLearner(self.test_dir)
        learner.evaluate_and_learn_run("fresh", 120, {"spirit"})
        self.assertEqual(learner.policy["total_runs_analyzed"], 1)

    def test_atomic_save_keeps_previous_file_on_failure(self):
        from unittest.mock import patch
        self.learner.evaluate_and_learn_run("first", 120, {"spirit"})
        previous = self.learner.policy_file.read_bytes()
        with patch("storage.os.replace", side_effect=OSError("disk unavailable")), self.assertLogs(level="ERROR"):
            self.learner.save()
        self.assertEqual(self.learner.policy_file.read_bytes(), previous)


    def test_update_movement_policy(self):
        rep = self.learner.update_movement_policy(weave_freq=3.8, weave_amp=0.35, chest_aggression=2.0, run_id="run_mv_1")
        self.assertEqual(rep["weave_frequency"], 3.8)
        self.assertEqual(rep["weave_amplitude"], 0.35)
        self.assertEqual(rep["chest_aggression"], 2.0)
        self.assertEqual(rep["total_sessions"], 1)

        mv_p = self.learner.get_movement_policy()
        self.assertEqual(mv_p["weave_frequency"], 3.8)
        self.assertEqual(mv_p["total_movement_sessions"], 1)

        # Second update smooths with exponential moving average
        rep2 = self.learner.update_movement_policy(weave_freq=4.2, weave_amp=0.40, chest_aggression=2.2, run_id="run_mv_2")
        self.assertEqual(rep2["total_sessions"], 2)
        self.assertAlmostEqual(rep2["weave_frequency"], (1 - 0.35) * 3.8 + 0.35 * 4.2, delta=0.05)


if __name__ == "__main__":
    unittest.main()
