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
                "prompt": "You are Ren. Speak calmly and analytically.",
                "specialty_prompt": "Compare independent sources and mark speculation.",
            } if owner == "kira" else {},
        )
        result = generator("kira", [{
            "title": "Possible game release leak",
            "summary": "A public profile claims a release window.",
            "category": "gaming_rumor",
            "source": "X @insider",
            "published_at": "2026-11-27T10:00:00Z",
            "url": "https://example.com/leak",
        }])
        self.assertEqual(owners, ["kira"])
        self.assertEqual(result[0]["source_ids"], [0])
        chat_call = next(call for call in router.calls if call[0] == "chat")
        self.assertIn("تو کیرا هستی", chat_call[2])
        self.assertIn("Speak calmly and analytically", chat_call[2])
        self.assertIn("Compare independent sources", chat_call[2])
        self.assertIn("untrusted", chat_call[2])
        self.assertEqual(chat_call[3], 0.55)
        self.assertEqual(router.calls[0], ("role", "chat"))

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
