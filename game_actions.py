"""Shared capture and menu actions for the GUI and CLI runners."""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from uuid import uuid4

import numpy as np

import botcore


class ActionCancelled(RuntimeError):
    """The user stopped the bot or the game lost focus."""


class FrameCaptureError(RuntimeError):
    pass


class GuardedController:
    """Check permission again before every input in a multi-step action."""

    def __init__(self, controller, can_act):
        self.controller = controller
        self.can_act = can_act

    def __getattr__(self, name):
        return getattr(self.controller, name)

    def _act(self, method, *args, **kwargs):
        with self.controller.lock:
            if not self.can_act():
                self.controller.release()
                raise ActionCancelled("Input đã dừng hoặc game không còn được chọn")
            return getattr(self.controller, method)(*args, **kwargs)

    def tap(self, *args, **kwargs):
        return self._act("tap", *args, **kwargs)

    def move(self, *args, **kwargs):
        return self._act("move", *args, **kwargs)

    def press_esc(self):
        return self._act("press_esc")

    def launch_game(self, *args, **kwargs):
        return self._act("launch_game", *args, **kwargs)


def capture_frame(controller, rect, desktop_capture):
    """Keep screenshots and input in the same coordinate space. Never mix ADB/desktop."""
    if hasattr(controller, "screen_width"):
        frame = controller.screenshot()
    else:
        frame = desktop_capture(rect)
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
        controller.release()
        raise FrameCaptureError("Không nhận được ảnh game; bỏ qua thao tác")
    return frame


@dataclass(frozen=True)
class LearnedSelection:
    key: str
    label: str
    index: int = 0


def _returned_to_game(frame):
    # A missing Learn button alone is insufficient: a black/loading frame is not success.
    if botcore.is_attribute_screen(frame):
        return False
    if botcore.find_best_combination_option(frame) is not None:
        return False
    return bool(botcore.is_level_up_screen(frame) or botcore.is_fast_combat_frame(frame))


def dismiss_death(controller, rect, capture, sleep=time.sleep):
    """Tap only a freshly verified Die label, never the nearby rewarded Revive."""
    controller.release()
    frame = capture()
    if botcore.detect_die_button(frame) is None:
        return False
    target = botcore.detect_verified_die_text(frame)
    if target is None:
        return False
    # CRITICAL HARD SAFETY GATE: Revive is at y ~ 0.64. Die is strictly at y >= 0.68.
    if target[1] < 0.68 or target[1] > 0.85:
        return False
    controller.tap(list(target), rect)
    sleep(0.40)
    confirm = botcore.detect_confirm_button(capture())
    if confirm is not None:
        return True
    for _ in range(2):
        sleep(0.40)
        if botcore.detect_confirm_button(capture()) is not None:
            return True
    return False


def close_ad(controller, rect, capture):
    """Find a dismiss control on a fresh frame and send exactly one input."""
    controller.release()
    target = botcore.detect_close_button(capture())
    if target is None:
        return None
    controller.tap(list(target), rect)
    # The ad may already have returned to the game. Never append a blind Back.
    return target


def back_from_ad(controller, rect, capture):
    """Use Back only while a fresh frame still shows an ad without a close control."""
    controller.release()
    frame = capture()
    if botcore.detect_close_button(frame) is not None or not botcore.is_ad_screen(frame):
        return False
    controller.press_esc()
    return True


def move_from_frame(controller, rect, config, direction, captured_at):
    """Reject a stale movement decision; lease background motion from frame age."""
    age = time.perf_counter() - captured_at
    if not math.isfinite(age) or age >= 1.0:
        controller.release()
        return False
    age = max(0.0, age)
    controller.move(direction, rect, {**config, "_movement_frame_age": age})
    return True


def select_chest_artifact(controller, rect, capture, active_skills=None, prefer_cc=True, sleep=time.sleep):
    """Revalidate the chest between slots and before Obtain; confirm its transition."""
    controller.release()
    frame = capture()
    obtain = botcore.detect_obtain_button(frame)
    if obtain is None:
        return None
    count = 3 if botcore.is_three_card_chest(frame, obtain[0]) else 1
    candidates = {}
    for index in range(1, count + 1):
        if count > 1:
            controller.tap(list(botcore.get_chest_card_target(index, obtain[0])), rect)
            sleep(0.30)
            frame = capture()
            obtain = botcore.detect_obtain_button(frame)
            if obtain is None:
                return None
        candidates[index] = botcore.evaluate_selected_chest_artifact(frame, prefer_cc, active_skills=active_skills)
    best = max(candidates, key=lambda index: candidates[index][0])
    if best != count:
        controller.tap(list(botcore.get_chest_card_target(best, obtain[0])), rect)
        sleep(0.30)
    obtain = botcore.detect_obtain_button(capture())
    if obtain is None:
        return None
    controller.tap(list(obtain), rect)
    for _ in range(3):
        sleep(0.30)
        after = capture()
        if botcore.detect_obtain_button(after):
            return None
        if botcore.is_fast_combat_frame(after) or botcore.is_level_up_screen(after):
            return LearnedSelection("", candidates[best][1], best)
    return None


def select_character(controller, rect, frame, capture, character="summoner", sleep=time.sleep):
    """Click the requested roster icon, verify its name, then confirm Selected."""
    controller.release()
    if not botcore.detect_selected(frame):
        return False
    target = botcore.detect_character_option(frame, character)
    if target is None:
        return False
    controller.tap(list(target), rect)
    # Allow the details panel to update; OCR failure never confirms another class.
    for _ in range(3):
        sleep(0.30)
        details = capture()
        selected = botcore.detect_selected(details)
        if not selected:
            return False
        if botcore.is_character_selected(details, character):
            controller.tap(list(selected), rect)
            for _ in range(3):
                sleep(0.40)
                if botcore.detect_enter_area(capture()):
                    return True
            return False
    return False


def select_attribute(controller, rect, capture, sleep=time.sleep):
    """Inspect each trait, confirm an active Learn button, then verify the transition."""
    controller.release()
    if not botcore.is_attribute_screen(capture()):
        return None
    circles = botcore.get_attribute_circle_targets()
    best = None
    last_index = None
    for index, target in circles.items():
        controller.tap(list(target), rect)
        sleep(0.30)
        frame = capture()
        if not botcore.is_attribute_screen(frame):
            return None
        score, label, parent = botcore.evaluate_selected_attribute(frame)
        if (parent or label != "Nhánh Attribute") and (best is None or score > best[0]):
            best = (score, index, label, parent)
        last_index = index
    if best is None:
        return None
    _, index, label, parent = best
    if last_index != index:
        controller.tap(list(circles[index]), rect)
        sleep(0.30)
    frame = capture()
    learn = botcore.detect_learn_button(frame)
    if not botcore.is_attribute_screen(frame) or not learn or not botcore.is_learn_button_active(frame):
        return None
    controller.tap(list(learn), rect)
    sleep(0.45)
    if not _returned_to_game(capture()):
        return None
    return LearnedSelection(parent, label, index)


def select_combination(controller, rect, frame, capture, priority=None, sleep=time.sleep):
    """Open only a red star; return a learned combo only after a confirmed transition."""
    star = botcore.detect_combination_star(frame)
    if not star:
        return None
    controller.tap(list(star), rect)
    sleep(0.45)
    menu = capture()
    choice = botcore.find_best_combination_option(menu, priority)
    if not choice:
        # Do not reuse the pre-menu screenshot or tap the star as a guessed close button.
        controller.press_esc()
        return None
    target, label, key = choice
    controller.tap(list(target), rect)
    sleep(0.35)
    details = capture()
    learn = botcore.detect_learn_button(details)
    if not learn or not botcore.is_learn_button_active(details):
        controller.press_esc()
        return None
    controller.tap(list(learn), rect)
    sleep(0.45)
    after = capture()
    if not _returned_to_game(after):
        if botcore.detect_learn_button(after) or botcore.find_best_combination_option(after):
            controller.press_esc()
        return None
    return LearnedSelection(key, label)


def select_card(controller, rect, frame, choice, capture, sleep=time.sleep):
    """Accept a card only when the choice screen visibly transitions to a known state."""
    if choice.target is None:
        return False
    controller.tap(list(choice.target), rect)
    sleep(0.40)
    after = capture()
    if botcore.is_attribute_screen(after):
        return True
    if botcore.is_level_up_screen(after):
        # Repeated attempts on the same level-up screen must not inflate skill levels.
        return False
    return bool(botcore.is_fast_combat_frame(after) or botcore.detect_obtain_button(after))


def remember_card(choice, active_skills, skill_levels, maxed_skills):
    """Call only after select_card succeeds. Prefer the level actually read on the card."""
    key = choice.skill_key
    if not key:
        return
    active_skills.add(key)
    level = getattr(choice, "offered_level", None)
    if level is not None:
        skill_levels[key] = level
    elif key not in skill_levels:
        skill_levels[key] = 1
    # A count of clicks is not proof that a skill reached its cap, particularly
    # when attaching to an ongoing run or when a level-4 trait screen appears.
    cap = botcore.SKILL_MAX_LEVELS.get(key, 1 if key in botcore.SPECIAL_STAR_PASSIVES else 7)
    if key in botcore.SPECIAL_STAR_PASSIVES or (level is not None and level >= cap):
        maxed_skills.add(key)


def format_match_summary(
    survival_seconds: float,
    active_skills: set[str],
    skill_levels: Optional[dict[str, int]] = None,
    report: Optional[dict[str, Any]] = None,
    character: str = "",
    gold: int = 0,
    kills: int = 0,
    game_map: str = "",
) -> tuple[str, str]:
    """Format human-readable log block and short status line for match results.
    Returns (summary_block, status_line).
    """
    mins, secs = divmod(int(max(0.0, survival_seconds)), 60)
    survival_str = f"{mins:02d}:{secs:02d}"
    survival_detail = f"{survival_str} ({int(max(0.0, survival_seconds))}s)"

    # Skills formatting
    levels = dict(skill_levels or {})
    all_skills = sorted(
        list(active_skills),
        key=lambda k: (-levels.get(k, 1), botcore.get_readable_skill_name(k)),
    )
    skill_items = [
        f"{botcore.get_readable_skill_name(k)} (Lv.{levels.get(k, 1)})"
        for k in all_skills
    ]
    skills_summary = ", ".join(skill_items) if skill_items else "Chưa chọn kỹ năng nào"

    # Điểm cộng trừ
    reward_str = "0.000"
    diff_str = ""
    skill_delta_lines = []
    n_runs = 0
    n_m, n_s = 0, 0
    is_dict_report = isinstance(report, dict)
    if is_dict_report and report:
        reward = float(report.get("reward", 0.0))
        reward_sign = "+" if reward >= 0 else ""
        reward_str = f"{reward_sign}{reward:.3f}"

        diff_sec = float(report.get("diff_sec", 0.0))
        diff_sign = "+" if diff_sec >= 0 else ""
        prev_avg = float(report.get("prev_avg_sec", 0.0))
        p_m, p_s = divmod(int(prev_avg), 60)
        diff_str = f"[{diff_sign}{diff_sec:.1f}s so với mốc TB {p_m:02d}:{p_s:02d}]"

        n_runs = int(report.get("total_runs", 0))
        n_avg = float(report.get("new_avg_survival", 0.0))
        n_m, n_s = divmod(int(n_avg), 60)

        deltas = report.get("skill_deltas", {})
        updated = report.get("skills_updated", {})
        for k in all_skills:
            d = float(deltas.get(k, 0.0))
            d_sign = "+" if d >= 0 else ""
            w = float(updated.get(k, 0.0))
            lvl = levels.get(k, 1)
            name = botcore.get_readable_skill_name(k)
            skill_delta_lines.append(f"    • {name} (Lv.{lvl}): {d_sign}{d:.3f}  ->  Tổng trọng số: {w:.3f}")

    lines = [
        "=" * 65,
        "🏁 KẾT QUẢ VÁN ĐẤU",
    ]
    if game_map:
        map_low = game_map.lower().strip()
        if "depth" in map_low:
            lines.append("🗺️  Bản đồ: Depth (Vực thẳm - Tốc độ thời gian x1.24 [Time Circuit])")
        elif "virtual" in map_low or "ecosystem" in map_low:
            lines.append("🗺️  Bản đồ: Virtual Ecosystem (Hệ sinh thái ảo)")
        else:
            lines.append(f"🗺️  Bản đồ: {game_map.title()}")
    lines.append(f"⏱️  Thời gian sống: {survival_detail} {diff_str}".strip())
    if is_dict_report and report and "reward" in report:
        lines.append(f"🎯  Điểm cộng/trừ AI: {reward_str} điểm (Ván #{n_runs} | Mốc TB mới: {n_m:02d}:{n_s:02d})")
    elif survival_seconds > 0:
        lines.append("🎯  Điểm cộng/trừ AI: Đã ghi nhận thời gian sống")
    else:
        lines.append("🎯  Điểm cộng/trừ AI: Bỏ qua (Thời gian sống chưa hợp lệ)")

    lines.append(f"📚  Kỹ năng đã học ({len(all_skills)}): {skills_summary}")
    if skill_delta_lines:
        lines.append("📊  Điểm cộng/trừ từng kỹ năng:")
        lines.extend(skill_delta_lines)
    if gold > 0 or kills > 0:
        lines.append(f"💰  Phần thưởng: {gold:,} Vàng | {kills:,} Quái hạ gục")
    lines.append("=" * 65)

    summary_block = "\n".join(lines)
    status_line = f"🏁 [Kết quả ván] ⏱️ {survival_str} | Điểm AI: {reward_str} | Skill: {skills_summary}"
    return summary_block, status_line


def finish_match(
    recorder,
    learner,
    frame,
    survival_seconds,
    active_skills,
    core_skills,
    skill_levels: Optional[dict[str, int]] = None,
    character: str = "",
    combos: Optional[list[str]] = None,
    gold: int = 0,
    kills: int = 0,
    game_map: str = "",
):
    """Preserve the run ID, train on gameplay survival time, and format log summary."""
    active_set = set(active_skills)
    levels = dict(skill_levels or {})
    if character:
        char_norm = character.lower().strip()
        start_skill = botcore.CHARACTER_STARTING_SKILLS.get(char_norm)
        if start_skill:
            active_set.add(start_skill)
            if start_skill not in levels:
                levels[start_skill] = 1

    recorder.record_decision(frame, "endgame", "confirm", metadata={"timer_source": "hud"})
    run_id = recorder.current_run_id or f"unrecorded_{uuid4().hex}"
    minutes, seconds = divmod(int(max(0.0, survival_seconds)), 60)
    survival_str = f"{minutes:02d}:{seconds:02d}" if survival_seconds > 0 else ""
    recorder.finish_run(survival_time=survival_str)
    if survival_seconds <= 0:
        summary_block, _ = format_match_summary(
            survival_seconds=0.0,
            active_skills=active_set,
            skill_levels=levels,
            report=None,
            character=character,
            gold=gold,
            kills=kills,
            game_map=game_map,
        )
        print(summary_block)
        return None

    learn_kwargs: dict[str, Any] = {
        "run_id": run_id,
        "survival_seconds": survival_seconds,
        "active_skills": active_set,
        "core_skills": set(core_skills),
    }
    if combos:
        learn_kwargs["combos"] = combos
    if kills:
        learn_kwargs["kills"] = kills
    if levels:
        learn_kwargs["skill_levels"] = levels

    report = learner.evaluate_and_learn_run(**learn_kwargs)

    summary_block, status_line = format_match_summary(
        survival_seconds=survival_seconds,
        active_skills=active_set,
        skill_levels=levels,
        report=report,
        character=character,
        gold=gold,
        kills=kills,
        game_map=game_map,
    )

    if isinstance(report, dict):
        report["summary_text"] = summary_block
        report["status_line"] = status_line
        report["skills"] = list(active_set)
        report["skill_levels"] = levels

    return report
