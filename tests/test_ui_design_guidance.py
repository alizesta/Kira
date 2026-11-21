import unittest

from kira.ui_design_guidance import (
    UI_DESIGN_GUIDANCE,
    guidance_for_task,
    is_ui_design_task,
)


class UiDesignGuidanceTests(unittest.TestCase):
    def test_detects_persian_and_english_interface_work(self):
        for request in (
            "رابط کاربری تنظیمات رو ساده کن",
            "دکمه‌های تکراری این صفحه رو حذف کن",
            "Redesign the dashboard layout",
            "Improve accessibility and responsive UI states",
            "Fix the React component layout",
        ):
            with self.subTest(request=request):
                self.assertTrue(is_ui_design_task(request))
                self.assertEqual(guidance_for_task(request), UI_DESIGN_GUIDANCE)

    def test_does_not_activate_for_unrelated_backend_work(self):
        for request in (
            "Fix the database migration",
            "Optimize the API retry policy",
            "Explain Python decorators",
            "Compose an email to the project team",
            "سلام، حالت چطوره؟",
            "ظاهر کیرا چطوره؟",
            "امروز تب دارم",
            "منو دوست داری؟",
        ):
            with self.subTest(request=request):
                self.assertFalse(is_ui_design_task(request))
                self.assertEqual(guidance_for_task(request), "")

    def test_guidance_contains_all_six_unslop_principles_and_appllama(self):
        self.assertIn("APPLLAMMA APP-DESIGN WORKFLOW", UI_DESIGN_GUIDANCE)
        self.assertIn("Jakob's Law", UI_DESIGN_GUIDANCE)
        for principle in (
            "Closure", "Figure-ground", "Banner blindness",
            "Parkinson's law", "Connectedness", "Choice overload",
        ):
            with self.subTest(principle=principle):
                self.assertIn(principle, UI_DESIGN_GUIDANCE)


if __name__ == "__main__":
    unittest.main()
