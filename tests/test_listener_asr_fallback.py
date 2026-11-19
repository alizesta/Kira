"""Listener backend priority and failover regression tests."""

import sys
import types
import unittest
from unittest.mock import patch

from kira.listener import Listener


class ListenerAsrFallbackTests(unittest.TestCase):
    def make_listener(self):
        return Listener(
            model_name="small",
            language="fa",
            settings={"local_voice_asr": True, "whisper_cpp_enabled": True},
        )

    def test_vulkan_engine_is_selected_before_faster_whisper(self):
        listener = self.make_listener()
        with patch("kira.whisper_cpp.is_ready", return_value=True):
            self.assertTrue(listener._load_local())
        self.assertEqual(listener.engine, "whisper_cpp")
        self.assertIsNone(listener._model)

    def test_faster_whisper_is_used_when_vulkan_runtime_is_missing(self):
        listener = self.make_listener()
        fake_module = types.ModuleType("faster_whisper")

        class FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        fake_module.WhisperModel = FakeWhisperModel
        with patch("kira.whisper_cpp.is_ready", return_value=False):
            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                self.assertTrue(listener._load_local())
        self.assertEqual(listener.engine, "whisper")
        self.assertEqual(listener._model.kwargs, {"device": "cpu", "compute_type": "int8"})

    def test_qwen_success_remains_the_primary_engine(self):
        listener = self.make_listener()
        with patch.object(listener, "_transcribe_local_qwen", return_value="سلام"):
            with patch.object(listener, "_load_local") as load_fallback:
                self.assertEqual(listener._transcribe(None, [0.0]), "سلام")
        self.assertEqual(listener.via, "local:qwen3-asr")
        load_fallback.assert_not_called()

    def test_vulkan_is_used_when_qwen_returns_no_text(self):
        listener = self.make_listener()
        listener.engine = "whisper_cpp"
        with patch.object(listener, "_transcribe_local_qwen", return_value=None):
            with patch.object(listener, "_transcribe_whisper_cpp", return_value="سلام دنیا"):
                self.assertEqual(listener._transcribe(None, [0.0]), "سلام دنیا")
        self.assertEqual(listener.via, "local:whisper.cpp-vulkan")

    def test_empty_vulkan_transcript_falls_through_to_cpu_whisper(self):
        listener = self.make_listener()
        listener.engine = "whisper_cpp"

        def load_cpu():
            listener.engine = "whisper"
            listener._model = object()
            return True

        with patch.object(listener, "_transcribe_local_qwen", return_value=None):
            with patch.object(listener, "_transcribe_whisper_cpp", return_value=""):
                with patch("kira.whisper_cpp.stop"):
                    with patch.object(listener, "_load_local", side_effect=load_cpu):
                        with patch.object(listener, "_transcribe_whisper", return_value="متن از CPU"):
                            self.assertEqual(listener._transcribe(None, [0.0]), "متن از CPU")
        self.assertEqual(listener.via, "local:faster-whisper-cpu")
        self.assertTrue(listener._whisper_cpp_failed)

    def test_vulkan_failure_falls_through_to_faster_whisper(self):
        listener = self.make_listener()
        listener.engine = "whisper_cpp"

        def load_cpu():
            listener.engine = "whisper"
            listener._model = object()
            return True

        with patch.object(listener, "_transcribe_local_qwen", return_value=None):
            with patch.object(listener, "_transcribe_whisper_cpp", side_effect=RuntimeError("Vulkan unavailable")):
                with patch("kira.whisper_cpp.stop"):
                    with patch.object(listener, "_load_local", side_effect=load_cpu):
                        with patch.object(listener, "_transcribe_whisper", return_value="متن پشتیبان"):
                            self.assertEqual(listener._transcribe(None, [0.0]), "متن پشتیبان")
        self.assertEqual(listener.via, "local:faster-whisper-cpu")
        self.assertTrue(listener._whisper_cpp_failed)


if __name__ == "__main__":
    unittest.main()
