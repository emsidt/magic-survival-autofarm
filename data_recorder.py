"""Structured gameplay data and decision recorder for Magic Survival AI learning.
Implements Step 2 of KE_HOACH_AI.md.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Optional
import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"


class DataRecorder:
    def __init__(self, enabled: bool = True, max_runs: int = 50):
        self.enabled = enabled
        self.max_runs = max_runs
        self.current_run_id: Optional[str] = None
        self.current_run_dir: Optional[Path] = None
        self.step_index: int = 0

    def start_new_run(self) -> str:
        if not self.enabled:
            return ""
        try:
            now = datetime.now()
            run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}"
            run_dir = RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            self.current_run_id = run_id
            self.current_run_dir = run_dir
            self.step_index = 0
            self._prune_old_runs()
            return run_id
        except Exception:
            return ""

    def record_decision(
        self,
        frame: np.ndarray,
        screen_type: str,
        action: str,
        confidence: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None
        try:
            if not self.current_run_dir:
                self.start_new_run()
            if not self.current_run_dir:
                return None

            self.step_index += 1
            step_id = f"step_{self.step_index:04d}_{screen_type}"
            img_name = f"{step_id}.png"
            img_path = self.current_run_dir / img_name
            cv2.imwrite(str(img_path), frame)

            record = {
                "step": self.step_index,
                "timestamp": datetime.now().isoformat(),
                "run_id": self.current_run_id,
                "screen_type": screen_type,
                "action": action,
                "confidence": round(confidence, 4),
                "image": img_name,
                "details": metadata or {},
            }

            jsonl_path = self.current_run_dir / "decisions.jsonl"
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return record
        except Exception:
            return None

    def finish_run(self, survival_time: str = "", kills: int = 0, gold: int = 0):
        if not self.enabled or not self.current_run_dir:
            return
        try:
            summary = {
                "run_id": self.current_run_id,
                "total_steps": self.step_index,
                "finished_at": datetime.now().isoformat(),
                "survival_time": survival_time,
                "kills": kills,
                "gold": gold,
            }
            with open(self.current_run_dir / "summary.json", "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        finally:
            self.current_run_id = None
            self.current_run_dir = None

    def _prune_old_runs(self):
        try:
            if not RUNS_DIR.is_dir():
                return
            all_runs = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()], key=lambda d: d.name)
            if len(all_runs) > self.max_runs:
                for old in all_runs[: len(all_runs) - self.max_runs]:
                    import shutil

                    shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass
