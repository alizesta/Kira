"""Pure tests for game-audio transcript importance filtering."""
import unittest

from kira.game_audio_policy import is_important_game_audio


class GameAudioPolicyTests(unittest.TestCase):
    def test_important_game_audio_phrases_are_detected(self):
        for phrase in (
            "Low health warning",
            "Mission complete",
            "Enemy spotted",
            "خونت کم",
            "دستاورد",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_important_game_audio(phrase))

    def test_ordinary_dialogue_is_not_treated_as_an_alert(self):
        for phrase in ("hello friend", "good morning", "nice weather today"):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_important_game_audio(phrase))


if __name__ == "__main__":
    unittest.main()
