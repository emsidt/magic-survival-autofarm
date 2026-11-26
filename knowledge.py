"""Truy cập tri thức game (game_knowledge.json): phép kết hợp, synergy cổ vật, Subject, công thức chỉ số.

Chỉ đọc dữ liệu; không phụ thuộc vào botcore để tránh vòng import.
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

KNOWLEDGE_PATH = Path(__file__).resolve().parent / "game_knowledge.json"

# Điểm thưởng khi một cổ vật giúp tiến tới / hoàn thành synergy cổ vật (cùng thang với tier_base của botcore)
SYNERGY_COMPLETE_BONUS = 2500
SYNERGY_PROGRESS_BONUS = 400      # mỗi cổ vật cùng bộ đã có
SYNERGY_PROGRESS_CAP = 1200
SYNERGY_POTENTIAL_BONUS = 60      # là thành phần của một synergy nhưng chưa có cổ vật nào khác

_owned: set[str] = set()


def norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", str(text).lower())


@lru_cache(maxsize=1)
def load_knowledge() -> dict[str, Any]:
    try:
        return json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------- Cổ vật đã sở hữu trong ván
def artifact_name_from_label(label: str) -> str:
    """'Opulence [Legendary | ...]' -> 'Opulence'."""
    return str(label).split("[", 1)[0].strip()


def remember_artifact(label_or_name: str) -> Optional[str]:
    """Ghi nhận một cổ vật vừa nhận/mua. Trả về tên chuẩn hoá nếu nhận ra được."""
    canon = canonical_artifact(artifact_name_from_label(label_or_name))
    if canon:
        _owned.add(canon)
    return canon


def seed_subject_artifact(subject_name: Optional[str]) -> Optional[str]:
    """Ghi nhận cổ vật khởi đầu của Subject đang chọn (nếu cổ vật đó thuộc một synergy)."""
    if not subject_name:
        return None
    info = subject_info(subject_name)
    if info and info.get("artifact"):
        return remember_artifact(info["artifact"])
    return None


def reset_owned_artifacts(subject_name: Optional[str] = None) -> None:
    _owned.clear()
    if subject_name:
        seed_subject_artifact(subject_name)


def owned_artifacts() -> set[str]:
    return set(_owned)


# ---------------------------------------------------------------- Synergy cổ vật
@lru_cache(maxsize=1)
def _synergy_data() -> tuple[list[dict[str, Any]], dict[str, str]]:
    syns = load_knowledge().get("artifact_synergies", {}).get("unique", [])
    display: dict[str, str] = {}
    for s in syns:
        for c in s.get("components", []):
            display[norm(c)] = c
    return syns, display


@lru_cache(maxsize=1)
def _all_artifact_names() -> frozenset[str]:
    arts = load_knowledge().get("artifacts", {})
    names = {norm(a.get("name", "")) for group in arts.values() for a in group}
    names.discard("")
    return frozenset(names)


def canonical_artifact(name: str, cutoff: float = 0.84) -> Optional[str]:
    """Khớp (mờ) tên OCR với tên cổ vật; chỉ trả về khoá chuẩn hoá nếu cổ vật đó thuộc một synergy, ngược lại None.

    Khớp với TẤT CẢ 181 cổ vật trước rồi mới xét synergy, để 'Lightning Rod' không bị nhầm thành 'Lightning'.
    """
    n = norm(name)
    if len(n) < 3:
        return None
    _, display = _synergy_data()
    pool = _all_artifact_names() | set(display)
    best = n if n in pool else (difflib.get_close_matches(n, list(pool), n=1, cutoff=cutoff) or [None])[0]
    return best if best in display else None


def artifact_synergy_bonus(artifact_name: str, owned: Optional[set[str]] = None) -> tuple[int, str]:
    """Điểm cộng cho cổ vật `artifact_name` dựa trên các cổ vật đã có. Trả về (điểm, nhãn)."""
    cand = canonical_artifact(artifact_name_from_label(artifact_name))
    if not cand:
        return 0, ""
    have_all = _owned if owned is None else owned
    if cand in have_all:
        return 0, ""  # đã có rồi, không thêm giá trị synergy
    syns, _ = _synergy_data()
    best_key = (-1, -10**6)
    best = (0, "")
    for s in syns:
        comps = [norm(c) for c in s.get("components", [])]
        if cand not in comps:
            continue
        have = sum(1 for c in comps if c != cand and c in have_all)
        need_after = len(comps) - 1 - have
        if need_after == 0:
            bonus, tag = SYNERGY_COMPLETE_BONUS, f"⚡ Hoàn thành Synergy {s['name']} ({len(comps)}/{len(comps)})"
        elif have >= 1:
            bonus = min(SYNERGY_PROGRESS_CAP, SYNERGY_PROGRESS_BONUS * have)
            tag = f"Synergy {s['name']} {have + 1}/{len(comps)}"
        else:
            bonus, tag = SYNERGY_POTENTIAL_BONUS, f"Synergy {s['name']} 1/{len(comps)}"
        key = (bonus, -need_after)
        if key > best_key:
            best_key = key
            best = (bonus, tag)
    return best


# ---------------------------------------------------------------- Phép kết hợp (fusion)
@lru_cache(maxsize=1)
def _fusion_index() -> list[dict[str, Any]]:
    return list(load_knowledge().get("magic_combinations", []))


def find_fusions(skill_a: str, skill_b: str = "") -> list[dict[str, Any]]:
    """Các fusion dùng skill_a (và skill_b nếu có) làm nguyên liệu. Tên so khớp không phân biệt hoa/thường/ký tự lạ."""
    a, b = norm(skill_a), norm(skill_b)
    out = []
    for f in _fusion_index():
        names = {norm(f["primary"]["skill"]), norm(f["secondary"]["skill"])}
        if a in names and (not b or b in names):
            out.append(f)
    return out


def fusion_by_name(name: str) -> Optional[dict[str, Any]]:
    n = norm(name)
    return next((f for f in _fusion_index() if norm(f["name"]) == n), None)


# ---------------------------------------------------------------- Subject
def subject_info(name: str) -> Optional[dict[str, Any]]:
    n = norm(name)
    return next((s for s in load_knowledge().get("subjects", {}).get("list", []) if norm(s["name"]) == n), None)


# ---------------------------------------------------------------- Nhóm chỉ số
def stat_groups_in_text(text: str) -> list[str]:
    """Nhóm chỉ số (cooldown, amplify, atk...) mà một đoạn mô tả cổ vật tác động tới."""
    t = str(text).lower()
    found = []
    for group, kws in load_knowledge().get("stat_mechanics", {}).get("keywords", {}).items():
        if any(k in t for k in kws):
            found.append(group)
    return found
