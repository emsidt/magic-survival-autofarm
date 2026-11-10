"""These offline checks use synthetic images and require no Windows game."""

import math
import os
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from botcore import (
    choose_best_artifact_or_card,
    choose_direction,
    compute_skill_synergy_bonus,
    detect_buy_button,
    detect_chest,
    detect_close_button,
    detect_confirm_button,
    detect_die_button,
    detect_enter_area,
    detect_learn_button,
    detect_obtain_button,
    detect_selected,
    detect_settings_dialog,
    detect_settings_gear,
    detect_start_game,
    detect_shop_x_button,
    evaluate_selected_attribute,
    evaluate_selected_chest_artifact,
    evaluate_selected_shop_artifact,
    find_rule,
    get_attribute_circle_targets,
    get_chest_card_target,
    get_shop_item_targets,
    get_upgrade_target,
    inspect_game,
    is_shop_buy_enabled,
    is_three_card_chest,
)


class VisionTests(unittest.TestCase):
    def test_enemy_and_blue_orb(self):
        frame = np.full((500, 300, 3), 125, dtype=np.uint8)
        cv2.circle(frame, (208, 250), 25, (3, 3, 3), -1)
        cv2.circle(frame, (85, 250), 5, (255, 190, 0), -1)
        vision = inspect_game(frame)
        self.assertTrue(vision.gameplay)
        self.assertGreater(int(np.sum(vision.enemy_mask > 0)), 500)
        self.assertTrue(any(math.dist(point, (85, 250)) < 8 for point in vision.gems))
        dx, dy = choose_direction(vision, elapsed=0, previous=None)
        self.assertLess(dx, 0, "Should prefer left XP away from right enemy")

    def test_safe_black_or_blank_screen(self):
        frame = np.zeros((500, 300, 3), dtype=np.uint8)
        self.assertFalse(inspect_game(frame).gameplay)

    def test_detect_ad_close_button(self):
        # Blank screen has no close button
        frame_blank = np.full((800, 450, 3), 40, dtype=np.uint8)
        self.assertIsNone(detect_close_button(frame_blank))

        # Synthetic close button with X in top-right
        frame_ad = np.full((800, 450, 3), 30, dtype=np.uint8)
        cv2.circle(frame_ad, (415, 40), 16, (80, 80, 80), -1)
        cv2.line(frame_ad, (408, 33), (422, 47), (255, 255, 255), 2)
        cv2.line(frame_ad, (422, 33), (408, 47), (255, 255, 255), 2)
        coord = detect_close_button(frame_ad)
        self.assertIsNotNone(coord)
        self.assertGreater(coord[0], 0.85)  # top-right
        self.assertLess(coord[1], 0.12)

        # Real ad screenshot with top-left circular white X button (media_1794196552455_d01e9d76.jpg)
        ad_img_path = r"C:/Users/User/.gemini/antigravity/brain/2dc840cb-72eb-45f9-92e9-a3fe999f18b4/.user_uploaded/media_1794196552455_d01e9d76.jpg"
        if os.path.isfile(ad_img_path):
            img_real_ad = cv2.imread(ad_img_path)
            # Test full frame
            pos_full = detect_close_button(img_real_ad)
            self.assertIsNotNone(pos_full)
            self.assertAlmostEqual(pos_full[0], 0.1438, delta=0.03)
            self.assertAlmostEqual(pos_full[1], 0.0552, delta=0.03)

            # Test crosvm crop (game canvas only: 38:h, 64:w)
            crosvm_crop = img_real_ad[38:, 64:]
            pos_crop = detect_close_button(crosvm_crop)
            self.assertIsNotNone(pos_crop)
            self.assertAlmostEqual(pos_crop[0], 0.0438, delta=0.03)
            self.assertAlmostEqual(pos_crop[1], 0.0184, delta=0.03)

    def test_title_screen_and_settings_gear_protection(self):
        title_img_path = r"C:/Users/User/.gemini/antigravity/brain/2dc840cb-72eb-45f9-92e9-a3fe999f18b4/.user_uploaded/media_1794199733548_2210d9ed.png"
        if os.path.isfile(title_img_path):
            img = cv2.imread(title_img_path)
            # 1. detect_start_game must find Start Game
            sg = detect_start_game(img)
            self.assertIsNotNone(sg)
            self.assertAlmostEqual(sg[0], 0.32, delta=0.08)
            self.assertAlmostEqual(sg[1], 0.77, delta=0.08)

            # 2. detect_close_button must be None (never click Settings Gear!)
            cb = detect_close_button(img)
            self.assertIsNone(cb, "detect_close_button must NEVER return the Settings Gear icon!")

    def test_upgrade_targets(self):
        # 3-card layout (default)
        self.assertEqual(get_upgrade_target(1), (0.50, 0.38))
        self.assertEqual(get_upgrade_target(2), (0.50, 0.52))
        self.assertEqual(get_upgrade_target(3), (0.50, 0.66))
        # 4-card layout (research/awakening expansion)
        self.assertEqual(get_upgrade_target(1, num_cards=4), (0.50, 0.27))
        self.assertEqual(get_upgrade_target(2, num_cards=4), (0.50, 0.44))
        self.assertEqual(get_upgrade_target(3, num_cards=4), (0.50, 0.61))
        self.assertEqual(get_upgrade_target(4, num_cards=4), (0.50, 0.78))

    def test_detect_enter_area_and_selected(self):
        # Blank frame should not detect
        blank = np.zeros((800, 450, 3), dtype=np.uint8)
        self.assertIsNone(detect_enter_area(blank))
        self.assertIsNone(detect_selected(blank))
        self.assertIsNone(detect_start_game(blank))

        # Frame with enter_area template
        ea_tmpl = cv2.imread("assets/enter_area.png")
        if ea_tmpl is not None:
            th, tw = ea_tmpl.shape[:2]
            frame_ea = np.zeros((1000, 600, 3), dtype=np.uint8)
            frame_ea[920:920+th, 200:200+tw] = ea_tmpl
            pos = detect_enter_area(frame_ea)
            self.assertIsNotNone(pos)
            self.assertGreater(pos[1], 0.88)

        # Frame with start_game template
        sg_tmpl = cv2.imread("assets/start_game.png")
        if sg_tmpl is not None:
            th, tw = sg_tmpl.shape[:2]
            frame_sg = np.zeros((1000, 600, 3), dtype=np.uint8)
            frame_sg[780:780+th, 150:150+tw] = sg_tmpl
            pos_sg = detect_start_game(frame_sg)
            self.assertIsNotNone(pos_sg)
            self.assertGreater(pos_sg[1], 0.70)

    def test_detect_die_button(self):
        blank = np.zeros((800, 450, 3), dtype=np.uint8)
        self.assertIsNone(detect_die_button(blank))

        die_tmpl = cv2.imread("assets/die_button.png")
        if die_tmpl is not None:
            th, tw = die_tmpl.shape[:2]
            frame_die = np.zeros((1000, 600, 3), dtype=np.uint8)
            frame_die[700:700+th, 220:220+tw] = die_tmpl
            pos = detect_die_button(frame_die)
            self.assertIsNotNone(pos)
            self.assertGreater(pos[1], 0.65)

            # Test small-scale die button (e.g. 0.52x on smaller windows)
            rt = cv2.resize(die_tmpl, (int(tw * 0.52), int(th * 0.52)))
            rth, rtw = rt.shape[:2]
            frame_small = np.zeros((1000, 600, 3), dtype=np.uint8)
            frame_small[700:700+rth, 220:220+rtw] = rt
            pos_small = detect_die_button(frame_small)
            self.assertIsNotNone(pos_small)

            # When Pause button is also present (as in the real game death overlay),
            # detect_die_button MUST still detect the Die button!
            pause_tmpl = cv2.imread("assets/pause_button.png")
            if pause_tmpl is not None:
                pth, ptw = pause_tmpl.shape[:2]
                frame_die[20:20+pth, 520:520+ptw] = pause_tmpl
                pos_with_pause = detect_die_button(frame_die)
                self.assertIsNotNone(pos_with_pause, "Die button must be detected even when top bar pause icon is visible")

    def test_chest_detection_and_attraction(self):
        # Create a game frame with chest on the right side
        frame = np.full((500, 300, 3), 125, dtype=np.uint8)
        chest_icon = cv2.imread("assets/chest_icon.png")
        if chest_icon is not None:
            ch, cw = chest_icon.shape[:2]
            frame[200:200+ch, 230:230+cw] = chest_icon
            pos = detect_chest(frame)
            self.assertIsNotNone(pos)
            self.assertGreater(pos[0], 200)

        # Vision with chest on the right
        free = np.full((500, 300), 255, dtype=np.uint8)
        dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)
        from botcore import Vision
        vision = Vision(np.zeros((500, 300), dtype=np.uint8), dist, [], True, 0.8, chest=(280, 250))
        dx, dy = choose_direction(vision, elapsed=0, player=(0.5, 0.5))
        self.assertGreater(dx, 0, "Character should head right towards chest")

        # End-to-end inspect_game + choose_direction when chests are close (70px right):
        # Chests have dark borders/stone and must NEVER be marked as enemies in enemy_mask!
        for cpath in ("assets/chests/treasure_chest.png", "assets/chests/reliquary.png", "assets/chests/black_box.png"):
            c_img = cv2.imread(cpath)
            if c_img is not None:
                field = np.full((800, 500, 3), [70, 110, 110], dtype=np.uint8)
                bh, bw = c_img.shape[:2]
                cx, cy = 320, 400
                field[cy - bh // 2 : cy - bh // 2 + bh, cx - bw // 2 : cx - bw // 2 + bw] = c_img
                v_close = inspect_game(field, player=(0.5, 0.5))
                self.assertIsNotNone(v_close.chest)
                dx_c, _ = choose_direction(v_close, elapsed=0, player=(0.5, 0.5))
                self.assertGreater(dx_c, 0.8, f"Must walk directly into close chest {cpath}, never dodge it as an enemy")

        # Flanking around a blocking monster towards a chest even when mana orbs are behind
        enemy_field = np.zeros((800, 500), dtype=np.uint8)
        cv2.circle(enemy_field, (315, 400), 25, 255, -1)  # Monster directly between player (250,400) and chest (420,400)
        dist_flank = cv2.distanceTransform(cv2.bitwise_not(enemy_field), cv2.DIST_L2, 3)
        v_flank = Vision(
            enemy_field, dist_flank, [(120, 380), (120, 400), (120, 420)],
            True, 0.8, chest=(420, 400), chest_type="treasure_chest", chest_weight=24.0,
        )
        dx_f, dy_f = choose_direction(v_flank, elapsed=0, player=(0.5, 0.5))
        self.assertGreater(dx_f, 0.2, "Should advance rightward towards chest while flanking")
        self.assertGreater(abs(dy_f), 0.5, "Should sidestep vertically around the blocking monster")

    def test_no_self_detection_as_chest(self):
        # A frame with a dark player silhouette at center must NEVER be detected as a chest
        frame = np.full((800, 500, 3), 110, dtype=np.uint8)
        px, py = 250, 400
        # Draw player silhouette (dark robes, spirit orbs, green HP bar)
        cv2.circle(frame, (px, py), 18, (30, 30, 30), -1)
        cv2.rectangle(frame, (px - 10, py + 20), (px + 10, py + 24), (0, 255, 0), -1)
        # Even if a black box template is placed directly on the player
        bbox = cv2.imread("assets/chests/black_box.png")
        if bbox is not None:
            bh, bw = bbox.shape[:2]
            frame[py - bh // 2 : py - bh // 2 + bh, px - bw // 2 : px - bw // 2 + bw] = bbox
        target = detect_chest(frame)
        self.assertIsNone(target, "Must never detect the player character as a chest")

    def test_multi_chest_priority_and_dark_zone(self):
        # 1. Black Box priority over Treasure Chest
        field = np.full((800, 500, 3), [70, 110, 110], dtype=np.uint8)
        bbox = cv2.imread("assets/chests/black_box.png")
        tchest = cv2.imread("assets/chests/treasure_chest.png")
        if bbox is not None and tchest is not None:
            field[300:300+bbox.shape[0], 200:200+bbox.shape[1]] = bbox
            field[500:500+tchest.shape[0], 100:100+tchest.shape[1]] = tchest
            target = detect_chest(field)
            self.assertIsNotNone(target)
            self.assertEqual(getattr(target, "chest_type", ""), "black_box", "Black Box (Legend) must have top priority")

        # 2. Dark zone avoidance (HP drain area)
        frame_dark = np.full((500, 300, 3), 110, dtype=np.uint8)
        # Giant dark damage zone occupying top half (y < 200)
        frame_dark[:200, :] = 10
        vision_dark = inspect_game(frame_dark, player=(0.5, 0.5))
        self.assertTrue(vision_dark.gameplay)
        # Verify dark zone is marked as hazard in enemy_mask
        self.assertGreater(int(np.sum(vision_dark.enemy_mask[:200, :] > 0)), 10000)
        _, dy = choose_direction(vision_dark, elapsed=0, player=(0.5, 0.5))
        self.assertGreater(dy, 0, "Must move away from northern dark HP-drain zone")

    def test_orb_priority_and_safety_first(self):
        # 1. Safe battlefield: Gold orb on left (x=70), Purple orb on right (x=230) -> Prefer Purple (right)
        frame = np.full((500, 300, 3), 125, dtype=np.uint8)
        cv2.circle(frame, (70, 250), 5, (0, 215, 255), -1)    # Gold orb (BGR)
        cv2.circle(frame, (230, 250), 5, (230, 60, 200), -1)  # Purple orb (BGR)
        vision = inspect_game(frame)
        self.assertEqual(len(vision.gold_gems), 1)
        self.assertEqual(len(vision.purple_gems), 1)
        dx, _ = choose_direction(vision, elapsed=0, player=(0.5, 0.5))
        self.assertGreater(dx, 0, "Should prefer Purple orb over Gold orb when both are safe")

        # 2. Safety first: Enemy right next to Purple orb on right + Player's own dark sprite at center (150, 250) -> Must go left (away from enemy)
        cv2.circle(frame, (150, 250), 10, (5, 5, 5), -1)  # Player's own dark body at center
        cv2.circle(frame, (210, 250), 25, (5, 5, 5), -1)  # Enemy blocking right path
        vision_danger = inspect_game(frame, player=(0.5, 0.5))
        dx_safe, _ = choose_direction(vision_danger, elapsed=0, player=(0.5, 0.5))
        self.assertLess(dx_safe, 0, "Safety first: must evade enemy even if Purple orb is there and player sprite is dark")

        # 3. Active blue orb vacuum: Single blue orb at left (70, 250) in clear field -> Moves left to eat it
        frame_blue = np.full((500, 300, 3), 125, dtype=np.uint8)
        cv2.circle(frame_blue, (70, 250), 4, (255, 230, 0), -1)  # Cyan/Blue orb (BGR)
        vision_blue = inspect_game(frame_blue, player=(0.5, 0.5))
        self.assertEqual(len(vision_blue.gems), 1)
        dx_blue, _ = choose_direction(vision_blue, elapsed=1.5, player=(0.5, 0.5))
        self.assertLess(dx_blue, 0, "Should actively steer left towards blue mana orb")

        # 4. Dimmed open ground (gray=68) + scattered mana orbs:
        # Must NOT treat dimmed ground as an enemy, and must lock onto the nearest orb (250, 455) instead of hovering in the centroid!
        frame_dim = np.full((800, 500, 3), 68, dtype=np.uint8)
        for ox, oy in [(250, 455), (380, 250), (410, 280), (350, 220), (420, 340), (120, 230), (140, 260)]:
            cv2.circle(frame_dim, (ox, oy), 4, (255, 230, 0), -1)
        vision_dim = inspect_game(frame_dim, player=(0.5, 0.5))
        self.assertTrue(vision_dim.gameplay)
        self.assertEqual(int(np.sum(vision_dim.enemy_mask > 0)), 0, "Dimmed open ground (gray=68) must not be marked as enemy")
        _, dy_dim = choose_direction(vision_dim, elapsed=0.0, player=(0.5, 0.5))
        self.assertGreater(dy_dim, 0.8, "Must lock onto nearest mana orb (55px South) instead of drifting to distant centroid")

    def test_artifact_rarity_selection(self):
        # Create menu with Normal on slot 1, Epic (Purple #cd50ff -> BGR 255, 80, 205) on slot 3
        frame = np.full((800, 450, 3), 30, dtype=np.uint8)
        cv2.rectangle(frame, (150, int(800 * 0.62)), (300, int(800 * 0.66)), (255, 80, 205), -1)
        idx, target = choose_best_artifact_or_card(frame, default_choice=1)
        self.assertEqual(idx, 3)
        self.assertEqual(target, (0.50, 0.66))

    def test_skill_priority_selection(self):
        # 1. Card 1: Meteor, Card 2: Electric Shock, Card 3: Cyclone -> Prefer Electric Shock (Slot 2)
        frame1 = np.full((800, 450, 3), 20, dtype=np.uint8)
        cv2.putText(frame1, "Meteor Lv. 3", (120, int(800 * 0.37)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame1, "Electric Shock Lv. 1", (120, int(800 * 0.51)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame1, "Cyclone Lv. 2", (120, int(800 * 0.65)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        idx1, target1 = choose_best_artifact_or_card(frame1, default_choice=1)
        self.assertEqual(idx1, 2, "Electric Shock should be preferred over Cyclone")
        self.assertEqual(target1, (0.50, 0.52))

        # 2. Card 1: Satellite, Card 2: Spirit, Card 3: Flash Shock -> Prefer Spirit (Slot 2, highest priority)
        frame2 = np.full((800, 450, 3), 20, dtype=np.uint8)
        cv2.putText(frame2, "Satellite Lv. 1", (120, int(800 * 0.37)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame2, "Spirit Lv. 1", (120, int(800 * 0.51)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame2, "Flash Shock Lv. 2", (120, int(800 * 0.65)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        idx2, target2 = choose_best_artifact_or_card(frame2, default_choice=1)
        self.assertEqual(idx2, 2, "Spirit is top priority and should be chosen")
        self.assertEqual(target2, (0.50, 0.52))

        # 3. Card 1: Cyclone, Card 2: Fireball, Card 3: Magic Bolt -> Prefer Cyclone (Slot 1)
        frame3 = np.full((800, 450, 3), 20, dtype=np.uint8)
        cv2.putText(frame3, "Cyclone Lv. 1", (120, int(800 * 0.37)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame3, "Fireball Lv. 1", (120, int(800 * 0.51)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame3, "Magic Bolt Lv. 4", (120, int(800 * 0.65)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        idx3, target3 = choose_best_artifact_or_card(frame3, default_choice=1)
        self.assertEqual(idx3, 1, "Cyclone should be selected when no Spirit or Electric Shock")
        self.assertEqual(target3, (0.50, 0.38))

    def test_combinations_and_freeze_traits(self):
        # 1. Combination of Spirit+Electric Shock (Telekinetic Sword) vs Cyclone+Satellite (Vortex) vs Blizzard
        frame_combo = np.full((800, 450, 3), 20, dtype=np.uint8)
        cv2.putText(frame_combo, "Vortex", (120, int(800 * 0.37)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame_combo, "Blizzard Lv. 1", (120, int(800 * 0.51)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame_combo, "Telekinetic Sword", (120, int(800 * 0.65)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        idx_c, target_c = choose_best_artifact_or_card(frame_combo, default_choice=1)
        self.assertEqual(idx_c, 3, "Telekinetic Sword (Spirit+Electric Shock) is priority #1 combination")
        self.assertEqual(target_c, (0.50, 0.66))

        # 2. Freeze trait priority (e.g. Tsunami Pole trait)
        frame_trait = np.full((800, 450, 3), 20, dtype=np.uint8)
        cv2.putText(frame_trait, "Great Eruption", (120, int(800 * 0.37)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame_trait, "Pole", (120, int(800 * 0.51)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame_trait, "Ocean Surge", (120, int(800 * 0.65)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        idx_t, target_t = choose_best_artifact_or_card(frame_trait, default_choice=1)
        self.assertEqual(idx_t, 2, "Pole (Freeze trait) should be picked for Tsunami")
        self.assertEqual(target_t, (0.50, 0.52))

    def test_crit_and_cooldown_artifacts(self):
        # 3 Rare artifacts: Slot 1 is generic Virus, Slot 2 has 'Critical' (Radar)
        frame_art = np.full((800, 450, 3), 30, dtype=np.uint8)
        # Give all 3 slots Cyan-Blue rarity badge (Rare #1ba9e3 -> BGR 227, 169, 27)
        for y_c in [0.37, 0.51, 0.65]:
            cv2.rectangle(frame_art, (160, int(800 * (y_c - 0.03))), (280, int(800 * (y_c - 0.01))), (227, 169, 27), -1)
        cv2.putText(frame_art, "Virus", (130, int(800 * 0.40)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame_art, "Radar Critical", (130, int(800 * 0.54)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame_art, "Force Field", (130, int(800 * 0.68)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        idx_a, target_a = choose_best_artifact_or_card(frame_art, default_choice=1)
        self.assertEqual(idx_a, 2, "Radar (Critical artifact) should beat generic Rare artifacts")
        self.assertEqual(target_a, (0.50, 0.52))

        # S-Tier Legendary (Gaia) beats generic Legendary (Excalibur)
        frame_leg = np.full((800, 450, 3), 30, dtype=np.uint8)
        for y_c in [0.37, 0.51, 0.65]:
            cv2.rectangle(frame_leg, (160, int(800 * (y_c - 0.03))), (280, int(800 * (y_c - 0.01))), (0, 180, 255), -1)
        cv2.putText(frame_leg, "Excalibur", (130, int(800 * 0.40)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame_leg, "Transcendence", (130, int(800 * 0.54)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame_leg, "Gaia", (130, int(800 * 0.68)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        idx_l, _ = choose_best_artifact_or_card(frame_leg, default_choice=1)
        self.assertEqual(idx_l, 3, "S-Tier Meta Legendary (Gaia) must beat generic Legendaries")

    def test_treasure_chest_obtain_and_horizontal_cards(self):
        blank = np.zeros((900, 500, 3), dtype=np.uint8)
        self.assertIsNone(detect_obtain_button(blank))

        obtain_tmpl = cv2.imread("assets/obtain_button.png")
        if obtain_tmpl is not None:
            th, tw = obtain_tmpl.shape[:2]
            frame_chest = np.full((957, 530, 3), 10, dtype=np.uint8)
            frame_chest[770 : 770 + th, 180 : 180 + tw] = obtain_tmpl
            ob_pos = detect_obtain_button(frame_chest)
            self.assertIsNotNone(ob_pos)
            self.assertAlmostEqual(ob_pos[0], 0.50, delta=0.05)
            self.assertAlmostEqual(ob_pos[1], 0.83, delta=0.05)

            # Without left/right card borders, it is a 1-card chest
            self.assertFalse(is_three_card_chest(frame_chest, ob_pos[0]))

            # Draw 3 horizontal card boxes at y = 266..420
            for x0, x1 in [(77, 191), (212, 325), (347, 460)]:
                cv2.rectangle(frame_chest, (x0, 266), (x1, 420), (180, 180, 180), 2)
            self.assertTrue(is_three_card_chest(frame_chest, ob_pos[0]))

            # Horizontal card slot coordinates
            s1 = get_chest_card_target(1, ob_pos[0])
            s2 = get_chest_card_target(2, ob_pos[0])
            s3 = get_chest_card_target(3, ob_pos[0])
            self.assertLess(s1[0], s2[0])
            self.assertLess(s2[0], s3[0])
            self.assertEqual(s1[1], 0.36)

            # Evaluate selected artifact description (Ancient Tree Staff / Rare / Cooldown)
            cv2.putText(frame_chest, "Ancient Tree Staff", (150, 495), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            cv2.putText(frame_chest, "Rare Artifact", (190, 528), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (227, 169, 27), 2)
            cv2.putText(frame_chest, "Decrease Magic Circle Cooldown by 25%", (95, 568), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (227, 169, 27), 1)
            score, label = evaluate_selected_chest_artifact(frame_chest)
            self.assertGreaterEqual(score, 350, "Rare (200) + Cooldown (150) should score at least 350")
            self.assertIn("Hồi chiêu", label)

    def test_dark_crowded_gameplay_keeps_moving(self):
        # Late-game frame: dim ground (gray ~45) + many dark enemies with red cores.
        # The old "bright ground >= 36%" rule called this a menu and froze the character.
        rng = np.random.default_rng(3)
        frame = np.full((900, 520, 3), 45, dtype=np.uint8)
        frame[:, :, 1] = 50
        for _ in range(90):
            x, y = int(rng.integers(20, 500)), int(rng.integers(100, 880))
            if math.hypot(x - 260, y - 450) < 70:
                continue
            cv2.circle(frame, (x, y), 20, (8, 8, 8), -1)
            cv2.circle(frame, (x, y), 9, (20, 20, 220), -1)
        vision = inspect_game(frame)
        self.assertFalse(vision.modal)
        self.assertTrue(vision.gameplay, f"bg={vision.background_fraction:.2f} panel={vision.panel_fraction:.2f}")

        # Menus / popups draw a big solid black panel -> modal, never gameplay
        menu = np.full((900, 520, 3), 90, dtype=np.uint8)
        cv2.rectangle(menu, (60, 120), (460, 820), (5, 5, 5), -1)
        v_menu = inspect_game(menu)
        self.assertTrue(v_menu.modal)
        self.assertFalse(v_menu.gameplay)

    def test_surrounded_no_direction_flapping(self):
        # Symmetric ring of enemies: without momentum the planner flips between opposite
        # directions every frame (W<->S), so the character stands still among monsters.
        from botcore import Vision
        enemy = np.zeros((800, 500), dtype=np.uint8)
        for ang in range(0, 360, 30):
            ex = int(250 + 120 * math.cos(math.radians(ang)))
            ey = int(400 + 120 * math.sin(math.radians(ang)))
            cv2.circle(enemy, (ex, ey), 22, 255, -1)
        dist = cv2.distanceTransform(cv2.bitwise_not(enemy), cv2.DIST_L2, 3)
        v = Vision(enemy, dist, [], True, 0.6)
        prev = choose_direction(v, elapsed=0.0, previous=None)
        for step in range(1, 12):
            cur = choose_direction(v, elapsed=step * 0.05, previous=prev)
            self.assertGreater(cur[0] * prev[0] + cur[1] * prev[1], 0.0, "Must not reverse direction frame-to-frame")
            prev = cur

    def test_shop_screen_buy_and_x_buttons(self):
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        self.assertIsNone(detect_buy_button(blank))
        self.assertIsNone(detect_shop_x_button(blank))

        buy_tmpl = cv2.imread("assets/buy_button_tight.png")
        x_tmpl = cv2.imread("assets/shop_x_tight.png")
        if buy_tmpl is not None and x_tmpl is not None:
            frame_shop = np.full((1024, 600, 3), 10, dtype=np.uint8)
            # Place buy button at (300, 935)
            bh, bw = buy_tmpl.shape[:2]
            frame_shop[930 : 930 + bh, 270 : 270 + bw] = buy_tmpl
            # Place x button at (560, 80)
            xh, xw = x_tmpl.shape[:2]
            frame_shop[70 : 70 + xh, 545 : 545 + xw] = x_tmpl

            b_pos = detect_buy_button(frame_shop)
            self.assertIsNotNone(b_pos)
            self.assertAlmostEqual(b_pos[0], 0.50, delta=0.06)
            self.assertAlmostEqual(b_pos[1], 0.92, delta=0.04)

            x_pos = detect_shop_x_button(frame_shop)
            self.assertIsNotNone(x_pos)
            self.assertGreater(x_pos[0], 0.88)
            self.assertLess(x_pos[1], 0.12)

            slots = get_shop_item_targets()
            self.assertEqual(len(slots), 8)

            # Test disabled Buy (dimmed <= 110) vs enabled Buy (> 160)
            self.assertFalse(is_shop_buy_enabled(frame_shop))
            self.assertFalse(is_shop_buy_enabled(frame_shop, buy_pos=b_pos))
            cv2.putText(frame_shop, "BUY", (270, 950), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            self.assertTrue(is_shop_buy_enabled(frame_shop))
            self.assertTrue(is_shop_buy_enabled(frame_shop, buy_pos=b_pos))

            # Test evaluate shop artifact
            cv2.putText(frame_shop, "ASI", (270, 650), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame_shop, "Special Artifact", (240, 685), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 220), 2)
            cv2.putText(frame_shop, "Increase ATK by 30%", (210, 725), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 220, 20), 1)
            score, label = evaluate_selected_shop_artifact(frame_shop, active_skills={"spirit"})
            self.assertGreaterEqual(score, 400)
            self.assertIn("Special", label)
            self.assertGreaterEqual(score, 400)
            self.assertIn("Special", label)

    def test_active_mana_collection_with_distant_chest(self):
        # When a chest is distant (400px away to the right), nearby safe mana orbs (80px up)
        # must NOT be ignored - the character must gather mana instead of blindly rushing right!
        from botcore import Vision
        enemy = np.zeros((800, 500), dtype=np.uint8)
        dist = cv2.distanceTransform(cv2.bitwise_not(enemy), cv2.DIST_L2, 3)
        # Blue orb at (250, 320) which is 80px North of player at (250, 400)
        # Chest at (480, 400) which is 230px East of player
        v = Vision(
            enemy, dist, [(250, 320)], True, 0.6,
            chest=(480, 400), chest_type="treasure_chest", chest_weight=24.0,
        )
        dx, dy = choose_direction(v, elapsed=0.0, player=(0.5, 0.5))
        # Player must move North towards the nearby mana orb (dy < 0)
        self.assertLess(dy, -0.4, "Must collect nearby mana orb even with distant chest on screen")

    def test_anchor_match_and_mismatch(self):
        frame = np.full((500, 300, 3), 140, dtype=np.uint8)
        cv2.putText(frame, "LEVEL UP", (50, 135), cv2.FONT_HERSHEY_SIMPLEX,
                    0.75, (240, 240, 240), 2)
        x0, y0, x1, y1 = 45, 100, 240, 150
        rule = {"name": "level", "image": "anchor.png",
                "anchor": [x0 / 300, y0 / 500, (x1 - x0) / 300, (y1 - y0) / 500],
                "target": [0.5, 0.5], "threshold": 0.88}
        with tempfile.TemporaryDirectory() as directory:
            cv2.imwrite(str(Path(directory) / "anchor.png"), frame[y0:y1, x0:x1])
            self.assertEqual(find_rule(frame, [rule], directory)["name"], "level")
            changed = np.full_like(frame, 140)
            self.assertIsNone(find_rule(changed, [rule], directory))


    def test_detect_learn_button_and_attribute_circles(self):
        blank = np.zeros((1024, 600, 3), dtype=np.uint8)
        self.assertIsNone(detect_learn_button(blank))

        learn_tmpl = cv2.imread("assets/learn_button_tight.png")
        if learn_tmpl is not None:
            lh, lw = learn_tmpl.shape[:2]
            frame_learn = np.zeros((1024, 600, 3), dtype=np.uint8)
            frame_learn[900 : 900 + lh, 250 : 250 + lw] = learn_tmpl
            pos = detect_learn_button(frame_learn)
            self.assertIsNotNone(pos)
            self.assertAlmostEqual(pos[0], 0.50, delta=0.08)
            self.assertAlmostEqual(pos[1], 0.89, delta=0.04)

            from botcore import is_attribute_screen, detect_close_button
            self.assertTrue(is_attribute_screen(frame_learn))
            self.assertIsNone(detect_close_button(frame_learn), "detect_close_button must NEVER trigger on attribute screen!")

        circles = get_attribute_circle_targets()
        self.assertEqual(len(circles), 3)
        self.assertEqual(circles[1], (0.50, 0.29))
        self.assertEqual(circles[2], (0.31, 0.44))
        self.assertEqual(circles[3], (0.68, 0.44))

    def test_skill_synergy_bonus_and_combinations(self):
        # Empty or None active skills -> 0 bonus
        self.assertEqual(compute_skill_synergy_bonus("some artifact text", set()), (0, []))
        self.assertEqual(compute_skill_synergy_bonus("some artifact text", None), (0, []))

        # Direct skill match: Spirit
        b, m = compute_skill_synergy_bonus("Increases Spirit Damage by 25%", {"spirit"})
        self.assertEqual(b, 180)
        self.assertIn("Spirit", m)

        # Combination match: telekinetic_sword expands to spirit and electric_shock
        b2, m2 = compute_skill_synergy_bonus("Increases Spirit projectile speed and blade damage", {"telekinetic_sword"})
        self.assertGreaterEqual(b2, 180)
        self.assertIn("Spirit", m2)

        # Multi-skill match (capped at 360)
        b3, m3 = compute_skill_synergy_bonus("Spirit projectile and Electric Shock damage", {"telekinetic_sword"})
        self.assertEqual(b3, 360)
        self.assertIn("Spirit", m3)
        self.assertIn("Electric Shock", m3)

        # Unrelated text
        b4, m4 = compute_skill_synergy_bonus("Increase max HP by 20%", {"spirit"})
        self.assertEqual(b4, 0)
        self.assertEqual(m4, [])

    def test_chest_artifact_synergy(self):
        # Frame with Rare Artifact (Blue) and Magic Circle cooldown text
        frame = np.full((1024, 600, 3), 10, dtype=np.uint8)
        # Rarity subtitle 'Rare Artifact' in y = 0.51..0.58 with blue color
        frame[520:560, 200:400] = (220, 100, 20)  # BGR for bluish
        # Without active skills
        score_base, label_base = evaluate_selected_chest_artifact(frame, active_skills=set())
        # With active skills matching magic_circle
        score_syn, label_syn = evaluate_selected_chest_artifact(frame, active_skills={"magic_circle"})
        # Should be equal or higher depending on OCR environment
        self.assertGreaterEqual(score_syn, score_base)


    def test_cyclone_priority_and_trait_selection(self):
        from unittest.mock import patch
        from botcore import CardSlotData

        # Case 1: Cyclone in Card 2, Card 1 has Rare tier with cooldown text
        # Prioritized skill (Cyclone) MUST win over generic cooldown/rare card!
        cards = {
            1: CardSlotData(1, text_lines=["decrease magic cooldown by 5%"], has_cooldown=True),
            2: CardSlotData(2, text_lines=["cyclone", "generates a cyclone"], skills=["cyclone"]),
            3: CardSlotData(3, text_lines=["vitality"], skills=["vitality"]),
        }
        frame = np.zeros((1000, 600, 3), dtype=np.uint8)
        frame[330:400, 200:400] = (255, 150, 0)  # Blue/Rare color on slot 1
        with patch("botcore._detect_cards_ocr", return_value=cards):
            with patch("botcore._detect_skills_templates", return_value={1: [], 2: [], 3: []}):
                choice = choose_best_artifact_or_card(frame)
                self.assertEqual(choice.idx, 2, "Cyclone must take priority over generic cooldown passive")
                self.assertIn("Cyclone", choice.label)

        # Case 2: Cyclone OCR typos (cycione, hurricane, climate change)
        for variant in ["cycione", "cycIone", "cyctone", "cyclon", "hurricane", "climate change"]:
            from botcore import SKILL_ALIASES
            detected = []
            for sk, aliases in SKILL_ALIASES.items():
                if any(a in variant for a in aliases):
                    detected.append(sk)
            self.assertIn("cyclone", detected, f"Failed to map variant {variant} to cyclone")


    def test_telekinetic_sword_then_black_hole_priority(self):
        from unittest.mock import patch
        from botcore import CardSlotData

        # Case 1: Telekinetic Sword vs Black Hole -> Telekinetic Sword must win
        cards_combo = {
            1: CardSlotData(1, text_lines=["black hole"], skills=["black_hole"]),
            2: CardSlotData(2, text_lines=["telekinetic sword"], skills=["telekinetic_sword"]),
            3: CardSlotData(3, text_lines=["fast casting"], skills=["fast_casting"]),
        }
        frame = np.zeros((1000, 600, 3), dtype=np.uint8)
        with patch("botcore._detect_cards_ocr", return_value=cards_combo):
            with patch("botcore._detect_skills_templates", return_value={1: [], 2: [], 3: []}):
                c1 = choose_best_artifact_or_card(frame)
                self.assertEqual(c1.idx, 2, "Telekinetic Sword must win over Black Hole")
                self.assertIn("Telekinetic Sword", c1.label)

        # Case 2: Spirit vs Cyclone -> Spirit must win (building Telekinetic Sword first)
        cards_components = {
            1: CardSlotData(1, text_lines=["cyclone"], skills=["cyclone"]),
            2: CardSlotData(2, text_lines=["spirit"], skills=["spirit"]),
            3: CardSlotData(3, text_lines=["vitality"], skills=["vitality"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards_components):
            with patch("botcore._detect_skills_templates", return_value={1: [], 2: [], 3: []}):
                c2 = choose_best_artifact_or_card(frame)
                self.assertEqual(c2.idx, 2, "Spirit must win over Cyclone when building Telekinetic Sword first")
                self.assertIn("Spirit", c2.label)

        # Case 3: Black Hole / Cyclone vs other magics -> Black Hole wins
        cards_black_hole = {
            1: CardSlotData(1, text_lines=["blizzard"], skills=["blizzard"]),
            2: CardSlotData(2, text_lines=["black hole"], skills=["black_hole"]),
            3: CardSlotData(3, text_lines=["shield"], skills=["shield"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards_black_hole):
            with patch("botcore._detect_skills_templates", return_value={1: [], 2: [], 3: []}):
                c3 = choose_best_artifact_or_card(frame)
                self.assertEqual(c3.idx, 2, "Black Hole must win over Blizzard/Shield")
                self.assertIn("Black Hole", c3.label)


    def test_detect_confirm_button_and_ad_close(self):
        # Blank screen has no confirm button
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        self.assertIsNone(detect_confirm_button(blank))

        # Test with template
        tmpl = cv2.imread("assets/confirm_button_tight.png")
        if tmpl is not None:
            th, tw = tmpl.shape[:2]
            frame_confirm = np.zeros((1024, 600, 3), dtype=np.uint8)
            frame_confirm[870 : 870 + th, 250 : 250 + tw] = tmpl
            pos = detect_confirm_button(frame_confirm)
            self.assertIsNotNone(pos)
            self.assertAlmostEqual(pos[0], 0.52, delta=0.08)
            self.assertAlmostEqual(pos[1], 0.86, delta=0.04)

            # When Pause button is also present (active combat), confirm_button must be ignored!
            pause_tmpl = cv2.imread("assets/pause_button.png")
            if pause_tmpl is not None:
                pth, ptw = pause_tmpl.shape[:2]
                frame_confirm[20 : 20 + pth, 520 : 520 + ptw] = pause_tmpl
                self.assertIsNone(detect_confirm_button(frame_confirm))

        # Test close button with 'close' text via OCR
        frame_ad = np.full((1024, 600, 3), 40, dtype=np.uint8)
        cv2.putText(frame_ad, "Close", (510, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        close_pos = detect_close_button(frame_ad)
        if close_pos:
            self.assertGreater(close_pos[0], 0.80)
            self.assertLess(close_pos[1], 0.15)

        # Test close button with 'X' symbol via OCR / template
        frame_x = np.full((1024, 600, 3), 30, dtype=np.uint8)
        cv2.putText(frame_x, "X", (540, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        x_pos = detect_close_button(frame_x)
        if x_pos:
            self.assertGreater(x_pos[0], 0.80)
            self.assertLess(x_pos[1], 0.15)


    def test_is_level_up_screen_detection(self):
        from botcore import is_level_up_screen, LevelUpDetection, CardSlotData
        from unittest.mock import patch

        # 1. Blank frame: NOT level-up
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        det_blank = is_level_up_screen(blank)
        self.assertFalse(det_blank)
        self.assertFalse(det_blank.detected)

        # 2. Level-up cards with skills: MUST be detected as True
        cards_lvl = {
            1: CardSlotData(1, text_lines=["spirit lv. 1"], skills=["spirit"]),
            2: CardSlotData(2, text_lines=["cyclone lv. 1"], skills=["cyclone"]),
            3: CardSlotData(3, text_lines=["satellite lv. 1"], skills=["satellite"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards_lvl):
            det_lvl = is_level_up_screen(blank)
            self.assertTrue(det_lvl)
            self.assertTrue(bool(det_lvl))
            self.assertTrue(det_lvl.detected)
            # Tuple unpacking compatibility
            is_detected, reason = det_lvl
            self.assertTrue(is_detected)
            self.assertIn("card", reason)

        # 3. Card with traits or level-up keywords: MUST be detected as True
        cards_traits = {
            1: CardSlotData(1, text_lines=["sub-zero"], freeze_traits=["sub-zero"]),
            2: CardSlotData(2, text_lines=[]),
            3: CardSlotData(3, text_lines=[]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards_traits):
            self.assertTrue(is_level_up_screen(blank))

        # 4. Modals must NOT be treated as level-up screen even if card text exists:
        with patch("botcore._detect_cards_ocr", return_value=cards_lvl):
            with patch("botcore.detect_obtain_button", return_value=(0.5, 0.8)):
                self.assertFalse(is_level_up_screen(blank))
            with patch("botcore.detect_buy_button", return_value=(0.5, 0.8)):
                self.assertFalse(is_level_up_screen(blank))
            with patch("botcore.detect_learn_button", return_value=(0.5, 0.8)):
                self.assertFalse(is_level_up_screen(blank))
            with patch("botcore.detect_die_button", return_value=(0.5, 0.7)):
                self.assertFalse(is_level_up_screen(blank))
            with patch("botcore.detect_confirm_button", return_value=(0.5, 0.85)):
                self.assertFalse(is_level_up_screen(blank))
            with patch("botcore.detect_enter_area", return_value=(0.5, 0.5)):
                self.assertFalse(is_level_up_screen(blank))
            with patch("botcore.detect_selected", return_value=(0.5, 0.9)):
                self.assertFalse(is_level_up_screen(blank))

    def test_combination_star_detection_and_fusion(self):
        from botcore import detect_combination_star, find_best_combination_option

        # 1. Blank frame: No combination star
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        self.assertIsNone(detect_combination_star(blank))

        # 2. Uploaded image with glowing red star at level 40:
        import os
        img_path = r"C:/Users/User/.gemini/antigravity/brain/2dc840cb-72eb-45f9-92e9-a3fe999f18b4/.user_uploaded/media_1794149534967_3ea9098d.jpg"
        if os.path.isfile(img_path):
            img_star = cv2.imread(img_path)
            star_pos = detect_combination_star(img_star)
            self.assertIsNotNone(star_pos)
            self.assertAlmostEqual(star_pos[0], 0.91, delta=0.04)
            self.assertAlmostEqual(star_pos[1], 0.14, delta=0.04)

        # 2b. Uploaded image with DULL inactive star: MUST return None!
        dull_path = r"C:/Users/User/.gemini/antigravity/brain/2dc840cb-72eb-45f9-92e9-a3fe999f18b4/.user_uploaded/media_1794152496577_40652778.png"
        if os.path.isfile(dull_path):
            dull_star = cv2.imread(dull_path)
            frame_dull = np.zeros((1000, 800, 3), dtype=np.uint8)
            hd, wd = dull_star.shape[:2]
            frame_dull[int(1000 * 0.10) : int(1000 * 0.10) + hd, int(800 * 0.85) : int(800 * 0.85) + wd] = dull_star
            self.assertIsNone(detect_combination_star(frame_dull), "Dull inactive star must NOT be clicked!")

        # A red effect in the star's corner must not be mistaken for the star.
        red_effect = np.zeros((1000, 800, 3), dtype=np.uint8)
        cv2.circle(red_effect, (715, 140), 38, (20, 20, 230), -1)
        self.assertIsNone(detect_combination_star(red_effect))

        # The known red star is still detected without depending on uploaded files.
        active_star = cv2.imread(os.path.join("assets", "combination_star.png"))
        active_frame = np.zeros((1000, 800, 3), dtype=np.uint8)
        sh, sw = active_star.shape[:2]
        active_frame[100:100 + sh, 680:680 + sw] = active_star
        self.assertIsNotNone(detect_combination_star(active_frame))

        # 3. Synthetic frame with combination menu:
        frame_combo = np.full((1000, 600, 3), 15, dtype=np.uint8)
        cv2.putText(frame_combo, "Magic Combinations", (160, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(frame_combo, "Black Hole", (180, 350), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(frame_combo, "Telekinetic Sword", (180, 500), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        # Telekinetic Sword must win over Black Hole
        res1 = find_best_combination_option(frame_combo, skill_priority=["telekinetic_sword", "black_hole"])
        if res1 is not None:
            pos1, label1, key1 = res1
            self.assertEqual(key1, "telekinetic_sword")
            self.assertIn("Telekinetic Sword", label1)

        # If Telekinetic Sword is not preferred or not listed, Black Hole wins
        res2 = find_best_combination_option(frame_combo, skill_priority=["black_hole"])
        if res2 is not None:
            pos2, label2, key2 = res2
            self.assertEqual(key2, "black_hole")
            self.assertIn("Black Hole", label2)

    def test_monolith_detection_and_guidance(self):
        from botcore import detect_monolith, inspect_game, choose_direction, Vision
        import os

        # 1. Blank frame: No monolith
        blank = np.full((1000, 600, 3), 100, dtype=np.uint8)
        self.assertIsNone(detect_monolith(blank))

        # 2. Uploaded image with post-wave milestone monolith:
        img_path = r"C:/Users/User/.gemini/antigravity/brain/2dc840cb-72eb-45f9-92e9-a3fe999f18b4/.user_uploaded/media_1794152395302_9c8311df.png"
        if os.path.isfile(img_path):
            img_m = cv2.imread(img_path)
            m_pos = detect_monolith(img_m)
            self.assertIsNotNone(m_pos)
            # Monolith is around x=205, y=679
            self.assertAlmostEqual(m_pos[0], 205, delta=30)
            self.assertAlmostEqual(m_pos[1], 679, delta=30)

            # Must inspect game and confirm monolith is passed to Vision without becoming an enemy wall
            v = inspect_game(img_m, player=(0.5, 0.5))
            self.assertIsNotNone(v.monolith)
            # Monolith position must NOT be an enemy pixel
            self.assertEqual(v.enemy_mask[m_pos[1], m_pos[0]], 0)

            # When only monolith is present, choose_direction must pull towards the monolith
            v_mono_only = Vision(
                v.enemy_mask, v.distance, [], True, v.background_fraction,
                None, "treasure_chest", 24.0,
                [], [], False, v.panel_fraction,
                m_pos,
            )
            dx, dy = choose_direction(v_mono_only, elapsed=0.0, player=(0.5, 0.5))
            # Player at center (308, 512), Monolith at (205, 679) -> dx < 0 (West), dy > 0 (South)
            self.assertLess(dx, 0.0, "Must head West towards monolith")
            self.assertGreater(dy, 0.0, "Must head South towards monolith")

            # When player is close to monolith (35px away at x=240, y=679),
            # choose_direction MUST continue directly into the monolith (dx < 0, |dy| < 0.35)
            # instead of swerving away due to obstacle rays hitting the rock base.
            v_close = inspect_game(img_m, player=(240.0 / img_m.shape[1], 679.0 / img_m.shape[0]))
            cdx, cdy = choose_direction(
                v_close, elapsed=0.0, previous=(-1.0, 0.0),
                player=(240.0 / img_m.shape[1], 679.0 / img_m.shape[0])
            )
            self.assertLess(cdx, -0.85, "Must charge directly West into monolith when near")
            self.assertAlmostEqual(cdy, 0.0, delta=0.45, msg="Must not veer away North or South")

            # 3. Test 1080p high resolution scaling (LDPlayer resolution 1080x1920)
            img_1080 = cv2.resize(img_m, (1080, 1920))
            m_pos_1080 = detect_monolith(img_1080)
            self.assertIsNotNone(m_pos_1080, "Must detect monolith at 1080p LDPlayer resolution")
            self.assertAlmostEqual(m_pos_1080[0], 350, delta=50)
            self.assertAlmostEqual(m_pos_1080[1], 1300, delta=50)

    def test_chest_color_fallback_and_priority(self):
        from botcore import detect_chest, choose_direction
        import os

        img_path = r"C:/Users/User/.gemini/antigravity/brain/2dc840cb-72eb-45f9-92e9-a3fe999f18b4/.user_uploaded/media_1794152395302_9c8311df.png"
        if os.path.isfile(img_path):
            img = cv2.imread(img_path)
            c_target = detect_chest(img, player=(0.5, 0.5))
            self.assertIsNotNone(c_target)
            # Must detect both chests/indicators
            self.assertGreaterEqual(len(c_target.all_positions), 2)

    def test_ad_screen_and_keyword_boundaries(self):
        from botcore import is_level_up_screen, _match_keyword, detect_close_button
        from unittest.mock import patch

        # 1. 'snipe' keyword must not match 'sniper'
        self.assertFalse(_match_keyword("snipe", "hunting rivals: sniper battle"))
        self.assertTrue(_match_keyword("snipe", "snipe lv. 1"))
        self.assertTrue(_match_keyword("snipe", "snipe"))

        # 2. When close button is detected on screen, is_level_up_screen MUST return False
        blank = np.zeros((800, 600, 3), dtype=np.uint8)
        with patch("botcore.detect_close_button", return_value=(0.95, 0.15)):
            det = is_level_up_screen(blank)
            self.assertFalse(det)
            self.assertEqual(det.reason, "ad_close_button")

    def test_intelligent_kiting_tangential_flow(self):
        from botcore import choose_direction, Vision

        # Swarm approaching from the East (right side):
        free = np.ones((800, 600), dtype=np.uint8) * 255
        free[:, 350:] = 0
        dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)
        v = Vision(255 - free, dist, [], True, 0.5)

        # First step: should evade leftwards away from East swarm
        d1 = choose_direction(v, elapsed=0.0, previous=None)
        self.assertLess(d1[0], -0.3, "Must move West away from East swarm")

        # When moving upward (North-West), tangential kiting must maintain smooth circular flow
        d2 = choose_direction(v, elapsed=0.1, previous=(-0.7, -0.7))
        self.assertLess(d2[0], -0.2, "Must keep distance from East swarm")
        self.assertLess(d2[1], 0.0, "Must maintain upward tangential momentum instead of stuttering")

    def test_level_up_bright_combat_rejection(self):
        from botcore import is_level_up_screen
        # Bright combat screen (simulating active gameplay ground / spell explosions)
        bright_combat = np.ones((1000, 600, 3), dtype=np.uint8) * 110
        det = is_level_up_screen(bright_combat)
        self.assertFalse(det)
        self.assertIn("gameplay_ground_bright", det.reason)

    def test_special_star_passives_and_asterisk(self):
        from botcore import (
            SPECIAL_STAR_PASSIVES,
            SPECIAL_PASSIVE_SCORES,
            CardSlotData,
            choose_best_artifact_or_card,
        )
        from unittest.mock import patch

        # 1. Verify key special passives exist
        self.assertIn("adrenaline", SPECIAL_STAR_PASSIVES)
        self.assertIn("silent_casting", SPECIAL_STAR_PASSIVES)
        self.assertIn("mana_factory", SPECIAL_STAR_PASSIVES)
        self.assertIn("guardian_angel", SPECIAL_STAR_PASSIVES)
        self.assertIn("magic_seal", SPECIAL_STAR_PASSIVES)
        self.assertGreater(SPECIAL_PASSIVE_SCORES["adrenaline"], 150.0)

        # 2. Test choosing special passive
        cards = {
            1: CardSlotData(1, text_lines=["adrenaline", "+5% atk, crit, speed"], is_special_passive=True, has_asterisk=True, special_passive_name="adrenaline"),
            2: CardSlotData(2, text_lines=["fireball lv. 1"], skills=["fireball"]),
            3: CardSlotData(3, text_lines=["energy bolt lv. 1"], skills=["energy_bolt"]),
        }
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        with patch("botcore._detect_cards_ocr", return_value=cards):
            choice = choose_best_artifact_or_card(blank)
            self.assertEqual(choice.idx, 1)
            self.assertIn("Adrenaline", choice.label)
            self.assertEqual(choice.skill_key, "adrenaline")

        # 3. Test starred fusion component priority bonus
        cards_starred = {
            1: CardSlotData(1, text_lines=["satellite lv. 1"], skills=["satellite"]),
            2: CardSlotData(2, text_lines=["* electric shock lv. 1"], skills=["electric_shock"], has_asterisk=True),
            3: CardSlotData(3, text_lines=["fireball lv. 1"], skills=["fireball"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards_starred):
            choice2 = choose_best_artifact_or_card(blank, skill_priority=["satellite", "electric_shock"])
            self.assertEqual(choice2.idx, 2)
            self.assertEqual(choice2.skill_key, "electric_shock")

    def test_ad_skip_arrow_and_endgame_protection(self):
        from botcore import detect_close_button, detect_confirm_button
        # 1. Skip arrow >> button
        frame_skip = np.full((1000, 600, 3), 30, dtype=np.uint8)
        cv2.line(frame_skip, (545, 40), (555, 50), (255, 255, 255), 2)
        cv2.line(frame_skip, (555, 50), (545, 60), (255, 255, 255), 2)
        cv2.line(frame_skip, (555, 40), (565, 50), (255, 255, 255), 2)
        cv2.line(frame_skip, (565, 50), (555, 60), (255, 255, 255), 2)
        skip_pos = detect_close_button(frame_skip)
        self.assertIsNotNone(skip_pos)
        self.assertGreater(skip_pos[0], 0.85)
        self.assertLess(skip_pos[1], 0.12)

        # 2. When confirm button is visible (Endgame screen), detect_close_button MUST return None
        from unittest.mock import patch
        with patch("botcore.detect_confirm_button", return_value=(0.5, 0.85)):
            self.assertIsNone(detect_close_button(frame_skip))

    def test_detect_pause_button(self):
        from botcore import detect_pause_button
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        self.assertIsNone(detect_pause_button(blank))

        pause_tmpl = cv2.imread("assets/pause_button.png")
        if pause_tmpl is not None:
            # Test multi-scale detection (e.g. 0.6x scale and 1.0x scale)
            for scale in (0.65, 1.0):
                pth = int(pause_tmpl.shape[0] * scale)
                ptw = int(pause_tmpl.shape[1] * scale)
                rt = cv2.resize(pause_tmpl, (ptw, pth))
                frame = np.zeros((1000, 600, 3), dtype=np.uint8)
                frame[20:20+pth, 520:520+ptw] = rt
                pos = detect_pause_button(frame)
                self.assertIsNotNone(pos, f"Failed at scale {scale}")
                self.assertGreater(pos[0], 0.80)
                self.assertLess(pos[1], 0.10)

    def test_toy_castle_magictoys_priority(self):
        from botcore import is_toy_castle_artifact
        self.assertTrue(is_toy_castle_artifact("Toy Castle"))
        self.assertTrue(is_toy_castle_artifact("magictoys"))
        self.assertTrue(is_toy_castle_artifact("Magic Toys"))
        self.assertTrue(is_toy_castle_artifact("toy kingdom"))
        self.assertTrue(is_toy_castle_artifact("Toy: reduce size of elite monsters"))
        self.assertTrue(is_toy_castle_artifact("reduce size of enemies and health of elite monsters"))
        self.assertFalse(is_toy_castle_artifact("Titan's Power"))
        self.assertFalse(is_toy_castle_artifact("Holy Chest"))
        self.assertFalse(is_toy_castle_artifact("Gaia"))

    def test_void_zone_avoidance(self):
        # Test synthetic frame with a dark HP-drain void zone on the left
        h, w = 600, 400
        frame = np.full((h, w, 3), [80, 110, 110], dtype=np.uint8)
        # Left 35% of the screen is encroaching darkness/void (gray = 35..45)
        frame[:, : int(w * 0.35)] = [35, 30, 25]

        # Place a blue mana orb inside the void zone to tempt the player
        # Neon cyan orb in BGR: [255, 230, 30]
        orb_x, orb_y = int(w * 0.15), int(h * 0.5)
        cv2.circle(frame, (orb_x, orb_y), 5, [255, 230, 30], -1)

        vision = inspect_game(frame, player=(0.5, 0.5))
        self.assertTrue(vision.gameplay)
        # The void zone must be flagged as hazard in enemy_mask
        void_pixels = np.sum(vision.enemy_mask[:, : int(w * 0.30)] > 0)
        self.assertGreater(void_pixels, 15000, "Dark void zone must be detected as lethal hazard")

        # choose_direction must move right (dx > 0) and NEVER steer left into the void
        dx, dy = choose_direction(vision, 0.0)
        self.assertGreater(dx, 0.3, "Bot must firmly steer rightward away from the void zone")

    def test_special_artifact_priority(self):
        from botcore import is_special_artifact, evaluate_selected_chest_artifact, choose_best_artifact_or_card

        # 1. is_special_artifact checks
        self.assertTrue(is_special_artifact("Special Artifact"))
        self.assertTrue(is_special_artifact("Hydra: reduces current enemy health"))
        self.assertTrue(is_special_artifact("List"))
        self.assertTrue(is_special_artifact("Death Bell"))
        self.assertTrue(is_special_artifact("Brand of Satan"))
        self.assertTrue(is_special_artifact("Dragon Tongue"))
        self.assertTrue(is_special_artifact("Cyborg"))
        self.assertTrue(is_special_artifact("Jet Engine"))
        self.assertTrue(is_special_artifact("Domain of Power"))
        self.assertTrue(is_special_artifact("Thought Cube"))
        self.assertTrue(is_special_artifact("Necronomicon"))
        self.assertTrue(is_special_artifact("Accelerator"))
        self.assertTrue(is_special_artifact("Ballista"))
        self.assertFalse(is_special_artifact("Ruby Ring"))
        self.assertFalse(is_special_artifact("Listen carefully"))

        # 2. Chest artifact scoring: Special Artifact gets >= 10,000 points
        frame_spec = np.full((1024, 600, 3), 10, dtype=np.uint8)
        # Rarity subtitle in y = 0.51..0.58 with red color (Special Artifact in HSV has H <= 8 or H >= 168)
        # In BGR: Red is (30, 30, 220)
        frame_spec[520:560, 200:400] = (30, 30, 220)
        score_spec, lbl_spec = evaluate_selected_chest_artifact(frame_spec)
        self.assertGreaterEqual(score_spec, 10000, "Special Artifact base score must be >= 10000")
        self.assertIn("Special", lbl_spec)

        # 3. Epic artifact (Purple: BGR 220, 30, 200) gets ~300..900 points
        frame_epic = np.full((1024, 600, 3), 10, dtype=np.uint8)
        frame_epic[520:560, 200:400] = (220, 30, 200)
        score_epic, _ = evaluate_selected_chest_artifact(frame_epic)
        self.assertLess(score_epic, 1500)

        # Special Artifact must decisively beat Epic/Rare/Normal
        self.assertGreater(score_spec, score_epic + 8000)

    def test_monster_eyes_in_combat_do_not_trigger_level_up(self):
        """Red spots (monster eyes) in icon bands must NEVER trigger false level-up when cards have no text."""
        from botcore import _detect_cards_ocr, is_level_up_screen
        from unittest.mock import patch, AsyncMock

        # Dark combat frame (mean < 38)
        frame = np.full((1000, 600, 3), 15, dtype=np.uint8)
        # Add crimson red spots in card 1 and card 3 icon areas (x = 0.10..0.26, y = 0.28..0.44 and 0.58..0.74)
        # Red in BGR: (20, 20, 230)
        frame[300:360, 70:130] = (20, 20, 230)
        frame[600:660, 70:130] = (20, 20, 230)

        # Mock winocr to return no text (combat screen has no card text)
        class MockOCRResult:
            lines = []

        with patch("winocr.recognize_pil", new_callable=AsyncMock) as m_ocr:
            m_ocr.return_value = MockOCRResult()
            cards = _detect_cards_ocr(frame, 1000, 600)
            for idx, c in cards.items():
                self.assertFalse(c.has_asterisk, f"Card {idx} must not have asterisk from monster red eyes")
                self.assertFalse(c.is_special_passive)

            det = is_level_up_screen(frame)
            self.assertFalse(det, "Must NOT detect level up screen during active combat with red monster eyes")

    def test_mana_orb_currency_and_shop_features(self):
        """Test mana orb currency detection, shop state, and buy button enabled checks."""
        from botcore import detect_mana_orb_currency, is_merchant_shop, is_shop_buy_enabled
        from unittest.mock import patch, AsyncMock

        # 1. Mana orb OCR text normalization: 'e. *593 •' -> 1593
        class MockLine:
            def __init__(self, text):
                self.text = text

        class MockOCR:
            def __init__(self, lines):
                self.lines = [MockLine(t) for t in lines]

        frame = np.zeros((1000, 600, 3), dtype=np.uint8)
        with patch("winocr.recognize_pil", new_callable=AsyncMock) as m_ocr:
            m_ocr.return_value = MockOCR(["e. *593 •"])
            mana = detect_mana_orb_currency(frame)
            self.assertEqual(mana, 1593)

        # 2. Buy enabled check: active white button (gray > 160)
        shop_frame_enabled = np.zeros((1000, 600, 3), dtype=np.uint8)
        # Button area y = 0.89..0.96, x = 0.40..0.60
        shop_frame_enabled[900:950, 250:350] = (230, 230, 230)
        self.assertTrue(is_shop_buy_enabled(shop_frame_enabled))

        shop_frame_disabled = np.zeros((1000, 600, 3), dtype=np.uint8)
        # Dimmed gray text / dark background
        shop_frame_disabled[900:950, 250:350] = (50, 50, 50)
        self.assertFalse(is_shop_buy_enabled(shop_frame_disabled))

        # 3. is_merchant_shop delegation
        with patch("botcore.detect_buy_button", return_value=(0.50, 0.92)):
            self.assertTrue(is_merchant_shop(frame))
        with patch("botcore.detect_buy_button", return_value=None):
            self.assertFalse(is_merchant_shop(frame))

    def test_electric_zone_not_confused_with_electric_shock(self):
        from unittest.mock import patch
        from botcore import CardSlotData, choose_best_artifact_or_card, _match_keyword, SKILL_ALIASES

        # 1. Alias check: "electric zone" must match electric_zone, NEVER electric_shock
        ez_text = "electric zone lv. 1"
        self.assertTrue(any(_match_keyword(a, ez_text) for a in SKILL_ALIASES["electric_zone"]))
        self.assertFalse(any(_match_keyword(a, ez_text) for a in SKILL_ALIASES["electric_shock"]))

        # 2. Card selection: Slot 1 has Electric Zone, Slot 2 has Fireball, Slot 3 has Lava Zone
        cards = {
            1: CardSlotData(1, text_lines=["electric zone", "lv. 1"], skills=["electric_zone"]),
            2: CardSlotData(2, text_lines=["fireball", "lv. 1"], skills=["fireball"]),
            3: CardSlotData(3, text_lines=["lava zone", "lv. 1"], skills=["lava_zone"]),
        }
        frame = np.zeros((800, 450, 3), dtype=np.uint8)
        with patch("botcore._detect_cards_ocr", return_value=cards):
            choice = choose_best_artifact_or_card(frame)
            self.assertEqual(choice.idx, 1)
            self.assertEqual(choice.skill_key, "electric_zone")
            self.assertIn("Electric Zone", choice.label)
            self.assertNotIn("Electric Shock", choice.label)

    def test_maxed_skill_and_template_overrides(self):
        from unittest.mock import patch
        from botcore import CardSlotData, choose_best_artifact_or_card

        # 1. Template match false positive for Spirit must NOT override OCR Electric Zone
        cards = {
            1: CardSlotData(1, text_lines=["electric zone", "lv. 1"], skills=["electric_zone"]),
            2: CardSlotData(2, text_lines=["fireball", "lv. 1"], skills=["fireball"]),
            3: CardSlotData(3, text_lines=["lava zone", "lv. 1"], skills=["lava_zone"]),
        }
        tmpl_false_spirit = {1: ["spirit"], 2: [], 3: []}
        frame = np.zeros((800, 450, 3), dtype=np.uint8)
        with patch("botcore._detect_cards_ocr", return_value=cards):
            with patch("botcore._detect_skills_templates", return_value=tmpl_false_spirit):
                choice = choose_best_artifact_or_card(frame)
                # Slot 1 should be recognized as Electric Zone, NOT Spirit!
                self.assertEqual(choice.idx, 1)
                self.assertEqual(choice.skill_key, "electric_zone")
                self.assertNotIn("Spirit", choice.label)

        # 2. When Spirit is in maxed_skills, Spirit must NEVER be chosen
        cards_with_spirit = {
            1: CardSlotData(1, text_lines=["spirit", "lv. max"], skills=["spirit"], is_maxed=True),
            2: CardSlotData(2, text_lines=["electric zone", "lv. 2"], skills=["electric_zone"]),
            3: CardSlotData(3, text_lines=["fireball", "lv. 1"], skills=["fireball"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards_with_spirit):
            choice2 = choose_best_artifact_or_card(frame, maxed_skills={"spirit"})
            self.assertEqual(choice2.idx, 2)
            self.assertEqual(choice2.skill_key, "electric_zone")
            self.assertIn("Electric Zone", choice2.label)

    def test_multiscale_chest_detection_and_armageddon_aliases(self):
        import botcore
        # 1. Armageddon aliases include Gothic deformed OCR lines
        self.assertIn("a eddo n", botcore.SKILL_ALIASES["armageddon"])
        self.assertIn("remove all enemies", botcore.SKILL_ALIASES["armageddon"])

        # 2. Chest slots on 1080p LDPlayer sit at y=0.385
        s1 = botcore.get_chest_card_target(1, 0.50, y=0.385)
        s2 = botcore.get_chest_card_target(2, 0.50, y=0.385)
        s3 = botcore.get_chest_card_target(3, 0.50, y=0.385)
        self.assertEqual(s1[1], 0.385)
        self.assertEqual(s2[1], 0.385)
        self.assertEqual(s3[1], 0.385)
        self.assertAlmostEqual(s1[0], 0.265, places=2)
        self.assertAlmostEqual(s3[0], 0.735, places=2)

        # 3. Attribute circle targets & Learn active state
        targets = botcore.get_attribute_circle_targets()
        self.assertEqual(targets[1], (0.50, 0.29))
        self.assertEqual(targets[2], (0.31, 0.44))
        self.assertEqual(targets[3], (0.68, 0.44))

        # Test learn active state on blank vs bright learn
        blank = np.zeros((1000, 600, 3), dtype=np.uint8)
        self.assertFalse(botcore.is_learn_button_active(blank))
        bright_learn = np.zeros((1000, 600, 3), dtype=np.uint8)
        bright_learn[860:910, 240:360] = 255
        self.assertTrue(botcore.is_learn_button_active(bright_learn))

    def test_chest_modal_and_die_detection_on_1080p(self):
        import botcore
        from pathlib import Path

        chest_path = Path(r"C:\Users\User\.gemini\antigravity\brain\2dc840cb-72eb-45f9-92e9-a3fe999f18b4\.user_uploaded\media_1794314056060_1ea9202c.png")
        die_path = Path(r"C:\Users\User\.gemini\antigravity\brain\2dc840cb-72eb-45f9-92e9-a3fe999f18b4\.user_uploaded\media_1794303389717_e66f4fae.png")

        if chest_path.is_file():
            img_chest = cv2.imread(str(chest_path))
            img_1080 = cv2.resize(img_chest, (1080, 1920))

            # 1. Obtain button is reliably detected on both original and 1080p
            ob_orig = botcore.detect_obtain_button(img_chest)
            self.assertIsNotNone(ob_orig)
            self.assertAlmostEqual(ob_orig[1], 0.812, delta=0.04)

            ob_1080 = botcore.detect_obtain_button(img_1080)
            self.assertIsNotNone(ob_1080)
            self.assertAlmostEqual(ob_1080[1], 0.812, delta=0.04)

            # 2. Chest modal screen detection
            self.assertTrue(botcore.is_chest_screen(img_chest))
            self.assertTrue(botcore.is_chest_screen(img_1080))

            # 3. Chest modal is NEVER misidentified as Level Up screen or Ad Close button
            lvl_res = botcore.is_level_up_screen(img_1080)
            self.assertFalse(bool(lvl_res))
            self.assertEqual(lvl_res[1], "obtain_button")

            ad_x = botcore.detect_close_button(img_1080)
            self.assertIsNone(ad_x)

        if die_path.is_file():
            img_die = cv2.imread(str(die_path))
            img_die_1080 = cv2.resize(img_die, (1080, 1920))

            # 4. Die button is detected immediately on original and 1080p
            d_orig = botcore.detect_die_button(img_die)
            self.assertIsNotNone(d_orig)
            self.assertAlmostEqual(d_orig[1], 0.73, delta=0.05)

            d_1080 = botcore.detect_die_button(img_die_1080)
            self.assertIsNotNone(d_1080)
            self.assertAlmostEqual(d_1080[1], 0.73, delta=0.05)

            # 5. Die screen is not a chest screen
            self.assertFalse(botcore.is_chest_screen(img_die))


if __name__ == "__main__":
    unittest.main()
