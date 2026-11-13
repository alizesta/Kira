"""Portable checks for Persian response quality and Persian app-action intent."""
import unittest

from kira.personality import CORE_LANGUAGE
from kira.tools import protocol


class PersianWritingContractTests(unittest.TestCase):
    def test_personality_contract_requires_silent_persian_proofreading(self):
        self.assertIn("silently proofread every Persian reply", CORE_LANGUAGE)
        self.assertIn("نیم‌فاصله", CORE_LANGUAGE)
        self.assertIn("می‌خوام", CORE_LANGUAGE)

    def test_persian_app_commands_enter_the_apps_tool_route(self):
        self.assertIn("apps", protocol.detect_categories("لطفاً اپرا جی ایکس رو باز کن"))
        self.assertIn("apps", protocol.detect_categories("برنامه‌ی تلگرام رو بالا بیار"))

    def test_english_app_commands_remain_supported(self):
        self.assertIn("apps", protocol.detect_categories("open Opera GX"))


if __name__ == "__main__":
    unittest.main()
