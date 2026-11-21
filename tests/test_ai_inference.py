import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import ai_inference
import botcore


class TestAIInference(unittest.TestCase):
    def test_feature_vector_dimensions_and_fusion_partner(self):
        vocab = ["cyclone", "electric_shock", "satellite", "spirit"]
        s2i = {s: i for i, s in enumerate(vocab)}
        vec = ai_inference.build_skill_feature_vector(
            vocab,
            s2i,
            candidate_skill="electric_shock",
            active_skills={"spirit"},
            skill_levels={"spirit": 7},
            level_count=20,
            offered_level=3,
            has_asterisk=True,
        )
        self.assertEqual(vec.shape, (2 * len(vocab) + 6,))
        # Spirit is at index 3 -> level 7/7 = 1.0
        self.assertAlmostEqual(float(vec[3]), 1.0, places=4)
        # Candidate electric_shock is at index 4 + 1 = 5
        self.assertAlmostEqual(float(vec[len(vocab) + 1]), 1.0, places=4)
        # Fusion partner flag is the last element (spirit + electric_shock are partners)
        self.assertAlmostEqual(float(vec[-1]), 1.0, places=4)

    def test_numpy_mlp_inference_and_ai_preset_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            vocab = ["cyclone", "spirit"]
            in_dim = 2 * len(vocab) + 6
            # Construct a 2-layer MLP that strongly rewards "spirit" (index vocab_len + 1 = 3)
            w1 = np.zeros((4, in_dim), dtype=np.float32)
            w1[0, len(vocab) + 1] = 5.0  # Neuron 0 fires when candidate == "spirit"
            b1 = np.zeros(4, dtype=np.float32)

            w2 = np.zeros((1, 4), dtype=np.float32)
            w2[0, 0] = 2.0
            b2 = np.array([0.5], dtype=np.float32)

            net_payload = {
                "version": 1,
                "vocab": vocab,
                "input_dim": in_dim,
                "layers": [
                    {"weight": w1.tolist(), "bias": b1.tolist()},
                    {"weight": w2.tolist(), "bias": b2.tolist()},
                ],
            }
            (tmp_dir / "skill_value_net.json").write_text(json.dumps(net_payload), encoding="utf-8")

            eng = ai_inference.AIInferenceEngine(models_dir=tmp_dir)
            self.assertTrue(eng.has_skill_model)
            spirit_score = eng.score_skill_candidate("spirit", active_skills=set(), level_count=12)
            cyclone_score = eng.score_skill_candidate("cyclone", active_skills=set(), level_count=12)
            self.assertGreater(spirit_score, cyclone_score + 5.0)

            # Verify botcore apply_build_preset('ai') sets empty skill_priority for pure AI mode
            cfg = botcore.apply_build_preset({}, "ai")
            self.assertEqual(cfg["build_mode"], "ai")
            self.assertEqual(cfg["skill_priority"], [])

            # Verify choose_best_artifact_or_card in AI mode picks the card with higher AI score
            frame = np.zeros((400, 300, 3), dtype=np.uint8)
            fake_cards = {
                1: botcore.CardSlotData(1, text_lines=["cyclone lv 2"], skills=["cyclone"], offered_level=2),
                2: botcore.CardSlotData(2, text_lines=["spirit lv 2"], skills=["spirit"], offered_level=2),
                3: botcore.CardSlotData(3, text_lines=["empty"], skills=[], is_maxed=True),
            }
            with patch("botcore._detect_cards_ocr", return_value=fake_cards), \
                 patch("botcore._detect_skills_templates", return_value={1: [], 2: [], 3: []}), \
                 patch("ai_inference.get_ai_engine", return_value=eng):
                choice = botcore.choose_best_artifact_or_card(
                    frame,
                    skill_priority=[],  # AI free mode
                    level_count=15,
                )
                self.assertEqual(choice[0], 2)
                self.assertEqual(choice.skill_key, "spirit")
                self.assertEqual(choice.offered_cards, {"1": ["cyclone"], "2": ["spirit"]})

    def test_numpy_vision_cnn_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            card_classes = ["cyclone", "electric_zone", "spirit"]
            meta = {
                "card_classes": card_classes,
                "screen_classes": ["chest", "level_up"],
                "card_size_wh": [192, 64],
                "screen_size_wh": [96, 160],
            }
            (tmp_dir / "vision_meta.json").write_text(json.dumps(meta), encoding="utf-8")

            # Save zero weights except fc_b strongly favoring index 1 ("electric_zone")
            weights = {
                "w0": np.zeros((24, 3, 3, 3), dtype=np.float32),
                "b0": np.zeros(24, dtype=np.float32),
                "w1": np.zeros((48, 24, 3, 3), dtype=np.float32),
                "b1": np.zeros(48, dtype=np.float32),
                "w2": np.zeros((96, 48, 3, 3), dtype=np.float32),
                "b2": np.zeros(96, dtype=np.float32),
                "w3": np.zeros((128, 96, 3, 3), dtype=np.float32),
                "b3": np.zeros(128, dtype=np.float32),
                "fc_w": np.zeros((3, 128), dtype=np.float32),
                "fc_b": np.array([-5.0, 10.0, -5.0], dtype=np.float32),
            }
            np.savez_compressed(str(tmp_dir / "card_vision.npz"), **weights)

            eng = ai_inference.AIInferenceEngine(models_dir=tmp_dir)
            self.assertTrue(eng.has_card_vision)
            frame = np.zeros((320, 180, 3), dtype=np.uint8)
            preds = eng.predict_card_skills(frame, num_cards=3)
            self.assertEqual(preds[1][0], "electric_zone")
            self.assertGreater(preds[1][1], 0.99)


if __name__ == "__main__":
    unittest.main()
