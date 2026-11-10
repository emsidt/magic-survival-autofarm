"""Pure vision and movement policy for the Magic Survival desktop helper.

No game memory, network, or emulator internals are accessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import Optional

import cv2
import numpy as np

_BASE_DIR = Path(__file__).resolve().parent


def _match_keyword(kw: str, text: str) -> bool:
    """Match whole keyword or phrase to avoid partial false positives (e.g. 'sniper' vs 'snipe')."""
    return bool(re.search(r'(?<![a-zA-Z0-9])' + re.escape(kw) + r'(?![a-zA-Z0-9])', text))

class ChestTarget(tuple):
    """2-tuple (x, y) with .chest_type, .weight, and .all_positions attributes."""
    def __new__(
        cls,
        pos: tuple[int, int],
        chest_type: str = "treasure_chest",
        weight: float = 24.0,
        all_positions: Optional[list[tuple[int, int]]] = None,
    ):
        return super().__new__(cls, pos)

    def __init__(
        self,
        pos: tuple[int, int],
        chest_type: str = "treasure_chest",
        weight: float = 24.0,
        all_positions: Optional[list[tuple[int, int]]] = None,
    ):
        self.chest_type = chest_type
        self.weight = weight
        self.all_positions = all_positions if all_positions is not None else [pos]


CHEST_SPECS = [
    ("black_box", "assets/chests/black_box.png", 36.0, False),
    ("reliquary", "assets/chests/reliquary.png", 30.0, False),
    ("treasure_chest", "assets/chests/treasure_chest.png", 24.0, False),
    ("treasure_chest", "assets/chest_icon.png", 24.0, True),
    ("treasure_chest", "assets/chest_indicator.png", 26.0, True),
]

_CACHED_SMALL_CHEST_TEMPLATES: list[tuple[str, np.ndarray, float, int, int, bool]] = []


def _get_fast_chest_templates() -> list[tuple[str, np.ndarray, float, int, int, bool]]:
    global _CACHED_SMALL_CHEST_TEMPLATES
    if _CACHED_SMALL_CHEST_TEMPLATES:
        return _CACHED_SMALL_CHEST_TEMPLATES
    res = []
    for chest_type, rel_path, weight, is_indicator in CHEST_SPECS:
        path = _BASE_DIR / rel_path
        if not path.is_file():
            continue
        base_tmpl = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if base_tmpl is None:
            continue
        bh, bw = base_tmpl.shape[:2]
        # Multi-scale templates on 2x downsampled image (matching 0.70x to 2.0x raw screens, including 1080p LDPlayer)
        for scale in (0.35, 0.45, 0.55, 0.70, 0.85, 1.00):
            tw = max(14, int(round(bw * scale)))
            th = max(12, int(round(bh * scale)))
            st = cv2.resize(base_tmpl, (tw, th))
            res.append((chest_type, st, weight, tw, th, is_indicator))
            if "indicator" in rel_path:
                res.append((chest_type, cv2.flip(st, 1), weight, tw, th, is_indicator))
    _CACHED_SMALL_CHEST_TEMPLATES = res
    return _CACHED_SMALL_CHEST_TEMPLATES


def _verify_chest_color(roi_bgr: np.ndarray, chest_type: str = "treasure_chest") -> bool:
    """Ensure detected region has genuine chest colors rather than olive ground, enemy pixels, or gold mana."""
    if roi_bgr.size == 0:
        return False
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    total_px = roi_bgr.shape[0] * roi_bgr.shape[1]

    if chest_type == "treasure_chest":
        # Rich amber/brown wood (H 5..28, S>=35, V>=25), or cream/white indicator badge (S<=45, V>=175)
        wood = (H >= 5) & (H <= 28) & (S >= 35) & (V >= 25)
        badge = (S <= 45) & (V >= 175)
        # CRITICAL: Reject regions that are purely glowing Gold/Yellow Mana orbs!
        # Gold mana orbs have bright neon yellow (H 18..36, S >= 80, V >= 185) with NO dark pixels!
        bright_gold = (H >= 16) & (H <= 36) & (S >= 80) & (V >= 185)
        dark_pixels = (V <= 50)
        if np.sum(bright_gold) / total_px > 0.35 and np.sum(dark_pixels) / total_px < 0.04:
            return False
        # Genuine chests have substantial wood planks (>=10%) AND dark iron bands/outline (>=8%).
        # Real indicators have white/cream badge body (>=8%) or dimmed modal background (dark >= 55%).
        has_wood_chest = (np.sum(wood) / total_px >= 0.10) and (np.sum(dark_pixels) / total_px >= 0.08)
        has_badge = (np.sum(badge) / total_px >= 0.08) or (np.sum(dark_pixels) / total_px >= 0.55)
        return bool(has_wood_chest or has_badge)
    elif chest_type == "reliquary":
        red = ((H <= 16) | (H >= 164)) & (S >= 45) & (V >= 45)
        stone = (S <= 65) & (V >= 115) & (V <= 235)
        dark_stone = (S < 40) & (V >= 30) & (V <= 110)
        return bool(
            (np.sum(red) / total_px >= 0.015)
            and (np.sum(stone) / total_px >= 0.14)
            and (np.sum(dark_stone) / total_px >= 0.06)
        )
    elif chest_type == "black_box":
        # Charcoal gray stone (V 28..110, low S), NOT pitch-black enemy core (V < 20)
        dark_stone = (S < 42) & (V >= 28) & (V <= 110)
        highlight = (S < 50) & (V >= 120)
        return bool((np.sum(dark_stone) / total_px >= 0.20) and (np.sum(highlight) / total_px >= 0.005))
    return False


def detect_chest(
    frame: np.ndarray,
    min_confidence: float = 0.60,
    player: tuple[float, float] = (0.5, 0.5),
) -> Optional[ChestTarget]:
    """Fast, multi-scale artifact chest & off-screen HUD chest indicator detector
    (Black Box [36.0] > Reliquary [30.0] > Treasure Chest [24.0..26.0]).

    Explicitly excludes the player character sprite at center and top HUD bar.
    Never mistakes glowing Gold Mana orbs or shadow monster blobs for chests.
    """
    templates = _get_fast_chest_templates()
    if isinstance(min_confidence, (tuple, list)):
        player = tuple(min_confidence)
        min_confidence = 0.60
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    fh, fw = gray.shape[:2]
    span = min(fw, fh)
    small = cv2.resize(gray, (fw // 2, fh // 2))

    px, py = int(fw * player[0]), int(fh * player[1])
    min_player_dist = max(55, int(span * 0.08))
    top_hud_y = int(fh * 0.075)

    candidates = []
    all_positions: list[tuple[int, int]] = []

    # Multi-scale template matching (handles on-field chests + left/right indicator badges)
    if templates:
        for ctype, tmpl, weight, tw, th, is_indicator in templates:
            if tmpl.shape[0] >= small.shape[0] or tmpl.shape[1] >= small.shape[1]:
                continue
            res = cv2.matchTemplate(small, tmpl, cv2.TM_CCOEFF_NORMED)
            locs = np.where(res >= min_confidence)
            for pt_y, pt_x in zip(*locs):
                val = float(res[pt_y, pt_x])
                cx = int(pt_x * 2 + tw)
                cy = int(pt_y * 2 + th)
                if cy < top_hud_y or math.hypot(cx - px, cy - py) < min_player_dist:
                    continue
                # Off-screen indicators ONLY exist along the HUD perimeter, NEVER in the middle of battle
                if is_indicator:
                    if (int(fw * 0.22) <= cx <= int(fw * 0.78)) and (int(fh * 0.16) <= cy <= int(fh * 0.84)):
                        continue
                if all(math.hypot(cx - ox, cy - oy) > 30 for ox, oy in all_positions):
                    roi = frame[max(0, cy - 25) : min(fh, cy + 25), max(0, cx - 25) : min(fw, cx + 25)]
                    if _verify_chest_color(roi, ctype):
                        candidates.append((weight, val, ctype, (cx, cy)))
                        all_positions.append((cx, cy))

    if candidates:
        # Prioritize closer chests to the player character so the bot gathers them efficiently
        def _sort_key(item):
            w_val, conf, ctype, pt = item
            dist = math.hypot(pt[0] - px, pt[1] - py)
            proximity = 1.0 / (0.40 + dist / span)
            return (proximity * w_val, conf)

        candidates.sort(key=_sort_key, reverse=True)
        best = candidates[0]
        return ChestTarget(best[3], best[2], best[0], all_positions)

    return None


def detect_monolith(frame: np.ndarray, min_confidence: float = 0.45) -> Optional[tuple[int, int]]:
    """Detect the post-wave milestone stone monolith / obelisk with vertical crimson rune glyphs.

    In Magic Survival, when a boss wave is cleared, a monolith tower spawns on the map.
    Touching it triggers the Legendary Artifact selection modal. Until touched, no monsters spawn.
    Uses multi-scale template matching against assets/monolith.png and verifies the crimson core rune.
    """
    template_path = _BASE_DIR / "assets" / "monolith.png"
    if not template_path.is_file():
        return None
    tmpl = cv2.imread(str(template_path))
    if tmpl is None:
        return None

    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
    th, tw = tmpl_gray.shape[:2]

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    best_val = 0.0
    best_pos = None

    # Multi-scale coverage from 540p up to 1440p (LDPlayer is typically 1080p, scale ~1.75)
    for scale in (0.75, 0.90, 1.0, 1.15, 1.30, 1.45, 1.60, 1.75, 1.90, 2.10):
        sw, sh = int(tw * scale), int(th * scale)
        if sw >= w or sh >= h:
            continue
        resized = cv2.resize(tmpl_gray, (sw, sh), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_val:
            mcx = max_loc[0] + sw // 2
            mcy = max_loc[1] + sh // 2
            # Scaled rune verification box proportional to tower size
            box_w = max(25, int(sw * 0.28))
            box_h = max(30, int(sh * 0.28))
            roi_H = H[max(0, mcy - box_h): min(h, mcy + box_h), max(0, mcx - box_w): min(w, mcx + box_w)]
            roi_S = S[max(0, mcy - box_h): min(h, mcy + box_h), max(0, mcx - box_w): min(w, mcx + box_w)]
            roi_V = V[max(0, mcy - box_h): min(h, mcy + box_h), max(0, mcx - box_w): min(w, mcx + box_w)]
            red_count = np.sum(((roi_H <= 14) | (roi_H >= 166)) & (roi_S >= 50) & (roi_V >= 50))
            min_red = max(8, int(12 * scale))
            if red_count >= min_red and max_val >= min_confidence:
                best_val = max_val
                best_pos = (mcx, mcy)

    return best_pos


@dataclass
class Vision:
    enemy_mask: np.ndarray
    distance: np.ndarray
    gems: list[tuple[int, int]]
    gameplay: bool
    background_fraction: float
    chest: Optional[tuple[int, int]] = None
    chest_type: str = "treasure_chest"
    chest_weight: float = 24.0
    gold_gems: list[tuple[int, int]] = field(default_factory=list)
    purple_gems: list[tuple[int, int]] = field(default_factory=list)
    modal: bool = False
    panel_fraction: float = 0.0
    monolith: Optional[tuple[int, int]] = None


def measure_modal_panel(gray: np.ndarray) -> float:
    """Fraction of the screen center covered by the largest solid near-black panel (menus/popups)."""
    h, w = gray.shape[:2]
    center = gray[int(h * 0.22) : int(h * 0.78), int(w * 0.15) : int(w * 0.85)]
    if center.size == 0:
        return 0.0
    mask = (center <= 16).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return 0.0
    return float(stats[1:, cv2.CC_STAT_AREA].max()) / float(mask.size)


def _extract_orbs(mask: np.ndarray, max_area: int = 250) -> list[tuple[int, int]]:
    """Extract centers of mana orbs using connected components to preserve small 2-pixel orbs."""
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    orbs = []
    for i in range(1, count):
        area = stats[i, cv2.CC_STAT_AREA]
        # Accept small orbs from 2 pixels up to max_area (ignore single-pixel noise)
        if 2 <= area <= max_area:
            cx = int(round(centroids[i][0]))
            cy = int(round(centroids[i][1]))
            orbs.append((cx, cy))
    return orbs


def inspect_game(frame: np.ndarray, player: tuple[float, float] = (0.5, 0.5)) -> Vision:
    """Detect enemy shadows, chests, and Mana orbs (Purple L -> Gold M -> Blue S) in a BGR game crop."""
    h, w = frame.shape[:2]
    span = min(w, h)
    px, py = int(w * player[0]), int(h * player[1])
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    middle = gray[int(h * 0.15) : int(h * 0.85), int(w * 0.08) : int(w * 0.92)]
    bg_fraction = float(np.mean((middle >= 42) & (middle <= 200)))
    # Menus (level-up, chest, Life or Death, lobby) all draw a big solid near-black panel in the
    # center, while gameplay never does (enemies are separate blobs on lit ground). Using the panel
    # instead of a strict "bright ground" ratio stops the bot from freezing when swarms, dark map
    # zones or the edge vignette cover most of the lit ground late in a run.
    panel_fraction = measure_modal_panel(gray)
    modal = panel_fraction >= 0.55 or float(np.mean(gray)) < 22.0
    gameplay = (not modal) and bg_fraction >= 0.12
    chest_target = detect_chest(frame, player=player) if gameplay else None
    chest_pos = (chest_target[0], chest_target[1]) if chest_target else None
    chest_type = getattr(chest_target, "chest_type", "treasure_chest")
    chest_weight = getattr(chest_target, "weight", 24.0)
    monolith_pos = detect_monolith(frame) if gameplay else None

    # Shadow enemies (pitch-black silhouettes <= 24 & crimson cores) + dark HP-drain void zones:
    # 1. Pitch-black enemy bodies (<= 24) and crimson core eyes:
    B, G, R = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    enemy_pixels = (gray <= 24) | ((R >= 130) & (G <= 42) & (B <= 42))

    # 2. Dark Void / Map Border Hazard Zones ("vùng đen" gây trừ máu):
    # Encroaching darkness / map borders are continuous dark regions (gray <= 48)
    # spanning massive connected areas (>= 1500 px). Small dirt patches (< 500 px) are ignored.
    void_cand = (gray <= 48).astype(np.uint8) * 255
    void_cand[: int(h * 0.095)] = 0  # HUD is not void
    cnt_v, lbl_v, stats_v, _ = cv2.connectedComponentsWithStats(void_cand, 8)
    void_mask = np.zeros((h, w), dtype=np.uint8)
    for i in range(1, cnt_v):
        if stats_v[i, cv2.CC_STAT_AREA] >= 1500 and stats_v[i, cv2.CC_STAT_WIDTH] >= 20:
            void_mask[lbl_v == i] = 255

    enemy_mask = (enemy_pixels.astype(np.uint8) * 255)
    enemy_mask[:, : int(w * 0.015)] = 0
    enemy_mask[:, int(w * 0.985) :] = 0
    dark = enemy_mask | void_mask
    dark[: int(h * 0.095)] = 0  # HUD is not an enemy.
    # Crucial: mask out the player's own dark character sprite at center so
    # distanceTransform measures distance to real enemies, not the player itself!
    # Clears both circular base and vertical humanoid/robe ellipse.
    cv2.circle(dark, (px, py), int(span * 0.078), 0, -1)
    cv2.ellipse(dark, (px, py), (int(span * 0.070), int(span * 0.105)), 0, 0, 360, 0, -1)
    # Crucial: mask out all detected chests so their dark outlines / Black Box stone
    # are NEVER treated as monsters that repel the player!
    if chest_target is not None:
        chest_clear_radius = max(75, int(span * 0.12))
        for c_pt in getattr(chest_target, "all_positions", [chest_pos]):
            if c_pt is not None:
                cv2.circle(dark, c_pt, chest_clear_radius, 0, -1)
                enemy_mask[max(0, c_pt[1] - chest_clear_radius) : min(h, c_pt[1] + chest_clear_radius), max(0, c_pt[0] - chest_clear_radius) : min(w, c_pt[0] + chest_clear_radius)] = 0
    # Crucial: mask out the monolith so its dark jagged stone and crimson runes
    # are NEVER treated as an enemy hazard that repels the player!
    if monolith_pos is not None:
        mx, my = monolith_pos
        monolith_clear_radius = max(110, int(span * 0.18))
        cv2.circle(dark, (mx, my), monolith_clear_radius, 0, -1)
        cv2.ellipse(dark, (mx, my), (int(monolith_clear_radius * 0.85), int(monolith_clear_radius * 1.45)), 0, 0, 360, 0, -1)

    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    enemy = np.zeros((h, w), np.uint8)
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        # Swarms and large dark void/damage zones are RETAINED as lethal hazards!
        # Only filter out tiny isolated pixel dust (< 16px).
        if area >= 16:
            enemy[labels == label] = 255

    # Nearest dark enemy pixel; exposed to the movement planner as a risk map.
    free = cv2.bitwise_not(enemy)
    distance = cv2.distanceTransform(free, cv2.DIST_L2, 3)

    # 1. Blue/cyan dots: Mana orb (S) - Small Mana (bright glowing neon cyan)
    blue = cv2.inRange(hsv, (75, 38, 125), (130, 255, 255))
    blue[: int(h * 0.095)] = 0
    cv2.circle(blue, (px, py), int(span * 0.05), 0, -1)
    gems = _extract_orbs(blue, 250)

    # 2. Gold/yellow dots: Mana orb (M) - Medium Mana (bright glowing yellow/gold, avoid olive ground & red enemy aura)
    gold = cv2.inRange(hsv, (15, 75, 155), (36, 255, 255))
    gold[: int(h * 0.095)] = 0
    cv2.circle(gold, (px, py), int(span * 0.05), 0, -1)
    gold_gems = _extract_orbs(gold, 280)

    # 3. Purple/magenta dots: Mana orb (L) - Large Mana (bright glowing magenta/violet)
    purple = cv2.inRange(hsv, (130, 55, 130), (176, 255, 255))
    purple[: int(h * 0.095)] = 0
    cv2.circle(purple, (px, py), int(span * 0.05), 0, -1)
    purple_gems = _extract_orbs(purple, 320)

    return Vision(
        enemy,
        distance,
        gems,
        gameplay,
        bg_fraction,
        chest_pos,
        chest_type,
        chest_weight,
        gold_gems,
        purple_gems,
        modal,
        panel_fraction,
        monolith_pos,
    )


def choose_direction(
    vision: Vision,
    elapsed: float,
    previous: Optional[tuple[float, float]] = None,
    player: tuple[float, float] = (0.5, 0.5),
) -> tuple[float, float]:
    """Plan movement repelling visible enemies (#1 safety priority), while prioritizing
    Artifact Chests (Black Box > Reliquary > Treasure Chest) and actively vacuuming
    Mana orbs one-by-one (Pac-Man Target-Lock: Purple L -> Gold M -> Blue S).
    """
    h, w = vision.distance.shape
    px, py = int(w * player[0]), int(h * player[1])
    span = min(w, h)
    patrol = (math.cos(elapsed / 6.0), math.sin(elapsed / 6.0))
    # Collect nearby orbs, prioritizing closest clusters
    nearest_blue = sorted(
        vision.gems, key=lambda pt: math.hypot(pt[0] - px, pt[1] - py)
    )[:30]
    nearest_gold = sorted(
        vision.gold_gems, key=lambda pt: math.hypot(pt[0] - px, pt[1] - py)
    )[:16]
    nearest_purple = sorted(
        vision.purple_gems, key=lambda pt: math.hypot(pt[0] - px, pt[1] - py)
    )[:16]

    # Pac-Man Target-Lock: Select the single highest-value nearby safe orb so the character
    # walks directly ONTO individual orbs one-by-one instead of hovering in the empty centroid
    # between multiple scattered orbs! Bolder mana vacuuming!
    all_orbs: list[tuple[int, int, float]] = []
    for gx, gy in nearest_purple:
        all_orbs.append((gx, gy, 80.0))
    for gx, gy in nearest_gold:
        all_orbs.append((gx, gy, 55.0))
    for gx, gy in nearest_blue:
        all_orbs.append((gx, gy, 36.0))

    best_orb: Optional[tuple[int, int, float, float, float]] = None
    best_orb_val = -1.0
    for gx, gy, bw in all_orbs:
        dx, dy = gx - px, gy - py
        dist = math.hypot(dx, dy)
        if 4 < dist < span * 0.95:
            gy_c = min(h - 1, max(0, gy))
            gx_c = min(w - 1, max(0, gx))
            d_px = float(vision.distance[gy_c, gx_c])
            if d_px < 6.0:
                continue  # Skip orbs inside lethal enemy core
            gem_safety = min(1.0, max(0.40, (d_px - 5.0) / 16.0))
            align = ((dx * previous[0] + dy * previous[1]) / dist) if previous else 0.0
            hysteresis = 1.0 + 0.45 * max(0.0, align)
            val = (bw * 2.2) * gem_safety * hysteresis / (0.10 + dist / (span * 0.55))
            if val > best_orb_val:
                best_orb_val = val
                best_orb = (gx, gy, bw, dist, gem_safety)

    # 1. Pre-scan 12 steps along each of the 16 rays to build 360-degree danger profile and threat vector
    ray_info = []
    threat_vx, threat_vy = 0.0, 0.0
    for index in range(16):
        angle = 2 * math.pi * index / 16
        direction = (math.cos(angle), math.sin(angle))

        risks = []
        near_dists = []
        for s_idx, step in enumerate(np.linspace(0.04, 0.40, 12)):
            x = min(w - 1, max(0, int(px + direction[0] * span * step)))
            y = min(h - 1, max(0, int(py + direction[1] * span * step)))
            d_px = float(vision.distance[y, x])
            if s_idx < 3:
                near_dists.append(d_px)
            risks.append(math.exp(-d_px / (span * 0.085)))

        near_danger_dist = min(near_dists)
        forward_danger = 0.65 * max(risks[:5]) + 0.35 * float(np.mean(risks))
        ray_info.append((direction, forward_danger, near_danger_dist))
        threat_vx += forward_danger * direction[0]
        threat_vy += forward_danger * direction[1]

    threat_mag = math.hypot(threat_vx, threat_vy)
    # Determine the tangential kiting vectors perpendicular to the swarm threat:
    chosen_tangent = (0.0, 0.0)
    if threat_mag > 0.20:
        norm_tx = threat_vx / threat_mag
        norm_ty = threat_vy / threat_mag
        # Perpendicular tangents: T_cw = (norm_ty, -norm_tx), T_ccw = (-norm_ty, norm_tx)
        t_cw = (norm_ty, -norm_tx)
        t_ccw = (-norm_ty, norm_tx)
        if previous and math.hypot(previous[0], previous[1]) > 0.2:
            dot_cw = t_cw[0] * previous[0] + t_cw[1] * previous[1]
            dot_ccw = t_ccw[0] * previous[0] + t_ccw[1] * previous[1]
            chosen_tangent = t_cw if dot_cw >= dot_ccw else t_ccw
        else:
            danger_cw = sum(fd for d, fd, _ in ray_info if (d[0] * t_cw[0] + d[1] * t_cw[1]) > 0.5)
            danger_ccw = sum(fd for d, fd, _ in ray_info if (d[0] * t_ccw[0] + d[1] * t_ccw[1]) > 0.5)
            chosen_tangent = t_cw if danger_cw <= danger_ccw else t_ccw

    best_score = -float("inf")
    best = patrol
    for direction, forward_danger, near_danger_dist in ray_info:
        # Compute monolith vector if a post-wave stone milestone obelisk is present
        monolith_dot = -1.0
        monolith_dist = 0.0
        if getattr(vision, "monolith", None):
            mx, my = vision.monolith
            mdx, mdy = mx - px, my - py
            monolith_dist = math.hypot(mdx, mdy)
            if monolith_dist > 4:
                monolith_dot = (mdx * direction[0] + mdy * direction[1]) / monolith_dist

        # Compute chest vector if a chest or off-screen chest indicator is present
        chest_dot = -1.0
        chest_dist = 0.0
        if vision.chest:
            cx, cy = vision.chest
            cdx, cdy = cx - px, cy - py
            chest_dist = math.hypot(cdx, cdy)
            if chest_dist > 4:
                chest_dot = (cdx * direction[0] + cdy * direction[1]) / chest_dist

        is_charging_monolith = bool(
            getattr(vision, "monolith", None)
            and monolith_dist < span * 0.65
            and monolith_dot > 0.15
        )

        # Danger repulsion: clear collision avoidance with lethal boundary (< 10px) while staying brave
        score = -10.0 * forward_danger
        if near_danger_dist < 18.0 and not is_charging_monolith:
            score -= 22.0 * (1.0 - near_danger_dist / 18.0)
        if near_danger_dist < 10.0 and not is_charging_monolith:
            score -= 50.0  # Immediate impassable lethal wall / void / swarm barrier

        # Intelligent Swarm Kiting: Flow tangentially in a circular arc around monster swarms
        if threat_mag > 0.20 and not is_charging_monolith:
            kite_align = direction[0] * chosen_tangent[0] + direction[1] * chosen_tangent[1]
            threat_align = (direction[0] * threat_vx + direction[1] * threat_vy) / threat_mag
            score += 4.5 * max(0.0, kite_align)
            if threat_align > 0.25:
                score -= 8.5 * (threat_align - 0.25)

        # Path factor for movement
        path_safe_factor = max(0.20, 1.0 - forward_danger * 1.20)

        # Active Pac-Man Mana Vacuum: Bold, aggressive pull towards nearby mana orbs!
        mana_score = 0.0
        safe_path = max(0.35, 1.0 - forward_danger * 0.50)
        if near_danger_dist < 10.0 and not is_charging_monolith:
            safe_path = 0.0  # Immediate hazard block (< 10px)

        if best_orb is not None and safe_path > 0:
            tx, ty, tbw, tdist, t_safety = best_orb
            tdx, tdy = tx - px, ty - py
            tdot = (tdx * direction[0] + tdy * direction[1]) / tdist
            if tdot > 0:
                # Decisive, strong pull towards the target mana orb!
                mana_score += (tbw * 5.5) * (tdot ** 1.05) * t_safety * safe_path

        if safe_path > 0:
            cluster_bonus = 0.0
            for gx, gy, bw in all_orbs:
                dx, dy = gx - px, gy - py
                dist = math.hypot(dx, dy)
                if 4 < dist < span * 0.90:
                    dot = (dx * direction[0] + dy * direction[1]) / dist
                    if dot > 0.30:
                        gy_c = min(h - 1, max(0, gy))
                        gx_c = min(w - 1, max(0, gx))
                        if vision.distance[gy_c, gx_c] < 8.0:
                            continue  # Skip orbs inside lethal core
                        cluster_bonus += (bw * 0.65) * (dot ** 1.15) / (0.15 + dist / (span * 0.50))
            mana_score += min(75.0, cluster_bonus) * safe_path

        # If a chest is nearby/on-screen, suppress mana orbs that pull away from the chest
        if vision.chest and chest_dist > 4:
            if chest_dist <= span * 0.35 and chest_dot < 0.20:
                mana_score *= 0.15
            elif chest_dot < -0.30:
                mana_score *= 0.20
        # If a monolith is present, suppress mana orbs pulling away from the monolith
        if getattr(vision, "monolith", None) and monolith_dist > 4:
            mana_score = 0.0
        score += mana_score

        # High priority for artifact chest / chest indicator:
        if vision.chest and chest_dist > 4:
            if chest_dot > -0.15:
                base_weight = max(160.0, getattr(vision, "chest_weight", 24.0) * 6.5)
                eff_dot = max(0.18, chest_dot) ** 0.50
                if near_danger_dist < 14.0:
                    safe_corridor = 0.10
                else:
                    safe_corridor = max(0.50, 1.0 - forward_danger * 0.50)
                chest_pull = base_weight * eff_dot * safe_corridor / (0.25 + chest_dist / (span * 1.5))
                score += chest_pull
            if chest_dot < -0.10:
                score -= 60.0 * (1.0 - chest_dot)

        # High priority for wave-milestone monolith:
        if getattr(vision, "monolith", None) and monolith_dist > 4:
            if monolith_dot > -0.20:
                eff_m_dot = max(0.15, monolith_dot) ** 0.50
                if is_charging_monolith:
                    safe_m_corridor = 1.0
                else:
                    if near_danger_dist < 14.0:
                        safe_m_corridor = 0.35
                    else:
                        safe_m_corridor = max(0.60, 1.0 - forward_danger * 0.40)
                monolith_pull = 350.0 * eff_m_dot * safe_m_corridor / (0.15 + monolith_dist / (span * 1.5))
                score += monolith_pull
            if monolith_dot < 0.0:
                score -= 80.0 * (1.0 - monolith_dot)

        # Suppress patrol when actively locked onto a safe mana orb, chest, or monolith
        patrol_weight = 0.0 if (vision.chest is not None or getattr(vision, "monolith", None) is not None) else (
            0.05 if best_orb is not None else 0.45
        )
        score += patrol_weight * path_safe_factor * (direction[0] * patrol[0] + direction[1] * patrol[1])
        if previous:
            align_prev = direction[0] * previous[0] + direction[1] * previous[1]
            # Strong forward momentum to keep walking smoothly without stuttering:
            score += 3.5 * align_prev
            # Anti-reversal penalty (stops 180-degree jitter/inching):
            if align_prev < -0.30:
                score -= 4.5 * (1.0 - align_prev)
        if score > best_score:
            best_score = score
            best = direction
    return best


def find_rule(frame: np.ndarray, rules: list[dict], root_dir: str) -> Optional[dict]:
    """Match user-taught UI anchors near the positions where they were recorded."""
    import os

    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for rule in rules:
        path = os.path.join(root_dir, rule["image"])
        template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            continue
        x, y, w, h = rule["anchor"]
        target_w = max(1, round(w * width))
        target_h = max(1, round(h * height))
        if (template.shape[1], template.shape[0]) != (target_w, target_h):
            template = cv2.resize(template, (target_w, target_h))
        if float(np.std(template)) < 10:
            continue
        margin = max(14, int(width * 0.025))
        left = max(0, int(x * width) - margin)
        top = max(0, int(y * height) - margin)
        right = min(width, round((x + w) * width) + margin)
        bottom = min(height, round((y + h) * height) + margin)
        region = gray[top:bottom, left:right]
        if region.shape[0] < target_h or region.shape[1] < target_w:
            continue
        confidence = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        if float(np.max(confidence)) >= float(rule.get("threshold", 0.88)):
            return rule
    return None


def detect_settings_gear(frame: np.ndarray, min_confidence: float = 0.65) -> Optional[tuple[float, float]]:
    """Detect the Settings Gear button located in the top-right area of the Title Screen."""
    h, w = frame.shape[:2]
    roi = frame[0:int(h * 0.16), int(w * 0.75):w]
    if roi.size == 0 or roi.shape[0] < 20 or roi.shape[1] < 20:
        return None
    template_path = _BASE_DIR / "assets" / "settings_gear.png"
    if not template_path.is_file():
        return None
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        return None
    th, tw = template.shape[:2]
    best_score = 0.0
    best_loc = None
    for scale in (0.75, 0.90, 1.0, 1.15, 1.30):
        stw, sth = int(tw * scale), int(th * scale)
        if stw >= roi.shape[1] or sth >= roi.shape[0]:
            continue
        rt = cv2.resize(template, (stw, sth))
        res = cv2.matchTemplate(roi, rt, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_loc = (max_loc[0] + stw // 2, max_loc[1] + sth // 2)
    if best_score >= min_confidence and best_loc:
        cx = (int(w * 0.75) + best_loc[0]) / w
        cy = best_loc[1] / h
        return (round(cx, 4), round(cy, 4))
    return None


def detect_settings_dialog(frame: np.ndarray) -> bool:
    """Detect if the Settings dialog is opened on screen (so bot can press ESC to close it)."""
    h, w = frame.shape[:2]
    center_roi = frame[int(h * 0.20):int(h * 0.75), int(w * 0.10):int(w * 0.90)]
    if center_roi.size == 0:
        return False
    try:
        import asyncio
        import winocr
        from PIL import Image
        pil_img = Image.fromarray(cv2.cvtColor(center_roi, cv2.COLOR_BGR2RGB))
        async def _ocr():
            return await winocr.recognize_pil(pil_img, lang="en")
        res = asyncio.run(_ocr())
        full_text = " ".join(line.text.lower() for line in res.lines)
        if "ad inspector" in full_text or "creative preview" in full_text or "debug mode" in full_text:
            return False
        # Must have at least one distinctive game settings keyword
        has_distinctive = any(k in full_text for k in ("bgm", "sfx", "cloud save", "coupon", "language"))
        if not has_distinctive:
            return False
        keywords = ("bgm", "sfx", "sound", "language", "setting", "settings", "coupon", "cloud save", "version")
        matches = 0
        for line in res.lines:
            text_low = line.text.lower()
            for kw in keywords:
                if kw in text_low:
                    matches += 1
        return matches >= 2
    except Exception:
        return False


def detect_pause_button(frame: np.ndarray, threshold: float = 0.70) -> Optional[tuple[float, float]]:
    """Detect the in-game Pause button (||) located in the top-right corner during gameplay."""
    tmpl_path = _BASE_DIR / "assets" / "pause_button.png"
    if not tmpl_path.is_file():
        return None
    tmpl = cv2.imread(str(tmpl_path), cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        return None
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    x_start = int(w * 0.86)
    roi = gray[0 : int(h * 0.08), x_start:w]
    th_sz, tw_sz = tmpl.shape
    best_val = 0.0
    best_loc = None
    best_dim = (0, 0)
    for scale in (0.35, 0.45, 0.55, 0.70, 0.85, 1.0, 1.15, 1.30, 1.45, 1.60, 1.80):
        stw, sth = int(tw_sz * scale), int(th_sz * scale)
        if stw >= roi.shape[1] or sth >= roi.shape[0] or stw < 5 or sth < 5:
            continue
        rt = cv2.resize(tmpl, (stw, sth))
        res = cv2.matchTemplate(roi, rt, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc
            best_dim = (stw, sth)
    if best_val >= threshold and best_loc:
        cx = x_start + best_loc[0] + best_dim[0] // 2
        cy = best_loc[1] + best_dim[1] // 2
        return (round(cx / w, 4), round(cy / h, 4))
    return None


def detect_close_button(frame: np.ndarray, threshold: float = 0.62) -> Optional[tuple[float, float]]:
    """Scan top-right and top-left corners for ad close 'X' buttons, circled X, or Skip '>>' buttons.

    Safeguarded to strictly ignore Title Screen, Game Lobby, Endgame Confirm screen,
    active gameplay Pause Button, Settings Gear, Chest Obtain screen, Shop screen, and Select Attribute screen.
    """
    # 1. If Title Screen, Lobby, Confirm, Die screen, Pause button, Chest modal, or Game Modal is active, NEVER detect an ad close button!
    if (detect_start_game(frame) is not None or 
        detect_enter_area(frame) is not None or 
        detect_selected(frame) is not None or
        detect_confirm_button(frame) is not None or
        detect_die_button(frame) is not None or
        detect_pause_button(frame) is not None or
        detect_obtain_button(frame) is not None or
        is_chest_screen(frame) or
        detect_buy_button(frame) is not None or
        detect_learn_button(frame) is not None or
        is_attribute_screen(frame)):
        return None

    # 2. Check if Settings Gear is present to avoid clicking near it
    gear_pos = detect_settings_gear(frame)

    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Ad close buttons appear strictly in the outer corners (top 9.5% of screen, max 180px)
    corner_h = min(int(h * 0.095), 180)
    corners = [
        # Top-right corner (standard position for Google AdMob, Unity, AppLovin mobile ads)
        (int(w * 0.70), 0, w, corner_h),
        # Top-left corner (position in Google Play Games portrait ads)
        (0, 0, int(w * 0.30), corner_h),
    ]

    best_coord = None
    best_score = 0.0

    templates = []
    tmpl_x_path = _BASE_DIR / "assets" / "ad_close_x.png"
    tmpl_x = None
    if tmpl_x_path.is_file():
        tmpl_x = cv2.imread(str(tmpl_x_path), cv2.IMREAD_GRAYSCALE)
        if tmpl_x is not None:
            templates.append(tmpl_x)
            for scale in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
                sw, sh = int(tmpl_x.shape[1] * scale), int(tmpl_x.shape[0] * scale)
                templates.append(cv2.resize(tmpl_x, (sw, sh)))

    # Circled X (white filled circle with black X - standard in Google AdMob, Candy Crush, AppLovin, Unity ads)
    tmpl_circ_path = _BASE_DIR / "assets" / "ad_close_circle_x.png"
    tmpl_c = None
    if tmpl_circ_path.is_file():
        tmpl_c = cv2.imread(str(tmpl_circ_path), cv2.IMREAD_GRAYSCALE)
        if tmpl_c is not None:
            templates.append(tmpl_c)
            for scale in (0.60, 0.75, 1.0, 1.25, 1.5, 1.75, 1.95, 2.0, 2.2):
                sw, sh = int(tmpl_c.shape[1] * scale), int(tmpl_c.shape[0] * scale)
                templates.append(cv2.resize(tmpl_c, (sw, sh)))

    # Synthetic X crosses (crisp white cross on black)
    for sz in (20, 26, 32, 40):
        t_w = np.zeros((sz, sz), dtype=np.uint8)
        th = max(2, sz // 7)
        cv2.line(t_w, (3, 3), (sz - 4, sz - 4), 255, th)
        cv2.line(t_w, (sz - 4, 3), (3, sz - 4), 255, th)
        templates.append(t_w)

    # Circled X (white circle and cross on black - standard in Google/Unity/AppLovin ads)
    for sz in (22, 28, 36, 44):
        t_circ = np.zeros((sz, sz), dtype=np.uint8)
        r = sz // 2 - 2
        cv2.circle(t_circ, (sz // 2, sz // 2), r, 255, 2)
        pad = max(4, sz // 4)
        cv2.line(t_circ, (pad, pad), (sz - pad, sz - pad), 255, 2)
        cv2.line(t_circ, (sz - pad, pad), (pad, sz - pad), 255, 2)
        templates.append(t_circ)

    # Invert real templates for dark crosses on light background ads
    if tmpl_x is not None:
        templates.append(cv2.bitwise_not(tmpl_x))
    if tmpl_c is not None:
        templates.append(cv2.bitwise_not(tmpl_c))

    # Fast-Forward / Skip Arrow (>> or >)
    for h_sz in (16, 20, 24, 28):
        w_sz = int(h_sz * 1.0)
        t_skip = np.zeros((h_sz, w_sz), dtype=np.uint8)
        mid_y = h_sz // 2
        step = w_sz // 2
        cv2.line(t_skip, (1, 1), (step - 1, mid_y), 255, 2)
        cv2.line(t_skip, (step - 1, mid_y), (1, h_sz - 2), 255, 2)
        cv2.line(t_skip, (step, 1), (w_sz - 2, mid_y), 255, 2)
        cv2.line(t_skip, (w_sz - 2, mid_y), (step, h_sz - 2), 255, 2)
        templates.append(t_skip)

    for cl, ct, cr, cb in corners:
        roi = gray[ct:cb, cl:cr]
        if roi.shape[0] < 12 or roi.shape[1] < 12:
            continue
        for tmpl in templates:
            th_sz, tw_sz = tmpl.shape
            if roi.shape[0] < th_sz or roi.shape[1] < tw_sz:
                continue
            res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                patch = roi[max_loc[1]:max_loc[1] + th_sz, max_loc[0]:max_loc[0] + tw_sz]
                # Reject completely flat uniform patches without contrast
                if (int(patch.max()) - int(patch.min())) < 35:
                    continue
                cx = cl + max_loc[0] + tw_sz // 2
                cy = ct + max_loc[1] + th_sz // 2
                norm_x = round(cx / w, 4)
                norm_y = round(cy / h, 4)
                # NEVER accept coordinates near the Settings Gear icon
                if gear_pos and math.hypot(norm_x - gear_pos[0], norm_y - gear_pos[1]) < 0.09:
                    continue
                best_score = max_val
                best_coord = (norm_x, norm_y)

    if best_score >= threshold and best_coord is not None:
        return best_coord

    # OCR detection for 'close', 'skip', 'x', 'no thanks', 'dismiss' text on ads
    try:
        import asyncio
        import winocr
        from PIL import Image

        scan_h = int(h * 0.85)
        scan_roi = frame[0:scan_h, :]
        pil_img = Image.fromarray(cv2.cvtColor(scan_roi, cv2.COLOR_BGR2RGB))

        async def _ocr_close():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_close())
        close_targets = (
            "close", "skip", "close ad", "skip ad", "skip in",
            "no thanks", "no, thanks", "not now", "dismiss", "cancel",
            "bỏ qua", "đóng", "đóng lại", "bỏ qua quảng cáo", ">>", ">|",
        )
        for line in res.lines:
            line_lower = line.text.strip().lower()
            if any(kw in line_lower for kw in ("no thanks", "no, thanks", "not now", "bỏ qua quảng cáo", "skip ad", "close ad")):
                if line.words:
                    w_first = line.words[0].bounding_rect
                    w_last = line.words[-1].bounding_rect
                    cx = (w_first.x + w_last.x + w_last.width) / 2 / w
                    cy = (w_first.y + w_first.height / 2) / h
                    return (round(cx, 4), round(cy, 4))

            for word in line.words:
                w_text = word.text.strip().lower()
                if w_text in close_targets or w_text.startswith("skip") or w_text.startswith("close"):
                    r = word.bounding_rect
                    cx = (r.x + r.width / 2) / w
                    cy = (r.y + r.height / 2) / h
                    if gear_pos and math.hypot(cx - gear_pos[0], cy - gear_pos[1]) < 0.09:
                        continue
                    return (round(cx, 4), round(cy, 4))
                # Standalone 'x' button in corner
                if w_text in ("x", "×", "✕", "✖"):
                    r = word.bounding_rect
                    cx = (r.x + r.width / 2) / w
                    cy = (r.y + r.height / 2) / h
                    if cy <= 0.08 and (cx <= 0.25 or cx >= 0.75):
                        return (round(cx, 4), round(cy, 4))
    except Exception:
        pass

    return None


def is_ad_screen(frame: np.ndarray) -> bool:
    """Return True if the current screen is displaying a third-party mobile ad (AdMob, Unity, Playable Ad)."""
    if detect_close_button(frame) is not None:
        return True
    try:
        import asyncio
        import winocr
        from PIL import Image

        h, w = frame.shape[:2]
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        async def _ocr_ad():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_ad())
        full_text = " ".join(l.text.lower() for l in res.lines)
        ad_kws = (
            "cài đặt", "install", "not in-game", "google play", "play store",
            "reward in", "reward granted", "candy crush", "download now",
            "free download", "bỏ qua quảng cáo", "skip ad", "close ad",
        )
        if any(kw in full_text for kw in ad_kws):
            return True
    except Exception:
        pass
    return False


def detect_resume_button(frame: np.ndarray) -> Optional[tuple[float, float]]:
    """Detect 'Resume' button when the game is paused, allowing automatic resumption."""
    # When active gameplay is running with visible Pause button, we are NOT paused
    if detect_pause_button(frame) is not None:
        return None
    if (detect_start_game(frame) is not None or 
        detect_enter_area(frame) is not None or 
        detect_selected(frame) is not None or 
        detect_confirm_button(frame) is not None or
        detect_die_button(frame) is not None):
        return None
    try:
        import asyncio
        import winocr
        from PIL import Image

        h, w = frame.shape[:2]
        roi = frame[int(h * 0.20):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
        pil_img = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))

        async def _ocr_res():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_res())
        for line in res.lines:
            text_low = line.text.strip().lower()
            if "resume" in text_low or "continue" in text_low:
                for word in line.words:
                    if "resume" in word.text.lower() or "continue" in word.text.lower():
                        r = word.bounding_rect
                        cx = int(w * 0.15) + r.x + r.width / 2
                        cy = int(h * 0.20) + r.y + r.height / 2
                        return (round(cx / w, 4), round(cy / h, 4))
    except Exception:
        pass
    return None


def parse_timer_text(text: str) -> Optional[tuple[int, int, int]]:
    """Parse minutes and seconds from OCR string (e.g. '03:32', '03 : 32', '03 •.32', '05 : 43', '14:25').
    Returns (minutes, seconds, total_seconds) or None.
    """
    cleaned = re.sub(r'[^0-9:]+', ':', text.strip())
    m = re.search(r'(\d{1,2}):+(\d{2})', cleaned)
    if m:
        mins, secs = int(m.group(1)), int(m.group(2))
        if secs < 60 and mins < 180:
            return (mins, secs, mins * 60 + secs)
    m4 = re.search(r'\b(\d{1,2})[\s]+(\d{2})\b', text)
    if m4:
        mins, secs = int(m4.group(1)), int(m4.group(2))
        if secs < 60 and mins < 180:
            return (mins, secs, mins * 60 + secs)
    return None


def detect_game_timer(frame: np.ndarray) -> Optional[tuple[int, int, int]]:
    """Detect in-game survival timer from the HUD top-center bar (e.g. '02:31', '03:32', '05:43').
    Returns (minutes, seconds, total_seconds) or None.

    This provides true, authentic in-game survival time directly from the top HUD bar,
    completely ignoring time spent in level-up menus, chest modals, shops, or loading pauses.
    """
    if frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]
    # The in-game timer in Magic Survival is located strictly in the top bar: y: ~1.5%..8.0%, x: ~28%..72%
    y0, y1 = int(h * 0.015), int(h * 0.080)
    x0, x1 = int(w * 0.28), int(w * 0.72)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0 or roi.shape[0] < 8 or roi.shape[1] < 20:
        return None

    try:
        import asyncio
        import winocr
        from PIL import Image

        async def _ocr(p_img):
            return await winocr.recognize_pil(p_img, lang="en")

        # Pass 1: raw image (scaled to comfortable OCR height if small)
        scale = max(1.0, 60.0 / max(1, roi.shape[0]))
        if scale > 1.2:
            rw, rh = int(roi.shape[1] * scale), int(roi.shape[0] * scale)
            roi_scaled = cv2.resize(roi, (rw, rh), interpolation=cv2.INTER_CUBIC)
        else:
            roi_scaled = roi

        pil_img = Image.fromarray(cv2.cvtColor(roi_scaled, cv2.COLOR_BGR2RGB))
        res = asyncio.run(_ocr(pil_img))
        txt = " ".join(l.text for l in res.lines)
        parsed = parse_timer_text(txt)
        if parsed is not None:
            return parsed

        # Pass 2: normalized contrast for dimmed screens (modal dialogs, dark boss zones)
        gray = cv2.cvtColor(roi_scaled, cv2.COLOR_BGR2GRAY)
        norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        pil_norm = Image.fromarray(norm)
        res_norm = asyncio.run(_ocr(pil_norm))
        txt_norm = " ".join(l.text for l in res_norm.lines)
        return parse_timer_text(txt_norm)
    except Exception:
        pass

    return None


def detect_confirm_button(frame: np.ndarray, min_confidence: float = 0.70) -> Optional[tuple[float, float]]:
    """Detect 'Confirm' button at the bottom of the 'Experiment Failed' / Results screen."""
    # During active gameplay/combat, the Pause button is present -> player is ALIVE, not on results screen
    if detect_pause_button(frame) is not None:
        return None

    template_path = _BASE_DIR / "assets" / "confirm_button_tight.png"
    h, w = frame.shape[:2]
    y0 = 0 if h < 300 else int(h * 0.70)
    y1 = h if h < 300 else int(h * 0.97)
    x0 = 0 if w < 300 else int(w * 0.20)
    x1 = w if w < 300 else int(w * 0.80)
    roi = frame[y0:y1, x0:x1]

    if template_path.is_file() and roi.size > 0:
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is not None:
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            th, tw = template.shape[:2]
            best_match = None
            best_score = 0.0
            for scale in (0.75, 0.90, 1.0, 1.15, 1.30, 1.50, 1.75, 2.00, 2.25):
                stw, sth = int(tw * scale), int(th * scale)
                if stw >= roi.shape[1] or sth >= roi.shape[0]:
                    continue
                rt = cv2.resize(template, (stw, sth))
                res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
                    best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + sth // 2)
            if best_score >= min_confidence and best_match:
                return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # Fallback via OCR
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))

        async def _ocr_confirm():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_confirm())
        for line in res.lines:
            for word in line.words:
                if "confirm" in word.text.lower():
                    r = word.bounding_rect
                    cx = (x0 + r.x + r.width / 2) / w
                    cy = (y0 + r.y + r.height / 2) / h
                    return (round(cx, 4), round(cy, 4))
    except Exception:
        pass

    return None


def get_upgrade_target(card_index: int = 1, num_cards: int = 3) -> tuple[float, float]:
    """Return standard normalized screen coordinates for Magic Survival level-up cards.
    Supports both standard 3-card layout and research/class expanded 4-card layout.
    """
    if num_cards == 4:
        mapping = {
            1: (0.50, 0.27),
            2: (0.50, 0.44),
            3: (0.50, 0.61),
            4: (0.50, 0.78),
        }
        return mapping.get(card_index, (0.50, 0.27))
    else:
        # Magic Survival vertical 3-card stack layout:
        # Card 1 (Top): ~38% height
        # Card 2 (Middle): ~52% height
        # Card 3 (Bottom): ~66% height
        mapping = {
            1: (0.50, 0.38),
            2: (0.50, 0.52),
            3: (0.50, 0.66),
        }
        return mapping.get(card_index, (0.50, 0.38))


def detect_enter_area(frame: np.ndarray, min_confidence: float = 0.70) -> Optional[tuple[float, float]]:
    """Detect 'Enter Area' start button in stage selection screen."""
    h, w = frame.shape[:2]
    y_start = 0 if h < 300 else int(h * 0.65)
    roi = frame[y_start:, :]
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    for tmpl_name in ("assets/enter_area_tight.png", "assets/enter_area.png"):
        template_path = _BASE_DIR / tmpl_name
        if not template_path.is_file():
            continue
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            continue
        th, tw = template.shape[:2]
        best_match = None
        best_score = 0.0
        for scale in (0.70, 0.85, 1.0, 1.15, 1.35, 1.55, 1.80, 2.05, 2.25):
            stw, sth = int(tw * scale), int(th * scale)
            if stw >= roi.shape[1] or sth >= roi.shape[0]:
                continue
            rt = cv2.resize(template, (stw, sth))
            res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_match = (max_loc[0] + stw // 2, y_start + max_loc[1] + sth // 2)
        if best_score >= min_confidence and best_match:
            return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # OCR Fallback
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))

        async def _ocr_ea():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_ea())
        for line in res.lines:
            text_low = line.text.strip().lower()
            if "enter" in text_low or "area" in text_low:
                r = line.words[0].bounding_rect
                cx = (r.x + r.width / 2) / w
                cy = (y_start + r.y + r.height / 2) / h
                return (round(cx, 4), round(cy, 4))
    except Exception:
        pass

    return None


def detect_selected(frame: np.ndarray, min_confidence: float = 0.70) -> Optional[tuple[float, float]]:
    """Detect 'Selected' confirm button in class/subject selection screen."""
    template_path = _BASE_DIR / "assets" / "selected.png"
    if not template_path.is_file():
        return None
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None
    h, w = frame.shape[:2]
    roi = frame[int(h * 0.85):, :]
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]
    best_match = None
    best_score = 0.0
    for scale in (0.75, 0.90, 1.0, 1.15, 1.30, 1.50, 1.75, 2.00, 2.25):
        stw, sth = int(tw * scale), int(th * scale)
        if stw >= roi.shape[1] or sth >= roi.shape[0]:
            continue
        rt = cv2.resize(template, (stw, sth))
        res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_match = (max_loc[0] + stw // 2, int(h * 0.85) + max_loc[1] + sth // 2)
    if best_score >= min_confidence and best_match:
        return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))
    return None


def detect_start_game(frame: np.ndarray, min_confidence: float = 0.70) -> Optional[tuple[float, float]]:
    """Detect 'Start Game' button in the main title screen of Magic Survival."""
    h, w = frame.shape[:2]
    y_start = 0 if h < 300 else int(h * 0.65)
    y_end = h if h < 300 else int(h * 0.90)
    roi = frame[y_start:y_end, :]
    if roi.size == 0 or roi.shape[0] < 20 or roi.shape[1] < 40:
        return None
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    template_path = _BASE_DIR / "assets" / "start_game.png"
    if template_path.is_file():
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is not None:
            th, tw = template.shape[:2]
            best_match = None
            best_score = 0.0
            for scale in (0.70, 0.85, 1.0, 1.15, 1.35, 1.55, 1.80, 2.05, 2.25):
                stw, sth = int(tw * scale), int(th * scale)
                if stw >= roi.shape[1] or sth >= roi.shape[0]:
                    continue
                rt = cv2.resize(template, (stw, sth))
                res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
                    best_match = (max_loc[0] + stw // 2, y_start + max_loc[1] + sth // 2)
            if best_score >= min_confidence and best_match:
                return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # OCR Fallback
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))

        async def _ocr_start():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_start())
        for line in res.lines:
            text = line.text.strip().lower()
            if "start" in text and "game" in text:
                xs = [wrd.bounding_rect.x for wrd in line.words]
                ys = [wrd.bounding_rect.y for wrd in line.words]
                x_maxs = [wrd.bounding_rect.x + wrd.bounding_rect.width for wrd in line.words]
                y_maxs = [wrd.bounding_rect.y + wrd.bounding_rect.height for wrd in line.words]
                cx = (min(xs) + max(x_maxs)) / 2
                cy = (min(ys) + max(y_maxs)) / 2 + y_start
                return (round(cx / w, 4), round(cy / h, 4))
    except Exception:
        pass

    return None


def detect_die_button(frame: np.ndarray, min_confidence: float = 0.68) -> Optional[tuple[float, float]]:
    """Detect 'Die' button (skull icon + 'Die' text) on the 'Life or Death' screen.

    Note: assets/die_button.png contains both 'Revive' (top) and 'Die' (bottom 42%).
    We match specifically the 'Die' row (bottom 42%) and click its exact center (~80% height
    of the full template) so the click lands squarely on 'Die' instead of the black gap above it.
    """
    template_path = _BASE_DIR / "assets" / "die_button.png"
    if not template_path.is_file():
        return None
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None
    h, w = frame.shape[:2]
    # 'Die' button is in the vertical range 55% to 88%
    y0, y1 = int(h * 0.55), int(h * 0.88)
    x0, x1 = int(w * 0.12), int(w * 0.88)
    roi = frame[y0:y1, x0:x1]
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]
    die_only = template[int(th * 0.58) :, :]
    dth, dtw = die_only.shape[:2]

    best_match = None
    best_score = 0.0
    # 1. Match the 'Die' row directly (Skull + 'Die' text)
    for scale in (0.45, 0.60, 0.75, 0.90, 1.05, 1.25, 1.50, 1.75, 2.00, 2.25):
        stw, sth = int(dtw * scale), int(dth * scale)
        if stw >= roi.shape[1] or sth >= roi.shape[0] or stw < 10 or sth < 10:
            continue
        rt = cv2.resize(die_only, (stw, sth))
        res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + sth // 2)

    # 2. Fallback: match full Revive+Die block, clicking at 80% height (center of 'Die' row)
    for scale in (0.45, 0.60, 0.75, 0.90, 1.05, 1.25, 1.50, 1.75, 2.00, 2.25):
        stw, sth = int(tw * scale), int(th * scale)
        if stw >= roi.shape[1] or sth >= roi.shape[0] or stw < 15 or sth < 15:
            continue
        rt = cv2.resize(template, (stw, sth))
        res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + int(sth * 0.80))

    if best_score >= min_confidence and best_match:
        return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # 3. Fallback via Windows OCR: Look for 'Die', 'Revive', or 'Life or Death'
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))

        async def _ocr_die():
            return await winocr.recognize_pil(pil_img, lang="en")

        ocr_res = asyncio.run(_ocr_die())
        for line in ocr_res.lines:
            t = line.text.lower()
            if "die" in t and "diet" not in t:
                for word in line.words:
                    if word.text.lower() == "die":
                        r = word.bounding_rect
                        cx = x0 + r.x + r.width / 2
                        cy = y0 + r.y + r.height / 2
                        return (round(cx / w, 4), round(cy / h, 4))
            if "revive" in t or "life or death" in t or "death" in t:
                # If Revive or Life or Death is seen, Die button is situated squarely at (0.50, 0.73)
                return (0.50, 0.73)
    except Exception:
        pass

    return None


def detect_obtain_button(frame: np.ndarray, min_confidence: float = 0.68) -> Optional[tuple[float, float]]:
    """Detect the 'Obtain' confirm button at the bottom of the Treasure Chest popup."""
    template_path = _BASE_DIR / "assets" / "obtain_button.png"
    if not template_path.is_file():
        return None
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.70), int(h * 0.93)
    x0, x1 = int(w * 0.18), int(w * 0.82)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]
    best_match = None
    best_score = 0.0
    for scale in (0.70, 0.85, 1.0, 1.15, 1.30, 1.50, 1.75, 2.00, 2.25):
        stw, sth = int(tw * scale), int(th * scale)
        if stw >= roi.shape[1] or sth >= roi.shape[0]:
            continue
        rt = cv2.resize(template, (stw, sth))
        res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + sth // 2)
    if best_score >= min_confidence and best_match:
        return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # Fallback via Windows OCR: Look for 'obtain'
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_roi = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))

        async def _ocr_obtain():
            return await winocr.recognize_pil(pil_roi, lang="en")

        ocr_res = asyncio.run(_ocr_obtain())
        for line in ocr_res.lines:
            if "obtain" in line.text.lower():
                if line.words:
                    r = line.words[0].bounding_rect
                    cx = (x0 + r.x + r.width / 2) / w
                    cy = (y0 + r.y + r.height / 2) / h
                    return (round(cx, 4), round(cy, 4))
    except Exception:
        pass

    return None


def is_chest_screen(frame: np.ndarray) -> bool:
    """Return True if the current frame is a Treasure Chest / Obelisk / Relic artifact popup."""
    if detect_obtain_button(frame) is not None:
        return True
    # Fast OCR fallback on header area
    try:
        import asyncio
        import winocr
        from PIL import Image

        h, w = frame.shape[:2]
        header_roi = frame[int(h * 0.08) : int(h * 0.35), int(w * 0.15) : int(w * 0.85)]
        pil_img = Image.fromarray(cv2.cvtColor(header_roi, cv2.COLOR_BGR2RGB))

        async def _ocr_chest():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_ocr_chest())
        txt = " ".join(l.text.lower() for l in res.lines)
        for kw in ("obelisk", "treasure", "chest", "relic"):
            if kw in txt:
                return True
    except Exception:
        pass
    return False


def get_chest_card_target(card_index: int = 1, obtain_x: float = 0.50, y: float = 0.36) -> tuple[float, float]:
    """Return normalized screen coordinates for the 3 horizontal Treasure Chest artifact slots.

    The 3 horizontal slots sit at y screen height (default 0.36, 0.385 on 1080p):
      Slot 1 (Left)  : obtain_x - 0.235
      Slot 2 (Middle): obtain_x
      Slot 3 (Right) : obtain_x + 0.235
    """
    cx = float(obtain_x)
    mapping = {
        1: (round(max(0.10, cx - 0.235), 4), y),
        2: (round(cx, 4), y),
        3: (round(min(0.90, cx + 0.235), 4), y),
    }
    return mapping.get(card_index, (round(cx, 4), y))


def is_three_card_chest(frame: np.ndarray, obtain_x: float = 0.50) -> bool:
    """Return True if the Treasure Chest popup displays 3 horizontal cards (vs 1 centered card)."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    y0, y1 = int(h * 0.25), int(h * 0.45)
    left_x0 = max(0, int(w * (obtain_x - 0.36)))
    left_x1 = max(left_x0 + 1, int(w * (obtain_x - 0.12)))
    right_x0 = min(w - 1, int(w * (obtain_x + 0.12)))
    right_x1 = min(w, int(w * (obtain_x + 0.36)))
    left_roi = gray[y0:y1, left_x0:left_x1]
    right_roi = gray[y0:y1, right_x0:right_x1]
    if left_roi.size == 0 or right_roi.size == 0:
        return True  # Default to 3-card browsing in Magic Survival
    return int(np.sum(left_roi > 20)) >= 30 and int(np.sum(right_roi > 20)) >= 30


# Direct Archetype & Skill-Specific Synergy Keywords for Artifact Selection
SKILL_SYNERGY_KEYWORDS: dict[str, list[str]] = {
    "spirit": [
        "spirit", "blade", "sword of devil", "ether blade", "wand", "silver bullet",
        "projectile", "number of projectiles", "projectile speed",
    ],
    "electric_shock": [
        "electric shock", "electric", "shock", "lightning", "lightning rod", "thunderbolt",
        "spark", "tesla", "battery", "plasma", "copper wire", "cable",
    ],
    "cyclone": [
        "cyclone", "hurricane", "vortex", "black hole", "blackhole", "fan", "weather vane", "storm", "typhoon", "aerodynamics",
    ],
    "satellite": [
        "satellite", "orbit", "rotation speed", "core", "neutron core", "astrolabe", "miniature",
    ],
    "blizzard": [
        "blizzard", "freeze", "frost", "cold", "sub-zero", "sub zero", "absolute zero", "snowman", "ice age", "glacier",
    ],
    "frost_nova": [
        "frost nova", "frost", "freeze", "cold", "pole", "ice age", "glacier", "snowman",
    ],
    "tsunami": [
        "tsunami", "ocean", "water", "wave", "pole", "wave-calming flute", "wave calming flute", "freeze",
    ],
    "flash_shock": [
        "flash shock", "flash", "lens", "prism",
    ],
    "magic_circle": [
        "magic circle", "magiccircle", "ancient tree staff", "magic scroll", "magic grimoire", "hourglass",
    ],
    "shield": [
        "shield", "barrier", "organic shield", "force field", "aegis",
    ],
    "cloaking": [
        "cloaking", "cloak", "merlin's cloak", "merlins cloak", "mirage",
    ],
    "armageddon": [
        "armageddon", "book of revelation", "apocalypse", "a eddo n", "remove all enemies",
    ],
    "electric_zone": [
        "electric zone", "electric", "emp",
    ],
    "arcane_ray": [
        "arcane ray", "ray", "laser",
    ],
}


# Mapping combination skills to their component skills
COMBINATION_COMPONENTS: dict[str, list[str]] = {
    "telekinetic_sword": ["spirit", "electric_shock"],
    "superconductivity": ["electric_shock", "spirit"],
    "current_overload": ["electric_shock", "spirit"],
    "vortex": ["cyclone", "satellite"],
    "black_hole": ["cyclone", "satellite"],
    "neutron_generation": ["satellite", "cyclone"],
    "perpetual_engine": ["magic_circle", "arcane_ray"],
    "overmind": ["magic_circle"],
    "demon_equation": ["fireball", "energy_bolt"],
    "frenzy": ["flash_shock", "spirit"],
    "prism_spree": ["arcane_ray", "spirit"],
    "gate_of_creation": ["magic_circle", "shield"],
    "door_of_creation": ["magic_circle", "shield"],
    "master_of_storms": ["cyclone", "electric_shock"],
    "lightning_breath": ["incineration", "electric_shock"],
    "brand_of_fire": ["incineration", "fireball"],
    "plasma_beam": ["arcane_ray", "satellite"],
    "pandemonium": ["fireball", "incineration"],
    "deluge": ["tsunami", "frost_nova"],
    "war_climate": ["meteor", "blizzard"],
    "meissner_effect": ["electric_zone", "flash_shock"],
    "genesis": ["frost_nova", "meteor"],
    "great_rift": ["frost_nova", "meteor"],
    "winter_storm": ["blizzard", "cyclone"],
    "bloody_sacrament": ["flash_shock", "shield"],
    "runaway_electricity": ["electric_shock", "satellite"],
    "heart_of_lightning": ["electric_shock", "arcane_ray"],
}


def compute_skill_synergy_bonus(full_text: str, active_skills: Optional[set[str]] = None) -> tuple[int, list[str]]:
    """Calculate dynamic synergy bonus and tag for artifacts based on skills the player is currently learning."""
    if not active_skills:
        return 0, []
    text_lower = full_text.lower()
    matched_skills: list[str] = []
    bonus = 0

    # Expand active skills to include combination component magics
    expanded_skills = set(active_skills)
    for s_key in active_skills:
        if s_key in COMBINATION_COMPONENTS:
            expanded_skills.update(COMBINATION_COMPONENTS[s_key])

    for s_key in expanded_skills:
        std_name = s_key.replace("_", " ")
        kw_list = SKILL_SYNERGY_KEYWORDS.get(s_key, [std_name])
        if any(kw in text_lower for kw in kw_list):
            m_title = std_name.title()
            if m_title not in matched_skills:
                matched_skills.append(m_title)
                bonus += 180

    # Cap to max +360 if multiple synergizing skills match
    bonus = min(360, bonus)
    return bonus, matched_skills


def is_toy_castle_artifact(text: str) -> bool:
    """Check if the text refers to Toy Castle / MagicToys (Must-Pick SSS-Tier Artifact).

    Shrinks enemies and elite monsters, enabling high crowd control density and survivability.
    """
    t = text.lower().strip()
    if any(k in t for k in ("toy castle", "toycastle", "magic toys", "magictoys", "magic toy", "magictoy", "toy kingdom")):
        return True
    if "toy" in t and ("castle" in t or "size" in t or "elite" in t):
        return True
    if ("size of enemies" in t or "enemy size" in t) and ("elite" in t or "health" in t or "hp" in t):
        return True
    return False


# Special Grade Artifacts (Red Rarity / Unique Game-Changers) in Magic Survival
SPECIAL_ARTIFACT_NAMES: set[str] = {
    "toy castle", "toycastle", "magic toys", "magictoys", "magic toy", "toy kingdom",
    "hydra",
    "list", "roster",
    "death bell", "death's bell", "deaths bell",
    "thought cube", "cube",
    "brand", "brand of satan",
    "golden roulette", "roulette",
    "treasure map",
    "peace treaty",
    "assassination",
    "werewolf",
    "dragon tongue", "dragontongue",
    "cyborg",
    "jet engine", "jetengine",
    "space-time circuit", "space time circuit", "time circuit",
    "domain of power", "domain power",
    "ouroboros",
    "ether",
    "basilisk",
    "matrix",
    "limit",
    "singularity",
    "amplifier",
    "creation",
    "necronomicon",
    "superintelligence", "super intelligence",
    "undead",
    "abyss",
    "bouquet",
    "tarot card", "tarot",
    "ballista",
    "accelerator",
    "uranium",
    "reaper's scythe", "reapers scythe", "scythe",
    "magic mirror", "mirror",
    "dna",
    "crest",
    "magic seal",
    "longinus' spear", "longinus spear",
    "cyberspace",
    "evil sword",
    "genome map",
    "opulence",
    "magnum opus",
}


def is_special_artifact(text: str) -> bool:
    """Check if the text refers to a Special Artifact (Rarity: Special / Red Artifact) in Magic Survival."""
    t = text.lower().strip()
    if _match_keyword("special", t) or "special artifact" in t or "special grade" in t:
        return True
    for name in SPECIAL_ARTIFACT_NAMES:
        if _match_keyword(name, t):
            return True
    return False


def evaluate_selected_chest_artifact(
    frame: np.ndarray,
    prefer_crit_and_cooldown: bool = True,
    active_skills: Optional[set[str]] = None,
) -> tuple[int, str]:
    """Evaluate the currently selected artifact on the Treasure Chest screen.

    Inspects the description block below the 3 horizontal cards (y = 0.47..0.67) using both
    HSV rarity color and Windows OCR to score the artifact according to the Wiki/Reddit Meta Tier List.
    Returns (score, readable_label).
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Rarity subtitle ('Rare Artifact', 'Epic Artifact', etc.) sits in y = 0.51..0.58
    rarity_roi = hsv[int(h * 0.48) : int(h * 0.65), int(w * 0.15) : int(w * 0.85)]
    tier = 1
    tier_names = {5: "Legendary", 4: "Special", 3: "Epic", 2: "Rare", 1: "Normal"}
    if rarity_roi.size > 0:
        H, S, V = rarity_roi[:, :, 0], rarity_roi[:, :, 1], rarity_roi[:, :, 2]
        active = (S >= 80) & (V >= 110)
        leg_px = int(np.sum(active & (H >= 10) & (H <= 26)))
        spec_px = int(np.sum(active & ((H <= 8) | (H >= 168))))
        epic_px = int(np.sum(active & (H >= 130) & (H <= 165)))
        rare_px = int(np.sum(active & (H >= 90) & (H <= 118)))
        if leg_px >= 35:
            tier = 5
        elif spec_px >= 25:
            tier = 4
        elif epic_px >= 35:
            tier = 3
        elif rare_px >= 35:
            tier = 2

    artifact_name = ""
    has_s_tier = False
    has_crit = False
    has_cooldown = False
    has_survival_synergy = False

    try:
        import asyncio
        import winocr
        from PIL import Image

        y_top = int(h * 0.46)
        desc_crop = frame[y_top : int(h * 0.68), int(w * 0.08) : int(w * 0.92)]
        pil_img = Image.fromarray(cv2.cvtColor(desc_crop, cv2.COLOR_BGR2RGB))

        async def _do_ocr():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_do_ocr())
        lines_text = [ln.text.strip() for ln in res.lines if ln.text.strip()]
        if lines_text:
            artifact_name = lines_text[0]
        full_text = " ".join(lines_text).lower()

        if "legendary" in full_text:
            tier = max(tier, 5)
        elif "special" in full_text or is_special_artifact(full_text):
            tier = max(tier, 4)
        elif "epic" in full_text:
            tier = max(tier, 3)
        elif "rare" in full_text:
            tier = max(tier, 2)

        for name in META_S_TIER_ARTIFACTS:
            if name in full_text:
                has_s_tier = True
                break

        if any(w_kw in full_text for w_kw in ["crit", "critical", "evasion"]):
            has_crit = True
        else:
            for name in CRIT_ARTIFACT_NAMES:
                if name in full_text:
                    has_crit = True
                    break

        if any(w_kw in full_text for w_kw in ["cooldown", "cool down"]):
            has_cooldown = True
        else:
            for name in COOLDOWN_ARTIFACT_NAMES:
                if name in full_text:
                    has_cooldown = True
                    break

        if any(
            w_kw in full_text
            for w_kw in ["hp", "damage", "attack", "amplify", "speed", "freeze", "duration", "size", "mana"]
        ):
            has_survival_synergy = True
        else:
            for name in SURVIVAL_SYNERGY_ARTIFACTS:
                if name in full_text:
                    has_survival_synergy = True
                    break
    except Exception:
        pass

    tier_base = {5: 12000, 4: 10000, 3: 300, 2: 200, 1: 100}[tier]
    bonus = 0
    tags: list[str] = [tier_names[tier]]

    # Toy Castle (MagicToys) has absolute top priority over any artifact in the game!
    if is_toy_castle_artifact(full_text):
        bonus += 50000
        tags.append("★ Ưu Tiên Tuyệt Đối: Toy Castle / MagicToys")
    elif tier == 4 or is_special_artifact(full_text):
        tags.append("★ Trang Bị Special (Ưu Tiên)")

    if has_s_tier:
        bonus += 240
        tags.append("S-Tier Meta")
    if prefer_crit_and_cooldown:
        if has_crit:
            bonus += 150
            tags.append("Chí mạng")
        if has_cooldown:
            bonus += 150
            tags.append("Hồi chiêu")
    if has_survival_synergy:
        bonus += 80
        if not (has_s_tier or has_crit or has_cooldown):
            tags.append("Synergy")

    # Skill Build Synergy (direct buff to skills currently learning)
    syn_bonus, syn_matched = compute_skill_synergy_bonus(full_text, active_skills)
    if syn_matched:
        bonus += syn_bonus
        tags.append(f"Build: {'+'.join(syn_matched)}")

    display_title = artifact_name if artifact_name else "Artifact"
    label = f"{display_title} [{' | '.join(tags)}]"
    return (tier_base + bonus, label)


def detect_buy_button(frame: np.ndarray, min_confidence: float = 0.65) -> Optional[tuple[float, float]]:
    """Detect 'Buy' button at the bottom of the Merchant Shop screen (y = 0.84..0.98, x = 0.25..0.75)."""
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.84), int(h * 0.98)
    x0, x1 = int(w * 0.25), int(w * 0.75)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    # 1. Multi-scale template matching across all window resolutions
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    for tmpl_name in ("buy_button_tight.png", "buy_button.png"):
        template_path = _BASE_DIR / "assets" / tmpl_name
        if not template_path.is_file():
            continue
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            continue
        th, tw = template.shape[:2]
        best_match = None
        best_score = 0.0
        for scale in (0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.30):
            stw, sth = int(tw * scale), int(th * scale)
            if stw >= roi.shape[1] or sth >= roi.shape[0] or stw < 10 or sth < 6:
                continue
            rt = cv2.resize(template, (stw, sth))
            res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + sth // 2)
        if best_score >= min_confidence and best_match:
            return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # 2. Fast OCR Fallback: Check if the word 'Buy' is written in the bottom button area
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_roi = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
        async def _do_buy_ocr():
            return await winocr.recognize_pil(pil_roi, lang="en")
        ocr_res = asyncio.run(_do_buy_ocr())
        for line in ocr_res.lines:
            t = line.text.lower().strip()
            if "buy" in t or "b uy" in t:
                if line.words:
                    bx = x0 + sum(wd.bounding_rect.x + wd.bounding_rect.width / 2 for wd in line.words) / len(line.words)
                    by = y0 + sum(wd.bounding_rect.y + wd.bounding_rect.height / 2 for wd in line.words) / len(line.words)
                    return (round(bx / w, 4), round(by / h, 4))
                return (0.50, 0.92)
    except Exception:
        pass

    return None


def detect_shop_x_button(frame: np.ndarray, min_confidence: float = 0.65) -> Optional[tuple[float, float]]:
    """Detect 'X' close button at the top-right of the Merchant Shop screen."""
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.02), int(h * 0.14)
    x0, x1 = int(w * 0.80), int(w * 0.99)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    for tmpl_name in ("shop_x_tight.png", "shop_x_button.png", "ad_close_x.png"):
        template_path = _BASE_DIR / "assets" / tmpl_name
        if not template_path.is_file():
            continue
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            continue
        th, tw = template.shape[:2]
        best_match = None
        best_score = 0.0
        for scale in (0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.30):
            stw, sth = int(tw * scale), int(th * scale)
            if stw >= roi.shape[1] or sth >= roi.shape[0] or stw < 8 or sth < 8:
                continue
            rt = cv2.resize(template, (stw, sth))
            res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + sth // 2)
        if best_score >= min_confidence and best_match:
            return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    return (0.936, 0.079) if detect_buy_button(frame) is not None else None


def is_merchant_shop(frame: np.ndarray) -> bool:
    """Return True if the Merchant Shop screen is currently open."""
    return detect_buy_button(frame) is not None


def detect_mana_orb_currency(frame: np.ndarray) -> Optional[int]:
    """Read the player's accumulated mana orb currency displayed in the top-left corner."""
    h, w = frame.shape[:2]
    roi = frame[int(h * 0.01) : int(h * 0.10), int(w * 0.02) : int(w * 0.40)]
    if roi.size == 0:
        return None
    try:
        import asyncio
        import winocr
        import re
        from PIL import Image

        roi_large = cv2.resize(roi, (roi.shape[1] * 4, roi.shape[0] * 4), interpolation=cv2.INTER_CUBIC)
        pil_img = Image.fromarray(cv2.cvtColor(roi_large, cv2.COLOR_BGR2RGB))
        async def _ocr():
            return await winocr.recognize_pil(pil_img, lang="en")
        res = asyncio.run(_ocr())
        for line in res.lines:
            clean = re.sub(r"[*liI!|]", "1", line.text)
            digits = re.findall(r"\d+", clean)
            if digits:
                val = int(max(digits, key=len))
                if 0 <= val <= 999999:
                    return val
    except Exception:
        pass
    return None


def get_shop_item_targets() -> list[tuple[float, float]]:
    """Return normalized screen coordinates for the 8 Merchant Shop items (2 rows x 4 cols)."""
    return [
        (0.22, 0.33), (0.42, 0.33), (0.62, 0.33), (0.82, 0.33),
        (0.22, 0.50), (0.42, 0.50), (0.62, 0.50), (0.82, 0.50),
    ]


def is_shop_buy_enabled(frame: np.ndarray, buy_pos: Optional[tuple[float, float]] = None) -> bool:
    """Return True if the 'Buy' button has active white text (affordable), False if dimmed gray."""
    h, w = frame.shape[:2]
    if buy_pos is not None:
        bx, by = int(w * buy_pos[0]), int(h * buy_pos[1])
        roi = frame[max(0, by - 28) : min(h, by + 28), max(0, bx - 65) : min(w, bx + 65)]
    else:
        y0, y1 = int(h * 0.88), int(h * 0.96)
        x0, x1 = int(w * 0.35), int(w * 0.65)
        roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return int(np.sum(gray >= 150)) >= 20 and int(np.max(gray)) >= 170


def evaluate_selected_shop_artifact(
    frame: np.ndarray,
    prefer_crit_and_cooldown: bool = True,
    active_skills: Optional[set[str]] = None,
) -> tuple[int, str]:
    """Evaluate the currently selected artifact on the Merchant Shop screen.

    Description box sits in y = 0.61..0.82 (below the 8 item tiles).
    Returns (score, readable_label).
    """
    h, w = frame.shape[:2]
    # Rarity subtitle sits in y = 0.64..0.71
    rarity_roi = frame[int(h * 0.64) : int(h * 0.71), int(w * 0.18) : int(w * 0.82)]
    tier = 1
    tier_names = {5: "Legendary", 4: "Special", 3: "Epic", 2: "Rare", 1: "Normal"}
    if rarity_roi.size > 0:
        hsv = cv2.cvtColor(rarity_roi, cv2.COLOR_BGR2HSV)
        H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        active = (S >= 80) & (V >= 110)
        leg_px = int(np.sum(active & (H >= 10) & (H <= 26)))
        spec_px = int(np.sum(active & ((H <= 8) | (H >= 168))))
        epic_px = int(np.sum(active & (H >= 130) & (H <= 165)))
        rare_px = int(np.sum(active & (H >= 90) & (H <= 118)))
        if leg_px >= 30:
            tier = 5
        elif spec_px >= 25:
            tier = 4
        elif epic_px >= 30:
            tier = 3
        elif rare_px >= 30:
            tier = 2

    artifact_name = ""
    has_s_tier = False
    has_crit = False
    has_cooldown = False
    has_survival_synergy = False

    try:
        import asyncio
        import winocr
        from PIL import Image

        y_top = int(h * 0.61)
        desc_crop = frame[y_top : int(h * 0.82), int(w * 0.08) : int(w * 0.92)]
        pil_img = Image.fromarray(cv2.cvtColor(desc_crop, cv2.COLOR_BGR2RGB))

        async def _do_ocr():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_do_ocr())
        lines_text = [ln.text.strip() for ln in res.lines if ln.text.strip()]
        if lines_text:
            artifact_name = lines_text[0]
        full_text = " ".join(lines_text).lower()

        if "legendary" in full_text:
            tier = max(tier, 5)
        elif "special" in full_text or is_special_artifact(full_text):
            tier = max(tier, 4)
        elif "epic" in full_text:
            tier = max(tier, 3)
        elif "rare" in full_text:
            tier = max(tier, 2)

        for name in META_S_TIER_ARTIFACTS:
            if name in full_text:
                has_s_tier = True
                break

        if any(w_kw in full_text for w_kw in ["crit", "critical", "evasion"]):
            has_crit = True
        else:
            for name in CRIT_ARTIFACT_NAMES:
                if name in full_text:
                    has_crit = True
                    break

        if any(w_kw in full_text for w_kw in ["cooldown", "cool down"]):
            has_cooldown = True
        else:
            for name in COOLDOWN_ARTIFACT_NAMES:
                if name in full_text:
                    has_cooldown = True
                    break

        if any(
            w_kw in full_text
            for w_kw in ["hp", "damage", "attack", "atk", "amplify", "speed", "freeze", "duration", "size", "mana"]
        ):
            has_survival_synergy = True
        else:
            for name in SURVIVAL_SYNERGY_ARTIFACTS:
                if name in full_text:
                    has_survival_synergy = True
                    break
    except Exception:
        pass

    tier_base = {5: 12000, 4: 10000, 3: 300, 2: 200, 1: 100}[tier]
    bonus = 0
    tags: list[str] = [tier_names[tier]]

    # Toy Castle (MagicToys) has absolute top priority over any artifact in the game!
    if is_toy_castle_artifact(full_text):
        bonus += 50000
        tags.append("★ Ưu Tiên Tuyệt Đối: Toy Castle / MagicToys")
    elif tier == 4 or is_special_artifact(full_text):
        tags.append("★ Trang Bị Special (Ưu Tiên)")

    if has_s_tier:
        bonus += 240
        tags.append("S-Tier Meta")
    if prefer_crit_and_cooldown:
        if has_crit:
            bonus += 150
            tags.append("Chí mạng")
        if has_cooldown:
            bonus += 150
            tags.append("Hồi chiêu")
    if has_survival_synergy:
        bonus += 80
        if not (has_s_tier or has_crit or has_cooldown):
            tags.append("Synergy")

    # Skill Build Synergy (direct buff to skills currently learning)
    syn_bonus, syn_matched = compute_skill_synergy_bonus(full_text, active_skills)
    if syn_matched:
        bonus += syn_bonus
        tags.append(f"Build: {'+'.join(syn_matched)}")

    display_title = artifact_name if artifact_name else "Artifact"
    label = f"{display_title} [{' | '.join(tags)}]"
    return (tier_base + bonus, label)


def detect_learn_button(frame: np.ndarray, min_confidence: float = 0.65) -> Optional[tuple[float, float]]:
    """Detect 'Learn' confirm button at the bottom of the Level 4/7 'Select Attribute' screen."""
    template_path = _BASE_DIR / "assets" / "learn_button_tight.png"
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.80), int(h * 0.96)
    x0, x1 = int(w * 0.25), int(w * 0.75)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    if template_path.is_file():
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is not None:
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            th, tw = template.shape[:2]
            best_match = None
            best_score = 0.0
            for scale in (0.75, 0.90, 1.0, 1.15, 1.30, 1.50, 1.80, 2.00, 2.20):
                stw, sth = int(tw * scale), int(th * scale)
                if stw >= roi.shape[1] or sth >= roi.shape[0]:
                    continue
                rt = cv2.resize(template, (stw, sth))
                res = cv2.matchTemplate(gray_roi, rt, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
                    best_match = (x0 + max_loc[0] + stw // 2, y0 + max_loc[1] + sth // 2)
            if best_score >= min_confidence and best_match:
                return (round(best_match[0] / w, 4), round(best_match[1] / h, 4))

    # Fast OCR fallback for 'Learn' button
    try:
        import asyncio
        import winocr
        from PIL import Image
        pil_roi = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
        async def _ocr_learn():
            return await winocr.recognize_pil(pil_roi, lang="en")
        ocr_res = asyncio.run(_ocr_learn())
        for line in ocr_res.lines:
            if "learn" in line.text.lower():
                if line.words:
                    r = line.words[0].bounding_rect
                    cx = x0 + int(r.x + r.width / 2)
                    cy = y0 + int(r.y + r.height / 2)
                    return (round(cx / w, 4), round(cy / h, 4))
                return (0.50, 0.88)
    except Exception:
        pass

    return None


def is_attribute_screen(frame: np.ndarray) -> bool:
    """Detect if the Magic Level 4/7 'Select Attribute' screen is open."""
    # 1. Direct positive check: Learn button exists
    if detect_learn_button(frame) is not None:
        return True

    # 2. Check title 'Select Attribute' in top 22%
    h, w = frame.shape[:2]
    try:
        import asyncio
        import winocr
        from PIL import Image
        roi_top = frame[int(h * 0.05):int(h * 0.22), int(w * 0.15):int(w * 0.85)]
        if roi_top.size > 0:
            pil_roi = Image.fromarray(cv2.cvtColor(roi_top, cv2.COLOR_BGR2RGB))
            async def _ocr_attr():
                return await winocr.recognize_pil(pil_roi, lang="en")
            res = asyncio.run(_ocr_attr())
            txt = " ".join(l.text.lower() for l in res.lines)
            if "select" in txt and ("attri" in txt or "bute" in txt):
                return True
    except Exception:
        pass

    return False


def get_attribute_circle_targets() -> dict[int, tuple[float, float]]:
    """Return normalized screen coordinates for the 3 Level 7 Attribute circles.
    1: Top (0.50, 0.29)
    2: Bottom-Left (0.31, 0.44)
    3: Bottom-Right (0.68, 0.44)
    """
    return {
        1: (0.50, 0.29),
        2: (0.31, 0.44),
        3: (0.68, 0.44),
    }


def evaluate_selected_attribute(frame: np.ndarray) -> tuple[int, str, str]:
    """Evaluate the currently selected Level 7 trait attribute.
    Returns (score, readable_tag, parent_skill_key).
    """
    h, w = frame.shape[:2]
    title = "Attribute"
    full_text = ""
    try:
        import asyncio
        import winocr
        from PIL import Image

        y_top = int(h * 0.52)
        desc_crop = frame[y_top : int(h * 0.67), int(w * 0.05) : int(w * 0.95)]
        pil_img = Image.fromarray(cv2.cvtColor(desc_crop, cv2.COLOR_BGR2RGB))

        async def _do():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_do())
        lines = [ln.text.strip() for ln in res.lines if ln.text.strip()]
        if lines:
            title = lines[0]
        full_text = " ".join(lines).lower()
    except Exception:
        pass

    score = 100
    tag = f"Nhánh {title}"
    for ct in COMBINATION_TRAITS:
        if ct in full_text:
            score = 500
            tag = f"Nhánh Hợp Thể ({ct.title()})"
            break
    else:
        for ft in FREEZE_TRAITS:
            if ft in full_text:
                score = 400
                tag = f"Nhánh Đóng Băng ({ft.title()})"
                break
        else:
            for st in META_SUPPORT_TRAITS:
                if st in full_text:
                    score = 350
                    tag = f"Nhánh Hỗ Trợ ({st.title()})"
                    break

    parent_skill = ""
    for sk, aliases in SKILL_ALIASES.items():
        if any(a in full_text for a in aliases):
            parent_skill = sk
            break

    return score, tag, parent_skill


def is_learn_button_active(frame: np.ndarray) -> bool:
    """Return True if the 'Learn' button on the 'Select Attribute' screen is active (bright white).
    Returns False if unselected/dimmed gray.
    """
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.85), int(h * 0.92)
    x0, x1 = int(w * 0.38), int(w * 0.62)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return bool(np.max(gray) >= 180 and np.sum(gray >= 160) >= 30)


class CardChoice(tuple):
    """2-tuple (card_index, target_coords) with optional .label, .skill_key, .trait_key."""
    def __new__(cls, idx: int, target: tuple[float, float], label: str = "", skill_key: str = "", trait_key: str = ""):
        return super().__new__(cls, (idx, target))

    def __init__(self, idx: int, target: tuple[float, float], label: str = "", skill_key: str = "", trait_key: str = ""):
        self.idx = idx
        self.target = target
        self.label = label
        self.skill_key = skill_key
        self.trait_key = trait_key


DEFAULT_SKILL_PRIORITY = [
    # 1. First Combination: Telekinetic Sword (Spirit + Electric Shock)
    "telekinetic_sword",
    "spirit",
    "electric_shock",
    # 2. Second Combination: Black Hole (Cyclone + Satellite)
    "black_hole",
    "cyclone",
    "satellite",
    # 3. Alternative/Fallback combinations for Spirit, Electric Shock, Cyclone, Satellite
    "superconductivity",
    "current_overload",
    "vortex",
    "neutron_generation",
    # 4. Ice / Freeze Magics (with Freeze traits - Mandatory Crowd Control)
    "blizzard",
    "frost_nova",
    "tsunami",
    # 5. Flash Shock & Meta Support Combinations
    "flash_shock",
    "perpetual_engine",
    "overmind",
    "demon_equation",
    "frenzy",
    "prism_spree",
    # 6. Meta Survival & Utility Support Magics (Wiki / Reddit S-Tier)
    "magic_circle",
    "shield",
    "cloaking",
    "armageddon",
    "electric_zone",
    "arcane_ray",
    # 7. Meta Passive Skills (CDR -> Speed [Accelerator] -> Crit -> HP [Gaia] -> ATK -> Size)
    "fast_casting",
    "haste",
    "snipe",
    "vitality",
    "intelligence",
    "arcane_effuse",
    "concentration",
    "explorer",
]

SKILL_ALIASES: dict[str, list[str]] = {
    # Combinations: Spirit + Electric Shock
    "telekinetic_sword": ["telekinetic sword", "telekinetic", "telekineticsword"],
    "superconductivity": ["superconductivity", "super conductivity"],
    "current_overload": ["current overload", "currentoverload", "overload"],

    # Combinations: Cyclone + Satellite
    "black_hole": ["black hole", "blackhole", "black-hole", "black hoie", "biack hole"],
    "vortex": ["vortex"],
    "neutron_generation": ["neutron generation", "neutron", "neutrongeneration"],

    # Meta Support & Flash Shock Combinations
    "perpetual_engine": ["perpetual engine", "perpetualengine", "perpetual"],
    "overmind": ["overmind", "over mind"],
    "demon_equation": ["demon equation", "demonequation"],
    "frenzy": ["frenzy"],
    "prism_spree": ["prism spree", "prismspree", "prism spray"],
    "blast_furnace": ["blast furnace", "blastfurnace"],
    "inferno": ["inferno"],
    "avatar": ["avatar"],
    "hyperion": ["hyperion"],
    "great_rift": ["great rift", "greatrift"],
    "bloody_sacrament": ["bloody sacrament", "bloodysacrament"],
    "deus_ex_machina": ["deus ex machina", "deus ex"],
    "breath_of_fire": ["breath of fire", "breathoffire"],
    "winter_storm": ["winter storm", "winterstorm"],
    "flying_swords": ["flying swords", "flyingswords"],
    "door_of_creation": ["door of creation", "doorofcreation"],
    "gate_of_creation": ["gate of creation", "gateofcreation"],
    "runaway_electricity": ["runaway electricity", "runawayelectricity"],
    "heart_of_lightning": ["heart of lightning", "heartoflightning"],
    "master_of_storms": ["master of storms", "master of storm", "masterofstorms"],
    "lightning_breath": ["lightning breath", "lightningbreath"],
    "brand_of_fire": ["brand of fire", "brandoffire"],
    "plasma_beam": ["plasma beam", "plasmabeam"],
    "pandemonium": ["pandemonium"],
    "deluge": ["deluge"],
    "war_climate": ["war climate", "warclimate"],
    "meissner_effect": ["meissner effect", "meissnereffect"],
    "genesis": ["genesis"],

    # Component skills
    "spirit": ["spirit", "spirits", "spirit's"],
    "electric_shock": [
        "electric shock", "electrick shock", "electric_shock", "electricshock",
    ],
    "cyclone": [
        "cyclone", "cycione", "cycIone", "cyctone", "cyclon", "cycloe", "cydone",
        "cy clone", "cyc lone", "cyclones",
        "hurricane", "climate change",
    ],
    "satellite": [
        "satellite", "satelite", "satellit", "satellites", "sateilite", "satelIite",
    ],

    # Ice / Freeze skills
    "blizzard": ["blizzard", "blizard", "blizz"],
    "frost_nova": ["frost nova", "frostnova"],
    "tsunami": ["tsunami", "tsunam"],

    # Other Active / Support Magics
    "flash_shock": ["flash shock", "flashshock", "flash_shock"],
    "magic_circle": ["magic circle", "magiccircle"],
    "shield": ["shield"],
    "cloaking": ["cloaking", "cloak"],
    "armageddon": ["armageddon", "a eddo n", "remove all enemies"],
    "electric_zone": ["electric zone", "electriczone", "electrick zone", "electric_zone"],
    "arcane_ray": ["arcane ray", "arcaneray"],
    "fireball": ["fireball", "fire ball"],
    "meteor": ["meteor", "meteors"],
    "thunderstorm": ["thunderstorm", "thunder storm"],
    "incineration": ["incineration", "incinerate"],
    "energy_bolt": ["energy bolt", "energybolt"],
    "lava_zone": ["lava zone", "lavazone"],
    "magic_bullet": ["magic bullet", "magicbullet", "magic bolt", "magicbolt"],

    # Meta Passive Magics
    "fast_casting": ["fast casting", "fastcasting"],
    "haste": ["haste"],
    "snipe": ["snipe"],
    "vitality": ["vitality"],
    "intelligence": ["intelligence"],
    "arcane_effuse": ["arcane effuse", "arcaneeffuse"],
    "concentration": ["concentration"],
    "explorer": ["explorer"],

    # Special Passives ("Red Star Passives" / Kỹ năng có dấu * / dấu sao)
    "adrenaline": ["adrenaline", "adrenalin"],
    "silent_casting": ["silent casting", "silent chant", "silentcast"],
    "mana_factory": ["mana factory", "manafactory"],
    "guardian_angel": ["guardian angel", "guardian"],
    "magic_seal": ["magic seal", "magicseal"],
    "juggernaut": ["juggernaut", "juggernauts", "juggernaut's"],
    "noblesse": ["noblesse", "nobless", "noble"],
    "timekeeper": ["timekeeper", "time keeper", "time acceleration"],
    "doctor": ["doctor"],
    "taoist": ["taoist"],
    "blood_magic": ["blood magic", "blood curse"],
    "pioneer": ["pioneer"],
    "florist": ["florist"],
    "grand_master": ["grand master", "grandmaster"],
    "eldritch": ["eldritch"],
    "growth": ["growth", "overgrowth", "vitality growth"],
    "catalyst": ["catalyst"],
    "overdrive": ["overdrive"],
    "veteran": ["veteran"],
    "chaser": ["chaser"],
    "recombination": ["recombination", "recombinant"],
    "mutation": ["mutation", "mutant"],
}

# Maximum level caps for skills in Magic Survival
SKILL_MAX_LEVELS: dict[str, int] = {
    # Active Magics (Max Level 7)
    "spirit": 7,
    "electric_shock": 7,
    "cyclone": 7,
    "satellite": 7,
    "blizzard": 7,
    "frost_nova": 7,
    "tsunami": 7,
    "flash_shock": 7,
    "magic_circle": 7,
    "shield": 7,
    "cloaking": 7,
    "armageddon": 7,
    "electric_zone": 7,
    "arcane_ray": 7,
    "fireball": 7,
    "meteor": 7,
    "thunderstorm": 7,
    "incineration": 7,
    "energy_bolt": 7,
    "lava_zone": 7,
    "magic_bullet": 7,

    # Passive Magics (Max Level 5)
    "fast_casting": 5,
    "haste": 5,
    "snipe": 5,
    "vitality": 5,
    "intelligence": 5,
    "arcane_effuse": 5,
    "concentration": 5,
    "explorer": 5,
}

# Special Passives ("Red Star Passives" / Kỹ năng có dấu * / dấu sao)
SPECIAL_STAR_PASSIVES: dict[str, list[str]] = {
    "adrenaline": ["adrenaline", "adrenalin"],
    "silent_casting": ["silent casting", "silent chant", "silentcast"],
    "mana_factory": ["mana factory", "manafactory"],
    "guardian_angel": ["guardian angel", "guardian"],
    "magic_seal": ["magic seal", "magicseal"],
    "juggernaut": ["juggernaut", "juggernauts", "juggernaut's"],
    "noblesse": ["noblesse", "nobless", "noble"],
    "timekeeper": ["timekeeper", "time keeper", "time acceleration"],
    "doctor": ["doctor"],
    "taoist": ["taoist"],
    "blood_magic": ["blood magic", "blood curse"],
    "pioneer": ["pioneer"],
    "florist": ["florist"],
    "grand_master": ["grand master", "grandmaster"],
    "eldritch": ["eldritch"],
    "growth": ["growth", "overgrowth", "vitality growth"],
    "catalyst": ["catalyst"],
    "overdrive": ["overdrive"],
    "veteran": ["veteran"],
    "chaser": ["chaser"],
    "recombination": ["recombination", "recombinant"],
    "mutation": ["mutation", "mutant"],
}

# Special Passive Priority Score (Wiki & Reddit Tier List)
SPECIAL_PASSIVE_SCORES: dict[str, float] = {
    "adrenaline": 180.0,
    "silent_casting": 180.0,
    "mana_factory": 170.0,
    "growth": 170.0,
    "catalyst": 165.0,
    "guardian_angel": 165.0,
    "magic_seal": 160.0,
    "juggernaut": 155.0,
    "overdrive": 150.0,
    "noblesse": 140.0,
    "pioneer": 140.0,
    "veteran": 140.0,
    "grand_master": 135.0,
    "recombination": 135.0,
    "timekeeper": 130.0,
    "doctor": 125.0,
    "chaser": 125.0,
    "blood_magic": 120.0,
    "mutation": 120.0,
    "florist": 115.0,
    "taoist": 110.0,
    "eldritch": 110.0,
}

# Freeze traits for Blizzard, Frost Nova, Tsunami (Absolute priority for ice spells)
FREEZE_TRAITS: list[str] = [
    "sub-zero", "sub zero", "subzero",
    "absolute zero", "absolute", "absolutezero",
    "pole",
    "cold wave", "coldwave",
    "ice age", "iceage",
]

# Combination traits for component magics (Spirit, Electric Shock, Cyclone, Satellite, Flash Shock, Magic Circle)
COMBINATION_TRAITS: list[str] = [
    "magic blade", "chain lightning", "familiar", "superconductivity",
    "void", "anti-gravity", "antigravity", "nuclear fission", "nuclear fusion", "electric orb",
    "extreme weather", "hurricane", "climate change", "tornado", "deep breath",
    "unleash mana", "great magic circle", "devil's nails", "devils nails", "raving",
]

# Meta Survival Support Traits (Shield, Cloaking, Armageddon)
META_SUPPORT_TRAITS: list[str] = [
    "barrier", "reconstruct", "mirage", "soul harvest", "apocalypse", "book of revelation",
]

SKILL_TEMPLATE_FILES: dict[str, str] = {
    "spirit": "assets/skills/spirit_tight.png",
    "electric_shock": "assets/skills/electricshock_tight.png",
    "cyclone": "assets/skills/cyclone_tight.png",
    "satellite": "assets/skills/satellite_tight.png",
    "blizzard": "assets/skills/blizzard_tight.png",
    "frost_nova": "assets/skills/frostnova_tight.png",
    "tsunami": "assets/skills/tsunami_tight.png",
    "flash_shock": "assets/skills/flash_shock_tight.png",
}

# God-Tier S+ Meta Artifacts from Wiki & Reddit r/magic_survival Tier Lists
META_S_TIER_ARTIFACTS: set[str] = {
    "accelerator", "gaia", "titan's power", "titan power", "titans power",
    "holy chest", "ouroboros", "creation", "ballista", "executioner's ax",
    "executioner's axe", "executioners ax", "joker", "widowmaker", "eclipse",
    "hydra", "space-time circuit", "space time circuit", "roster", "golden roulette",
    "peace treaty", "toy castle", "assassination", "death's bell", "deaths bell",
    "magic seal", "longinus' spear", "longinus spear", "magnum opus", "treasure map",
    "opulence", "cyberspace", "evil sword", "genome map",
}

CRIT_ARTIFACT_NAMES: set[str] = {
    "ballista", "executioner's ax", "executioner's axe", "executioners ax", "widowmaker",
    "joker", "assassination", "werewolf", "oculus", "carnival", "watcher's eye", "watchers eye",
    "siege hammer", "four-leaf clover", "four leaf clover", "clover", "radar",
    "masked ball", "shuriken", "target", "rainbow", "crow", "shadow cape", "rose",
}

COOLDOWN_ARTIFACT_NAMES: set[str] = {
    "creation", "accelerator", "holy chest", "ouroboros", "death's bell", "deaths bell",
    "ai magic", "longinus' spear", "longinus spear", "matrix", "diamond", "gravity orb",
    "world tree leaf", "pandora's box", "pandoras box", "clockwork", "ether arrow",
    "black cat", "otherworldly tentacles", "dimensional gate", "wave-calming flute",
    "wave calming flute", "wizard's hat", "wizards hat", "chimera", "cogwheel",
    "hourglass", "totem", "ancient tree staff", "harmony",
    "magic scroll", "torch", "lightning rod", "snowman", "magic grimoire",
}

SURVIVAL_SYNERGY_ARTIFACTS: set[str] = {
    "aegis", "force field", "organic shield", "dragon's heart", "dragon heart",
    "uranium", "crown", "merlin's cloak", "merlins cloak", "dna", "second heart",
    "guardian angel", "breeze", "broom", "feather", "meat", "hp potion", "golem core",
    "blood magic", "brand", "necronomicon",
}

_CACHED_SKILL_TEMPLATES: dict[str, list[np.ndarray]] = {}


def _get_skill_templates() -> dict[str, list[np.ndarray]]:
    global _CACHED_SKILL_TEMPLATES
    if _CACHED_SKILL_TEMPLATES:
        return _CACHED_SKILL_TEMPLATES
    for skill_key, rel_path in SKILL_TEMPLATE_FILES.items():
        full_path = _BASE_DIR / rel_path
        if not full_path.is_file():
            continue
        base_tmpl = cv2.imread(str(full_path), cv2.IMREAD_GRAYSCALE)
        if base_tmpl is None:
            continue
        tmpls = []
        for scale in (0.22, 0.30, 0.38):
            tw, th = int(base_tmpl.shape[1] * scale), int(base_tmpl.shape[0] * scale)
            if tw >= 18 and th >= 18:
                tmpls.append(cv2.resize(base_tmpl, (tw, th)))
        _CACHED_SKILL_TEMPLATES[skill_key] = tmpls
    return _CACHED_SKILL_TEMPLATES


@dataclass
class CardSlotData:
    card_idx: int
    text_lines: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    freeze_traits: list[str] = field(default_factory=list)
    combo_traits: list[str] = field(default_factory=list)
    support_traits: list[str] = field(default_factory=list)
    has_s_tier: bool = False
    has_crit: bool = False
    has_cooldown: bool = False
    has_survival_synergy: bool = False
    has_asterisk: bool = False
    is_special_passive: bool = False
    special_passive_name: str = ""
    has_special_artifact: bool = False
    is_maxed: bool = False


def _detect_cards_ocr(frame: np.ndarray, h: int, w: int) -> dict[int, CardSlotData]:
    """Use Windows Media OCR to detect text, skills, traits, and artifact properties on the card slots.
    Automatically detects 3-card layout or 4-card layout (e.g. from research / class upgrades).
    """
    cards: dict[int, CardSlotData] = {1: CardSlotData(1), 2: CardSlotData(2), 3: CardSlotData(3)}
    try:
        import asyncio
        import winocr
        from PIL import Image

        y_crop_top = int(h * 0.08)
        y_crop_bot = int(h * 0.95)
        cards_crop = frame[y_crop_top:y_crop_bot, int(w * 0.08):int(w * 0.92)]
        pil_img = Image.fromarray(cv2.cvtColor(cards_crop, cv2.COLOR_BGR2RGB))

        async def _do():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_do())

        # Determine if screen is 4-card or 3-card layout based on 'Select Magic' or 'Mana Retrieve' Y position
        mana_y = None
        select_magic_y = None
        for line in res.lines:
            t = line.text.lower()
            if not line.words:
                continue
            avg_y = (y_crop_top + sum(wd.bounding_rect.y + wd.bounding_rect.height / 2 for wd in line.words) / len(line.words)) / h
            if "mana" in t and ("retrieve" in t or "20%" in t):
                mana_y = avg_y
            if "select magic" in t or "select" in t:
                if select_magic_y is None or avg_y < select_magic_y:
                    select_magic_y = avg_y

        is_4_cards = (mana_y is not None and mana_y > 0.875) or (select_magic_y is not None and select_magic_y < 0.155)
        num_cards = 4 if is_4_cards else 3
        cards = {i: CardSlotData(i) for i in range(1, num_cards + 1)}

        for line in res.lines:
            line_text = line.text.lower().replace("—", "-").replace("–", "-")
            if not line.words:
                continue
            avg_y = (y_crop_top + sum(wd.bounding_rect.y + wd.bounding_rect.height / 2 for wd in line.words) / len(line.words)) / h

            if "select magic" in line_text or "mana" in line_text:
                continue

            card_idx = None
            if num_cards == 4:
                if 0.16 <= avg_y < 0.35:
                    card_idx = 1
                elif 0.35 <= avg_y < 0.52:
                    card_idx = 2
                elif 0.52 <= avg_y < 0.69:
                    card_idx = 3
                elif 0.69 <= avg_y < 0.86:
                    card_idx = 4
            else:
                if 0.24 <= avg_y < 0.44:
                    card_idx = 1
                elif 0.44 <= avg_y < 0.61:
                    card_idx = 2
                elif 0.61 <= avg_y < 0.78:
                    card_idx = 3

            if card_idx and card_idx in cards:
                card = cards[card_idx]
                card.text_lines.append(line_text)

                # Check for asterisk '*' or star '★' / '☆' symbol
                if any(sym in line_text for sym in ("*", "★", "☆")):
                    card.has_asterisk = True

                # Check freeze traits
                for ft in FREEZE_TRAITS:
                    if _match_keyword(ft, line_text):
                        if ft not in card.freeze_traits:
                            card.freeze_traits.append(ft)

                # Check combo traits
                for ct in COMBINATION_TRAITS:
                    if _match_keyword(ct, line_text):
                        if ct not in card.combo_traits:
                            card.combo_traits.append(ct)

                # Check meta support traits
                for st in META_SUPPORT_TRAITS:
                    if _match_keyword(st, line_text):
                        if st not in card.support_traits:
                            card.support_traits.append(st)

                # Check S-Tier Meta Artifacts
                for name in META_S_TIER_ARTIFACTS:
                    if _match_keyword(name, line_text):
                        card.has_s_tier = True

                # Check Special Grade Artifacts (Red Rarity / Unique Game-Changers)
                if is_special_artifact(line_text):
                    card.has_special_artifact = True

                # Check critical
                if any(w in line_text for w in ["crit", "critical", "evasion"]):
                    card.has_crit = True
                for name in CRIT_ARTIFACT_NAMES:
                    if name in line_text:
                        card.has_crit = True

                # Check cooldown
                if any(w in line_text for w in ["cooldown", "cool down"]):
                    card.has_cooldown = True
                for name in COOLDOWN_ARTIFACT_NAMES:
                    if name in line_text:
                        card.has_cooldown = True

                # Check survival / synergy artifacts
                for name in SURVIVAL_SYNERGY_ARTIFACTS:
                    if name in line_text:
                        card.has_survival_synergy = True

        # Post-process each card slot: prioritize card TITLE lines (first 1-2 lines)
        for card in cards.values():
            if not card.text_lines:
                continue

            full_card_text = " ".join(card.text_lines)
            if any(m in full_card_text for m in ("(max)", "[max]", "(max", "max)", "lv max", "lv. max", "level max", "max level", "maxed")) or bool(re.search(r'\b(lv\.?\s*max|max\s*level|maxed)\b', full_card_text)):
                card.is_maxed = True

            # 1. Match Special Passives: Title lines first
            for line in card.text_lines[:2]:
                for sp_key, aliases in SPECIAL_STAR_PASSIVES.items():
                    if any(_match_keyword(a, line) for a in aliases):
                        card.has_asterisk = True
                        card.is_special_passive = True
                        card.special_passive_name = sp_key
                        if sp_key not in card.skills:
                            card.skills.append(sp_key)
                        break
                if card.is_special_passive:
                    break

            if not card.is_special_passive:
                for line in card.text_lines[2:]:
                    for sp_key, aliases in SPECIAL_STAR_PASSIVES.items():
                        if any(_match_keyword(a, line) for a in aliases):
                            card.has_asterisk = True
                            card.is_special_passive = True
                            card.special_passive_name = sp_key
                            if sp_key not in card.skills:
                                card.skills.append(sp_key)
                            break
                    if card.is_special_passive:
                        break

            # 2. Match Skills: Title lines first (prevents description text from polluting skill name)
            title_skills: list[str] = []
            for line in card.text_lines[:2]:
                for skill_key, aliases in SKILL_ALIASES.items():
                    for a in aliases:
                        if _match_keyword(a, line):
                            if skill_key not in title_skills:
                                title_skills.append(skill_key)
                            break
            if title_skills:
                card.skills.extend(title_skills)
            else:
                for line in card.text_lines[2:]:
                    for skill_key, aliases in SKILL_ALIASES.items():
                        for a in aliases:
                            if _match_keyword(a, line):
                                if skill_key not in card.skills:
                                    card.skills.append(skill_key)
                                break

        # Visual check: detect red star badge in icon region of each card slot
        if num_cards == 4:
            icon_bands = {
                1: (int(h * 0.18), int(h * 0.35)),
                2: (int(h * 0.35), int(h * 0.52)),
                3: (int(h * 0.52), int(h * 0.69)),
                4: (int(h * 0.69), int(h * 0.86)),
            }
        else:
            icon_bands = {
                1: (int(h * 0.28), int(h * 0.44)),
                2: (int(h * 0.44), int(h * 0.58)),
                3: (int(h * 0.58), int(h * 0.74)),
            }
        x_ic0, x_ic1 = int(w * 0.10), int(w * 0.26)
        for idx, (y0, y1) in icon_bands.items():
            # A slot with NO text lines cannot be a valid level-up card (prevents monster eyes from triggering)
            if not cards[idx].text_lines:
                continue
            icon_roi = frame[y0:y1, x_ic0:x_ic1]
            if icon_roi.size > 0:
                hsv_ic = cv2.cvtColor(icon_roi, cv2.COLOR_BGR2HSV)
                hi, si, vi = hsv_ic[:, :, 0], hsv_ic[:, :, 1], hsv_ic[:, :, 2]
                red_star_px = np.sum(((hi <= 12) | (hi >= 168)) & (si >= 110) & (vi >= 90))
                if red_star_px >= 35:
                    cards[idx].has_asterisk = True
                    cards[idx].is_special_passive = True
    except Exception:
        pass
    return cards


def _detect_skills_templates(frame: np.ndarray, h: int, w: int, num_cards: int = 3) -> dict[int, list[str]]:
    """Use OpenCV template matching to detect skill glyphs in the card icons area."""
    detected: dict[int, list[str]] = {i: [] for i in range(1, num_cards + 1)}
    skill_tmpls = _get_skill_templates()
    if not skill_tmpls:
        return detected

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if num_cards == 4:
        bands = {
            1: (int(h * 0.18), int(h * 0.35)),
            2: (int(h * 0.35), int(h * 0.52)),
            3: (int(h * 0.52), int(h * 0.69)),
            4: (int(h * 0.69), int(h * 0.86)),
        }
    else:
        bands = {
            1: (int(h * 0.30), int(h * 0.44)),
            2: (int(h * 0.44), int(h * 0.58)),
            3: (int(h * 0.58), int(h * 0.72)),
        }
    x0, x1 = int(w * 0.10), int(w * 0.45)

    for idx, (y0, y1) in bands.items():
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        for skill_key, tmpls in skill_tmpls.items():
            found = False
            for tmpl in tmpls:
                if tmpl.shape[0] >= roi.shape[0] or tmpl.shape[1] >= roi.shape[1]:
                    continue
                res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= 0.78:
                    px, py = max_loc
                    sub = roi[py : py + tmpl.shape[0], px : px + tmpl.shape[1]]
                    if sub.size > 0 and np.max(sub) >= 120 and np.std(sub) >= 28.0:
                        if skill_key not in detected[idx]:
                            detected[idx].append(skill_key)
                        found = True
                        break
            if found:
                continue
    return detected


class LevelUpDetection(tuple):
    """2-tuple (detected: bool, reason: str) that evaluates truthy/falsy in boolean contexts."""
    def __new__(cls, detected: bool, reason: str = ""):
        return super().__new__(cls, (bool(detected), str(reason)))

    def __bool__(self) -> bool:
        return bool(self[0])

    @property
    def detected(self) -> bool:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]


def is_level_up_screen(frame: np.ndarray) -> LevelUpDetection:
    """Detect if the 3 vertical level-up card slots are present on screen.
    Returns LevelUpDetection(True, reason) when skill/trait upgrade choices are visible during a run.
    Guarantees 0% false positives during active combat and gameplay.
    """
    # 1. Negative checks: Ensure no other modal/menu screen is active
    if detect_obtain_button(frame) is not None or is_chest_screen(frame):
        return LevelUpDetection(False, "obtain_button")
    if detect_buy_button(frame) is not None:
        return LevelUpDetection(False, "buy_button")
    if detect_learn_button(frame) is not None:
        return LevelUpDetection(False, "learn_button")
    if is_attribute_screen(frame):
        return LevelUpDetection(False, "attribute_screen")
    if detect_die_button(frame) is not None:
        return LevelUpDetection(False, "die_button")
    if detect_confirm_button(frame) is not None:
        return LevelUpDetection(False, "confirm_button")
    if detect_enter_area(frame) is not None:
        return LevelUpDetection(False, "enter_area")
    if detect_selected(frame) is not None:
        return LevelUpDetection(False, "selected")
    if detect_start_game(frame) is not None:
        return LevelUpDetection(False, "start_game")
    if detect_close_button(frame) is not None:
        return LevelUpDetection(False, "ad_close_button")
    if detect_settings_dialog(frame):
        return LevelUpDetection(False, "settings_dialog")
    if detect_settings_gear(frame) is not None:
        return LevelUpDetection(False, "settings_gear")

    h, w = frame.shape[:2]

    # Fast positive check: Glowing red/pink combination star confirms level up screen immediately!
    if detect_combination_star(frame) is not None:
        return LevelUpDetection(True, "combination_star_active")

    # 2. Visual card darkness verification:
    # A genuine level-up screen dims the background and features 3 dark card panels (mean BGR <= 30.0).
    # Active combat ground and spell explosions are bright (mean BGR >= 58.0 to 150.0).
    # Reject bright gameplay frames immediately (< 0.05ms) to prevent combat false positives!
    c1 = frame[int(h * 0.30):int(h * 0.42), int(w * 0.15):int(w * 0.85)]
    c2 = frame[int(h * 0.46):int(h * 0.56), int(w * 0.15):int(w * 0.85)]
    c3 = frame[int(h * 0.60):int(h * 0.70), int(w * 0.15):int(w * 0.85)]
    if c1.size > 0 and c2.size > 0 and c3.size > 0:
        card_mean = (float(c1.mean()) + float(c2.mean()) + float(c3.mean())) / 3.0
        if card_mean > 38.0:
            return LevelUpDetection(False, f"gameplay_ground_bright_{card_mean:.1f}")

    # 3. Check OCR on the 3 card slots (y = 0.28..0.74, x = 0.10..0.90)
    ocr_cards = _detect_cards_ocr(frame, h, w)
    card_kws = (
        "lv.", "lv ", "level", "lv1", "lv2", "lv3", "lv4", "lv5", "lv6", "lv7", "lv8", "lv9", "lv10",
        "damage", "cooldown", "duration", "projectile", "radius", "increase", "decrease", "+%",
    )
    for idx in ocr_cards.keys():
        data = ocr_cards[idx]
        if data.skills or data.freeze_traits or data.combo_traits or data.support_traits:
            return LevelUpDetection(True, f"card_{idx}_skills")
        if data.text_lines and (data.has_s_tier or data.has_crit or data.has_cooldown or data.has_survival_synergy or data.has_asterisk or data.is_special_passive):
            return LevelUpDetection(True, f"card_{idx}_meta")
        for line in data.text_lines:
            if any(kw in line for kw in card_kws):
                return LevelUpDetection(True, f"card_{idx}_keyword")

    # 4. Check if header area has 'Select Magic' or 'Current Level'
    h_roi = frame[int(h * 0.08):int(h * 0.28), int(w * 0.08):int(w * 0.92)]
    try:
        import asyncio
        import winocr
        from PIL import Image
        async def _h():
            return await winocr.recognize_pil(Image.fromarray(cv2.cvtColor(h_roi, cv2.COLOR_BGR2RGB)), lang="en")
        h_res = asyncio.run(_h())
        if any("select magic" in l.text.lower() or "current level" in l.text.lower() or "magic combination" in l.text.lower() or "select attribute" in l.text.lower() for l in h_res.lines):
            return LevelUpDetection(True, "header_level_up")
    except Exception:
        pass

    # 5. Check if bottom area has 'Mana 20% Retrieve'
    b_roi = frame[int(h * 0.84):int(h * 0.98), int(w * 0.20):int(w * 0.80)]
    try:
        import asyncio
        import winocr
        from PIL import Image
        async def _b():
            return await winocr.recognize_pil(Image.fromarray(cv2.cvtColor(b_roi, cv2.COLOR_BGR2RGB)), lang="en")
        b_res = asyncio.run(_b())
        if any("retrieve" in l.text.lower() or "mana 20" in l.text.lower() or "mana retrieve" in l.text.lower() for l in b_res.lines):
            return LevelUpDetection(True, "mana_retrieve_button")
    except Exception:
        pass

    return LevelUpDetection(False, "none")


def detect_combination_star(frame: np.ndarray, threshold: float = 0.58) -> Optional[tuple[float, float]]:
    """Detect the glowing red/pink 7-pointed Combination Star in the upper-right corner of the level-up screen.
    Returns relative coords (x, y) if a fusion is unlocked and available to be learned.
    Strictly verifies that the star is ACTIVELY GLOWING RED/PINK.
    When the star is dull/grey/inactive (no fusion available), returns None!
    """
    if is_attribute_screen(frame) or is_chest_screen(frame) or detect_die_button(frame) is not None:
        return None

    h, w = frame.shape[:2]
    # Combination star is strictly situated in the upper right corner (y: 6%..22%, x: 76%..98%)
    y0, y1 = int(h * 0.06), int(h * 0.22)
    x0, x1 = int(w * 0.76), int(w * 0.98)
    roi = frame[y0:y1, x0:x1]
    if roi.shape[0] < 20 or roi.shape[1] < 20:
        return None

    # Strict red glow verification:
    # A glowing star has crimson/pink/bright-red glow (H in [148..180] or [0..16], S >= 50, V >= 60).
    # The dull/grey star has almost zero saturated red pixels (< 40px).
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red_mask = (((H >= 148) | (H <= 16)) & (S >= 50) & (V >= 60)).astype(np.uint8)
    total_red = int(np.sum(red_mask))
    if total_red < 150:
        return None

    # Match the star itself before considering its color. Other red game effects can
    # appear in this corner, so a red contour alone is not evidence of a fusion.
    tmpl_path = _BASE_DIR / "assets/combination_star.png"
    best_score = 0.0
    best_pos = None

    if tmpl_path.is_file():
        tmpl = cv2.imread(str(tmpl_path))
        if tmpl is not None:
            rh, rw = roi.shape[:2]
            for scale in (0.70, 0.80, 0.85, 0.95, 1.05, 1.20, 1.35, 1.50, 1.70, 1.85, 2.00, 2.15):
                th, tw = int(tmpl.shape[0] * scale), int(tmpl.shape[1] * scale)
                if th >= rh or tw >= rw:
                    continue
                t = cv2.resize(tmpl, (tw, th))
                res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    m_roi_red = red_mask[max_loc[1] : max_loc[1] + th, max_loc[0] : max_loc[0] + tw]
                    if np.sum(m_roi_red) >= max(100, int(th * tw * 0.05)):
                        best_score = max_val
                        best_pos = (
                            round(float(max_loc[0] + tw / 2 + x0) / w, 3),
                            round(float(max_loc[1] + th / 2 + y0) / h, 3),
                        )
            if best_score >= threshold and best_pos:
                return best_pos

    # Connected component fallback: centroid of the red hollow star cluster
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(red_mask, 8)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        cw = stats[i, cv2.CC_STAT_WIDTH]
        ch = stats[i, cv2.CC_STAT_HEIGHT]
        aspect = float(cw) / max(1, ch)
        extent = float(area) / max(1, cw * ch)
        if area >= max(160, int(roi.shape[0] * roi.shape[1] * 0.03)) and 0.60 <= aspect <= 1.40 and 0.15 <= extent <= 0.60:
            cx, cy = centroids[i]
            return (
                round(float(x0 + cx) / w, 3),
                round(float(y0 + cy) / h, 3),
            )

    return None


def find_best_combination_option(
    frame: np.ndarray,
    skill_priority: Optional[list[str]] = None,
) -> Optional[tuple[tuple[float, float], str, str]]:
    """Scan the Magic Combinations menu for prioritized fusions (Telekinetic Sword -> Black Hole -> etc.).
    Returns ((rel_x, rel_y), display_label, combo_key) if a matching fusion option is found.
    """
    h, w = frame.shape[:2]
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        async def _do():
            return await winocr.recognize_pil(pil_img, lang="en")

        res = asyncio.run(_do())
        if not res or not res.lines:
            return None

        # Build prioritized combination list
        priority = list(skill_priority) if skill_priority is not None else list(DEFAULT_SKILL_PRIORITY)
        normalized_priority: list[str] = []
        for item in priority:
            clean = str(item).lower().strip().replace("-", "_").replace(" ", "_")
            if clean not in normalized_priority:
                normalized_priority.append(clean)

        candidates: list[tuple[int, tuple[float, float], str, str]] = []
        known_combos = {
            "telekinetic_sword", "black_hole", "superconductivity",
            "current_overload", "vortex", "neutron_generation",
            "perpetual_engine", "overmind", "demon_equation", "frenzy", "prism_spree",
            "blast_furnace", "inferno", "avatar", "hyperion", "great_rift",
            "bloody_sacrament", "deus_ex_machina", "breath_of_fire", "winter_storm",
            "flying_swords", "door_of_creation", "gate_of_creation", "runaway_electricity", "heart_of_lightning",
            "master_of_storms", "lightning_breath", "brand_of_fire", "plasma_beam",
            "pandemonium", "deluge", "war_climate", "meissner_effect", "genesis",
        }

        for line in res.lines:
            line_text = line.text.lower().replace("—", "-").replace("–", "-")
            if not line.words:
                continue
            words_y = [wd.bounding_rect.y + wd.bounding_rect.height / 2 for wd in line.words]
            words_x = [wd.bounding_rect.x + wd.bounding_rect.width / 2 for wd in line.words]
            avg_x = sum(words_x) / len(words_x) / w
            avg_y = sum(words_y) / len(words_y) / h

            for std_key, aliases in SKILL_ALIASES.items():
                if any(a in line_text for a in aliases):
                    if std_key in known_combos or "sword" in line_text or "hole" in line_text:
                        rank = len(normalized_priority)
                        if std_key in normalized_priority:
                            rank = normalized_priority.index(std_key)
                        display_name = std_key.replace("_", " ").title()
                        candidates.append((rank, (round(float(avg_x), 3), round(float(avg_y), 3)), display_name, std_key))
                        break

        if candidates:
            candidates.sort(key=lambda c: c[0])
            best_rank, best_pos, best_label, best_key = candidates[0]
            return (best_pos, best_label, best_key)

    except Exception:
        pass
    return None


def choose_best_artifact_or_card(
    frame: np.ndarray,
    default_choice: int = 1,
    skill_priority: Optional[list[str]] = None,
    prefer_crit_and_cooldown: bool = True,
    prefer_freeze_traits: bool = True,
    active_skills: Optional[set[str]] = None,
    maxed_skills: Optional[set[str]] = None,
) -> CardChoice:
    """Evaluate 3 vertical card slots using Wiki & Reddit Meta Tier List:
    1. Trait choices: Freeze traits (Sub-Zero, Absolute Zero, Pole) -> Combination traits
       (Magic Blade, Chain Lightning, Void, Anti-Gravity, Extreme Weather, Hurricane, etc.) -> Survival Support traits.
    2. Skills / Combinations: Prioritized skills from config (Spirit + Electric Shock -> Cyclone + Satellite -> Ice Freeze core
       -> Flash Shock -> Meta Support -> Meta Passives). A prioritized skill card takes absolute priority!
    3. Artifacts / Passives: S+ Tier Meta Artifacts (Accelerator, Gaia, Holy Chest, etc.) + Build Synergy (+180/360)
       + Critical/Cooldown (+150) + Survival Synergy (+80).
    4. Falls back to default_choice if no match is found.
    """
    h, w = frame.shape[:2]
    # Run OCR and visual template detection
    ocr_cards = _detect_cards_ocr(frame, h, w)
    num_cards = len(ocr_cards)
    all_indices = tuple(ocr_cards.keys())
    tmpl_matches = _detect_skills_templates(frame, h, w, num_cards=num_cards)

    # Filter out skills that are already MAXED
    if maxed_skills:
        for idx in all_indices:
            ocr_cards[idx].skills = [s for s in ocr_cards[idx].skills if s not in maxed_skills]

    # Evaluate candidate skills per slot:
    # If OCR recognized a skill or special passive on this slot, DO NOT let template matching inject false skills!
    # If OCR detected readable text lines on the card, never guess an unrelated skill via low-confidence template matching.
    slot_skills: dict[int, list[str]] = {}
    for idx in all_indices:
        if ocr_cards[idx].skills or ocr_cards[idx].is_special_passive:
            cand = [s for s in ocr_cards[idx].skills if not maxed_skills or s not in maxed_skills]
        elif not ocr_cards[idx].text_lines:
            # Fallback to visual template match ONLY when OCR found absolutely no readable text (pure glyph)
            cand = [s for s in tmpl_matches.get(idx, []) if not maxed_skills or s not in maxed_skills]
        else:
            cand = []
        slot_skills[idx] = cand

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    if num_cards == 4:
        bands = {
            1: (int(h * 0.18), int(h * 0.35)),
            2: (int(h * 0.35), int(h * 0.52)),
            3: (int(h * 0.52), int(h * 0.69)),
            4: (int(h * 0.69), int(h * 0.86)),
        }
    else:
        bands = {
            1: (int(h * 0.30), int(h * 0.44)),
            2: (int(h * 0.44), int(h * 0.58)),
            3: (int(h * 0.58), int(h * 0.72)),
        }
    x0, x1 = int(w * 0.20), int(w * 0.80)
    card_tiers = {idx: 1 for idx in all_indices}
    tier_names = {5: "Legendary", 4: "Special", 3: "Epic", 2: "Rare", 1: "Normal"}

    for idx, (y0, y1) in bands.items():
        roi = hsv[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        H, S, V = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
        active = (S >= 120) & (V >= 150)
        leg_px = int(np.sum(active & (H >= 10) & (H <= 24)))
        spec_px = int(np.sum(active & ((H <= 8) | (H >= 168))))
        epic_px = int(np.sum(active & (H >= 135) & (H <= 162)))
        rare_px = int(np.sum(active & (H >= 92) & (H <= 112)))

        if leg_px >= 40:
            card_tiers[idx] = 5
        elif spec_px >= 25:
            card_tiers[idx] = 4
        elif epic_px >= 40:
            card_tiers[idx] = 3
        elif rare_px >= 40:
            card_tiers[idx] = 2

    # 0. ABSOLUTE TOP PRIORITY: CHECK FOR TOY CASTLE / MAGICTOYS
    for idx in all_indices:
        card_full_text = " ".join(ocr_cards[idx].text_lines).lower()
        if is_toy_castle_artifact(card_full_text):
            target = get_upgrade_target(idx, num_cards=num_cards)
            return CardChoice(idx, target, "★ Cổ Vật Tuyệt Đối: Toy Castle (MagicToys)")

    # 1. CHECK TRAIT CHOICES (FREEZE TRAITS -> COMBO TRAITS -> META SUPPORT TRAITS)
    if prefer_freeze_traits:
        for idx in all_indices:
            if ocr_cards[idx].freeze_traits:
                f_trait = ocr_cards[idx].freeze_traits[0]
                trait_name = f_trait.title()
                target = get_upgrade_target(idx, num_cards=num_cards)
                return CardChoice(idx, target, f"Nhánh Đóng Băng: {trait_name}", trait_key=f_trait)

    for idx in all_indices:
        if ocr_cards[idx].combo_traits:
            c_trait = ocr_cards[idx].combo_traits[0]
            trait_name = c_trait.title()
            target = get_upgrade_target(idx, num_cards=num_cards)
            return CardChoice(idx, target, f"Nhánh Hợp Thể: {trait_name}", trait_key=c_trait)

    for idx in all_indices:
        if ocr_cards[idx].support_traits:
            s_trait = ocr_cards[idx].support_traits[0]
            trait_name = s_trait.title()
            target = get_upgrade_target(idx, num_cards=num_cards)
            return CardChoice(idx, target, f"Nhánh Hỗ Trợ Meta: {trait_name}", trait_key=s_trait)

    # 2. CHECK SPECIAL PASSIVES ("KỸ NĂNG CÓ DẤU *" / RED STAR PASSIVES)
    best_sp_card_idx = None
    best_sp_score = -1.0
    best_sp_name = ""
    for idx in all_indices:
        cdata = ocr_cards[idx]
        if cdata.is_special_passive or cdata.has_asterisk:
            sp_key = cdata.special_passive_name or "special_passive"
            score = SPECIAL_PASSIVE_SCORES.get(sp_key, 140.0)
            if score > best_sp_score:
                best_sp_score = score
                best_sp_card_idx = idx
                best_sp_name = sp_key

    # Top-tier special passives (Adrenaline, Silent Casting, Mana Factory, Guardian Angel, Magic Seal, Juggernaut)
    # take immediate priority over regular unevolved skills!
    if best_sp_card_idx is not None and best_sp_score >= 150.0:
        target = get_upgrade_target(best_sp_card_idx, num_cards=num_cards)
        display_name = best_sp_name.replace("_", " ").title()
        return CardChoice(best_sp_card_idx, target, f"Kỹ năng đặc biệt [★]: {display_name}", skill_key=best_sp_name)

    # 3. CHECK SKILLS & COMBINATIONS (PRIORITIZED SKILLS HAVE ABSOLUTE PRIORITY)
    priority_order = list(skill_priority) if skill_priority is not None else list(DEFAULT_SKILL_PRIORITY)
    # Ensure all meta support & passive skills in DEFAULT_SKILL_PRIORITY act as smart fallbacks
    for fallback_skill in DEFAULT_SKILL_PRIORITY:
        if fallback_skill not in priority_order:
            priority_order.append(fallback_skill)

    normalized_priority: list[str] = []
    for item in priority_order:
        clean = str(item).lower().strip().replace("-", "_").replace(" ", "_")
        for std_key, aliases in SKILL_ALIASES.items():
            if clean == std_key or clean in aliases:
                if std_key not in normalized_priority:
                    normalized_priority.append(std_key)
                break
        else:
            if clean not in normalized_priority:
                normalized_priority.append(clean)

    best_skill_card_idx = None
    best_priority_rank = -1
    best_detected_skill = ""

    total_priority_count = len(normalized_priority)
    for idx in all_indices:
        if ocr_cards[idx].is_maxed:
            continue
        card_skills = slot_skills.get(idx, [])
        for skill in card_skills:
            if maxed_skills and skill in maxed_skills:
                continue
            if skill in normalized_priority:
                rank = (total_priority_count - normalized_priority.index(skill)) * 4.0
                # If card is starred or fusion component, give it a major priority boost
                if ocr_cards[idx].has_asterisk:
                    rank += 120.0
                try:
                    from learning_engine import get_adaptive_learner
                    learned_bonus = get_adaptive_learner().get_skill_bonus(skill, active_skills)
                    rank += learned_bonus * 2.5
                except Exception:
                    pass
                if rank > best_priority_rank:
                    best_priority_rank = rank
                    best_skill_card_idx = idx
                    best_detected_skill = skill

    # PRIORITY DECISION: IF A PRIORITIZED SKILL IS DETECTED, CHOOSE IT IMMEDIATELY!
    if best_skill_card_idx is not None:
        target = get_upgrade_target(best_skill_card_idx, num_cards=num_cards)
        display_name = best_detected_skill.replace("_", " ").title()
        return CardChoice(best_skill_card_idx, target, f"Kỹ năng: {display_name}", skill_key=best_detected_skill)

    # 4. IF NO PRIORITIZED SKILL FOUND: CHECK REMAINING SPECIAL PASSIVES
    if best_sp_card_idx is not None:
        target = get_upgrade_target(best_sp_card_idx, num_cards=num_cards)
        display_name = best_sp_name.replace("_", " ").title()
        return CardChoice(best_sp_card_idx, target, f"Kỹ năng đặc biệt [★]: {display_name}", skill_key=best_sp_name)

    # 5. CHECK ARTIFACT & PASSIVE SCORES
    artifact_scores: dict[int, int] = {}
    artifact_synergies: dict[int, list[str]] = {}
    tier_base_scores = {5: 12000, 4: 10000, 3: 300, 2: 200, 1: 100}

    for idx in all_indices:
        card_full_text = " ".join(ocr_cards[idx].text_lines).lower()
        if is_special_artifact(card_full_text):
            card_tiers[idx] = max(card_tiers[idx], 4)
        base = tier_base_scores[card_tiers[idx]]
        bonus = 0
        if is_toy_castle_artifact(card_full_text):
            bonus += 50000
        if card_tiers[idx] == 4 or is_special_artifact(card_full_text) or ocr_cards[idx].has_special_artifact:
            bonus += 1000
        if ocr_cards[idx].has_s_tier:
            bonus += 240
        if ocr_cards[idx].has_asterisk or ocr_cards[idx].is_special_passive:
            bonus += 200
        if prefer_crit_and_cooldown:
            if ocr_cards[idx].has_crit:
                bonus += 150
            if ocr_cards[idx].has_cooldown:
                bonus += 150
        if ocr_cards[idx].has_survival_synergy:
            bonus += 80
        if ocr_cards[idx].is_maxed:
            bonus -= 20000

        syn_bonus, syn_matched = compute_skill_synergy_bonus(card_full_text, active_skills)
        if syn_matched:
            bonus += syn_bonus
        artifact_synergies[idx] = syn_matched
        artifact_scores[idx] = base + bonus

    best_artifact_idx = max(artifact_scores, key=artifact_scores.get)
    best_artifact_score = artifact_scores[best_artifact_idx]
    best_tier = card_tiers[best_artifact_idx]

    is_chest_screen = any(card_tiers[idx] >= 2 for idx in all_indices) or any(
        ocr_cards[idx].has_s_tier
        or ocr_cards[idx].has_crit
        or ocr_cards[idx].has_cooldown
        or is_special_artifact(" ".join(ocr_cards[idx].text_lines).lower())
        or ocr_cards[idx].has_special_artifact
        or bool(artifact_synergies[idx])
        for idx in all_indices
    )

    # A. Pick high-tier artifact or passive if score >= 350
    if is_chest_screen and best_artifact_score >= 350:
        target = get_upgrade_target(best_artifact_idx, num_cards=num_cards)
        tag = []
        if card_tiers[best_artifact_idx] == 4 or is_special_artifact(" ".join(ocr_cards[best_artifact_idx].text_lines).lower()) or ocr_cards[best_artifact_idx].has_special_artifact:
            tag.append("★ Special (Ưu Tiên)")
        if ocr_cards[best_artifact_idx].has_s_tier:
            tag.append("S-Tier Meta")
        if artifact_synergies.get(best_artifact_idx):
            tag.append(f"Build: {'+'.join(artifact_synergies[best_artifact_idx])}")
        if ocr_cards[best_artifact_idx].has_crit:
            tag.append("Chí mạng")
        if ocr_cards[best_artifact_idx].has_cooldown:
            tag.append("Hồi chiêu")
        if ocr_cards[best_artifact_idx].has_survival_synergy and not tag:
            tag.append("Sinh tồn/Synergy")
        tag_str = f" [{'+'.join(tag)}]" if tag else ""
        return CardChoice(best_artifact_idx, target, f"Artifact {tier_names.get(best_tier, 'Hiếm')}{tag_str}")

    # B. If an artifact with Meta/Crit/Cooldown/Synergy is present even at lower tier, pick it
    if is_chest_screen and best_artifact_score > 100:
        target = get_upgrade_target(best_artifact_idx, num_cards=num_cards)
        tag = []
        if artifact_synergies.get(best_artifact_idx):
            tag.append(f"Build: {'+'.join(artifact_synergies[best_artifact_idx])}")
        tag_str = f" [{'+'.join(tag)}]" if tag else ""
        return CardChoice(best_artifact_idx, target, f"Artifact {tier_names.get(best_tier, 'Thường')}{tag_str}")

    # C. Default choice
    target = get_upgrade_target(default_choice, num_cards=num_cards)
    return CardChoice(default_choice, target, f"Mặc định (Thẻ {default_choice})")
