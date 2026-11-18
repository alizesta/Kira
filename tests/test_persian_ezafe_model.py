"""Opt-in evaluation against a small, manually annotated Persian ezafe corpus.

Set KIRA_TEST_PERSIAN_EZAFE_MODEL=1 on a machine with the optional ONNX model
available (or network access for its initial download) to run this evaluation.
"""
import json
import os
import re
import unittest
from pathlib import Path

from kira import persian_ezafe


@unittest.skipUnless(
    os.environ.get("KIRA_TEST_PERSIAN_EZAFE_MODEL") == "1",
    "set KIRA_TEST_PERSIAN_EZAFE_MODEL=1 to evaluate the real ONNX model",
)
class PersianEzafeModelCorpusTests(unittest.TestCase):
    def test_real_model_precision_recall_on_annotated_persian_corpus(self):
        fixture = Path(__file__).parent / "fixtures" / "persian_ezafe_gold.json"
        cases = json.loads(fixture.read_text(encoding="utf-8"))
        true_positive = false_positive = false_negative = 0
        for case in cases:
            marked = persian_ezafe.add_persian_ezafe(case["text"])
            self.assertIsInstance(marked, str)
            predicted = set()
            for token in marked.split():
                clean = re.sub(r"[،؛:,.!?؟…)\]}»\\\"']+$", "", token)
                if "\u0650" in clean:
                    predicted.add(clean.replace("\u0650", ""))
            expected = set(case["ezafe_words"])
            true_positive += len(predicted & expected)
            false_positive += len(predicted - expected)
            false_negative += len(expected - predicted)

        precision = true_positive / max(1, true_positive + false_positive)
        recall = true_positive / max(1, true_positive + false_negative)
        f1 = 2 * precision * recall / max(1e-9, precision + recall)
        self.assertGreaterEqual(
            f1, 0.65,
            f"Persian ezafe corpus F1 too low: precision={precision:.3f}, recall={recall:.3f}, F1={f1:.3f}",
        )


if __name__ == "__main__":
    unittest.main()
