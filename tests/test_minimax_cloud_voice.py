import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kira import cloud_voice as cv


class MiniMaxCloudVoiceTests(unittest.TestCase):
    def test_provider_is_registered_for_tts_only(self):
        self.assertIn("minimax", cv.PROVIDERS)
        self.assertIn("minimax", cv.TTS_CALLS)
        self.assertNotIn("minimax", cv.STT_CALLS)
        self.assertEqual(cv.MINIMAX_BASE, "https://api.minimax.io/v1")

    def test_tts_caps_and_default_voice(self):
        self.assertEqual(cv.tts_caps("minimax", "speech-2.8-turbo"), {"rate", "style"})
        store = cv.CloudVoiceStore(Path(tempfile.gettempdir()) / "kira-minimax-test-do-not-create.json")
        service = cv.CloudVoice(store)
        self.assertEqual(service._voice_for("minimax", "speech-2.8-turbo", "fa"), cv.MINIMAX_DEFAULT_VOICE)

    @patch("kira.cloud_voice._request")
    def test_synthesis_builds_global_request_and_decodes_hex(self, request):
        request.return_value.json.return_value = {"base_resp": {"status_code": 0}, "data": {"audio": "01020304"}}
        audio, ext = cv._tts_minimax("secret-key", "speech-2.8-hd", "سلام", "my-voice",
                                     "fa", {"rate": 20, "style": "cheerful"})
        self.assertEqual(audio, bytes.fromhex("01020304"))
        self.assertEqual(ext, "mp3")
        args, kwargs = request.call_args
        self.assertEqual(args[:3], ("post", "minimax", "https://api.minimax.io/v1/t2a_v2"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")
        body = kwargs["json"]
        self.assertEqual(body["model"], "speech-2.8-hd")
        self.assertEqual(body["voice_setting"]["voice_id"], "my-voice")
        self.assertEqual(body["voice_setting"]["speed"], 1.2)
        self.assertEqual(body["voice_setting"]["emotion"], "happy")
        self.assertEqual(body["output_format"], "hex")

    @patch("kira.cloud_voice._tts_minimax")
    def test_key_validation_probes_real_tts_and_returns_catalog(self, synth):
        synth.return_value = (b"audio", "mp3")
        result = cv.validate("minimax", "secret-key")
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["detected"]["tts"], ["speech-2.8-turbo", "speech-2.8-hd"])
        self.assertEqual(result["detected"]["tts_source"], "catalog")
        synth.assert_called_once_with("secret-key", "speech-2.8-turbo", "سلام.",
                                      cv.MINIMAX_DEFAULT_VOICE, "fa", {})

    @patch("kira.cloud_voice._request")
    def test_provider_error_maps_quota_and_never_echoes_key(self, request):
        request.return_value.json.return_value = {
            "base_resp": {"status_code": 1008, "status_msg": "insufficient balance for account"},
            "data": {},
        }
        with self.assertRaises(cv.CVError) as caught:
            cv._tts_minimax("private-key", "speech-2.8-turbo", "سلام", "", "fa")
        self.assertEqual(caught.exception.kind, "quota")
        self.assertNotIn("private-key", str(caught.exception))

    def test_legacy_store_migrates_with_minimax_provider_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud_voice.json"
            path.write_text('{"version":1,"providers":{"google":{"keys":[]}}}', encoding="utf-8")
            store = cv.CloudVoiceStore(path)
            self.assertIn("minimax", store.data["providers"])
            self.assertEqual(store.data["tts"]["order"][-1], "minimax")


if __name__ == "__main__":
    unittest.main()
