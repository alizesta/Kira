"""Synthetic tests for adaptive microphone echo cancellation."""
import unittest

import numpy as np

from kira.echo_cancellation import AdaptiveEchoCanceller


class AdaptiveEchoCancellerTests(unittest.TestCase):
    def test_invalid_or_silent_reference_preserves_microphone(self):
        canceller = AdaptiveEchoCanceller(block_size=128, filter_length=64)
        mic = np.linspace(-0.1, 0.1, 128, dtype=np.float32)
        np.testing.assert_array_equal(canceller.process(mic, np.zeros_like(mic)), mic)
        np.testing.assert_array_equal(canceller.process(mic, np.ones(12)), mic)

    def test_adaptive_filter_reduces_synthetic_speaker_echo(self):
        rng = np.random.default_rng(19)
        reference = rng.normal(0.0, 0.12, 16000 * 3).astype(np.float32)
        # A short simulated room impulse response: direct path + two reflections.
        echo = (
            0.62 * reference
            + np.concatenate(([0.0], 0.18 * reference[:-1]))
            + np.concatenate((np.zeros(7), 0.08 * reference[:-7]))
        ).astype(np.float32)
        canceller = AdaptiveEchoCanceller(
            block_size=512, filter_length=128, step_size=0.45
        )
        residual = []
        for start in range(0, reference.size, 512):
            ref = reference[start:start + 512]
            mic = echo[start:start + 512]
            if ref.size != 512:
                break
            residual.append(canceller.process(mic, ref))
        before = float(np.mean(echo[512 * 10:] ** 2))
        after = float(np.mean(np.concatenate(residual)[512 * 10:] ** 2))
        self.assertGreater(canceller.adaptation_blocks, 10)
        self.assertLess(after, before * 0.35)

    def test_double_talk_does_not_reset_or_explode_filter(self):
        rng = np.random.default_rng(23)
        canceller = AdaptiveEchoCanceller(block_size=256, filter_length=64)
        for _ in range(30):
            ref = rng.normal(0.0, 0.1, 256).astype(np.float32)
            canceller.process(0.5 * ref, ref)
        before = canceller.weights.copy()
        before_blocks = canceller.adaptation_blocks
        ref = rng.normal(0.0, 0.1, 256).astype(np.float32)
        near_end = rng.normal(0.0, 0.8, 256).astype(np.float32)
        canceller.process(0.5 * ref + near_end, ref)
        self.assertTrue(np.all(np.isfinite(canceller.weights)))
        self.assertTrue(np.all(np.abs(canceller.weights) <= 2.0))
        self.assertEqual(canceller.adaptation_blocks, before_blocks)
        np.testing.assert_array_equal(canceller.weights, before)

    def test_silent_reference_advances_history_without_changing_microphone(self):
        canceller = AdaptiveEchoCanceller(block_size=128, filter_length=64)
        rng = np.random.default_rng(11)
        reference = rng.normal(0.0, 0.1, 128).astype(np.float32)
        microphone = 0.4 * reference
        canceller.process(microphone, reference)
        self.assertGreater(float(np.max(np.abs(canceller.history))), 0.0)
        silence = np.zeros(128, dtype=np.float32)
        result = canceller.process(microphone, silence)
        np.testing.assert_array_equal(result, microphone)
        self.assertEqual(float(np.max(np.abs(canceller.history))), 0.0)

    def test_reset_clears_learned_path(self):
        canceller = AdaptiveEchoCanceller(block_size=128, filter_length=64)
        rng = np.random.default_rng(7)
        for _ in range(10):
            ref = rng.normal(0.0, 0.1, 128).astype(np.float32)
            canceller.process(0.4 * ref, ref)
        canceller.reset()
        self.assertEqual(float(np.max(np.abs(canceller.weights))), 0.0)
        self.assertEqual(canceller.adaptation_blocks, 0)


if __name__ == "__main__":
    unittest.main()
