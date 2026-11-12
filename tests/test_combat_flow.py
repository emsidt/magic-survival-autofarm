from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

import cv2
import numpy as np

import botcore


class CombatFlowTests(unittest.TestCase):
    def test_real_level_up_hud_is_not_fast_combat(self):
        path = Path(__file__).parent / "fixtures/movement/level_up.png"
        frame = botcore.prepare_analysis_frame(cv2.imread(str(path)))
        self.assertFalse(botcore.is_fast_combat_frame(frame))

    def test_real_level_up_header_reports_player_level(self):
        path = Path(__file__).parent / "fixtures/movement/level_up.png"
        frame = botcore.prepare_analysis_frame(cv2.imread(str(path)))
        self.assertEqual(botcore.detect_player_level(frame), 8)

    def test_real_combat_uses_fast_path(self):
        path = Path(__file__).parent / "fixtures/movement/combat.png"
        frame = botcore.prepare_analysis_frame(cv2.imread(str(path)))
        self.assertEqual(frame.shape[1], 540)
        self.assertTrue(botcore.is_fast_combat_frame(frame))

    def test_missing_hud_and_failed_ocr_use_menu_checks(self):
        frame = np.full((800, 450, 3), 100, np.uint8)
        self.assertFalse(botcore.is_fast_combat_frame(frame))
        with patch("botcore.detect_pause_button", return_value=(0.93, 0.04)), \
                patch("winocr.recognize_pil", new=AsyncMock(side_effect=RuntimeError("OCR unavailable"))):
            self.assertFalse(botcore.is_fast_combat_frame(frame))

    def test_bright_level_up_header_prevents_fast_path(self):
        frame = np.full((800, 450, 3), 160, np.uint8)
        result = Mock(lines=[Mock(text="Select Magic")])
        with patch("botcore.detect_pause_button", return_value=(0.93, 0.04)), \
                patch("winocr.recognize_pil", new=AsyncMock(return_value=result)):
            self.assertFalse(botcore.is_fast_combat_frame(frame))

    def test_restore_gold_uses_confirm_above_results_button_region(self):
        frame = np.zeros((1000, 600, 3), np.uint8)
        word = Mock(text="Confirm", bounding_rect=Mock(x=220, y=460, width=100, height=30))
        result = Mock(lines=[Mock(text="Restore Gold", words=[]), Mock(text="Confirm", words=[word])])
        with patch("winocr.recognize_pil", new=AsyncMock(return_value=result)):
            self.assertEqual(botcore.detect_restore_gold(frame), (0.5, 0.675))
        result.lines[0].text = "Experiment Failed"
        with patch("winocr.recognize_pil", new=AsyncMock(return_value=result)):
            self.assertIsNone(botcore.detect_restore_gold(frame))

    def wave_scene(self, player=(0.5, 0.5), monolith=False):
        frame = np.full((800, 500, 3), 110, np.uint8)
        frame[:, 290:] = 28  # Continuous dark wave zone on the right.
        target = botcore.ChestTarget((320, 400))
        with patch("botcore.detect_chest", return_value=None if monolith else target), \
                patch("botcore.detect_monolith", return_value=(320, 400) if monolith else None):
            return botcore.inspect_game(frame, player)

    def test_loot_exclusion_does_not_erase_wave_darkness(self):
        for monolith in (False, True):
            with self.subTest(monolith=monolith):
                vision = self.wave_scene(monolith=monolith)
                self.assertEqual(vision.hazard_mask[400, 320], 255)
                self.assertEqual(vision.distance[400, 320], 0)
                direction = botcore.choose_direction(vision, 0, previous=(1, 0), active_skills={"telekinetic_sword"})
                self.assertLessEqual(direction[0], 0.01)

    def test_player_inside_dark_zone_exits_instead_of_chasing_chest(self):
        vision = self.wave_scene(player=(0.65, 0.5))
        direction = botcore.choose_direction(vision, 0, player=(0.65, 0.5), previous=(1, 0))
        self.assertLess(direction[0], -0.95)

    def test_mana_inside_dark_zone_cannot_trigger_direct_approach(self):
        vision = self.wave_scene()
        vision.chest = None
        vision.gems = [(320, 400)]
        direction = botcore.choose_direction(vision, 0, active_skills={"telekinetic_sword"})
        self.assertLessEqual(direction[0], 0.01)

    def test_all_dark_has_no_random_patrol(self):
        mask = np.full((800, 500), 255, np.uint8)
        vision = botcore.Vision(mask, np.zeros(mask.shape, np.float32), [], True, 0, hazard_mask=mask)
        self.assertEqual(botcore.choose_direction(vision, 0), (0, 0))

    def test_soft_dark_boundary_and_spell_glow_do_not_attract_player(self):
        # Like the reported arena: light above-left, gradual darkness below-right.
        y, x = np.mgrid[:800, :500]
        shade = np.clip((x + y * 0.65 - 460) / 100, 0, 1)
        gray = (100 - 48 * shade).astype(np.uint8)  # Even the core is > old 48 threshold.
        frame = np.repeat(gray[:, :, None], 3, axis=2)
        cv2.circle(frame, (300, 480), 30, (180, 220, 255), -1)
        with patch("botcore.detect_chest", return_value=None), patch("botcore.detect_monolith", return_value=None):
            vision = botcore.inspect_game(frame)
        self.assertEqual(vision.hazard_mask[480, 300], 255)
        vision.chest = (350, 550)
        vision.gems = [(300, 480)]
        direction = botcore.choose_direction(vision, 0, previous=(0.7, 0.7), active_skills={"telekinetic_sword"})
        self.assertLess(direction[0], 0)
        self.assertLess(direction[1], 0)

    def test_enclosed_spell_light_is_not_an_escape_destination(self):
        frame = np.full((800, 500, 3), 100, np.uint8)
        frame[:, 200:] = 25
        cv2.circle(frame, (300, 400), 35, (255, 255, 255), -1)
        with patch("botcore.detect_chest", return_value=None), patch("botcore.detect_monolith", return_value=None):
            vision = botcore.inspect_game(frame)
        self.assertEqual(vision.hazard_mask[400, 300], 255)
        direction = botcore.choose_direction(vision, 0)
        self.assertLess(direction[0], -0.95)
