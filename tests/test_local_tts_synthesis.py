"""Native Piper TTS configuration, caching, and model-resolution tests."""

import io
import os
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

from kira import local_voice


class _FakeSynthesisConfig:
    def __init__(self, length_scale=None):
        self.length_scale = length_scale


class _FakePiperVoice:
    loads = []
    instances = {}
    fail_paths = set()

    def __init__(self, path):
        self.path = path
        self.configs = []

    @classmethod
    def load(cls, path):
        cls.loads.append(path)
        if path in cls.fail_paths:
            raise RuntimeError("model load failed")
        if path not in cls.instances:
            cls.instances[path] = cls(path)
        return cls.instances[path]

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.configs.append((text, syn_config))
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00" * 240)


def _fake_piper_module():
    module = types.ModuleType("piper")
    module.PiperVoice = _FakePiperVoice
    module.SynthesisConfig = _FakeSynthesisConfig
    return module


class LocalPiperSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.previous = (
            local_voice._tts,
            local_voice._tts_model_path,
            local_voice._tts_model_label,
            local_voice._tts_model_signature,
            local_voice._tts_error,
        )
        local_voice._tts = None
        local_voice._tts_model_path = ""
        local_voice._tts_model_label = ""
        local_voice._tts_model_signature = None
        local_voice._tts_error = None
        _FakePiperVoice.loads = []
        _FakePiperVoice.instances = {}
        _FakePiperVoice.fail_paths = set()
        self.piper_patch = mock.patch.dict(sys.modules, {"piper": _fake_piper_module()})
        self.piper_patch.start()
        self.addCleanup(self.piper_patch.stop)
        self.ezafe_patch = mock.patch("kira.persian_ezafe.add_persian_ezafe", side_effect=lambda text: text)
        self.ezafe_patch.start()
        self.addCleanup(self.ezafe_patch.stop)
        self.addCleanup(self._restore_state)

    def _model_path(self, name):
        path = Path(tempfile.gettempdir()) / name
        path.write_bytes(b"fake onnx")
        Path(str(path) + ".json").write_text("{}", encoding="utf-8")
        return path

    def _restore_state(self):
        (
            local_voice._tts,
            local_voice._tts_model_path,
            local_voice._tts_model_label,
            local_voice._tts_model_signature,
            local_voice._tts_error,
        ) = self.previous

    def test_native_rate_control_preserves_wav_sample_rate_and_pitch_parameter(self):
        path = self._model_path("mana-test.onnx")
        with mock.patch.object(
            local_voice, "_resolve_tts_model_path", return_value=(path, "bundled")
        ):
            fast = local_voice.synthesize_persian("سلام", rate=25)
            slow = local_voice.synthesize_persian("دوباره سلام", rate=-20)

        voice = _FakePiperVoice.instances[str(path)]
        self.assertEqual(len(_FakePiperVoice.loads), 1, "the active ONNX voice should load once")
        self.assertEqual([item[1].length_scale for item in voice.configs], [0.8, 1.25])

        for payload in (fast, slow):
            self.assertTrue(payload.startswith(b"RIFF"))
            with wave.open(io.BytesIO(payload), "rb") as wav_file:
                self.assertEqual(wav_file.getframerate(), 24000)
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)

    def test_zero_rate_uses_native_default_length_scale(self):
        path = self._model_path("mana-default.onnx")
        with mock.patch.object(
            local_voice, "_resolve_tts_model_path", return_value=(path, "bundled")
        ):
            payload = local_voice.synthesize_persian("آزمایش", rate=0)

        self.assertTrue(payload.startswith(b"RIFF"))
        voice = _FakePiperVoice.instances[str(path)]
        self.assertEqual(voice.configs[0][1].length_scale, 1.0)

    def test_switching_models_replaces_only_active_cached_voice(self):
        first = self._model_path("voice-a.onnx")
        second = self._model_path("voice-b.onnx")
        with mock.patch.object(
            local_voice,
            "_resolve_tts_model_path",
            side_effect=[(first, str(first)), (second, str(second))],
        ):
            local_voice.synthesize_persian("الف", model_path=str(first))
            local_voice.synthesize_persian("ب", model_path=str(second))

        self.assertEqual(_FakePiperVoice.loads, [str(first), str(second)])
        state = local_voice.status(str(second))
        self.assertTrue(state["tts_loaded"])
        self.assertEqual(state["tts_model"], str(second))

    def test_failed_model_switch_keeps_previous_voice_loaded(self):
        first = self._model_path("voice-ok.onnx")
        broken = self._model_path("voice-broken.onnx")
        _FakePiperVoice.fail_paths.add(str(broken))
        with mock.patch.object(
            local_voice,
            "_resolve_tts_model_path",
            side_effect=[(first, str(first)), (broken, str(broken))],
        ):
            local_voice.synthesize_persian("اول", model_path=str(first))
            with self.assertRaisesRegex(RuntimeError, "model load failed"):
                local_voice.synthesize_persian("دوم", model_path=str(broken))

        self.assertIs(local_voice._tts, _FakePiperVoice.instances[str(first)])
        self.assertEqual(local_voice._tts_model_path, str(first))
        self.assertEqual(local_voice._tts_model_label, str(first))

    def test_default_model_resolves_the_mana_snapshot_in_kira_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "models--MahtaFetrat--Mana-Persian-Piper" / "snapshots" / "test"
            snapshot.mkdir(parents=True)
            model = snapshot / "fa_IR-mana-medium.onnx"
            model.write_bytes(b"fake model")
            Path(str(model) + ".json").write_text("{}", encoding="utf-8")
            hub = types.ModuleType("huggingface_hub")
            hub.snapshot_download = mock.Mock(return_value=str(snapshot))

            with mock.patch.dict(sys.modules, {"huggingface_hub": hub}), mock.patch.dict(
                os.environ, {"HF_HUB_CACHE": temp}
            ):
                path, label = local_voice._resolve_tts_model_path()

        self.assertEqual(path, model)
        self.assertEqual(label, "bundled")
        hub.snapshot_download.assert_called_once_with(
            repo_id="MahtaFetrat/Mana-Persian-Piper",
            cache_dir=temp,
            local_files_only=True,
        )

    def test_default_model_downloads_when_not_cached_and_requires_its_config(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "snapshot"
            snapshot.mkdir()
            model = snapshot / "fa_IR-mana-medium.onnx"
            model.write_bytes(b"fake model")
            Path(str(model) + ".json").write_text("{}", encoding="utf-8")
            hub = types.ModuleType("huggingface_hub")
            hub.snapshot_download = mock.Mock(
                side_effect=[OSError("not cached"), str(snapshot)]
            )

            with mock.patch.dict(sys.modules, {"huggingface_hub": hub}), mock.patch.dict(
                os.environ, {"HF_HUB_CACHE": temp}
            ):
                path, label = local_voice._resolve_tts_model_path()

        self.assertEqual(path, model)
        self.assertEqual(label, "bundled")
        self.assertEqual(hub.snapshot_download.call_count, 2)
        self.assertTrue(hub.snapshot_download.call_args_list[0].kwargs["local_files_only"])
        self.assertFalse(hub.snapshot_download.call_args_list[1].kwargs["local_files_only"])

    def test_status_exposes_optional_ezafe_diagnostics(self):
        expected = {"enabled": True, "loaded": False, "error": "offline"}
        with mock.patch("kira.persian_ezafe.status", return_value=expected):
            self.assertEqual(local_voice.status()["ezafe"], expected)

    def test_tts_ready_requires_sidecar_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            model=Path(temp)/"custom.onnx"
            model.write_bytes(b"fake model")
            with mock.patch.dict(sys.modules,{"piper":_fake_piper_module()}):
                self.assertFalse(local_voice.tts_ready(str(model)))
                Path(str(model)+".json").write_text("{}",encoding="utf-8")
                self.assertTrue(local_voice.tts_ready(str(model)))

    def test_same_path_model_reloads_when_file_signature_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"mutable.onnx"
            path.write_bytes(b"first")
            Path(str(path)+".json").write_text("{}",encoding="utf-8")
            with mock.patch.object(local_voice,"_resolve_tts_model_path",return_value=(path,"voice")):
                local_voice._load_tts_voice(str(path))
                path.write_bytes(b"second version")
                local_voice._load_tts_voice(str(path))
            self.assertEqual(_FakePiperVoice.loads,[str(path),str(path)])

    def test_custom_model_must_have_its_piper_sidecar_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "custom.onnx"
            model.write_bytes(b"fake model")
            with self.assertRaisesRegex(RuntimeError, "configuration is missing"):
                local_voice._resolve_tts_model_path(str(model))


if __name__ == "__main__":
    unittest.main()
