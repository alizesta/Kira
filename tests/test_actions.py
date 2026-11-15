import unittest
from unittest import mock

from kira.actions import run_safe_action


class SafeActionTests(unittest.TestCase):
    def test_competitive_safe_blocks_desktop_shortcuts(self):
        with mock.patch("kira.actions.subprocess.Popen") as popen, \
             mock.patch("kira.actions.webbrowser.open") as open_browser:
            result = run_safe_action("ماشین حساب", allow_desktop=False)
        self.assertIn("Competitive Safe", result)
        popen.assert_not_called()
        open_browser.assert_not_called()

    def test_competitive_safe_blocks_browser_launch(self):
        with mock.patch("kira.actions.webbrowser.open") as open_browser:
            result = run_safe_action("مرورگر رو باز کن", allow_desktop=False)
        self.assertIn("Competitive Safe", result)
        open_browser.assert_not_called()

    def test_story_mode_keeps_fixed_shortcuts_available(self):
        with mock.patch("kira.actions.subprocess.Popen") as popen:
            result = run_safe_action("ماشین حساب", allow_desktop=True)
        self.assertIn("Calculator", result)
        popen.assert_called_once_with(["calc.exe"], shell=False)


if __name__ == "__main__":
    unittest.main()
