"""Low-cost adaptive acoustic echo cancellation for Kira's microphone input.

The far-end reference is the exact mono PCM signal sent to Kira's WAV player.
A normalized block-LMS filter estimates the room/speaker path and subtracts
that estimate before VAD, barge-in detection, denoising and ASR.
"""
from __future__ import annotations


class AdaptiveEchoCanceller:
    """Single-channel adaptive FIR echo canceller for float32 mono audio."""

    def __init__(
        self,
        rate: int = 16000,
        block_size: int = 512,
        *,
        filter_length: int = 1024,
        step_size: float = 0.35,
        double_talk_ratio: float = 2.5,
    ) -> None:
        import numpy as np

        self.np = np
        self.rate = max(1, int(rate))
        self.block_size = max(1, int(block_size))
        self.filter_length = max(32, int(filter_length))
        self.step_size = max(0.01, min(1.0, float(step_size)))
        self.double_talk_ratio = max(1.1, float(double_talk_ratio))
        self.weights = np.zeros(self.filter_length, dtype=np.float32)
        self.history = np.zeros(self.filter_length - 1, dtype=np.float32)
        self.adaptation_blocks = 0

    def reset(self) -> None:
        """Forget the learned acoustic path after a device/output route change."""
        self.weights.fill(0.0)
        self.history.fill(0.0)
        self.adaptation_blocks = 0

    def process(self, microphone, reference):
        """Subtract estimated speaker echo; return the microphone block unchanged on invalid input."""
        np = self.np
        mic = np.asarray(microphone, dtype=np.float32).reshape(-1)
        ref = np.asarray(reference, dtype=np.float32).reshape(-1)
        if mic.size == 0 or mic.size != ref.size:
            return mic.copy()
        if not np.all(np.isfinite(mic)) or not np.all(np.isfinite(ref)):
            return mic.copy()
        ref_power = float(np.mean(ref * ref))
        if ref_power < 1e-9:
            # Advance the reference timeline through silence so stale samples
            # from the previous sentence cannot leak into the next one.
            joined = np.concatenate((self.history, ref))
            self.history = joined[-(self.filter_length - 1):].copy()
            return mic.copy()

        joined = np.concatenate((self.history, ref))
        windows = np.lib.stride_tricks.sliding_window_view(
            joined, self.filter_length
        )[:, ::-1]
        # Each row contains the current and preceding far-end samples.
        estimate = windows @ self.weights
        error = mic - estimate
        estimate_power = float(np.mean(estimate * estimate))
        error_power = float(np.mean(error * error))

        # Freeze adaptation during likely double-talk. Cancellation remains active
        # with the last stable filter so the user's voice is not learned as echo.
        coherence = abs(float(np.mean(error * estimate))) / (
            (error_power * estimate_power) ** 0.5 + 1e-8
        )
        double_talk = (
            estimate_power > max(1e-8, ref_power * 0.01)
            and error_power > estimate_power * self.double_talk_ratio
            and coherence < 0.35
        )
        if not double_talk:
            # Normalize by average tap energy, not the full window matrix energy;
            # this keeps convergence independent of FIR length and block size.
            energy = float(np.sum(windows * windows) / self.filter_length) + 1e-8
            gradient = windows.T @ error
            update = (self.step_size / energy) * gradient
            self.weights += update.astype(np.float32, copy=False)
            np.clip(self.weights, -2.0, 2.0, out=self.weights)
            self.adaptation_blocks += 1

        self.history = joined[-(self.filter_length - 1):].copy()
        if not np.all(np.isfinite(error)):
            return mic.copy()
        return np.clip(error, -1.0, 1.0).astype(np.float32, copy=False)
