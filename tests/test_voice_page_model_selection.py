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

    def test_unsupported_saved_engine_is_preserved_without_page_side_effects(self):
        settings = {
            "local_voice_asr_backend": "qwen3",
            "local_voice_asr_model": "Qwen/Qwen3-ASR-0.6B",
        }
        before = dict(settings)
        page = VoicePage(settings, lambda key: key)
        self.assertEqual(page.asr_backend.currentData(), "qwen3")
        self.assertIn("پشتیبانی نمی‌شود", page.asr_backend.currentText())
        self.assertEqual(page.asr_model.currentData(), "Qwen/Qwen3-ASR-0.6B")
        self.assertEqual(settings, before)

    def test_adapter_catalog_populates_engine_and_supported_models(self):
        from kira.asr_manager import ASRManager
        settings = {
            "local_voice_asr_backend": "shenava",
            "local_voice_asr_model": "SajjadMajdi/shenava-koochik-fa-int8",
        }
        page = VoicePage(settings, lambda key: key, asr_catalog=ASRManager().catalog())
        self.assertEqual(page.asr_backend.currentData(), "shenava")
        self.assertEqual(page.asr_model.currentData(), settings["local_voice_asr_model"])
        self.assertEqual(page.asr_model.count(), 2)

    def test_gemini_live_remains_available(self):
        page = VoicePage({}, lambda key: key)
        self.assertEqual(page.voice_engine.currentData(), "gemini_live")
        self.assertEqual(page.gemini_model.currentText(), "gemini-3.8-live")

    def test_gemini_provider_refresh_does_not_replace_a_deleted_selection(self):
        settings = {
            "gemini_live_provider": "deleted-google",
            "providers": {
                "google-secondary": {
                    "service": "google", "label": "Secondary account", "api_key": "secondary-secret"
                },
            },
        }
        page = VoicePage(settings, lambda key: key)
        page.refresh_gemini_providers(settings)
        self.assertEqual(page.gemini_provider.currentData(), "deleted-google")
        self.assertIn("جایگزین نشد", page.gemini_provider.currentText())

    def test_gemini_provider_refresh_keeps_selected_connection_when_its_key_is_empty(self):
        settings = {
            "gemini_live_provider": "google-primary",
            "providers": {
                "google-primary": {"service": "google", "label": "Primary account", "api_key": ""},
                "google-secondary": {"service": "google", "label": "Secondary account", "api_key": "secondary-secret"},
            },
        }
        page = VoicePage(settings, lambda key: key)
        page.refresh_gemini_providers(settings)
        self.assertEqual(page.gemini_provider.currentData(), "google-primary")
        self.assertIn("کلید API خالی است", page.gemini_provider.currentText())

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
