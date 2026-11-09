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


if __name__ == "__main__":
    unittest.main()
