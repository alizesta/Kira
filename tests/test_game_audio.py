import unittest

from kira.game_audio import is_important_game_audio


class GameAudioFilterTests(unittest.TestCase):
    def test_urgent_game_audio_is_important(self):
        self.assertTrue(is_important_game_audio("Warning! Low health."))

    def test_mission_completion_is_important(self):
        self.assertTrue(is_important_game_audio("Mission complete"))

    def test_persian_alert_is_important(self):
        self.assertTrue(is_important_game_audio("خونت کم شده، خطر!"))

    def test_ordinary_dialogue_is_ignored(self):
        self.assertFalse(is_important_game_audio("Welcome back, traveler. How are you?"))


if __name__ == "__main__":
    unittest.main()
