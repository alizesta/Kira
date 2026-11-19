"""Regression tests for Google's OpenAI-compatible Gemini endpoint routing."""
import unittest

from kira.hybrid_ai import CustomOpenAIProvider


class GeminiOpenAICompatibilityTests(unittest.TestCase):
    def _prepare(self, base_url):
        provider = CustomOpenAIProvider(
            {
                "base_url": base_url,
                "api_key": "test-gemini-key",
                "model": "gemini-3.8-flash",
            },
            name="google",
        )
        return provider._prepare(
            [{"role": "user", "content": "سلام"}],
            "You are Kira.",
            0.7,
            False,
        )

    def test_host_only_base_url_gets_google_openai_path(self):
        url, headers, payload = self._prepare("https://generativelanguage.googleapis.com")
        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(headers["Authorization"], "Bearer test-gemini-key")
        self.assertEqual(payload["model"], "gemini-3.8-flash")

    def test_v1beta_base_url_gets_openai_suffix(self):
        url, _, _ = self._prepare("https://generativelanguage.googleapis.com/v1beta")
        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )

    def test_existing_openai_base_url_is_not_duplicated(self):
        url, _, _ = self._prepare(
            "https://generativelanguage.googleapis.com/v1beta/openai"
        )
        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
