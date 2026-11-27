"""Regression tests for the supported Gemini Live model catalog."""
import unittest

from kira.settings_schema import (
    DEFAULTS,
    GEMINI_LIVE_MODELS,
    GEMINI_LIVE_MODELS_WITHOUT_PROACTIVE_AUDIO,
)


class GeminiLiveModelCatalogTests(unittest.TestCase):
    def test_default_live_model_is_the_current_recommended_generation(self):
        self.assertEqual(DEFAULTS["gemini_live_model"], "gemini-3.8-live")
        self.assertIn(DEFAULTS["gemini_live_model"], GEMINI_LIVE_MODELS)

    def test_current_live_alternatives_are_available_for_selection(self):
        self.assertIn("gemini-3.1-flash-live-preview", GEMINI_LIVE_MODELS)
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", GEMINI_LIVE_MODELS)

    def test_proactive_audio_capability_is_model_specific(self):
        self.assertIn("gemini-3.1-flash-live-preview", GEMINI_LIVE_MODELS_WITHOUT_PROACTIVE_AUDIO)
        self.assertNotIn("gemini-2.5-flash-native-audio-preview-12-2025", GEMINI_LIVE_MODELS_WITHOUT_PROACTIVE_AUDIO)

    def test_shutdown_live_models_are_not_offered_as_supported_defaults(self):
        self.assertNotIn("gemini-2.0-flash-live-001", GEMINI_LIVE_MODELS)
        self.assertNotIn("gemini-live-2.5-flash-preview", GEMINI_LIVE_MODELS)


if __name__ == "__main__":
    unittest.main()
