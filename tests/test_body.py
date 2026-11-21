"""Chat -> 3D body commands (kira/body.py): user phrases, model tags and parser integration."""
import unittest

from tests import helpers  # noqa: F401  (redirects the data folder)
from kira import body
from kira.emotion.director import EmotionDirector



class UserCommandTests(unittest.TestCase):
    def cmd(self, text):
        return body.parse_user_command(text)

    def test_raise_hand_variants(self):
        for t in ("دستتو بیار بالا", "دستتو ببر بالا", "دست راستتو بلند کن", "دستت رو بالا بگیر", "raise your right hand"):
            self.assertEqual(self.cmd(t), ["raise_right_hand"], t)
        self.assertEqual(self.cmd("دست چپتو ببر بالا"), ["raise_left_hand"])
        self.assertEqual(self.cmd("دستاتو ببر بالا"), ["arms_up"])

    def test_turn_bend_sit_and_release(self):
        self.assertEqual(self.cmd("پشتتو کن"), ["turn_back"])
        self.assertEqual(self.cmd("پشتتو کن به من"), ["turn_back"])
        self.assertEqual(self.cmd("برگرد"), ["face_front"])
        self.assertEqual(self.cmd("خم شو"), ["bend_forward"])
        self.assertEqual(self.cmd("تعظیم کن"), ["bow"])
        self.assertEqual(self.cmd("به عقب خم شو"), ["bend_back"])
        self.assertEqual(self.cmd("بشین"), ["sit"])
        self.assertEqual(self.cmd("پاشو"), ["stand_up"])
        self.assertEqual(self.cmd("دستتو بیار پایین"), ["lower_hands"])
        self.assertEqual(self.cmd("حالت عادی"), ["reset"])

    def test_several_orders_in_one_message(self):
        self.assertEqual(self.cmd("دستتو ببر بالا و پشتتو کن"), ["raise_right_hand", "turn_back"])
        self.assertEqual(self.cmd("خم شو و تعظیم کن"), ["bend_forward", "bow"])

    def test_ordinary_chat_and_negations_do_nothing(self):
        for t in ("امروز هوا چطوره؟", "من دستمو بردم بالا", "کمرم درد میکنه", "سرم درد می‌کنه", "دستتو بالا نبر",
                  "how are you", "my hand is up", ""):
            self.assertEqual(self.cmd(t), [], t)

    def test_head_and_gestures(self):
        self.assertEqual(self.cmd("سرتو بنداز پایین"), ["head_down"])
        self.assertEqual(self.cmd("سرتو تکون بده"), ["nod"])
        self.assertEqual(self.cmd("بپر"), ["hop"])
        self.assertEqual(self.cmd("دست تکون بده"), ["wave_right_hand"])

    def test_dance(self):
        self.assertEqual(self.cmd("برقص"), ["dance"])
        self.assertEqual(self.cmd("آروم برقص"), ["dance_sway"])
        self.assertEqual(self.cmd("دیگه نرقص"), ["stand_up"])
        self.assertEqual(self.cmd("dance"), ["dance"])


class TagTests(unittest.TestCase):
    def test_extract_removes_tags_and_names_commands(self):
        text, names = body.extract("[smug:70]\n[body:raise-right hand+bow]\nباشه [body:turn_back] حتما")
        self.assertNotIn("body", text)
        self.assertEqual(names, ["raise_right_hand", "bow", "turn_back"])

    def test_unknown_names_are_dropped_but_tag_is_hidden(self):
        text, names = body.extract("hi [body:fly_to_the_moon] there")
        self.assertEqual(names, [])
        self.assertNotIn("[body", text)

    def test_half_typed_tag_at_the_end_is_hidden_while_streaming(self):
        self.assertEqual(body.extract("hello [body:rai")[0].strip(), "hello")
        self.assertEqual(body.extract("hello [bo")[0].strip(), "hello")
        self.assertEqual(body.extract("see [1] and [note]")[0], "see [1] and [note]")

    def test_parse_reply_carries_body_and_keeps_emotion(self):
        director = EmotionDirector()
        meta = director.parse_reply("[smug:70]\n[body:raise_right_hand]\nخیلی خب، دستمو بردم بالا.")
        self.assertEqual(meta.body, ["raise_right_hand"])
        self.assertEqual(meta.emotions, ["smug"])
        self.assertNotIn("[", meta.text)
        self.assertIn("دستمو", meta.text)
        self.assertEqual(director.parse_reply("[happy:50]\nسلام").body, [])

    def test_prompt_mentions_every_command_and_done_note(self):
        hint = body.format_hint()
        for name in body.ALL:
            self.assertIn(name, hint)
        self.assertIn("raise_right_hand", body.done_note(["raise_right_hand"]))
        self.assertEqual(body.done_note([]), "")
        self.assertEqual(body.canonical("Turn Around"), "turn_back")



if __name__ == "__main__":
    unittest.main()
