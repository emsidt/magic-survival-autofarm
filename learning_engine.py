"""Adaptive Learning Engine for Magic Survival.
Learns skill, fusion, and synergy priorities across games based on survival duration.
Implements Step 2, 4, 7 of KE_HOACH_AI.md.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Optional
from storage import write_json_atomic

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
POLICY_FILE = DATA_DIR / "learned_policy.json"
HISTORY_FILE = DATA_DIR / "learning_history.json"


class AdaptiveLearner:
    def __init__(self, data_dir: Path = DATA_DIR):
        data_dir = Path(data_dir)
        self.data_dir = data_dir
        self.policy_file = data_dir / "learned_policy.json"
        self.history_file = data_dir / "learning_history.json"
        self.policy = self._load_policy()
        self.history = self._load_history()

    def _load_policy(self) -> dict[str, Any]:
        if self.policy_file.is_file():
            try:
                with open(self.policy_file, "r", encoding="utf-8") as f:
                    policy = json.load(f)
                if not isinstance(policy, dict):
                    raise ValueError("Invalid policy object")
                for field in ("skill_weights", "synergy_weights"):
                    weights = policy.setdefault(field, {})
                    if not isinstance(weights, dict) or not all(
                        isinstance(k, str) and isinstance(v, (int, float)) and math.isfinite(v)
                        for k, v in weights.items()
                    ):
                        raise ValueError("Invalid policy weights")
                if not isinstance(policy.get("total_runs_analyzed", 0), int) or policy.get("total_runs_analyzed", 0) < 0:
                    raise ValueError("Invalid run count")
                average = policy.get("average_survival_sec", 0.0)
                if not isinstance(average, (int, float)) or not math.isfinite(average) or average < 0:
                    raise ValueError("Invalid survival average")
                recent = policy.get("recent_run_ids", [])
                policy["recent_run_ids"] = [item for item in recent if isinstance(item, str)][-100:] if isinstance(recent, list) else []
                return policy
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
                    history = json.load(f)
                if isinstance(history, list):
                    return [item for item in history if isinstance(item, dict)][-100:]
            except Exception:
                pass
        return []

    def save(self):
        try:
            write_json_atomic(self.policy_file, self.policy)
            write_json_atomic(self.history_file, self.history[-100:])
        except Exception:
            logging.exception("Cannot persist learned policy")

    def evaluate_and_learn_run(
        self,
        run_id: str,
        survival_seconds: float,
        active_skills: set[str],
        combos: Optional[list[str]] = None,
        kills: int = 0,
        core_skills: Optional[set[str]] = None,
        skill_levels: Optional[dict[str, int]] = None,
    ) -> dict[str, Any]:
        """Evaluate match outcome against the bot's own historical average.
        - Better than average: Award positive reward to build on successful skills/synergies.
        - Below average: Apply gentle adjustment without destroying proven builds (bot is still learning movement).
        """
        if not run_id or not math.isfinite(survival_seconds) or survival_seconds <= 0:
            raise ValueError("A run needs a unique ID and positive finite HUD survival time")
        if run_id in self.policy.get("recent_run_ids", []) or any(r.get("run_id") == run_id for r in self.history):
            return {
                "run_id": run_id,
                "skipped": "already_analyzed",
                "skills_updated": {},
                "skill_deltas": {},
                "total_runs": self.policy.get("total_runs_analyzed", 0),
            }
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
        skill_deltas = {}
        all_skills = sorted(list(active_skills))
        for sk in all_skills:
            current = self.policy["skill_weights"].get(sk, 0.0)
            # Protect core/preferred skills from dropping below 0
            floor = 0.0 if (sk in core_skills) else -1.5
            new_val = round(max(floor, min(8.0, current + lr * reward * 2.0)), 3)
            self.policy["skill_weights"][sk] = new_val
            skills_updated[sk] = new_val
            skill_deltas[sk] = round(new_val - current, 3)

        # Synergy pairs update
        synergies_updated = {}
        synergy_deltas = {}
        for i in range(len(all_skills)):
            for j in range(i + 1, len(all_skills)):
                pair_key = f"{all_skills[i]}+{all_skills[j]}"
                cur_syn = self.policy["synergy_weights"].get(pair_key, 0.0)
                new_syn = round(max(-1.0, min(5.0, cur_syn + lr * reward * 1.5)), 3)
                self.policy["synergy_weights"][pair_key] = new_syn
                synergies_updated[pair_key] = new_syn
                synergy_deltas[pair_key] = round(new_syn - cur_syn, 3)

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
            "skill_deltas": skill_deltas,
            "combos": combos,
        }
        if skill_levels:
            run_record["skill_levels"] = {k: int(v) for k, v in skill_levels.items() if k in all_skills}
        self.history.append(run_record)
        self.history = self.history[-100:]
        self.policy["recent_run_ids"] = (self.policy.get("recent_run_ids", []) + [run_id])[-100:]
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
            "skill_deltas": skill_deltas,
        }

    def get_skill_bonus(self, skill_key: str, active_skills: Optional[set[str]] = None) -> float:
        """Return learned bonus score to add to the base meta score of a skill card."""
        bonus = self.policy.get("skill_weights", {}).get(skill_key, 0.0)
        if active_skills:
            syn_map = self.policy.get("synergy_weights", {})
            for active in active_skills:
                if active == skill_key:
                    continue
                pair = "+".join(sorted((skill_key, active)))
                bonus += syn_map.get(pair, 0.0)
        return bonus

    def update_movement_policy(
        self,
        weave_freq: float,
        weave_amp: float,
        chest_aggression: float = 1.5,
        run_id: str = "",
    ) -> dict[str, Any]:
        """Update learned movement policy parameters from human demonstration."""
        mp = self.policy.setdefault("movement_policy", {
            "weave_frequency": 3.2,
            "weave_amplitude": 0.28,
            "chest_aggression": 1.5,
            "total_movement_sessions": 0,
        })
        n = mp.get("total_movement_sessions", 0)
        alpha = 0.35 if n > 0 else 1.0
        cur_freq = float(mp.get("weave_frequency", 3.2))
        cur_amp = float(mp.get("weave_amplitude", 0.28))
        cur_agg = float(mp.get("chest_aggression", 1.5))

        new_freq = round((1.0 - alpha) * cur_freq + alpha * max(1.0, min(6.0, weave_freq)), 2)
        new_amp = round((1.0 - alpha) * cur_amp + alpha * max(0.05, min(0.60, weave_amp)), 3)
        new_agg = round((1.0 - alpha) * cur_agg + alpha * max(1.0, min(3.0, chest_aggression)), 2)

        mp["weave_frequency"] = new_freq
        mp["weave_amplitude"] = new_amp
        mp["chest_aggression"] = new_agg
        mp["total_movement_sessions"] = n + 1
        self.save()
        return {
            "weave_frequency": new_freq,
            "weave_amplitude": new_amp,
            "chest_aggression": new_agg,
            "total_sessions": n + 1,
        }

    def get_movement_policy(self) -> dict[str, Any]:
        """Return current learned movement policy for kiting and chest approach."""
        return self.policy.get("movement_policy", {
            "weave_frequency": 3.2,
            "weave_amplitude": 0.28,
            "chest_aggression": 1.5,
            "total_movement_sessions": 0,
        })


_GLOBAL_LEARNER: Optional[AdaptiveLearner] = None


def get_adaptive_learner() -> AdaptiveLearner:
    global _GLOBAL_LEARNER
    if _GLOBAL_LEARNER is None:
        _GLOBAL_LEARNER = AdaptiveLearner()
    return _GLOBAL_LEARNER

