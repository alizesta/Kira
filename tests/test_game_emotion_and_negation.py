import tempfile
import unittest
from pathlib import Path

from kira import mood
from kira.emotion.library import Library
from kira.emotion.runtime import BEHAVIORS, EMOTIONS, EmotionalRuntime
from kira.vision_pipeline import HIGHLIGHT_EVENTS, extract_highlight, extract_highlight_event


class NegationTests(unittest.TestCase):
    DETECTED = {
        "استرس دارم": "stressed", "می‌ترسم": "stressed", "خسته‌ام": "down", "خسته‌ام.": "down", "خسته‌ام، اصلا نمیتونم": "down",
        "تنهام؟": "down", "دلم گرفته": "down", "گریه کردم": "down", "حرصم گرفته": "frustrated", "i'm so tired": "down",
        "i feel bad": "down", "تو بی مصرفی": "hostile", "هیچ امیدی ندارم": "down", "نگرانم": "stressed",
    }
    NEGATED = ["استرس ندارم", "بدون استرس", "نمی‌ترسم", "خسته نیستم", "گریه نکن", "حرصم نمیاد", "i'm not tired",
               "i don't feel bad", "تو بی‌مصرف نیستی", "اضطراب ندارم", "استرس نداشته باش"]

    def test_real_signals_still_detected(self):
        for text, state in self.DETECTED.items():
            self.assertIn(state, mood.detect_user_states(text), text)

    def test_negated_keywords_are_ignored(self):
        for text in self.NEGATED:
            self.assertEqual(mood.detect_user_states(text), [], text)

    def test_negation_is_per_clause(self):
        self.assertIn("frustrated", mood.detect_user_states("کلافه‌ام ولی استرس ندارم"))
        self.assertIn("frustrated", mood.detect_user_states("استرس ندارم ولی کلافه‌ام"))
        self.assertNotIn("stressed", mood.detect_user_states("استرس ندارم ولی کلافه‌ام"))


class GameEventTests(unittest.TestCase):
    def test_highlight_kind_parsing(self):
        self.assertEqual(extract_highlight_event("x\n[HIGHLIGHT:death] آخی مردی"), ("game_player_died", "آخی مردی"))
        self.assertEqual(extract_highlight_event("[HIGHLIGHT: WIN] ایول!"), ("game_victory", "ایول!"))
        self.assertEqual(extract_highlight_event("[HIGHLIGHT] بدون نوع"), (None, "بدون نوع"))
        self.assertEqual(extract_highlight_event("[HIGHLIGHT:unknown] چیزی"), (None, "چیزی"))
        self.assertEqual(extract_highlight_event("[HIGHLIGHT:win]   "), (None, None))
        self.assertEqual(extract_highlight_event("فقط متن"), (None, None))
        self.assertEqual(extract_highlight("[HIGHLIGHT:funny] خنده‌دار بود"), "خنده‌دار بود")

    def test_every_event_exists_in_library_with_valid_names(self):
        library = Library.load()
        for name in HIGHLIGHT_EVENTS.values():
            ev = library.events.get(name)
            self.assertIsNotNone(ev, name)
            self.assertTrue(library.resolve_name(ev["emotion"]), name)
            self.assertTrue(set(ev["runtime_emotions"]) <= EMOTIONS, name)
            self.assertTrue(set(ev["runtime_behaviors"]) <= BEHAVIORS, name)

    def test_events_change_feeling_in_the_right_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            rt = EmotionalRuntime(Library.load(), Path(folder) / "s.json", clock=lambda: 1000.0)
            died = rt.trigger("game_player_died", "game", now=1000)
            self.assertGreater(died["emotions"]["protective"], 0)
            self.assertNotIn("excited", died["emotions"])
            won = rt.trigger("game_victory", "game", now=1000)
            self.assertGreater(won["emotions"]["excited"], 0)
            self.assertGreater(won["emotions"]["proud"], 0)


if __name__ == "__main__":
    unittest.main()
