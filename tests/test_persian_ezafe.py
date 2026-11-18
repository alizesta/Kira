"""Tests for optional ALBERT-based Persian ezafe preprocessing."""
import os
import tempfile
import unittest
from pathlib import Path
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


    def test_partial_word_at_token_truncation_boundary_is_not_modified(self):
        text = "کتابخانه"
        tokenizer = _Tokenizer([(0, 3)])
        session = _Session([1])
        with mock.patch.object(
            persian_ezafe, "_load_predictor",
            return_value=(tokenizer, session, {"input_ids", "attention_mask"}, np),
        ):
            self.assertEqual(persian_ezafe.add_persian_ezafe(text), text)

    def test_loader_retries_after_transient_initialization_failure(self):
        old_state = (
            persian_ezafe._predictor, persian_ezafe._load_failures,
            persian_ezafe._retry_after, persian_ezafe._last_error,
        )
        self.addCleanup(lambda: self._restore_loader(old_state))
        persian_ezafe._predictor = None
        persian_ezafe._load_failures = 0
        persian_ezafe._retry_after = 0.0
        persian_ezafe._last_error = ""
        predictor = (_Tokenizer([(0, 4)]), _Session([0]), {"input_ids", "attention_mask"}, np)
        with mock.patch.object(persian_ezafe.time, "monotonic", side_effect=[100.0, 106.0]), \
             mock.patch.object(
                 persian_ezafe, "_initialize_predictor",
                 side_effect=[OSError("temporary offline failure"), predictor],
             ) as initialize:
            with self.assertRaisesRegex(OSError, "temporary"):
                persian_ezafe._load_predictor()
            self.assertIs(persian_ezafe._load_predictor(), predictor)
        self.assertEqual(initialize.call_count, 2)
        self.assertEqual(persian_ezafe.status()["load_failures"], 0)

    def test_failed_initialization_has_bounded_backoff_and_diagnostics(self):
        old_state = (
            persian_ezafe._predictor, persian_ezafe._load_failures,
            persian_ezafe._retry_after, persian_ezafe._last_error,
        )
        self.addCleanup(lambda: self._restore_loader(old_state))
        persian_ezafe._predictor = None
        persian_ezafe._load_failures = 0
        persian_ezafe._retry_after = 0.0
        persian_ezafe._last_error = ""
        with mock.patch.object(persian_ezafe.time, "monotonic", return_value=10.0), \
             mock.patch.object(persian_ezafe, "_initialize_predictor", side_effect=OSError("network")):
            with self.assertRaisesRegex(OSError, "network"):
                persian_ezafe._load_predictor()
            with self.assertRaisesRegex(RuntimeError, "cooling down"):
                persian_ezafe._load_predictor()
        state = persian_ezafe.status()
        self.assertEqual(state["load_failures"], 1)
        self.assertIn("network", state["error"])
        self.assertGreater(state["retry_in_seconds"], 0)

    def test_cache_directory_aligns_huggingface_environment(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {"HF_HUB_CACHE": temp, "HUGGINGFACE_HUB_CACHE": "/wrong/cache"}
        ):
            self.assertEqual(persian_ezafe._cache_directory(), Path(temp))
            self.assertEqual(os.environ["HUGGINGFACE_HUB_CACHE"], temp)

    @staticmethod
    def _restore_loader(state):
        (persian_ezafe._predictor, persian_ezafe._load_failures,
         persian_ezafe._retry_after, persian_ezafe._last_error) = state

    def test_empty_text_does_not_load_model(self):
        with mock.patch.object(persian_ezafe, "_load_predictor") as load:
            self.assertEqual(persian_ezafe.add_persian_ezafe("  "), "  ")
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
