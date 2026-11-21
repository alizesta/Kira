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
        self.assertEqual(page.asr_backend.count(), 1)
        self.assertEqual(page.asr_backend.currentData(), "shenava")
        self.assertEqual(page.whisper.currentText(), "disabled")
        self.assertFalse(page.whisper.isVisible())

    def test_gemini_live_remains_available(self):
        page = VoicePage({}, lambda key: key)
        self.assertEqual(page.voice_engine.currentData(), "gemini_live")
        self.assertEqual(page.gemini_model.currentText(), "gemini-3.8-live")


if __name__ == "__main__":
    unittest.main()
