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
    memory_fail_once = set()

    def __init__(self, path):
        self.path = path
        self.configs = []

    @classmethod
    def load(cls, path):
        cls.loads.append(path)
        if path in cls.memory_fail_once:
            cls.memory_fail_once.remove(path)
            raise MemoryError("not enough memory to load voice")
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
            local_voice._tts_error,
            local_voice._tts_model_signature,
        )
        local_voice._tts = None
        local_voice._tts_model_path = ""
        local_voice._tts_model_label = ""
        local_voice._tts_model_signature = None
        local_voice._tts_error = None
        _FakePiperVoice.loads = []
        _FakePiperVoice.instances = {}
        _FakePiperVoice.fail_paths = set()
        _FakePiperVoice.memory_fail_once = set()
        self.piper_patch = mock.patch.dict(sys.modules, {"piper": _fake_piper_module()})
        self.piper_patch.start()
        self.addCleanup(self.piper_patch.stop)
        self.addCleanup(self._restore_state)

    def _restore_state(self):
        (
            local_voice._tts,
            local_voice._tts_model_path,
            local_voice._tts_model_label,
            local_voice._tts_error,
            local_voice._tts_model_signature,
        ) = self.previous

    def test_native_rate_control_preserves_wav_sample_rate_and_pitch_parameter(self):
        path = Path(tempfile.gettempdir()) / "mana-test.onnx"
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
        path = Path(tempfile.gettempdir()) / "mana-default.onnx"
        with mock.patch.object(
            local_voice, "_resolve_tts_model_path", return_value=(path, "bundled")
        ):
            payload = local_voice.synthesize_persian("آزمایش", rate=0)

        self.assertTrue(payload.startswith(b"RIFF"))
        voice = _FakePiperVoice.instances[str(path)]
        self.assertEqual(voice.configs[0][1].length_scale, 1.0)

    def test_switching_models_replaces_only_active_cached_voice(self):
        first = Path(tempfile.gettempdir()) / "voice-a.onnx"
        second = Path(tempfile.gettempdir()) / "voice-b.onnx"
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
        first = Path(tempfile.gettempdir()) / "voice-ok.onnx"
        broken = Path(tempfile.gettempdir()) / "voice-broken.onnx"
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


    def test_memory_pressure_releases_old_voice_and_retries_new_model(self):
        first = Path(tempfile.gettempdir()) / "voice-memory-old.onnx"
        second = Path(tempfile.gettempdir()) / "voice-memory-new.onnx"
        _FakePiperVoice.memory_fail_once.add(str(second))
        with mock.patch.object(
            local_voice, "_resolve_tts_model_path",
            side_effect=[(first, str(first)), (second, str(second))],
        ):
            local_voice.synthesize_persian("اول", model_path=str(first))
            local_voice.synthesize_persian("دوم", model_path=str(second))

        self.assertEqual(_FakePiperVoice.loads, [str(first), str(second), str(second)])
        self.assertEqual(local_voice._tts_model_path, str(second))
        self.assertEqual(local_voice._tts_model_label, str(second))

    def test_memory_pressure_failed_switch_restores_previous_voice(self):
        first = Path(tempfile.gettempdir()) / "voice-memory-restore-old.onnx"
        second = Path(tempfile.gettempdir()) / "voice-memory-restore-new.onnx"
        _FakePiperVoice.memory_fail_once.add(str(second))
        _FakePiperVoice.fail_paths.add(str(second))
        with mock.patch.object(
            local_voice, "_resolve_tts_model_path",
            side_effect=[(first, str(first)), (second, str(second))],
        ):
            local_voice.synthesize_persian("اول", model_path=str(first))
            with self.assertRaisesRegex(RuntimeError, "previous voice restored"):
                local_voice.synthesize_persian("دوم", model_path=str(second))

        self.assertEqual(
            _FakePiperVoice.loads,
            [str(first), str(second), str(second), str(first)],
        )
        self.assertIs(local_voice._tts, _FakePiperVoice.instances[str(first)])
        self.assertEqual(local_voice._tts_model_path, str(first))
        self.assertEqual(local_voice._tts_model_label, str(first))

    def test_replaced_model_at_same_path_is_reloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "mutable.onnx"
            model.write_bytes(b"first")
            second_sidecar = Path(str(model) + ".json")
            second_sidecar.write_text("{}", encoding="utf-8")
            with mock.patch.object(
                local_voice, "_resolve_tts_model_path", return_value=(model, str(model))
            ):
                local_voice.synthesize_persian("اول", model_path=str(model))
                model.write_bytes(b"replacement with a different size")
                os.utime(model, None)
                local_voice.synthesize_persian("دوم", model_path=str(model))

        self.assertEqual(_FakePiperVoice.loads, [str(model), str(model)])
        self.assertEqual(local_voice._tts_model_path, str(model))


    def test_replaced_piper_sidecar_at_same_path_invalidates_voice_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "stable.onnx"
            sidecar = Path(str(model) + ".json")
            model.write_bytes(b"same model")
            sidecar.write_text('{"length_scale": 1}', encoding="utf-8")
            with mock.patch.object(
                local_voice, "_resolve_tts_model_path", return_value=(model, str(model))
            ):
                local_voice.synthesize_persian("اول", model_path=str(model))
                sidecar.write_text('{"length_scale": 2, "new_metadata": true}', encoding="utf-8")
                os.utime(sidecar, None)
                local_voice.synthesize_persian("دوم", model_path=str(model))

        self.assertEqual(_FakePiperVoice.loads, [str(model), str(model)])

    def test_custom_voice_readiness_requires_piper_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "voice.onnx"
            model.write_bytes(b"model")
            self.assertFalse(local_voice.tts_ready(str(model)))
            Path(str(model) + ".json").write_text("{}", encoding="utf-8")
            self.assertTrue(local_voice.tts_ready(str(model)))

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

    def test_custom_model_must_have_its_piper_sidecar_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "custom.onnx"
            model.write_bytes(b"fake model")
            with self.assertRaisesRegex(RuntimeError, "configuration is missing"):
                local_voice._resolve_tts_model_path(str(model))


    def test_tts_cache_identity_changes_when_model_or_sidecar_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "cache-identity.onnx"
            sidecar = Path(str(model) + ".json")
            model.write_bytes(b"model-v1")
            sidecar.write_text('{"length_scale": 1}', encoding="utf-8")
            with mock.patch.object(
                local_voice, "_resolve_tts_model_path", return_value=(model, str(model))
            ):
                original = local_voice.tts_cache_identity(str(model))
                sidecar.write_text('{"length_scale": 2}', encoding="utf-8")
                os.utime(sidecar, None)
                metadata_changed = local_voice.tts_cache_identity(str(model))
                model.write_bytes(b"model-v2-with-new-weights")
                os.utime(model, None)
                weights_changed = local_voice.tts_cache_identity(str(model))

        self.assertNotEqual(original, metadata_changed)
        self.assertNotEqual(metadata_changed, weights_changed)


if __name__ == "__main__":
    unittest.main()
