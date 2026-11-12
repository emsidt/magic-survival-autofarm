import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np

from data_recorder import DataRecorder


class TestDataRecorder(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.patcher = unittest.mock.patch("data_recorder.RUNS_DIR", self.test_dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_record_flow(self):
        recorder = DataRecorder(enabled=True, max_runs=5)
        run_id = recorder.start_new_run()
        self.assertTrue(run_id.startswith("run_"))

        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        rec = recorder.record_decision(
            frame=dummy_frame,
            screen_type="level_up",
            action="card_1",
            confidence=0.95,
            metadata={"chosen_card": 1, "skill_key": "spirit"},
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["action"], "card_1")
        self.assertEqual(rec["screen_type"], "level_up")

        # Verify file written
        run_folder = self.test_dir / run_id
        self.assertTrue((run_folder / "step_0001_level_up.png").is_file())
        self.assertTrue((run_folder / "decisions.jsonl").is_file())

        recorder.finish_run(survival_time="10:00", kills=1200, gold=350)
        self.assertTrue((run_folder / "summary.json").is_file())
        self.assertIsNone(recorder.current_run_id)

    def test_disabled_recorder(self):
        recorder = DataRecorder(enabled=False)
        self.assertEqual(recorder.start_new_run(), "")
        dummy_frame = np.zeros((50, 50, 3), dtype=np.uint8)
        self.assertIsNone(recorder.record_decision(dummy_frame, "level_up", "card_1"))

    def test_fast_restarts_do_not_overwrite_previous_run(self):
        recorder = DataRecorder()
        first = recorder.start_new_run()
        recorder.record_decision(np.zeros((10, 10, 3), np.uint8), "level_up", "card_1")
        second = recorder.start_new_run()
        self.assertNotEqual(first, second)
        self.assertTrue((self.test_dir / first / "step_0001_level_up.png").is_file())

    def test_image_failure_does_not_log_nonexistent_image(self):
        recorder = DataRecorder()
        recorder.start_new_run()
        with patch("data_recorder.cv2.imwrite", return_value=False), self.assertLogs(level="ERROR"):
            self.assertIsNone(recorder.record_decision(np.zeros((10, 10, 3), np.uint8), "level_up", "card_1"))
        self.assertFalse((recorder.current_run_dir / "decisions.jsonl").exists())
        self.assertEqual(recorder.step_index, 0)

    def test_pruning_only_removes_completed_owned_runs(self):
        foreign = self.test_dir / "human_demo"
        foreign.mkdir()
        incomplete = self.test_dir / "run_in_progress"
        incomplete.mkdir()
        recorder = DataRecorder(max_runs=1)
        completed = recorder.start_new_run()
        recorder.finish_run()
        current = recorder.start_new_run()
        self.assertFalse((self.test_dir / completed).exists())
        self.assertTrue((self.test_dir / current).exists())
        self.assertTrue(foreign.exists())
        self.assertTrue(incomplete.exists())

    def test_invalid_retention_is_rejected(self):
        with self.assertRaises(ValueError):
            DataRecorder(max_runs=0)


if __name__ == "__main__":
    unittest.main()

