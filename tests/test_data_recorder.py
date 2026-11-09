import shutil
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()

