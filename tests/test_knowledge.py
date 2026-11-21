import unittest

import knowledge


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        knowledge.reset_owned_artifacts()
        self.addCleanup(knowledge.reset_owned_artifacts)

    def test_wiki_counts_match(self):
        k = knowledge.load_knowledge()
        self.assertEqual(len(k["magic_combinations"]), 60)
        self.assertEqual(len(k["artifact_synergies"]["unique"]), 35)
        self.assertEqual(len(k["subjects"]["list"]), 25)
        self.assertEqual(sum(len(v) for v in k["artifacts"].values()), 181)
        names = [f["name"] for f in k["magic_combinations"]]
        self.assertEqual(len(names), len(set(names)))

    def test_key_fusion_recipes(self):
        bh = knowledge.fusion_by_name("Black Hole")
        self.assertEqual((bh["primary"]["trait"], bh["secondary"]["trait"]), ("Void", "Nuclear Fission"))
        sc = knowledge.fusion_by_name("super cyclone")
        self.assertEqual({sc["primary"]["skill"], sc["secondary"]["skill"]}, {"Cyclone", "Electric Zone"})
        self.assertEqual(sc["secondary"]["trait"], "Fire Aura")
        self.assertEqual(knowledge.fusion_by_name("Deus Ex Machina")["primary"]["skill"], "Overmind")
        pair = knowledge.find_fusions("Cyclone", "Satellite")
        self.assertEqual({f["name"] for f in pair}, {"Vortex", "Black Hole", "Neutron Generation"})

    def test_subjects(self):
        e = knowledge.subject_info("Electromancer")
        self.assertEqual(e["artifact"], "Robot")
        self.assertEqual(knowledge.subject_info("Druid")["artifact"], "Palm Leaf Fan")

    def test_stat_groups(self):
        self.assertEqual(knowledge.stat_groups_in_text("Decrease All Magic Cooldown by 6%"), ["magic_cooldown"])
        self.assertIn("atk_amplify", knowledge.stat_groups_in_text("Amplify ATK by 40%"))

    def test_synergy_progress_and_completion(self):
        # Monarch = Crown + Diamond + Sapphire + Ruby
        bonus0, tag0 = knowledge.artifact_synergy_bonus("Crown")
        self.assertEqual(bonus0, knowledge.SYNERGY_POTENTIAL_BONUS)
        for name in ("Crown", "Diamond"):
            knowledge.remember_artifact(name)
        bonus2, tag2 = knowledge.artifact_synergy_bonus("Sapphire")
        self.assertEqual(bonus2, knowledge.SYNERGY_PROGRESS_BONUS * 2)
        self.assertIn("3/4", tag2)
        knowledge.remember_artifact("Sapphire")
        bonus3, tag3 = knowledge.artifact_synergy_bonus("Ruby [Normal | ATK]")
        self.assertEqual(bonus3, knowledge.SYNERGY_COMPLETE_BONUS)
        self.assertIn("Monarch", tag3)

    def test_owned_or_unknown_artifact_gets_nothing(self):
        knowledge.remember_artifact("Crown")
        self.assertEqual(knowledge.artifact_synergy_bonus("Crown")[0], 0)
        self.assertEqual(knowledge.artifact_synergy_bonus("Totally Unknown Thing")[0], 0)
        self.assertEqual(knowledge.artifact_synergy_bonus("")[0], 0)

    def test_similar_names_are_not_confused(self):
        # Seen live: 'Lightning Rod' (no synergy) was matched to 'Lightning' (Godhand/Nymph component)
        self.assertIsNone(knowledge.canonical_artifact("Lightning Rod"))
        self.assertEqual(knowledge.artifact_synergy_bonus("Lightning Rod [Rare | Hồi chiêu]")[0], 0)
        self.assertIsNotNone(knowledge.canonical_artifact("Lightning"))
        self.assertIsNotNone(knowledge.canonical_artifact("Rai n bow"))

    def test_ocr_noise_still_matches(self):
        self.assertIsNotNone(knowledge.canonical_artifact("Wizards Hat"))
        self.assertIsNotNone(knowledge.canonical_artifact("Wizarcl's Hat"))


if __name__ == "__main__":
    unittest.main()
