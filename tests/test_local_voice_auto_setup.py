"""Automatic local Piper provisioning is safe to retry and shared by warm-up/first-use."""
import unittest
from unittest import mock

from kira import local_voice


class PiperAutomaticSetupTests(unittest.TestCase):
    def test_runtime_is_installed_when_missing(self):
        with mock.patch.object(local_voice, "tts_ready", side_effect=[False, False, True]), \\
             mock.patch.object(local_voice, "_install_voice_package") as install:
            self.assertTrue(local_voice.ensure_piper_runtime())
        install.assert_called_once_with("piper-tts>=1.3.0,<2", None)

    def test_runtime_install_is_skipped_when_already_available(self):
        with mock.patch.object(local_voice, "tts_ready", return_value=True), \\
             mock.patch.object(local_voice, "_install_voice_package") as install:
            self.assertTrue(local_voice.ensure_piper_runtime())
        install.assert_not_called()

    def test_runtime_install_failure_is_reported_and_retained(self):
        failure = RuntimeError("pip could not install Piper")
        with mock.patch.object(local_voice, "tts_ready", return_value=False), \\
             mock.patch.object(local_voice, "_install_voice_package", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "نصب خودکار موتور Piper ناموفق بود"):
                local_voice.ensure_piper_runtime()
        self.assertIs(local_voice._tts_error, failure)

    def test_default_voice_is_loaded_after_runtime_preparation(self):
        with mock.patch.object(local_voice, "ensure_piper_runtime") as prepare, \\
             mock.patch.object(local_voice, "warmup_tts", return_value=True) as warmup:
            self.assertTrue(local_voice.ensure_tts_ready(""))
        prepare.assert_called_once_with(cancel_event=None)
        warmup.assert_called_once_with("")


if __name__ == "__main__":
    unittest.main()
