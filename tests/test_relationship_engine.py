import unittest

from kira.character.relationship import RelationshipEngine, DEFAULT_RELATIONSHIP


class RelationshipEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = RelationshipEngine()
        self.state = dict(DEFAULT_RELATIONSHIP)

    def test_user_signals_change_relationship_gradually(self):
        before = dict(self.state)
        self.engine.on_user_signals(self.state, ["thanks"])
        self.assertGreater(self.state["closeness"], before["closeness"])
        self.assertLess(self.state["closeness"] - before["closeness"], 1.0)
        self.assertGreater(self.state["familiarity"], before["familiarity"])

    def test_hostility_adds_tension_and_apology_reduces_it(self):
        self.engine.on_user_signals(self.state, ["hostile"])
        tense = self.state["tension"]
        self.assertGreater(tense, 0)
        self.engine.on_user_signals(self.state, ["apology"])
        self.assertLess(self.state["tension"], tense)
        self.assertGreater(self.state["trust"], DEFAULT_RELATIONSHIP["trust"])

    def test_time_reduces_tension_not_trust_or_closeness(self):
        self.state.update({"tension": 40.0, "trust": 61.0, "closeness": 43.0})
        before = dict(self.state)
        self.engine.advance(self.state, 86400)
        self.assertEqual(self.state["trust"], before["trust"])
        self.assertEqual(self.state["closeness"], before["closeness"])
        self.assertEqual(self.state["tension"], 38.0)

    def test_reply_affection_changes_closeness_slightly(self):
        self.engine.on_reply(self.state, ["happy", "affectionate"])
        self.assertAlmostEqual(self.state["closeness"], DEFAULT_RELATIONSHIP["closeness"] + 0.025)

    def test_style_feedback_changes_comfort_and_trust(self):
        self.engine.on_feedback(self.state, "disliked_teasing")
        self.assertGreater(self.state["comfort"], DEFAULT_RELATIONSHIP["comfort"])
        self.assertGreater(self.state["trust"], DEFAULT_RELATIONSHIP["trust"])

    def test_all_dimensions_remain_bounded(self):
        for _ in range(2000):
            self.engine.on_user_signals(self.state, ["thanks", "praise", "hostile"])
            self.engine.on_feedback(self.state, "liked_teasing")
        self.assertTrue(all(0 <= value <= 100 for value in self.state.values()))


if __name__ == "__main__":
    unittest.main()
