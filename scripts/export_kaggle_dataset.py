"""Export local Magic Survival gameplay logs & screenshots into a Kaggle-ready Dataset.

Creates `data/kaggle_magic_survival_dataset.zip` containing:
1. `vocab.json`: Canonical skill list, screen classes, card classes, fusion recipes.
2. `skill_decisions.csv`: Step-by-step skill selection records (state, chosen skill, rejected skills, survival outcome).
3. `run_summaries.csv`: Match-level survival duration, kills, skill sets, and rewards.
4. `vision_screens.csv` + `images/screens/*.jpg`: Downscaled 96x160 full-screen thumbnails for Screen Classification CNN.
5. `vision_cards.csv` + `images/cards/<skill_key>/*.jpg`: Cropped 192x64 card slot images for Card Skill Recognition CNN.
"""
from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

import cv2

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ai_inference import FUSION_PARTNERS, crop_card_slots
import botcore

DATA_DIR = BASE_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"
HISTORY_FILE = DATA_DIR / "learning_history.json"
EXPORT_DIR = DATA_DIR / "kaggle_export"
ZIP_PATH = DATA_DIR / "kaggle_magic_survival_dataset.zip"

SCREEN_SIZE_WH = (96, 160)  # 9:16 portrait thumbnail
CARD_SIZE_WH = (192, 64)    # Card slot banner aspect


def _parse_survival_str(val: object) -> float:
    """Convert '11:06' or numeric seconds into float seconds."""
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str) or not val.strip():
        return 0.0
    s = val.strip()
    m = re.match(r"^(\d{1,3}):(\d{2})$", s)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2)))
    try:
        return float(s)
    except ValueError:
        return 0.0


def _build_canonical_vocab() -> list[str]:
    skills = set(botcore.SKILL_ALIASES.keys()) | set(botcore.SPECIAL_STAR_PASSIVES.keys())
    return sorted(skills)


def _normalize_skill_name(raw: object, canonical_set: set[str]) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    s = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if s in canonical_set:
        return s
    for std_key, aliases in botcore.SKILL_ALIASES.items():
        if s == std_key or raw.strip().lower() in aliases:
            return std_key
    for sp_key, aliases in botcore.SPECIAL_STAR_PASSIVES.items():
        if s == sp_key or raw.strip().lower() in aliases:
            return sp_key
    return ""


def export_dataset() -> Path:
    if EXPORT_DIR.exists():
        shutil.rmtree(EXPORT_DIR)
    screens_img_dir = EXPORT_DIR / "images" / "screens"
    cards_img_dir = EXPORT_DIR / "images" / "cards"
    screens_img_dir.mkdir(parents=True, exist_ok=True)
    cards_img_dir.mkdir(parents=True, exist_ok=True)

    vocab = _build_canonical_vocab()
    canonical_set = set(vocab)

    # 1. Load learning_history.json for run survival outcomes
    history_by_run: dict[str, dict] = {}
    if HISTORY_FILE.is_file():
        try:
            hist_list = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            for item in hist_list:
                if isinstance(item, dict) and item.get("run_id"):
                    history_by_run[str(item["run_id"])] = item
        except Exception as e:
            print(f"[WARN] Could not parse learning_history.json: {e}")

    skill_rows: list[dict] = []
    run_rows: list[dict] = []
    screen_rows: list[dict] = []
    card_rows: list[dict] = []

    card_class_counts: dict[str, int] = {}
    screen_class_counts: dict[str, int] = {}

    run_dirs = sorted(RUNS_DIR.glob("run_*")) if RUNS_DIR.is_dir() else []
    print(f"[*] Scanning {len(run_dirs)} run folders in {RUNS_DIR} ...")

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        dec_file = run_dir / "decisions.jsonl"
        sum_file = run_dir / "summary.json"

        summary_data = {}
        if sum_file.is_file():
            try:
                summary_data = json.loads(sum_file.read_text(encoding="utf-8"))
            except Exception:
                summary_data = {}

        hist_data = history_by_run.get(run_id, {})
        survival_sec = float(hist_data.get("survival_sec") or _parse_survival_str(summary_data.get("survival_time")) or 0.0)
        kills = int(hist_data.get("kills") or summary_data.get("kills") or 0)
        is_human = bool(hist_data.get("is_human") or (survival_sec >= 1200.0))

        decisions = []
        if dec_file.is_file():
            for line in dec_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip():
                    try:
                        decisions.append(json.loads(line))
                    except Exception:
                        pass

        # Estimate survival time from timestamps if summary_data was not written
        if survival_sec <= 10.0 and len(decisions) >= 4:
            try:
                t0 = datetime.fromisoformat(decisions[0]["timestamp"])
                t1 = datetime.fromisoformat(decisions[-1]["timestamp"])
                est = (t1 - t0).total_seconds()
                if 30.0 <= est <= 7200.0:
                    survival_sec = round(est, 1)
            except Exception:
                pass

        if any(d.get("screen_type") in ("human_level_up", "human_shop_buy") for d in decisions):
            is_human = True
            if survival_sec < 600.0:
                survival_sec = max(survival_sec, 1200.0)

        # Track running active skills and levels across the run
        running_active: set[str] = set()
        running_levels: dict[str, int] = {}

        for d in decisions:
            step = int(d.get("step", 1))
            screen_type = str(d.get("screen_type", "unknown"))
            action = str(d.get("action", ""))
            img_name = str(d.get("image", ""))
            details = d.get("details") or {}

            # Normalize screen_type for screen classification
            clean_screen = "level_up" if screen_type in ("level_up", "human_level_up") else (
                "shop" if screen_type in ("shop", "human_shop_buy") else screen_type
            )

            img_path = run_dir / img_name if img_name else None
            frame = None
            if img_path and img_path.is_file():
                frame = cv2.imread(str(img_path))

            # 1. Export full-screen thumbnail for Screen Classifier
            if frame is not None and frame.size > 0:
                thumb = cv2.resize(frame, SCREEN_SIZE_WH, interpolation=cv2.INTER_AREA)
                out_screen_name = f"{run_id}_s{step:04d}_{clean_screen}.jpg"
                out_screen_rel = f"images/screens/{out_screen_name}"
                cv2.imwrite(str(EXPORT_DIR / out_screen_rel), thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                screen_rows.append({
                    "image_path": out_screen_rel,
                    "label": clean_screen,
                    "original_screen_type": screen_type,
                    "run_id": run_id,
                    "step": step,
                })
                screen_class_counts[clean_screen] = screen_class_counts.get(clean_screen, 0) + 1

            # 2. Extract skill choice and card crops on level_up / human_level_up
            if clean_screen == "level_up":
                raw_skill = details.get("skill_key") or details.get("chosen_skill") or ""
                chosen_skill = _normalize_skill_name(raw_skill, canonical_set)

                chosen_slot = 0
                if action.startswith("card_"):
                    try:
                        chosen_slot = int(action.split("_")[1])
                    except ValueError:
                        chosen_slot = 0
                elif isinstance(details.get("chosen_card"), int):
                    chosen_slot = int(details["chosen_card"])

                offered_map: dict[int, list[str]] = {}
                raw_offered = details.get("offered_cards")
                if isinstance(raw_offered, dict):
                    for k_str, v_list in raw_offered.items():
                        try:
                            s_idx = int(k_str)
                        except ValueError:
                            continue
                        if isinstance(v_list, list):
                            norm_list = [
                                _normalize_skill_name(x, canonical_set)
                                for x in v_list
                            ]
                            offered_map[s_idx] = [x for x in norm_list if x]

                if chosen_slot > 0 and chosen_skill and chosen_slot not in offered_map:
                    offered_map[chosen_slot] = [chosen_skill]
                elif chosen_slot > 0 and not chosen_skill and len(offered_map.get(chosen_slot, [])) == 1:
                    chosen_skill = offered_map[chosen_slot][0]

                # Export cropped card images whenever a card slot has a single unambiguous skill label
                if frame is not None and frame.size > 0:
                    num_cards = 4 if (4 in offered_map or chosen_slot == 4) else 3
                    crops = crop_card_slots(frame, num_cards=num_cards)
                    slot_labels: dict[int, str] = {}
                    for s_idx, sk_list in offered_map.items():
                        if len(sk_list) == 1:
                            slot_labels[s_idx] = sk_list[0]
                    if chosen_slot in crops and chosen_skill:
                        slot_labels[chosen_slot] = chosen_skill

                    for s_idx, sk_label in slot_labels.items():
                        if s_idx not in crops or not sk_label:
                            continue
                        sk_folder = cards_img_dir / sk_label
                        sk_folder.mkdir(parents=True, exist_ok=True)
                        card_thumb = cv2.resize(crops[s_idx], CARD_SIZE_WH, interpolation=cv2.INTER_AREA)
                        card_fname = f"{run_id}_s{step:04d}_c{s_idx}.jpg"
                        card_rel = f"images/cards/{sk_label}/{card_fname}"
                        cv2.imwrite(str(EXPORT_DIR / card_rel), card_thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                        card_rows.append({
                            "image_path": card_rel,
                            "label": sk_label,
                            "slot_idx": s_idx,
                            "is_chosen": 1 if s_idx == chosen_slot else 0,
                            "run_id": run_id,
                            "step": step,
                        })
                        card_class_counts[sk_label] = card_class_counts.get(sk_label, 0) + 1

                # Record decision row for Skill Selection AI
                if chosen_skill:
                    state_before = sorted(running_active)
                    levels_before = dict(running_levels)
                    offered_lvl = details.get("offered_level")
                    if not isinstance(offered_lvl, int):
                        offered_lvl = levels_before.get(chosen_skill, 0) + 1

                    # Rejected skills from other offered cards on the same screen
                    rejected: list[str] = []
                    for s_idx, sk_list in offered_map.items():
                        if s_idx != chosen_slot:
                            for sk in sk_list:
                                if sk and sk != chosen_skill and sk not in rejected:
                                    rejected.append(sk)

                    skill_rows.append({
                        "run_id": run_id,
                        "step": step,
                        "chosen_skill": chosen_skill,
                        "chosen_slot": chosen_slot,
                        "offered_level": offered_lvl,
                        "active_skills_json": json.dumps(state_before),
                        "skill_levels_json": json.dumps(levels_before),
                        "rejected_skills_json": json.dumps(rejected),
                        "survival_sec": round(survival_sec, 1),
                        "kills": kills,
                        "is_human": 1 if is_human else 0,
                    })

                    # Update running state
                    running_active.add(chosen_skill)
                    running_levels[chosen_skill] = min(10, offered_lvl)
                    if isinstance(details.get("active_skills"), list):
                        for sk_raw in details["active_skills"]:
                            norm_sk = _normalize_skill_name(sk_raw, canonical_set)
                            if norm_sk:
                                running_active.add(norm_sk)
                                running_levels.setdefault(norm_sk, 1)

            elif clean_screen == "combination_magic":
                combo_key = _normalize_skill_name(action, canonical_set)
                if combo_key:
                    running_active.add(combo_key)
                    running_levels[combo_key] = 7

        if running_active or survival_sec > 0:
            run_rows.append({
                "run_id": run_id,
                "survival_sec": round(survival_sec, 1),
                "kills": kills,
                "is_human": 1 if is_human else 0,
                "total_steps": len(decisions),
                "skills_json": json.dumps(sorted(running_active)),
                "skill_levels_json": json.dumps(running_levels),
                "source": "runs_dir",
            })

    # Also add any runs from learning_history.json not already in run_rows
    existing_run_ids = {r["run_id"] for r in run_rows}
    for r_id, h_item in history_by_run.items():
        if r_id in existing_run_ids:
            continue
        sk_list = [
            _normalize_skill_name(s, canonical_set)
            for s in h_item.get("skills", [])
        ]
        sk_list = [s for s in sk_list if s]
        surv = float(h_item.get("survival_sec", 0.0))
        is_hum = bool(h_item.get("is_human") or surv >= 1200.0)
        sk_lvls = h_item.get("skill_levels") or {s: 4 for s in sk_list}
        run_rows.append({
            "run_id": r_id,
            "survival_sec": round(surv, 1),
            "kills": int(h_item.get("kills", 0)),
            "is_human": 1 if is_hum else 0,
            "total_steps": len(sk_list) * 3,
            "skills_json": json.dumps(sorted(sk_list)),
            "skill_levels_json": json.dumps(sk_lvls),
            "source": "learning_history",
        })

    # Write CSVs and vocab.json
    def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    _write_csv(
        EXPORT_DIR / "skill_decisions.csv",
        skill_rows,
        [
            "run_id", "step", "chosen_skill", "chosen_slot", "offered_level",
            "active_skills_json", "skill_levels_json", "rejected_skills_json",
            "survival_sec", "kills", "is_human",
        ],
    )
    _write_csv(
        EXPORT_DIR / "run_summaries.csv",
        run_rows,
        ["run_id", "survival_sec", "kills", "is_human", "total_steps", "skills_json", "skill_levels_json", "source"],
    )
    _write_csv(
        EXPORT_DIR / "vision_screens.csv",
        screen_rows,
        ["image_path", "label", "original_screen_type", "run_id", "step"],
    )
    _write_csv(
        EXPORT_DIR / "vision_cards.csv",
        card_rows,
        ["image_path", "label", "slot_idx", "is_chosen", "run_id", "step"],
    )

    vocab_meta = {
        "vocab": vocab,
        "fusion_partners": {k: sorted(v) for k, v in FUSION_PARTNERS.items()},
        "screen_classes": sorted(screen_class_counts.keys()),
        "screen_class_counts": screen_class_counts,
        "card_classes": sorted(card_class_counts.keys()),
        "card_class_counts": card_class_counts,
        "screen_size_wh": list(SCREEN_SIZE_WH),
        "card_size_wh": list(CARD_SIZE_WH),
        "total_skill_decisions": len(skill_rows),
        "total_runs": len(run_rows),
        "total_screen_images": len(screen_rows),
        "total_card_images": len(card_rows),
    }
    (EXPORT_DIR / "vocab.json").write_text(json.dumps(vocab_meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Package into zip for Kaggle
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in EXPORT_DIR.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(EXPORT_DIR))

    zip_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print("=" * 65)
    print(f"[OK] Đã xuất Kaggle Dataset thành công: {ZIP_PATH} ({zip_mb:.2f} MB)")
    print(f"  - Số ván đấu (run_summaries.csv)     : {len(run_rows)} ván")
    print(f"  - Số bước chọn phép (skill_decisions): {len(skill_rows)} mẫu")
    print(f"  - Ảnh phân loại màn hình (96x160)    : {len(screen_rows)} ảnh ({len(screen_class_counts)} lớp)")
    print(f"  - Ảnh cắt thẻ kỹ năng (192x64)       : {len(card_rows)} ảnh ({len(card_class_counts)} kỹ năng)")
    print("=" * 65)
    return ZIP_PATH


if __name__ == "__main__":
    export_dataset()
