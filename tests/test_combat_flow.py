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

    def test_combat_near_dark_map_boundary_still_uses_fast_path(self):
        frame = np.full((960, 540, 3), 70, np.uint8)
        frame[680:, :] = 0  # Bottom dark map-boundary fog
        with patch("botcore.detect_pause_button", return_value=(0.935, 0.032)), \
                patch("winocr.recognize_pil", new=AsyncMock(return_value=Mock(lines=[]))):
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

    def test_inspect_game_skips_monolith_and_chest_when_boss_present(self):
        frame = np.full((960, 540, 3), 110, np.uint8)
        mock_mono = Mock(return_value=(100, 200))
        mock_chest = Mock(return_value=botcore.ChestTarget((150, 250)))
        with patch("botcore.detect_pause_button", return_value=(0.935, 0.032)), \
                patch("botcore.detect_boss_monsters", return_value=[(270, 350, 80)]), \
                patch("botcore.detect_monolith", mock_mono), \
                patch("botcore.detect_chest", mock_chest):
            vision = botcore.inspect_game(frame, known_monolith=(100, 200), known_chest=(150, 250))
        mock_mono.assert_not_called()
        mock_chest.assert_not_called()
        self.assertIsNone(vision.monolith)
        self.assertIsNone(vision.chest)
        self.assertFalse(vision.monolith_detected)
        self.assertFalse(vision.chest_detected)

    def test_inspect_game_respects_scan_flags(self):
        frame = np.full((960, 540, 3), 110, np.uint8)
        mock_mono = Mock(return_value=(100, 200))
        mock_chest = Mock(return_value=botcore.ChestTarget((150, 250)))
        with patch("botcore.detect_pause_button", return_value=(0.935, 0.032)), \
                patch("botcore.detect_boss_monsters", return_value=[]), \
                patch("botcore.detect_monolith", mock_mono), \
                patch("botcore.detect_chest", mock_chest):
            vision = botcore.inspect_game(frame, scan_monolith=False, scan_chest=False)
        mock_mono.assert_not_called()
        mock_chest.assert_not_called()
        self.assertIsNone(vision.monolith)
        self.assertIsNone(vision.chest)

    def test_is_fast_combat_frame_skip_ocr_avoids_winocr(self):
        combat = botcore.prepare_analysis_frame(cv2.imread(str(Path(__file__).parent / "fixtures/movement/combat.png")))
        level_up = botcore.prepare_analysis_frame(cv2.imread(str(Path(__file__).parent / "fixtures/movement/level_up.png")))
        crowded_lu = botcore.prepare_analysis_frame(cv2.imread(str(Path(__file__).parent / "fixtures/movement/level_up_crowded.png")))
        with patch("winocr.recognize_pil", new=AsyncMock(side_effect=AssertionError("should not run"))):
            self.assertTrue(botcore.is_fast_combat_frame(combat, skip_ocr=True))
            self.assertFalse(botcore.is_fast_combat_frame(level_up, skip_ocr=True))
            self.assertFalse(botcore.is_fast_combat_frame(crowded_lu, skip_ocr=True))

    def test_crowded_level_up_modal_rejects_fast_combat_with_and_without_ocr(self):
        crowded_lu = botcore.prepare_analysis_frame(cv2.imread(str(Path(__file__).parent / "fixtures/movement/level_up_crowded.png")))
        self.assertFalse(botcore.is_fast_combat_frame(crowded_lu, skip_ocr=False))
        self.assertFalse(botcore.is_fast_combat_frame(crowded_lu, skip_ocr=True))
        self.assertTrue(bool(botcore.is_level_up_screen(crowded_lu)))

    def test_boss_evasion_disables_weave_and_avoids_boss(self):
        mask = np.zeros((960, 540), np.uint8)
        dist = np.full((960, 540), 500.0, np.float32)
        vision = botcore.Vision(
            mask,
            dist,
            [(400, 480)],
            True,
            0.8,
            bosses=[(390, 480, 90)],
        )
        d_weave = botcore.choose_direction(vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=True)
        d_plain = botcore.choose_direction(vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=False)
        self.assertEqual(d_weave, d_plain)
        self.assertLess(d_weave[0], -0.2)

    def test_near_chest_disables_human_weave(self):
        mask = np.zeros((960, 540), np.uint8)
        dist = np.full((960, 540), 500.0, np.float32)
        vision = botcore.Vision(
            mask,
            dist,
            [],
            True,
            0.8,
            chest=(350, 480),
        )
        d_weave = botcore.choose_direction(vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=True)
        d_plain = botcore.choose_direction(vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=False)
        self.assertEqual(d_weave, d_plain)

    def test_distant_boss_triggers_wide_evasion_and_blocks_chest(self):
        mask = np.zeros((960, 540), np.uint8)
        dist = np.full((960, 540), 500.0, np.float32)
        vision = botcore.Vision(
            mask,
            dist,
            [],
            True,
            0.8,
            chest=(450, 480),
            bosses=[(490, 480, 75)],
        )
        direction = botcore.choose_direction(
            vision,
            elapsed=0.0,
            previous=(1.0, 0.0),
            active_skills={"spirit", "electric_zone"},
        )
        self.assertLess(direction[0], -0.3)

    def test_top_wave_darkness_is_detected_and_avoided(self):
        frame = np.full((800, 500, 3), 110, np.uint8)
        frame[int(800 * 0.10) : int(800 * 0.42), :] = 25
        with patch("botcore.detect_chest", return_value=None), patch("botcore.detect_monolith", return_value=None):
            vision = botcore.inspect_game(frame, player=(0.5, 0.5))
        self.assertEqual(vision.hazard_mask[200, 250], 255)
        direction = botcore.choose_direction(vision, elapsed=0.0, player=(0.5, 0.5), previous=(0.0, -1.0))
        self.assertGreater(direction[1], 0.3)

    def test_boss_evasion_never_backs_into_wave_darkness(self):
        mask = np.zeros((800, 500), np.uint8)
        hazard = np.zeros((800, 500), np.uint8)
        hazard[:, 360:] = 255
        dist = cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5)
        vision = botcore.Vision(
            mask,
            dist,
            [],
            True,
            0.8,
            bosses=[(130, 400, 55)],
            hazard_mask=hazard,
        )
        direction = botcore.choose_direction(vision, elapsed=0.0, player=(0.5, 0.5), previous=(1.0, 0.0))
        self.assertGreater(abs(direction[1]), 0.4)
        self.assertLessEqual(direction[0], 0.15)

    def test_wave_active_disables_weave_and_avoids_risky_orb(self):
        mask = np.zeros((960, 540), np.uint8)
        # Put dense enemies on the right between player (270, 480) and risky orb at (355, 480)
        mask[450:510, 315:345] = 255
        dist = cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5)
        vision = botcore.Vision(mask, dist, [(355, 480)], True, 0.8)

        d_wave_weave = botcore.choose_direction(
            vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=True, wave_active=True
        )
        d_wave_plain = botcore.choose_direction(
            vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=False, wave_active=True
        )
        d_normal = botcore.choose_direction(
            vision, elapsed=0.078125, previous=(1.0, 0.0), enable_weave=False, wave_active=False
        )
        self.assertEqual(d_wave_weave, d_wave_plain)
        self.assertLess(d_wave_plain[0], d_normal[0])
        self.assertLess(d_wave_plain[0], 0.45)
