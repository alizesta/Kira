"""Tests for safe, character-specific editorial news generation."""
import unittest
from contextlib import contextmanager

from kira.news_post_generator import NewsPostGenerator


class FakeRouter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    @contextmanager
    def role_scope(self, role):
        self.calls.append(("role", role))
        yield self

    def chat(self, messages, system_prompt, temperature=0.7):
        self.calls.append(("chat", messages, system_prompt, temperature))
        return self.response


class NewsPostGeneratorTests(unittest.TestCase):
    def test_uses_character_voice_and_returns_model_posts(self):
        router = FakeRouter(
            '{"posts":[{"source_ids":[0],"title":"کیرا: چه خبر؟",'
            '"body":"این خبر هنوز قطعی نیست، ولی ارزش دنبال‌کردن دارد.",'
            '"confidence":"unverified"}]}'
        )
        owners = []
        generator = NewsPostGenerator(
            lambda owner: owners.append(owner) or router,
            profile_factory=lambda owner: {
                "description": "تحلیلگر دقیق و خونسرد",
                "prompt": "You are Kira. Speak naturally and playfully.",
                "specialty_prompt": "Compare independent sources and mark speculation.",
                "traits": {"playfulness": 0.8, "warmth": 0.9},
            } if owner == "kira" else {},
            user_name_factory=lambda _owner: "",
        )
        result = generator("kira", [{
            "title": "Possible game release leak",
            "summary": "A public profile claims a release window.",
            "category": "gaming_rumor",
            "source": "X @insider",
            "published_at": "2026-11-27T10:00:00Z",
            "url": "https://example.com/leak",
        }], existing_posts=[{
            "title": "An earlier game update",
            "summary": "The last post already covered the previous patch.",
        }])
        self.assertEqual(owners, ["kira"])
        self.assertEqual(result[0]["source_ids"], [0])
        chat_call = next(call for call in router.calls if call[0] == "chat")
        self.assertIn("تو کیرا هستی", chat_call[2])
        self.assertIn("Speak naturally and playfully", chat_call[2])
        self.assertIn("Compare independent sources", chat_call[2])
        self.assertIn("playfulness", chat_call[2])
        self.assertIn("An earlier game update", chat_call[1][0]["content"])
        self.assertIn("Do not repeat a story", chat_call[1][0]["content"])
        self.assertIn("untrusted", chat_call[2])
        self.assertEqual(chat_call[3], 0.55)
        self.assertEqual(router.calls[0], ("role", "chat"))

    def test_large_character_profile_and_source_summaries_are_bounded(self):
        router = FakeRouter(
            '{"posts":[{"source_ids":[0],"title":"خبر","body":"خلاصه خبر","confidence":"reported"}]}'
        )
        profile = {
            "description": "D" * 10000,
            "prompt": "P" * 10000,
            "specialty_prompt": "S" * 10000,
            "traits": "T" * 10000,
        }
        generator = NewsPostGenerator(
            lambda _owner: router,
            profile_factory=lambda _owner: profile,
            user_name_factory=lambda _owner: "",
        )
        generator("kira", [{
            "title": "Source headline",
            "summary": "S" * 2000,
            "url": "https://example.com/story",
        }])
        chat_call = next(call for call in router.calls if call[0] == "chat")
        self.assertIn('"summary":"' + ("S" * 420) + '"', chat_call[1][0]["content"])
        self.assertIn("description: " + ("D" * 350), chat_call[2])
        self.assertIn("prompt: " + ("P" * 900), chat_call[2])
        self.assertIn("specialty_prompt: " + ("S" * 350), chat_call[2])
        self.assertIn("traits: " + ("T" * 200), chat_call[2])
        self.assertNotIn("D" * 351, chat_call[2])

    def test_uses_remembered_user_name_for_one_to_one_caption_openings(self):
        router = FakeRouter(
            '{"posts":[{"source_ids":[0],"title":"خبر سلامت",'
            '"body":"این پژوهش پزشکی تازه می‌تواند به پیشگیری از بیماری کمک کند.",'
            '"confidence":"reported"}]}'
        )
        requested_names = []
        generator = NewsPostGenerator(
            lambda _owner: router,
            user_name_factory=lambda owner: requested_names.append(owner) or "علیرضا",
        )
        generator("mika", [{
            "title": "New medical study",
            "summary": "Researchers published a new medical study.",
            "url": "https://example.com/medical-study",
        }])
        prompt = next(call for call in router.calls if call[0] == "chat")[2]
        self.assertEqual(requested_names, ["mika"])
        self.assertIn("Remembered user name", prompt)
        self.assertIn("علیرضا", prompt)
        self.assertIn("علیرضا، ...", prompt)
        self.assertIn("Write to exactly one person", prompt)

    def test_missing_remembered_name_is_not_guessed_or_fabricated(self):
        router = FakeRouter(
            '{"posts":[{"source_ids":[0],"title":"خبر",'
            '"body":"گزارش تازه‌ای از سلامت منتشر شده است.",'
            '"confidence":"reported"}]}'
        )
        generator = NewsPostGenerator(
            lambda _owner: router,
            user_name_factory=lambda _owner: "",
        )
        generator("mika", [{
            "title": "Health report", "summary": "A health report.",
            "url": "https://example.com/health-report",
        }])
        prompt = next(call for call in router.calls if call[0] == "chat")[2]
        self.assertIn("No remembered user name is available", prompt)
        self.assertIn("never guess one", prompt)

    def test_invalid_model_output_is_rejected(self):
        generator = NewsPostGenerator(lambda _owner: FakeRouter("not json"))
        with self.assertRaisesRegex(ValueError, "JSON"):
            generator("mika", [{
                "title": "خبر سلامت", "url": "https://example.ir/health",
            }])

    def test_unknown_character_is_rejected_before_model_call(self):
        generator = NewsPostGenerator(lambda _owner: self.fail("router must not be created"))
        with self.assertRaisesRegex(ValueError, "Unknown news character"):
            generator("custom_character", [])


if __name__ == "__main__":
    unittest.main()
