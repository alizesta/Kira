import unittest
from unittest import mock

from kira import local_voice, voice_memory


class VoiceMemoryTests(unittest.TestCase):
    def setUp(self):
        self._saved = (
            local_voice._tts, local_voice._tts_model_path, local_voice._tts_model_label,
            local_voice._tts_model_signature, local_voice._tts_error,
        )

    def tearDown(self):
        (local_voice._tts, local_voice._tts_model_path, local_voice._tts_model_label,
         local_voice._tts_model_signature, local_voice._tts_error) = self._saved

    def test_unload_tts_clears_loaded_voice(self):
        local_voice._tts = object()
        local_voice._tts_model_path = "voice.onnx"
        local_voice._tts_model_label = "bundled"
        local_voice._tts_model_signature = ("voice.onnx", (1, 2, 3), (1, 2, 3))
        self.assertTrue(voice_memory.unload_tts())
        self.assertIsNone(local_voice._tts)
        self.assertEqual(local_voice._tts_model_path, "")
        self.assertIsNone(local_voice._tts_model_signature)

    def test_unload_tts_reports_nothing_when_not_loaded(self):
        local_voice._tts = None
        self.assertFalse(voice_memory.unload_tts())

    def test_unload_asr_reports_state_and_calls_unload(self):
        with mock.patch.object(local_voice, "_shenava_recognizer", object()), \
                mock.patch.object(local_voice, "unload_shenava") as unload:
            self.assertTrue(voice_memory.unload_asr())
            unload.assert_called_once_with()
        with mock.patch.object(local_voice, "_shenava_recognizer", None), \
                mock.patch.object(local_voice, "unload_shenava"):
            self.assertFalse(voice_memory.unload_asr())

    def test_release_voice_models_honours_flags_and_survives_errors(self):
        with mock.patch.object(voice_memory, "unload_tts", return_value=True) as tts, \
                mock.patch.object(voice_memory, "unload_asr", side_effect=RuntimeError("boom")) as asr, \
                mock.patch.object(voice_memory, "unload_ezafe", return_value=True) as ezafe:
            report = voice_memory.release_voice_models(ezafe=False)
        self.assertEqual(report, {"tts": True, "asr": False, "ezafe": False})
        tts.assert_called_once_with()
        asr.assert_called_once_with()
        ezafe.assert_not_called()

    def test_unload_ezafe_without_hook_is_false(self):
        fake = mock.Mock(spec=[])
        with mock.patch.dict("sys.modules", {"kira.persian_ezafe": fake}), \
                mock.patch("kira.persian_ezafe", fake, create=True):
            self.assertFalse(voice_memory.unload_ezafe())


if __name__ == "__main__":
    unittest.main()
