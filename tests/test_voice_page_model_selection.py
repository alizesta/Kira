"""Regression tests for the supported local STT selection."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from kira.ui.pages.voice_page import VoicePage


class VoicePageModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shenava_is_the_only_local_asr_engine(self):
        settings = {"local_voice_asr_backend": "qwen3", "local_voice_asr_model": "Qwen/Qwen3-ASR-0.6B"}
        page = VoicePage(settings, lambda key: key)
        self.assertEqual(settings["local_voice_asr_backend"], "shenava")
        self.assertEqual(settings["local_voice_asr_model"], "SajjadMajdi/shenava-koochik-fa-int8")
        self.assertFalse(hasattr(page, "asr_backend"))
        self.assertFalse(hasattr(page, "whisper"))
        self.assertEqual(page.shenava_variant.count(), 2)

    def test_gemini_live_remains_available(self):
        page = VoicePage({}, lambda key: key)
        self.assertEqual(page.voice_engine.currentData(), "gemini_live")
        self.assertEqual(page.gemini_model.currentText(), "gemini-3.8-live")

    def test_removed_selected_google_connection_is_not_replaced_by_another_account(self):
        settings = {
            "gemini_live_provider": "deleted-google",
            "providers": {
                "other-google": {"service": "google", "label": "Other account", "api_key": "other-secret"},
            },
        }
        page = VoicePage(settings, lambda key: key)
        page.refresh_gemini_providers(settings)
        self.assertEqual(page.gemini_provider.currentData(), "deleted-google")
        self.assertEqual(settings["gemini_live_provider"], "deleted-google")

    def test_empty_selected_google_key_is_not_replaced_by_another_account(self):
        settings = {
            "gemini_live_provider": "selected-google",
            "providers": {
                "selected-google": {"service": "google", "label": "Selected", "api_key": ""},
                "other-google": {"service": "google", "label": "Other", "api_key": "other-secret"},
            },
        }
        page = VoicePage(settings, lambda key: key)
        page.refresh_gemini_providers(settings)
        self.assertEqual(page.gemini_provider.currentData(), "selected-google")

    def test_local_voice_controls_are_embedded_in_stt_and_tts_sections(self):
        page = VoicePage({}, lambda key: key)
        self.assertTrue(hasattr(page, "local_asr_chk"))
        self.assertTrue(hasattr(page, "local_tts_chk"))
        self.assertEqual(page.local_tts_model.count(), 1)
        self.assertTrue(hasattr(page, "piper_download_btn"))
        self.assertTrue(hasattr(page, "piper_test_btn"))
        self.assertTrue(hasattr(page, "piper_file_btn"))
        self.assertEqual(page.kitten_model.count(), 3)
        self.assertEqual(page.kitten_model.itemData(0), "pico")
        self.assertEqual(page.kitten_model.itemData(1), "nano")
        self.assertEqual(page.kitten_model.itemData(2), "mini")
        self.assertTrue(hasattr(page, "kitten_test_btn"))
        self.assertTrue(hasattr(page, "kitten_result"))
        self.assertFalse(hasattr(page, "local_model_tabs"))


if __name__ == "__main__":
    unittest.main()
