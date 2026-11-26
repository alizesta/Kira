import time
import unittest

from kira.character import repetition as rep
from kira.vision_pipeline import HighlightGate


class RepetitionGuardTests(unittest.TestCase):
    def setUp(self):
        rep.reset()

    def test_names_worn_openers_and_phrases(self):
        for text in ("وای عزیزم چه روزی بود امروز", "وای عزیزم داری چیکار میکنی الان", "وای عزیزم این بازی خیلی باحاله"):
            rep.record("kira", text)
        out = rep.note("kira")
        self.assertIn("وای عزیزم", out)
        self.assertLessEqual(len(out), 320)

    def test_quiet_when_replies_vary_and_per_character(self):
        rep.record("kira", "سلام امروز چطوری")
        rep.record("kira", "بیا یه بازی جدید امتحان کنیم")
        self.assertEqual(rep.note("kira"), "")
        self.assertEqual(rep.note("ren"), "")

    def test_flags_near_identical_replies(self):
        rep.record("kira", "این باس خیلی سخته باید مراقب باشی")
        rep.record("kira", "این باس خیلی سخته باید مراقب باشی ها")
        self.assertIn("almost identical", rep.note("kira"))

    def test_fast(self):
        for i in range(6):
            rep.record("kira", f"این یه جواب نسبتا بلند شماره {i} است که کلی کلمه دارد " * 5)
        t = time.perf_counter()
        for _ in range(200):
            rep.note("kira")
        self.assertLess((time.perf_counter() - t) / 200, 0.005)      # < 5 ms per request

    def test_highlight_gate_drops_near_duplicates(self):
        t = [0.0]
        gate = HighlightGate(min_interval=0, per_hour=10, clock=lambda: t[0])
        self.assertTrue(gate.allow("وای باس رو با یه ضربه زدی"))
        self.assertFalse(gate.allow("وای باس رو با یه ضربه زدی!"))
        self.assertTrue(gate.allow("آخی مردی بیچاره"))


if __name__ == "__main__":
    unittest.main()
