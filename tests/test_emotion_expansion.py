"""New user states, trigger coverage, absence ladder and the 3-emotion blend."""
import json
import tempfile
import unittest
from pathlib import Path

from kira import mood
from kira.emotion import runtime as rt
from kira.emotion.runtime import EmotionalRuntime, EMOTIONS, BEHAVIORS


def make(box):
    d = tempfile.mkdtemp()
    return EmotionalRuntime(path=Path(d) / "r.json", clock=lambda: box[0])


class UserStateDetection(unittest.TestCase):
    def test_new_states_detected(self):
        cases = {"حوصله‌ام سر رفته": "bored", "بالاخره تمومش کردم": "achievement",
                 "ازت دلخورم": "hurt", "میخوام بازی کنم": "gaming"}
        for text, state in cases.items():
            self.assertIn(state, mood.detect_user_states(text), text)

    def test_negated_forms_ignored(self):
        for text in ("حوصله‌ام سر نرفته", "ازت دلخور نیستم"):
            states = mood.detect_user_states(text)
            self.assertNotIn("bored", states, text)
            self.assertNotIn("hurt", states, text)


class Coverage(unittest.TestCase):
    def test_tables_reference_valid_names(self):
        for effect in rt.USER_EFFECTS.values():
            for part in effect:
                for k in part:
                    self.assertTrue(k in EMOTIONS or k in BEHAVIORS, k)
        for v in rt.FEEDBACK_EMOTIONS.values():
            for k in v:
                self.assertIn(k, EMOTIONS)

    def test_every_emotion_has_a_local_trigger(self):
        reach = set()
        for emo, _b, _c in rt.USER_EFFECTS.values():
            reach |= set(emo)
        for v in rt.FEEDBACK_EMOTIONS.values():
            reach |= set(v)
        for table in (rt.WAIT_EMOTIONS, rt.LONG_AWAY_EMOTIONS, rt.VERY_LONG_AWAY_EMOTIONS):
            reach |= set(table)
        data = json.loads((Path(rt.__file__).parents[2] / "emotion_library" / "events.json").read_text("utf-8"))
        def walk(o):
            if isinstance(o, dict):
                if isinstance(o.get("runtime_emotions"), dict):
                    reach.update(o["runtime_emotions"])
                for x in o.values(): walk(x)
            elif isinstance(o, list):
                for x in o: walk(x)
        walk(data)
        self.assertEqual(set(EMOTIONS) - reach - {"neutral", "disgusted"}, set())


class Absence(unittest.TestCase):
    def after(self, gap):
        t = [1000.0]
        r = make(t)
        r.on_user_message("hi", [], now=t[0])
        r.on_user_message("hi", [], now=t[0] + gap)
        return dict(r._state["emotions"])

    def test_ladder(self):
        short, wait, away, very = self.after(60), self.after(3000), self.after(7 * 3600), self.after(25 * 3600)
        self.assertGreater(wait.get("bored", 0), short.get("bored", 0))
        self.assertGreater(away.get("lonely", 0), short.get("lonely", 0))
        self.assertGreater(very.get("nostalgic", 0), away.get("nostalgic", 0))


class Blend(unittest.TestCase):
    def test_three_emotions_applied_fourth_ignored(self):
        t = [1000.0]
        r = make(t)
        r.on_reply(["happy", "playful", "curious", "sad"], 60, now=t[0])
        em = r._state["emotions"]
        for k in ("happy", "playful", "curious"):
            self.assertGreater(em.get(k, 0), 0, k)
        self.assertGreater(em["happy"], em["curious"])
        self.assertLess(em.get("sad", 0), em["curious"])


if __name__ == "__main__":
    unittest.main()
