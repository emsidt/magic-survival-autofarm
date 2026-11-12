"""Structured gameplay data and decision recorder for Magic Survival AI learning.
Implements Step 2 of KE_HOACH_AI.md.
"""
from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional
from uuid import uuid4
import cv2
import numpy as np
from storage import write_json_atomic

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"


class DataRecorder:
    def __init__(self, enabled: bool = True, max_runs: int = 50):
        self.enabled = enabled
        if max_runs < 1:
            raise ValueError("max_runs must be at least 1")
        self.max_runs = max_runs
        self.current_run_id: Optional[str] = None
        self.current_run_dir: Optional[Path] = None
        self.step_index: int = 0

    def start_new_run(self) -> str:
        if not self.enabled:
            return ""
        try:
            now = datetime.now()
            run_id = f"run_{now.strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
            run_dir = RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            self.current_run_id = run_id
            self.current_run_dir = run_dir
            self.step_index = 0
            self._prune_old_runs()
            return run_id
        except Exception:
            logging.exception("Cannot start recording")
            self.current_run_id = None
            self.current_run_dir = None
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

            if not isinstance(frame, np.ndarray) or frame.size == 0:
                return None
            next_step = self.step_index + 1
            safe_screen_type = re.sub(r"[^a-zA-Z0-9_-]", "_", screen_type)
            step_id = f"step_{next_step:04d}_{safe_screen_type}"
            img_name = f"{step_id}.png"
            img_path = self.current_run_dir / img_name
            record = {
                "step": next_step,
                "timestamp": datetime.now().isoformat(),
                "run_id": self.current_run_id,
                "screen_type": screen_type,
                "action": action,
                "confidence": round(confidence, 4),
                "image": img_name,
                "details": metadata or {},
            }
            serialized = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            if not cv2.imwrite(str(img_path), frame):
                raise OSError(f"Could not save image: {img_path}")

            jsonl_path = self.current_run_dir / "decisions.jsonl"
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(serialized)
            self.step_index = next_step
            return record
        except Exception:
            logging.exception("Cannot record decision")
            return None

    def finish_run(
        self,
        survival_time: str = "",
        kills: int = 0,
        gold: int = 0,
        skills: Optional[list[str]] = None,
        skill_levels: Optional[dict[str, int]] = None,
        reward: Optional[float] = None,
        skill_deltas: Optional[dict[str, float]] = None,
    ):
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
            if skills is not None:
                summary["skills"] = skills
            if skill_levels is not None:
                summary["skill_levels"] = skill_levels
            if reward is not None:
                summary["reward"] = reward
            if skill_deltas is not None:
                summary["skill_deltas"] = skill_deltas
            write_json_atomic(self.current_run_dir / "summary.json", summary)
        except Exception:
            logging.exception("Cannot save run summary")
        finally:
            self.current_run_id = None
            self.current_run_dir = None

    def _prune_old_runs(self):
        try:
            if not RUNS_DIR.is_dir():
                return
            root = RUNS_DIR.resolve()
            all_runs = []
            for folder in root.iterdir():
                # Only delete this recorder's completed runs, never other folders,
                # active/incomplete sessions, symlinks or Windows junction targets.
                if (not folder.name.startswith("run_") or not folder.is_dir()
                        or folder.is_symlink() or folder.resolve() != folder.absolute()
                        or folder.resolve().parent != root or folder == self.current_run_dir):
                    continue
                summary_path = folder / "summary.json"
                if not summary_path.is_file():
                    continue
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if summary.get("run_id") == folder.name:
                    all_runs.append(folder)
            all_runs.sort(key=lambda d: d.name)
            excess = len(all_runs) + (1 if self.current_run_dir else 0) - self.max_runs
            if excess > 0:
                for old in all_runs[:excess]:
                    import shutil

                    shutil.rmtree(old, ignore_errors=True)
        except Exception:
            logging.exception("Cannot prune completed recordings")
