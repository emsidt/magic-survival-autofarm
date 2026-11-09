"""Adaptive Learning Engine for Magic Survival.
Learns skill, fusion, and synergy priorities across games based on survival duration.
Implements Step 2, 4, 7 of KE_HOACH_AI.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
POLICY_FILE = DATA_DIR / "learned_policy.json"
HISTORY_FILE = DATA_DIR / "learning_history.json"


class AdaptiveLearner:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.policy_file = data_dir / "learned_policy.json"
        self.history_file = data_dir / "learning_history.json"
        self.policy = self._load_policy()
        self.history = self._load_history()

    def _load_policy(self) -> dict[str, Any]:
        if self.policy_file.is_file():
            try:
                with open(self.policy_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "version": 1,
            "total_runs_analyzed": 0,
            "skill_weights": {},       # skill_key -> learned weight bonus (-5.0 to +8.0)
            "synergy_weights": {},     # "skill_a+skill_b" -> synergy weight bonus
            "average_survival_sec": 0.0,
        }

    def _load_history(self) -> list[dict[str, Any]]:
        if self.history_file.is_file():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.policy_file, "w", encoding="utf-8") as f:
                json.dump(self.policy, f, indent=2, ensure_ascii=False)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history[-100:], f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def evaluate_and_learn_run(
        self,
        run_id: str,
        survival_seconds: float,
        active_skills: set[str],
        combos: Optional[list[str]] = None,
        kills: int = 0,
        core_skills: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        """Evaluate match outcome against the bot's own historical average.
        - Better than average: Award positive reward to build on successful skills/synergies.
        - Below average: Apply gentle adjustment without destroying proven builds (bot is still learning movement).
        """
        combos = combos or []
        core_skills = core_skills or set()

        n = self.policy.get("total_runs_analyzed", 0)
        prev_avg = float(self.policy.get("average_survival_sec", 0.0))

        # Baseline: initialize from first run if no history
        if n == 0 or prev_avg <= 10.0:
            prev_avg = max(180.0, survival_seconds)
            self.policy["average_survival_sec"] = prev_avg

        diff = survival_seconds - prev_avg

        if diff >= 0:
            # Better than average: Strong reward to encourage this build progression
            reward = min(1.5, diff / max(prev_avg * 0.70, 120.0))
            lr = 0.20
        else:
            # Below average: Mild penalty because the bot is still clumsy in movement
            # Never harshly punish a build that the user knows is strong!
            reward = max(-0.30, diff / max(prev_avg * 2.5, 360.0))
            lr = 0.06  # Asymmetric: much slower decay on losses

        skills_updated = {}
        all_skills = sorted(list(active_skills))
        for sk in all_skills:
            current = self.policy["skill_weights"].get(sk, 0.0)
            # Protect core/preferred skills from dropping below 0
            floor = 0.0 if (sk in core_skills) else -1.5
            new_val = round(max(floor, min(8.0, current + lr * reward * 2.0)), 3)
            self.policy["skill_weights"][sk] = new_val
            skills_updated[sk] = new_val

        # Synergy pairs update
        synergies_updated = {}
        for i in range(len(all_skills)):
            for j in range(i + 1, len(all_skills)):
                pair_key = f"{all_skills[i]}+{all_skills[j]}"
                cur_syn = self.policy["synergy_weights"].get(pair_key, 0.0)
                new_syn = round(max(-1.0, min(5.0, cur_syn + lr * reward * 1.5)), 3)
                self.policy["synergy_weights"][pair_key] = new_syn
                synergies_updated[pair_key] = new_syn

        # Moving average update with dampening so it doesn't fluctuate wildly
        weight = min(n, 12)
        new_avg = round((prev_avg * weight + survival_seconds) / (weight + 1), 1)
        self.policy["total_runs_analyzed"] = n + 1
        self.policy["average_survival_sec"] = new_avg

        run_record = {
            "run_id": run_id,
            "survival_sec": round(survival_seconds, 1),
            "prev_avg_sec": round(prev_avg, 1),
            "diff_sec": round(diff, 1),
            "kills": kills,
            "reward": round(reward, 3),
            "skills": all_skills,
            "combos": combos,
        }
        self.history.append(run_record)
        self.save()

        return {
            "run_id": run_id,
            "survival_sec": survival_seconds,
            "prev_avg_sec": prev_avg,
            "diff_sec": diff,
            "reward": reward,
            "total_runs": n + 1,
            "new_avg_survival": new_avg,
            "skills_updated": skills_updated,
        }

    def get_skill_bonus(self, skill_key: str, active_skills: Optional[set[str]] = None) -> float:
        """Return learned bonus score to add to the base meta score of a skill card."""
        bonus = self.policy.get("skill_weights", {}).get(skill_key, 0.0)
        if active_skills:
            syn_map = self.policy.get("synergy_weights", {})
            for active in active_skills:
                pair1 = f"{skill_key}+{active}"
                pair2 = f"{active}+{skill_key}"
                bonus += syn_map.get(pair1, 0.0)
                bonus += syn_map.get(pair2, 0.0)
        return bonus


_GLOBAL_LEARNER: Optional[AdaptiveLearner] = None


def get_adaptive_learner() -> AdaptiveLearner:
    global _GLOBAL_LEARNER
    if _GLOBAL_LEARNER is None:
        _GLOBAL_LEARNER = AdaptiveLearner()
    return _GLOBAL_LEARNER

