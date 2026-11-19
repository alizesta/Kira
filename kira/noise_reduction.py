"""Lightweight adaptive spectral noise reduction for microphone segments.

The reducer uses only NumPy (already required by Kira). A short room-noise
calibration builds a per-frequency noise profile; overlapping STFT frames then
apply a conservative soft spectral gate before ASR receives the segment.
"""
from __future__ import annotations


class SpectralNoiseReducer:
    """Adaptive spectral-subtraction denoiser for mono float32 microphone audio."""

    def __init__(
        self,
        rate: int = 16000,
        frame_size: int = 512,
        *,
        strength: float = 0.78,
        floor_gain: float = 0.22,
        noise_update: float = 0.002,
        calibration_blocks: int = 12,
    ) -> None:
        import numpy as np

        self.np = np
        self.rate = max(1, int(rate))
        self.frame_size = max(128, int(frame_size))
        self.hop_size = self.frame_size // 2
        self.strength = max(0.0, min(1.0, float(strength)))
        self.floor_gain = max(0.05, min(1.0, float(floor_gain)))
        self.noise_update = max(0.0, min(0.05, float(noise_update)))
        self.calibration_blocks = max(1, int(calibration_blocks))
        self.window = np.hanning(self.frame_size).astype(np.float32)
        self.noise_profile = None
        self._calibration = []

    def _magnitude(self, block):
        np = self.np
        values = np.asarray(block, dtype=np.float32).reshape(-1)
        if values.size != self.frame_size:
            if values.size < self.frame_size:
                values = np.pad(values, (0, self.frame_size - values.size))
            else:
                values = values[:self.frame_size]
        values = values - float(np.mean(values))
        return np.abs(np.fft.rfft(values * self.window)).astype(np.float32)

    def calibrate_block(self, block) -> bool:
        """Collect room-noise spectra; return True once a robust median profile exists."""
        if self.noise_profile is not None:
            return True
        self._calibration.append(self._magnitude(block))
        if len(self._calibration) < self.calibration_blocks:
            return False
        self.noise_profile = self.np.median(
            self.np.stack(self._calibration, axis=0), axis=0
        ).astype(self.np.float32)
        self._calibration.clear()
        return True

    def update_noise(self, block) -> None:
        """Track slow room-noise changes only while the VAD considers the mic quiet."""
        if self.noise_profile is None or self.noise_update <= 0:
            return
        observed = self._magnitude(block)
        alpha = self.noise_update
        self.noise_profile *= 1.0 - alpha
        self.noise_profile += observed * alpha

    def process(self, audio):
        """Denoise a complete mono segment while preserving its exact sample count."""
        np = self.np
        values = np.asarray(audio, dtype=np.float32).reshape(-1)
        if (
            self.noise_profile is None
            or self.strength <= 0.0
            or values.size < self.frame_size
            or not np.any(values)
            or not np.any(self.noise_profile > 1e-7)
        ):
            return values.copy()

        half = self.frame_size // 2
        padded = np.pad(values, (half, half), mode="reflect")
        frame_count = max(
            1,
            int(np.ceil(max(0, padded.size - self.frame_size) / self.hop_size)) + 1,
        )
        required = (frame_count - 1) * self.hop_size + self.frame_size
        if padded.size < required:
            padded = np.pad(padded, (0, required - padded.size))

        output = np.zeros(required, dtype=np.float32)
        weight = np.zeros(required, dtype=np.float32)
        previous_gain = np.ones(self.noise_profile.shape, dtype=np.float32)
        frequency_kernel = np.asarray([0.2, 0.6, 0.2], dtype=np.float32)

        for index in range(frame_count):
            start = index * self.hop_size
            frame = padded[start:start + self.frame_size]
            spectrum = np.fft.rfft(frame * self.window)
            magnitude = np.abs(spectrum)
            estimate = self.strength * self.noise_profile
            gain = np.maximum(
                self.floor_gain,
                1.0 - estimate / np.maximum(magnitude, 1e-8),
            )
            # Smooth the mask across adjacent frequencies and time to reduce musical noise.
            gain = np.convolve(gain, frequency_kernel, mode="same")
            gain = 0.68 * previous_gain + 0.32 * gain
            gain = np.clip(gain, self.floor_gain, 1.0)
            previous_gain = gain.astype(np.float32, copy=False)

            cleaned = np.fft.irfft(spectrum * gain, n=self.frame_size).astype(np.float32)
            output[start:start + self.frame_size] += cleaned * self.window
            weight[start:start + self.frame_size] += self.window * self.window

        output /= np.maximum(weight, 1e-7)
        result = output[half:half + values.size]
        if result.size != values.size or not np.all(np.isfinite(result)):
            return values.copy()
        return np.clip(result, -1.0, 1.0).astype(np.float32, copy=False)
