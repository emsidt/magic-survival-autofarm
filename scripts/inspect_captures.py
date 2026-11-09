"""Script to inspect, classify, and label all images in captures/ according to Step 0 of KE_HOACH_AI.md."""

from __future__ import annotations

import json
from pathlib import Path
import cv2

import sys
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
import botcore

CAPTURES_DIR = BASE_DIR / "captures"
MANIFEST_PATH = CAPTURES_DIR / "manifest.json"


def classify_image(path: Path) -> dict:
    frame = cv2.imread(str(path))
    if frame is None:
        return {"file": path.name, "error": "cannot_read"}

    h, w = frame.shape[:2]
    res = {
        "file": path.name,
        "width": w,
        "height": h,
        "aspect_ratio": round(w / h, 3),
        "detected_scenes": [],
        "combination_star": None,
    }

    # 1. Level up screen
    is_lvl, lvl_reason = botcore.is_level_up_screen(frame)
    if is_lvl:
        res["detected_scenes"].append(f"level_up ({lvl_reason})")
        star_coord = botcore.detect_combination_star(frame)
        res["combination_star"] = "RED (Active)" if star_coord else "INACTIVE/GREY/NONE"

    # 2. Chest / Obtain button
    obtain_pos = botcore.detect_obtain_button(frame)
    if obtain_pos:
        is_3card = botcore.is_three_card_chest(frame, obtain_pos[0])
        res["detected_scenes"].append(f"chest_obtain (3_card={is_3card})")

    # 3. Confirm button (Endgame / Results)
    confirm_pos = botcore.detect_confirm_button(frame)
    if confirm_pos:
        res["detected_scenes"].append("endgame_results (Confirm)")

    # 4. Enter Area / Selected (Lobby)
    ea_pos = botcore.detect_enter_area(frame)
    if ea_pos:
        res["detected_scenes"].append("lobby (Enter Area)")
    sel_pos = botcore.detect_selected(frame)
    if sel_pos:
        res["detected_scenes"].append("lobby (Selected)")

    # 5. Ad close X button
    close_pos = botcore.detect_close_button(frame)
    if close_pos:
        res["detected_scenes"].append(f"ad_screen (X at {close_pos})")

    # 6. Monolith
    mono_pos = botcore.detect_monolith(frame)
    if mono_pos:
        res["detected_scenes"].append(f"monolith_milestone at {mono_pos}")

    # 7. In-game gameplay inspection
    vis = botcore.inspect_game(frame, (0.5, 0.5))
    if vis.gameplay:
        res["detected_scenes"].append(f"active_gameplay (gems={len(vis.gems)}, chest={vis.chest is not None})")

    if not res["detected_scenes"]:
        res["detected_scenes"].append("uncategorized / crop / debug")

    return res


def main():
    if not CAPTURES_DIR.is_dir():
        print(f"Directory {CAPTURES_DIR} does not exist.")
        return

    images = sorted([p for p in CAPTURES_DIR.glob("*.*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
    print(f"Found {len(images)} images in captures/. Classifying...")

    manifest = []
    for p in images:
        manifest.append(classify_image(p))

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Classification complete! Manifest saved to {MANIFEST_PATH}")
    # Print summary
    scene_counts: dict[str, int] = {}
    for item in manifest:
        for s in item.get("detected_scenes", []):
            base_s = s.split()[0]
            scene_counts[base_s] = scene_counts.get(base_s, 0) + 1

    print("\nSummary of capture classifications:")
    for scene, count in sorted(scene_counts.items(), key=lambda x: -x[1]):
        print(f"  - {scene}: {count} images")


if __name__ == "__main__":
    main()
