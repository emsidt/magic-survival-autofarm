"""Offline movement scenarios; no input is sent to the game."""

import math
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from botcore import Vision, choose_direction, inspect_game


class PickupMovementTests(unittest.TestCase):
    def scene(self, enemies=(), chest=None, gems=()):
        mask = np.zeros((800, 500), np.uint8)
        for x, y, radius in enemies:
            cv2.circle(mask, (x, y), radius, 255, -1)
        distance = cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5)
        return Vision(mask, distance, list(gems), True, 1.0, chest=chest)

    def test_enemy_beyond_nearby_mana_does_not_prevent_pickup(self):
        vision = self.scene(enemies=[(300, 400, 10)], gems=[(270, 404)])
        direction = choose_direction(vision, 0, previous=(-1, 0))
        expected = np.array([20, 4]) / math.hypot(20, 4)
        np.testing.assert_allclose(direction, expected)

    def test_close_chest_overrides_previous_retreat_and_mana(self):
        vision = self.scene(chest=(310, 417), gems=[(220, 400)])
        direction = choose_direction(vision, 0, previous=(-1, 0))
        np.testing.assert_allclose(direction, np.array([60, 17]) / math.hypot(60, 17))

    def test_distant_chest_still_allows_nearby_mana(self):
        vision = self.scene(chest=(480, 400), gems=[(250, 365)])
        self.assertEqual(choose_direction(vision, 0), (0, -1))

    def test_sword_approaches_nearest_blocker(self):
        vision = self.scene(enemies=[(325, 400, 14)], chest=(420, 400))
        self.assertLess(choose_direction(vision, 0)[0], 0.99)
        self.assertEqual(choose_direction(vision, 0, active_skills={"telekinetic_sword"}), (1, 0))

    def test_enemy_behind_player_takes_autoaim_priority(self):
        vision = self.scene(enemies=[(325, 400, 14), (220, 400, 8)], chest=(420, 400))
        self.assertLess(choose_direction(vision, 0, active_skills={"telekinetic_sword"})[0], 0.99)

    def test_sword_still_flanks_enemy_in_contact_range(self):
        vision = self.scene(enemies=[(290, 400, 14)], chest=(420, 400))
        self.assertLess(choose_direction(vision, 0, active_skills={"telekinetic_sword"})[0], 0.99)

    def test_sword_does_not_charge_dense_wall(self):
        vision = self.scene(chest=(420, 400))
        vision.enemy_mask[:, 315:350] = 255
        vision.distance = cv2.distanceTransform(255 - vision.enemy_mask, cv2.DIST_L2, 5)
        self.assertLess(choose_direction(vision, 0, active_skills={"telekinetic_sword"})[0], 0.99)

    def test_only_acquired_configured_autoaim_skills_enable_approach(self):
        vision = self.scene(enemies=[(325, 400, 14)], chest=(420, 400))
        self.assertLess(choose_direction(vision, 0, active_skills={"other_skill"})[0], 0.99)
        self.assertLess(choose_direction(vision, 0, nearest_target_skills={"telekinetic_sword"})[0], 0.99)
        self.assertLess(choose_direction(vision, 0, active_skills={"telekinetic_sword"}, nearest_target_skills=set())[0], 0.99)
        self.assertEqual(choose_direction(vision, 0, active_skills={"other_skill"}, nearest_target_skills={"other_skill"}), (1, 0))

    def test_approach_changes_to_dodging_when_enemy_remains_alive(self):
        first = self.scene(enemies=[(325, 400, 14)], chest=(420, 400))
        second = self.scene(enemies=[(290, 400, 14)], chest=(385, 400))
        previous = choose_direction(first, 0, active_skills={"telekinetic_sword"})
        self.assertEqual(previous, (1, 0))
        following = choose_direction(second, 1, previous=previous, active_skills={"telekinetic_sword"})
        self.assertLess(following[0], 0.99)

    def test_detects_mana_close_to_player_and_at_high_resolution(self):
        for width, height, offset, radius in [(500, 800, 20, 4), (1080, 1920, 160, 16)]:
            with self.subTest(width=width):
                frame = np.full((height, width, 3), 110, np.uint8)
                orb = (width // 2 + offset, height // 2)
                cv2.circle(frame, orb, radius, (255, 190, 0), -1)
                with patch("botcore.detect_chest", return_value=None), patch("botcore.detect_monolith", return_value=None):
                    vision = inspect_game(frame)
                self.assertTrue(any(math.dist(point, orb) < 3 for point in vision.gems), vision.gems)

    def test_open_field_patrol_turns_smoothly_without_directional_lock(self):
        """Character in an open field must turn dynamically rather than locking in 1 direction forever."""
        mask = np.zeros((1920, 1080), np.uint8)
        distance = np.full((1920, 1080), 500.0, dtype=np.float32)
        vision = Vision(mask, distance, [], True, 0.8)

        dirs = []
        prev = (0.0, 1.0)
        for t in range(0, 30, 2):
            d = choose_direction(vision, float(t), prev)
            dirs.append(d)
            prev = d

        unique_headings = set((round(d[0], 2), round(d[1], 2)) for d in dirs)
        self.assertGreaterEqual(len(unique_headings), 4, f"Expected at least 4 unique headings, got {unique_headings}")

    def test_player_sprite_is_not_treated_as_pickup(self):
        """Player's own sprite features at screen center must not be extracted as mana orbs."""
        frame = np.full((1920, 1080, 3), 110, np.uint8)
        px, py = 540, 960
        # Draw simulated player robe / hat highlight at offset (dx=-7, dy=-28)
        cv2.circle(frame, (px - 7, py - 28), 3, (137, 123, 1), -1)
        with patch("botcore.detect_chest", return_value=None), patch("botcore.detect_monolith", return_value=None):
            vision = inspect_game(frame)
        self.assertFalse(any(math.hypot(gx - px, gy - py) < 35 for gx, gy in vision.gems))

    def test_detect_boss_monsters_finds_red_health_bar(self):
        """Elite and Boss monsters with prominent horizontal red health bars must be detected."""
        frame = np.full((1000, 1000, 3), 110, np.uint8)
        # Draw horizontal red health bar at (600, 700), width=100, height=6
        frame[700:706, 600:700] = (30, 30, 210)
        from botcore import detect_boss_monsters
        bosses = detect_boss_monsters(frame)
        self.assertEqual(len(bosses), 1)
        bx, by, br = bosses[0]
        self.assertAlmostEqual(bx, 650, delta=10)
        self.assertLess(by, 700)  # Boss body is above health bar

    def test_choose_direction_evades_boss_away_from_danger(self):
        """When an Elite/Boss is nearby, choose_direction must steer away from the boss."""
        mask = np.zeros((1000, 1000), np.uint8)
        dist = np.full((1000, 1000), 500.0, np.float32)
        # Boss on the right at (700, 500), player at center (500, 500)
        v = Vision(mask, dist, [(700, 500)], True, 0.8, bosses=[(700, 500, 120)])
        d = choose_direction(v, 0.0, player=(0.5, 0.5))
        self.assertLess(d[0], -0.2, f"Expected steering left away from boss, got dx={d[0]}")

    def test_approach_pickup_blocks_path_near_boss(self):
        """_approach_pickup must reject targets inside or passing through a boss danger zone."""
        from botcore import _approach_pickup
        mask = np.zeros((1000, 1000), np.uint8)
        dist = np.full((1000, 1000), 500.0, np.float32)
        v = Vision(mask, dist, [(700, 500)], True, 0.8, bosses=[(700, 500, 120)])
        app = _approach_pickup(v, (700, 500), (500, 500), False)
        self.assertIsNone(app)

    def test_guaranteed_skills_advance_to_chest_through_normal_blocker(self):
        """When player has guaranteed damage skills (Electric Zone, Spirit), bot advances to chest."""
        vision = self.scene(enemies=[(290, 400, 12)], chest=(420, 400))
        # With electric_zone, bot should advance towards the chest (+x direction)
        d = choose_direction(vision, 0.0, active_skills={"electric_zone"})
        self.assertGreater(d[0], 0.40, f"Expected positive chest approach dx, got {d[0]}")

    def test_apply_human_weave(self):
        """apply_human_weave produces an oscillating perpendicular micro-vector."""
        from botcore import apply_human_weave
        d_base = (1.0, 0.0)
        # At elapsed = 0.0 -> sin(0) = 0 -> exact same direction
        w0 = apply_human_weave(d_base, 0.0)
        self.assertEqual(w0, (1.0, 0.0))

        # At elapsed = 0.25 / freq (quarter phase) -> max positive perpendicular oscillation
        w_peak = apply_human_weave(d_base, 0.25 / 3.2, frequency=3.2, amplitude=0.30)
        self.assertAlmostEqual(w_peak[0] ** 2 + w_peak[1] ** 2, 1.0, delta=0.01)
        self.assertNotEqual(w_peak[1], 0.0)


if __name__ == "__main__":
    unittest.main()
