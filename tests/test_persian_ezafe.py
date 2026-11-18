"""Tests for optional ALBERT-based Persian ezafe preprocessing."""
import os
import unittest
from unittest import mock

import numpy as np

from kira import persian_ezafe


class _Tokenizer:
    is_fast = True

    def __init__(self, offsets):
        self.offsets = offsets

    def __call__(self, text, **kwargs):
        count = len(self.offsets)
        return {
            "input_ids": np.ones((1, count), dtype=np.int64),
            "attention_mask": np.ones((1, count), dtype=np.int64),
            "offset_mapping": np.asarray([self.offsets], dtype=np.int64),
        }


class _Session:
    def __init__(self, labels):
        self.labels = labels
        self.inputs = None

    def run(self, _outputs, inputs):
        self.inputs = inputs
        logits = np.zeros((1, len(self.labels), 2), dtype=np.float32)
        for index, label in enumerate(self.labels):
            logits[0, index, int(label)] = 1.0
        return [logits]


class PersianEzafeTests(unittest.TestCase):
    def test_adds_predicted_kasra_before_attached_punctuation(self):
        text = "کتاب خوب، خانه"
        tokenizer = _Tokenizer([(0, 4), (5, 8), (10, 14)])
        session = _Session([1, 1, 0])
        with mock.patch.object(
            persian_ezafe, "_load_predictor",
            return_value=(tokenizer, session, {"input_ids", "attention_mask"}, np),
        ):
            result = persian_ezafe.add_persian_ezafe(text)

        self.assertEqual(result, "کتابِ خوبِ، خانه")
        self.assertIn("input_ids", session.inputs)
        self.assertIn("attention_mask", session.inputs)

    def test_uses_first_subtoken_label_for_a_split_word(self):
        text = "دانشگاه"
        tokenizer = _Tokenizer([(0, 3), (3, 7)])
        session = _Session([1, 0])
        with mock.patch.object(
            persian_ezafe, "_load_predictor",
            return_value=(tokenizer, session, {"input_ids", "attention_mask"}, np),
        ):
            result = persian_ezafe.add_persian_ezafe(text)
        self.assertEqual(result, "دانشگاهِ")

    def test_does_not_duplicate_existing_kasra(self):
        text = "کتابِ خوب"
        tokenizer = _Tokenizer([(0, 5), (6, 9)])
        session = _Session([1, 1])
        with mock.patch.object(
            persian_ezafe, "_load_predictor",
            return_value=(tokenizer, session, {"input_ids", "attention_mask"}, np),
        ):
            result = persian_ezafe.add_persian_ezafe(text)
        self.assertEqual(result, "کتابِ خوبِ")

    def test_disabled_setting_returns_original_without_loading_model(self):
        with mock.patch.dict(os.environ, {"KIRA_TTS_EZAFE": "0"}), mock.patch.object(
            persian_ezafe, "_load_predictor"
        ) as load:
            self.assertEqual(persian_ezafe.add_persian_ezafe("کتاب خوب"), "کتاب خوب")
        load.assert_not_called()

    def test_model_failure_preserves_original_text(self):
        text = "کتاب خوب"
        with mock.patch.object(
            persian_ezafe, "_load_predictor", side_effect=RuntimeError("offline")
        ):
            self.assertEqual(persian_ezafe.add_persian_ezafe(text), text)
        self.assertIn("offline", persian_ezafe.status()["error"])

    def test_albert_download_uses_the_shared_kira_huggingface_cache(self):
        import tempfile
        import types
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "snapshot"
            quantized = snapshot / "quantized"
            quantized.mkdir(parents=True)
            (quantized / "model_quantized.onnx").write_bytes(b"fake model")

            hub = types.ModuleType("huggingface_hub")
            hub.snapshot_download = mock.Mock(return_value=str(snapshot))
            ort = types.ModuleType("onnxruntime")
            ort.SessionOptions = type("SessionOptions", (), {})
            class Session:
                def __init__(self, *_args, **_kwargs):
                    pass
                def get_inputs(self):
                    return [types.SimpleNamespace(name="input_ids"),
                            types.SimpleNamespace(name="attention_mask")]
            ort.InferenceSession = Session
            transformers = types.ModuleType("transformers")
            class AutoTokenizer:
                @staticmethod
                def from_pretrained(*_args, **_kwargs):
                    return _Tokenizer([])
            transformers.AutoTokenizer = AutoTokenizer

            with mock.patch.dict(sys.modules, {
                "huggingface_hub": hub, "onnxruntime": ort, "transformers": transformers,
            }), mock.patch("kira.local_voice.cache_directory", return_value=temp):
                persian_ezafe._initialize_predictor()

            self.assertEqual(hub.snapshot_download.call_args.kwargs["cache_dir"], temp)
            self.assertEqual(hub.snapshot_download.call_args.kwargs["repo_id"],
                             "abreza/persian-ezafe-albert")

    def test_partial_word_at_truncation_boundary_is_untouched(self):
        text="کلمه‌"
        tokenizer=_Tokenizer([(0,2)])
        session=_Session([1])
        with mock.patch.object(persian_ezafe,"_load_predictor",
             return_value=(tokenizer,session,{"input_ids","attention_mask"},np)):
            self.assertEqual(persian_ezafe.add_persian_ezafe(text),text)

    def test_failed_initialization_can_retry_after_cooldown(self):
        old=(persian_ezafe._predictor,persian_ezafe._next_retry_at,persian_ezafe._last_error)
        try:
            persian_ezafe._predictor=None
            persian_ezafe._next_retry_at=0
            persian_ezafe._last_error=""
            ready=(object(),object(),{"input_ids","attention_mask"},np)
            with mock.patch.object(persian_ezafe,"_initialize_predictor",
                 side_effect=[RuntimeError("temporary network failure"),ready]), \
                 mock.patch.object(persian_ezafe,"_RETRY_DELAY_SECONDS",0):
                with self.assertRaisesRegex(RuntimeError,"temporary network"):
                    persian_ezafe._load_predictor()
                self.assertIs(persian_ezafe._load_predictor(),ready)
        finally:
            persian_ezafe._predictor,persian_ezafe._next_retry_at,persian_ezafe._last_error=old

    def test_empty_text_does_not_load_model(self):
        with mock.patch.object(persian_ezafe, "_load_predictor") as load:
            self.assertEqual(persian_ezafe.add_persian_ezafe("  "), "  ")
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
