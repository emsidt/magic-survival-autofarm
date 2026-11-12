import unittest
from unittest.mock import patch
import numpy as np

import botcore
from botcore import CardSlotData, choose_best_artifact_or_card


class TestElectricZoneEarlyPriority(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((1000, 800, 3), dtype=np.uint8)

    def test_electric_zone_prioritized_over_spirit_in_first_ten_levels(self):
        """In the first 10 levels, Electric Zone should be picked over Spirit or Shield to survive early swarms."""
        cards = {
            1: CardSlotData(1, text_lines=["Spirit Lv. 1"], skills=["spirit"]),
            2: CardSlotData(2, text_lines=["Electric Zone Lv. 1"], skills=["electric_zone"]),
            3: CardSlotData(3, text_lines=["Shield Lv. 1"], skills=["shield"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards), patch("botcore._detect_skills_templates", return_value={}):
            choice = choose_best_artifact_or_card(
                self.frame,
                skill_priority=["spirit", "shield", "electric_zone"],
                level_count=2,
                skill_levels={},
            )
            self.assertEqual(choice.idx, 2)
            self.assertEqual(choice.skill_key, "electric_zone")
            self.assertIn("Ưu tiên đầu trận", choice.label)

    def test_electric_zone_up_to_level_four(self):
        """Electric Zone is prioritized up to Level 4."""
        cards = {
            1: CardSlotData(1, text_lines=["Spirit Lv. 2"], skills=["spirit"]),
            2: CardSlotData(2, text_lines=["Electric Zone Lv. 3"], skills=["electric_zone"]),
            3: CardSlotData(3, text_lines=["Vitality"], skills=["vitality"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards), patch("botcore._detect_skills_templates", return_value={}):
            choice = choose_best_artifact_or_card(
                self.frame,
                skill_priority=["spirit", "electric_zone"],
                level_count=6,
                skill_levels={"electric_zone": 2},
            )
            self.assertEqual(choice.idx, 2)
            self.assertEqual(choice.skill_key, "electric_zone")

    def test_normal_priority_resumes_once_electric_zone_reaches_level_four(self):
        """Once Electric Zone reaches level 4, normal skill priority (Spirit) takes over."""
        cards = {
            1: CardSlotData(1, text_lines=["Spirit Lv. 2"], skills=["spirit"]),
            2: CardSlotData(2, text_lines=["Electric Zone Lv. 5"], skills=["electric_zone"], offered_level=5),
            3: CardSlotData(3, text_lines=["Vitality"], skills=["vitality"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards), patch("botcore._detect_skills_templates", return_value={}):
            choice = choose_best_artifact_or_card(
                self.frame,
                skill_priority=["spirit", "electric_zone"],
                level_count=7,
                skill_levels={"electric_zone": 4},
            )
            self.assertEqual(choice.idx, 1)
            self.assertEqual(choice.skill_key, "spirit")

    def test_normal_priority_resumes_after_level_ten(self):
        """After player level 10, normal skill priority (Spirit) takes over even if Electric Zone is offered."""
        cards = {
            1: CardSlotData(1, text_lines=["Spirit Lv. 1"], skills=["spirit"]),
            2: CardSlotData(2, text_lines=["Electric Zone Lv. 2"], skills=["electric_zone"]),
            3: CardSlotData(3, text_lines=["Vitality"], skills=["vitality"]),
        }
        with patch("botcore._detect_cards_ocr", return_value=cards), patch("botcore._detect_skills_templates", return_value={}):
            choice = choose_best_artifact_or_card(
                self.frame,
                skill_priority=["spirit", "electric_zone"],
                level_count=12,
                skill_levels={"electric_zone": 1},
            )
            self.assertEqual(choice.idx, 1)
            self.assertEqual(choice.skill_key, "spirit")


if __name__ == "__main__":
    unittest.main()
