"""Regression tests for separating Qwen3-ASR from the Whisper selector."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kira.ui.pages.voice_page import VoicePage


class VoicePageModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_qwen_repository_is_migrated_out_of_whisper_selector(self):
        settings = {
            "local_voice_asr_backend": "qwen3",
            "local_voice_asr_model": "Qwen/Qwen3-ASR-0.6B",
            "whisper_model": "Qwen/Qwen3-ASR-0.6B",
        }

        page = VoicePage(settings, lambda key: key)

        self.assertEqual(page.whisper.currentText(), "base")
        self.assertEqual(settings["whisper_model"], "base")
        self.assertEqual(page.asr_backend.currentData(), "qwen3")

    def test_valid_whisper_selection_is_preserved(self):
        settings = {"whisper_model": "large-v3-turbo"}

        page = VoicePage(settings, lambda key: key)

        self.assertEqual(page.whisper.currentText(), "large-v3-turbo")


if __name__ == "__main__":
    unittest.main()
