"""Regression tests for the local-only STT/TTS policy."""

import io
import json
import tempfile
import unittest
from pathlib import Path
import wave
from types import MethodType, SimpleNamespace
from unittest import mock

import numpy as np

from kira import config
from kira.listener import Listener
from kira.voice import Speaker, _envelope


ROOT = Path(__file__).resolve().parents[1]


class LocalAudioPolicyTests(unittest.TestCase):
    def test_no_remote_voice_engine_is_referenced_by_active_audio_code(self):
        banned = (
            "cloud_voice",
            "CloudVoicePage",
            "edge_tts",
            "recognize_google",
            "speech_recognition",
            "SAPI_SCRIPT",
            "System.Speech",
        )
        for relative in ("kira/voice.py", "kira/listener.py", "kira/main.py", "kira/voice_caps.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            for token in banned:
                with self.subTest(file=relative, token=token):
                    self.assertNotIn(token.casefold(), source.casefold())

    def test_cloud_voice_implementation_files_are_removed(self):
        self.assertFalse((ROOT / "kira/cloud_voice.py").exists())
        self.assertFalse((ROOT / "kira/cloud_voice_ui.py").exists())

    def test_disabled_local_tts_fails_without_trying_any_engine(self):
        fake = SimpleNamespace(settings={"local_voice_tts": False}, _tmp=tempfile.gettempdir())
        with mock.patch("kira.local_voice.tts_ready") as ready, \
             mock.patch("kira.local_voice.synthesize_persian") as synth:
            with self.assertRaisesRegex(RuntimeError, "غیرفعال"):
                Speaker._synth(fake, SimpleNamespace(gen=1, rate=0, cache=False), 0, "سلام")
        ready.assert_not_called()
        synth.assert_not_called()

    def test_piper_wav_is_the_only_tts_synthesis_result(self):
        wav_buffer = io.BytesIO()
        samples = np.full(2400, 1200, dtype=np.int16)
        with wave.open(wav_buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(samples.tobytes())

        with tempfile.TemporaryDirectory() as tmp:
            fake = SimpleNamespace(
                settings={"local_voice_tts": True, "local_voice_tts_model": "", "voice_rate": 0},
                _tmp=tmp,
            )
            fake._save_local_wav = MethodType(Speaker._save_local_wav, fake)
            with mock.patch("kira.local_voice.tts_ready", return_value=True), \
                 mock.patch("kira.local_voice.synthesize_persian", return_value=wav_buffer.getvalue()) as synth:
                path, envelope = Speaker._synth(
                    fake, SimpleNamespace(gen=2, rate=0, cache=False), 0, "سلام"
                )
            self.assertTrue(Path(path).is_file())
            self.assertTrue(envelope)
            synth.assert_called_once_with("سلام", "", 0)

    def test_very_short_audio_envelope_does_not_crash(self):
        envelope = _envelope(np.array([100, -100], dtype=np.int16), 24000)
        self.assertEqual(len(envelope), 1)
        self.assertTrue(0.0 <= envelope[0] <= 1.0)

    def test_stt_falls_back_from_qwen_only_to_local_whisper(self):
        fake = SimpleNamespace(
            engine="whisper",
            via="",
            _transcribe_local_qwen=mock.Mock(return_value=None),
            _load_local=mock.Mock(return_value=True),
            _transcribe_whisper=mock.Mock(return_value="متن محلی"),
        )
        result = Listener._transcribe(fake, object(), np.zeros(16000, dtype=np.float32))
        self.assertEqual(result, "متن محلی")
        self.assertEqual(fake.via, "local:whisper")
        fake._load_local.assert_not_called()
        fake._transcribe_whisper.assert_called_once()

    def test_successful_qwen_transcription_does_not_load_another_engine(self):
        fake = SimpleNamespace(
            engine=None,
            via="",
            _transcribe_local_qwen=mock.Mock(return_value="متن Qwen"),
            _load_local=mock.Mock(side_effect=AssertionError("no fallback expected")),
        )
        result = Listener._transcribe(fake, object(), np.zeros(16000, dtype=np.float32))
        self.assertEqual(result, "متن Qwen")
        self.assertEqual(fake.via, "local:qwen3-asr")

    def test_old_remote_voice_settings_are_removed_during_config_migration(self):
        old_settings = {
            "voice_fa": "fa-IR-DilaraNeural",
            "voice_en": "en-US-AriaNeural",
            "voice_pitch": 4,
            "cloud_voice_provider": "elevenlabs",
            "character_voice": {
                "kira": {
                    "voice_fa": "fa-IR-DilaraNeural",
                    "cloud_voice_provider": "elevenlabs",
                    "cloud_voice_id": "old-voice-id",
                    "voice_rate": 7,
                    "voice_volume": 0.7,
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(old_settings), encoding="utf-8")
            with mock.patch.object(config, "CONFIG_PATH", path), \
                 mock.patch.object(config, "prepare_user_data", return_value=[]):
                migrated = config.load_settings()

        for key in ("voice_fa", "voice_en", "voice_ja", "voice_pitch", "voice_style"):
            self.assertNotIn(key, migrated)
        profile = migrated["character_voice"]["kira"]
        for key in ("voice_fa", "cloud_voice_provider", "cloud_voice_id", "voice_pitch"):
            self.assertNotIn(key, profile)
        self.assertEqual(profile["voice_rate"], 7)
        self.assertEqual(profile["voice_volume"], 0.7)
        self.assertTrue(migrated["local_voice_asr"])
        self.assertTrue(migrated["local_voice_tts"])


if __name__ == "__main__":
    unittest.main()
