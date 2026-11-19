"""Synthetic regression coverage for adaptive microphone noise reduction."""
import unittest

import numpy as np

from kira.noise_reduction import SpectralNoiseReducer


class SpectralNoiseReducerTests(unittest.TestCase):
    def _calibrated(self, seed=7):
        rng = np.random.default_rng(seed)
        reducer = SpectralNoiseReducer(
            rate=16000,
            frame_size=512,
            strength=0.78,
            floor_gain=0.22,
            calibration_blocks=12,
        )
        for _ in range(12):
            block = rng.normal(0.0, 0.025, 512).astype(np.float32)
            reducer.calibrate_block(block)
        return reducer, rng

    def test_calibration_uses_a_robust_noise_profile(self):
        reducer, _ = self._calibrated()
        self.assertIsNotNone(reducer.noise_profile)
        self.assertEqual(reducer.noise_profile.shape, (257,))
        self.assertTrue(np.all(np.isfinite(reducer.noise_profile)))

    def test_uncalibrated_audio_is_preserved_until_profile_exists(self):
        reducer = SpectralNoiseReducer(calibration_blocks=12)
        source = np.linspace(-0.1, 0.1, 2048, dtype=np.float32)
        np.testing.assert_array_equal(reducer.process(source), source)

    def test_denoising_improves_snr_and_preserves_sample_count(self):
        reducer, rng = self._calibrated()
        rate = 16000
        time_axis = np.arange(rate, dtype=np.float32) / rate
        speech = 0.18 * np.sin(2.0 * np.pi * 440.0 * time_axis)
        noise = rng.normal(0.0, 0.025, rate).astype(np.float32)
        noisy = (speech + noise).astype(np.float32)

        cleaned = reducer.process(noisy)
        before_error = noisy - speech
        after_error = cleaned - speech
        before_snr = 10.0 * np.log10(np.mean(speech ** 2) / np.mean(before_error ** 2))
        after_snr = 10.0 * np.log10(np.mean(speech ** 2) / np.mean(after_error ** 2))

        self.assertEqual(cleaned.size, noisy.size)
        self.assertTrue(np.all(np.isfinite(cleaned)))
        self.assertGreater(after_snr, before_snr + 1.0)

    def test_digital_silence_remains_silent(self):
        reducer, _ = self._calibrated()
        silence = np.zeros(4096, dtype=np.float32)
        cleaned = reducer.process(silence)
        self.assertEqual(cleaned.size, silence.size)
        self.assertEqual(float(np.max(np.abs(cleaned))), 0.0)

    def test_quiet_room_noise_updates_the_profile_slowly(self):
        reducer, rng = self._calibrated()
        previous = reducer.noise_profile.copy()
        reducer.update_noise(rng.normal(0.0, 0.03, 512).astype(np.float32))
        self.assertFalse(np.array_equal(reducer.noise_profile, previous))
        self.assertTrue(np.all(np.isfinite(reducer.noise_profile)))


if __name__ == "__main__":
    unittest.main()
