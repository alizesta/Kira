"""Regression tests for low-latency reasoning settings on supported Gemini models."""
import unittest

from kira.hybrid_providers import OpenAICompatibleProvider


MESSAGES = [{"role": "user", "content": "سلام"}]


class GeminiReasoningEffortTests(unittest.TestCase):
    def test_gemini_38_flash_uses_low_effort_for_stream_and_non_stream(self):
        provider = OpenAICompatibleProvider({
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "gemini-3.8-flash",
        }, name="google-ai")

        for streaming in (False, True):
            _url, _headers, payload = provider._prepare(
                MESSAGES, "system", 0.7, streaming
            )
            self.assertEqual(payload["reasoning_effort"], "low")
            self.assertEqual(payload["stream"], streaming)

    def test_gemini_4_hydrogen_uses_low_effort_for_stream_and_non_stream(self):
        provider = OpenAICompatibleProvider({
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "gemini-4-hydrogen",
        }, name="google-ai")

        for streaming in (False, True):
            _url, _headers, payload = provider._prepare(
                MESSAGES, "system", 0.1, streaming
            )
            self.assertEqual(payload["reasoning_effort"], "low")
            self.assertEqual(payload["stream"], streaming)

    def test_thinking_models_get_a_token_floor_for_small_caps(self):
        for model in ("gemini-3.8-flash", "gemini-4-hydrogen"):
            provider = OpenAICompatibleProvider({
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "api_key": "google-test-key",
                "model": model,
            }, name="google-ai")
            _u, _h, small = provider._prepare(MESSAGES, "system", 0.3, True, 48)
            _u, _h, big = provider._prepare(MESSAGES, "system", 0.3, True, 4000)
            _u, _h, none = provider._prepare(MESSAGES, "system", 0.3, True)
            self.assertGreaterEqual(small["max_tokens"], 1024)
            self.assertEqual(big["max_tokens"], 4000)
            self.assertNotIn("max_tokens", none)

    def test_other_google_models_keep_provider_default_reasoning(self):
        provider = OpenAICompatibleProvider({
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "gemini-3.5-flash",
        }, name="google-ai")

        _url, _headers, payload = provider._prepare(
            MESSAGES, "system", 0.7, False
        )
        self.assertNotIn("reasoning_effort", payload)

    def test_non_google_endpoint_does_not_receive_google_reasoning_parameter(self):
        provider = OpenAICompatibleProvider({
            "base_url": "https://example.com/v1",
            "api_key": "example-key",
            "model": "gemini-3.8-flash",
        }, name="custom")

        _url, _headers, payload = provider._prepare(
            MESSAGES, "system", 0.7, True
        )
        self.assertNotIn("reasoning_effort", payload)


if __name__ == "__main__":
    unittest.main()
