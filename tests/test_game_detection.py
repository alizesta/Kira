import unittest

from kira.game_detection import is_ai1_window


class GameWindowIdentityTests(unittest.TestCase):
    def test_current_process_is_always_excluded(self):
        self.assertTrue(is_ai1_window({"pid": 42, "title": "Some window"}, 42))

    def test_project_kira_stable_title_is_excluded_even_with_different_pid(self):
        self.assertTrue(is_ai1_window({"pid": 999, "title": "Project Kira 1 stable"}, 42))

    def test_ai1_title_is_excluded(self):
        self.assertTrue(is_ai1_window({"pid": 999, "title": "Ai1"}, 42))

    def test_unrelated_large_game_title_is_not_excluded(self):
        self.assertFalse(is_ai1_window({"pid": 999, "title": "Some Game"}, 42))


if __name__ == "__main__":
    unittest.main()
