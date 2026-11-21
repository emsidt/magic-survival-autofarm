"""Adaptive Learning Engine for Magic Survival.
Learns skill, fusion, and synergy priorities across games based on survival duration.
Implements Step 2, 4, 7.
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

POLICY_VERSION = 2
# Credit assignment (v2): a skill is credited by its ADVANTAGE, i.e. (used this run - how often it is normally used).
# A skill present in every run (Spirit) therefore gets ~0 instead of drifting to the cap, and only skills that are used
# MORE than usual in good runs (or less in bad ones) move. This replaces the v1 rule that gave every used skill the
# same bonus, which saturated 23/43 weights at the +8.0 ceiling.
USAGE_ALPHA = 0.10      # EMA speed of the per-skill usage rate
USAGE_PRIOR = 0.5       # usage rate assumed for a skill never seen before (uninformative)
WEIGHT_DECAY = 0.01     # per-run pull towards 0 so stale preferences fade (~100 run memory)
ABSENT_FACTOR = 0.5     # skills NOT used in a run are weaker evidence than skills that were


class AdaptiveLearner:
    def __init__(self, data_dir: Path = DATA_DIR):
        data_dir = Path(data_dir)
        self.data_dir = data_dir
        self.policy_file = data_dir / "learned_policy.json"
        self.history_file = data_dir / "learning_history.json"
        self.policy = self._load_policy()
        self.history = self._load_history()
        self._migrate_policy_if_needed()

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
                usage = policy.setdefault("skill_usage", {})
                if not isinstance(usage, dict) or not all(
                    isinstance(k, str) and isinstance(v, (int, float)) and math.isfinite(v) and 0.0 <= v <= 1.0
                    for k, v in usage.items()
                ):
                    policy["skill_usage"] = {}
                recent = policy.get("recent_run_ids", [])
                policy["recent_run_ids"] = [item for item in recent if isinstance(item, str)] if isinstance(recent, list) else []
                return policy
            except Exception:
                pass
        return {
            "version": POLICY_VERSION,
            "total_runs_analyzed": 0,
            "skill_weights": {},       # skill_key -> learned weight bonus (-1.5 to +8.0)
            "synergy_weights": {},     # "skill_a+skill_b" -> synergy weight bonus (-1.0 to +5.0)
            "skill_usage": {},         # skill_key -> EMA of how often it is used (baseline for the advantage)
            "average_survival_sec": 0.0,
        }

    # ------------------------------------------------------------------ credit assignment (v2)
    def _apply_credit(
        self,
        active_skills: set[str],
        reward: float,
        lr: float,
        core_skills: Optional[set[str]] = None,
    ) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
        """Advantage-based update of skill/synergy weights. Returns (skills_updated, skill_deltas, syn_updated, syn_deltas)
        for the skills used in this run."""
        core_skills = core_skills or set()
        weights = self.policy["skill_weights"]
        syn_weights = self.policy["synergy_weights"]
        usage = self.policy.setdefault("skill_usage", {})
        all_skills = sorted(active_skills)
        prior = {sk: float(usage.get(sk, USAGE_PRIOR)) for sk in set(all_skills) | set(usage)}

        # 1) gentle forgetting so old, no longer supported preferences fade out
        for table in (weights, syn_weights):
            for key in list(table):
                table[key] = round(table[key] * (1.0 - WEIGHT_DECAY), 3)

        skills_updated: dict[str, float] = {}
        skill_deltas: dict[str, float] = {}
        # 2) skills: used -> (1 - usual rate); known-but-unused -> (0 - usual rate) at half strength
        for sk, p in prior.items():
            used = sk in active_skills
            if not used and sk not in weights:
                continue
            advantage = (1.0 - p) if used else -p * ABSENT_FACTOR
            current = weights.get(sk, 0.0)
            floor = 0.0 if sk in core_skills else -1.5
            new_val = round(max(floor, min(8.0, current + lr * reward * 2.0 * advantage)), 3)
            weights[sk] = new_val
            if used:
                skills_updated[sk] = new_val
                skill_deltas[sk] = round(new_val - current, 3)

        # 3) synergy: expected co-use under independence is p_a * p_b, so an always-together pair gets ~0
        synergies_updated: dict[str, float] = {}
        synergy_deltas: dict[str, float] = {}
        for i in range(len(all_skills)):
            for j in range(i + 1, len(all_skills)):
                a, b = all_skills[i], all_skills[j]
                pair_key = f"{a}+{b}"
                cur_syn = syn_weights.get(pair_key, 0.0)
                advantage = 1.0 - prior[a] * prior[b]
                new_syn = round(max(-1.0, min(5.0, cur_syn + lr * reward * 1.5 * advantage)), 3)
                syn_weights[pair_key] = new_syn
                synergies_updated[pair_key] = new_syn
                synergy_deltas[pair_key] = round(new_syn - cur_syn, 3)

        # 4) update the usage baseline AFTER crediting (so this run is judged against past behaviour)
        for sk in set(all_skills) | set(usage):
            p = prior.get(sk, USAGE_PRIOR)
            usage[sk] = round((1.0 - USAGE_ALPHA) * p + USAGE_ALPHA * (1.0 if sk in active_skills else 0.0), 4)
        return skills_updated, skill_deltas, synergies_updated, synergy_deltas

    def _migrate_policy_if_needed(self) -> None:
        """v1 -> v2: weights were saturated (every used skill got the same bonus), so rebuild them by replaying the
        recorded runs with the advantage rule. The old file is kept as learned_policy.v1.bak.json."""
        if self.policy.get("version", 1) >= POLICY_VERSION:
            return
        try:
            if self.policy_file.is_file():
                backup = self.policy_file.with_name("learned_policy.v1.bak.json")
                if not backup.exists():
                    backup.write_bytes(self.policy_file.read_bytes())
        except Exception:
            logging.exception("Cannot back up v1 policy")
        self.policy["skill_weights"] = {}
        self.policy["synergy_weights"] = {}
        self.policy["skill_usage"] = {}
        for rec in self.history:
            skills = {s for s in rec.get("skills", []) if isinstance(s, str)}
            reward = rec.get("reward")
            if not skills or not isinstance(reward, (int, float)) or not math.isfinite(reward):
                continue
            lr = 0.20 if (reward >= 0 or rec.get("is_human")) else 0.06
            self._apply_credit(skills, float(reward), lr, None)
        self.policy["version"] = POLICY_VERSION
        self.save()

    def _load_history(self) -> list[dict[str, Any]]:
        if self.history_file.is_file():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                if isinstance(history, list):
                    return [item for item in history if isinstance(item, dict)]
            except Exception:
                pass
        return []

    def save(self):
        try:
            write_json_atomic(self.policy_file, self.policy)
            write_json_atomic(self.history_file, self.history)
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
            prev_avg = max(180.0, min(600.0, survival_seconds))
            self.policy["average_survival_sec"] = prev_avg

        # Phân biệt ván người chơi (>= 20 phút) vs ván bot tự chơi (< 20 phút)
        is_human_run = bool(survival_seconds >= 1200.0)
        diff = survival_seconds - prev_avg

        if is_human_run or diff >= 0:
            # Vượt mốc trung bình hoặc ván người chơi xuất sắc:
            # Trao thưởng điểm dương để bot học hỏi cách chọn kỹ năng mạnh
            reward = min(1.5, max(1.0 if is_human_run else 0.0, diff / max(prev_avg * 0.70, 120.0)))
            lr = 0.20
        else:
            # Dưới trung bình: Giảm nhẹ điểm để tránh phá vỡ các build tốt khi bot di chuyển lỗi
            reward = max(-0.30, diff / max(prev_avg * 2.5, 360.0))
            lr = 0.06  # Asymmetric: much slower decay on losses

        all_skills = sorted(list(active_skills))
        # Core/preferred skills never drop below 0; credit goes by advantage over their usual usage rate
        skills_updated, skill_deltas, synergies_updated, synergy_deltas = self._apply_credit(
            set(active_skills), reward, lr, core_skills
        )
        self.policy["version"] = POLICY_VERSION

        # Cập nhật thời gian trung bình (Moving average)
        # QUAN TRỌNG: TUYỆT ĐỐI KHÔNG để các ván người chơi (25p - 110p) làm lệch mốc trung bình của bot!
        if not is_human_run:
            weight = min(n, 12)
            new_avg = round((prev_avg * weight + survival_seconds) / (weight + 1), 1)
            self.policy["total_runs_analyzed"] = n + 1
            self.policy["average_survival_sec"] = new_avg
        else:
            self.policy["total_runs_analyzed"] = n + 1
            new_avg = prev_avg

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
            "is_human": is_human_run,
        }
        if skill_levels:
            run_record["skill_levels"] = {k: int(v) for k, v in skill_levels.items() if k in all_skills}
        self.history.append(run_record)
        self.policy["recent_run_ids"] = self.policy.get("recent_run_ids", []) + [run_id]
        self.save()

        return {
            "run_id": run_id,
            "survival_sec": survival_seconds,
            "prev_avg_sec": prev_avg,
            "diff_sec": diff,
            "reward": reward,
            "total_runs": n + 1,
            "average_survival_sec": new_avg,
            "new_avg_survival": new_avg,
            "skills_updated": skills_updated,
            "skill_deltas": skill_deltas,
            "synergies_updated": synergies_updated,
            "synergy_deltas": synergy_deltas,
            "is_human": is_human_run,
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

