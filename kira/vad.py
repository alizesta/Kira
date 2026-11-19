"""Speech segmenter for the microphone (numpy only - no Qt, no audio device, so it can be tested with synthetic audio).

It turns a stream of 512-sample blocks into events:
    ("start",)            speech began (the pre-roll is already included in the segment)
    ("barge",)            the person started talking over Kira (only while kira_speaking=True)
    ("segment", audio)    the sentence ended; `audio` is float32 mono, trimmed to the voiced part + a short tail
    ("noise",)            a sound that was too short to be speech was dropped

What makes it less sensitive to room noise
  * the level is measured only in the speech band (100-4000 Hz): fan rumble and hiss count for much less;
  * the noise floor is measured at start-up and followed afterwards (down quickly, up slowly);
  * speech must stay above the start threshold for 3 blocks (~0.1 s), so keyboard clicks and bumps do not trigger it;
  * two thresholds (hysteresis): starting needs more than continuing, and "continuing" is also relative to how loud
    this person is talking, so the end of a sentence is found even in a noisy room.
"""
from __future__ import annotations

from collections import deque

from .noise_reduction import SpectralNoiseReducer
from .echo_cancellation import AdaptiveEchoCanceller

RATE = 16000
BLOCK = 512
CALIBRATION_BLOCKS = 12          # ~0.38 s of room noise measured at start
ONSET_BLOCKS = 3                 # speech must persist ~0.1 s before it counts
PRE_ROLL_BLOCKS = 12             # ~0.4 s kept from before the start, so the first syllable is not cut
TAIL_BLOCKS = 6                  # ~0.19 s of the silence after the last voiced block is kept
MIN_VOICED_S = 0.30              # less voiced audio than this is a bump, not a word
MAX_SEGMENT_S = 25.0
BARGE_CAL_BLOCKS = 14            # ~0.45 s at the start of Kira's speech used to learn how loud she is in the mic
BARGE_BLOCKS = 12                # ~0.4 s of clearly louder sound than her own echo = the person is talking


class Segmenter:
    def __init__(self, sensitivity=100, rate=RATE, block=BLOCK):
        import numpy as np
        self.np = np
        self.rate, self.block = rate, block
        sens = max(50, min(200, int(sensitivity or 100)))
        self.f = 100.0 / sens                                   # higher sensitivity -> lower thresholds
        self.min_start, self.min_stay = 0.014 * self.f, 0.008 * self.f
        self.noise = 0.003
        self._calib = []
        self._windows = {}
        freqs = np.fft.rfftfreq(block, 1.0 / rate)
        self._band = (freqs >= 100) & (freqs <= 4000)
        self._denoiser = SpectralNoiseReducer(rate, block)
        self._echo_canceller = AdaptiveEchoCanceller(rate, block)
        self.reset()

    # ---- state ----
    def reset(self):
        """Forget the sentence in progress (used while the microphone is muted). The noise floor is kept."""
        self.pre = deque(maxlen=PRE_ROLL_BLOCKS)
        self.buf, self.speaking, self.barged = [], False, False
        self.onset = self.silence = self.voiced = self.last_voiced = 0
        self.voiced_avg = 0.0
        self._reset_barge_watch()

    def _reset_barge_watch(self):
        self._cal_n, self._cal_mic, self._cal_out, self._cal_max, self._loud = 0, 0.0, 0.0, 0.0, 0

    @property
    def start_thr(self):
        return max(self.min_start, self.noise * 3.5 * self.f)

    @property
    def stay_thr(self):
        return max(self.min_stay, self.noise * 2.0 * self.f, 0.15 * self.voiced_avg)

    @property
    def calibrating(self):
        return len(self._calib) < CALIBRATION_BLOCKS

    # ---- measurement ----
    def level(self, blk):
        """RMS of the block inside the speech band (0 for digital silence)."""
        np = self.np
        x = blk - float(np.mean(blk))
        rms = float(np.sqrt(np.mean(x * x)))
        if rms < 1e-6:
            return 0.0
        n = len(x)
        win = self._windows.get(n)
        if win is None:
            win = self._windows[n] = np.hanning(n).astype(np.float32)
        power = np.abs(np.fft.rfft(x * win)) ** 2
        band = self._band if n == self.block else (np.fft.rfftfreq(n, 1.0 / self.rate) >= 100) & (np.fft.rfftfreq(n, 1.0 / self.rate) <= 4000)
        frac = float(power[band].sum() / max(float(power.sum()), 1e-12))
        return rms * frac ** 0.5

    def calibrate(self, blk):
        """Feed room-noise blocks first; returns True while still calibrating."""
        if self.calibrating:
            level = self.level(blk)
            self._calib.append(level)
            self._denoiser.calibrate_block(
                blk, quiet=level < max(self.min_start * 2.0, self.noise * 4.0)
            )
            if not self.calibrating:
                ordered = sorted(self._calib)
                self.noise = max(0.001, min(0.05, ordered[len(ordered) // 2]))      # median: a single bump cannot skew it
        return self.calibrating

    # ---- main entry ----
    def feed(self, blk, kira_speaking=False, kira_level=0.0, echo_reference=None):
        # Cancel Kira's own speaker signal before VAD and barge-in detection.
        # The reference is absent for unsupported/external audio paths, in which
        # case the original microphone samples pass through unchanged.
        if echo_reference is not None:
            blk = self._echo_canceller.process(blk, echo_reference)
        lvl = self.level(blk)
        events = []
        if not self.speaking:
            self.pre.append(blk)
            if kira_speaking:
                if self._barge_check(lvl, kira_level):
                    self._begin(events, barge=True)
                return events
            self._reset_barge_watch()
            if lvl < self.start_thr:
                self._denoiser.update_noise(blk)
                a = 0.1 if lvl < self.noise else 0.005          # follow the room: down fast, up slowly
                self.noise = max(0.001, min(0.05, (1 - a) * self.noise + a * lvl))
                self.onset = 0
                return events
            self.onset += 1
            if self.onset >= ONSET_BLOCKS:
                self._begin(events, barge=False)
            return events
        self.buf.append(blk)
        if lvl > self.stay_thr:
            self.silence = 0
            self.voiced += 1
            self.last_voiced = len(self.buf)
            self.voiced_avg = lvl if not self.voiced_avg else 0.9 * self.voiced_avg + 0.1 * lvl
        else:
            self.silence += 1
        voiced_s = self.voiced * self.block / self.rate
        end_s = 0.42 + (0.18 if voiced_s < 1.0 else 0.0)        # a short utterance gets a longer pause allowance (hesitation)
        if self.silence >= int(end_s * self.rate / self.block) or len(self.buf) * self.block / self.rate > MAX_SEGMENT_S:
            self._finish(events)
        return events

    # ---- internals ----
    def _begin(self, events, barge):
        self.speaking, self.barged = True, barge
        self.buf = list(self.pre)
        self.pre.clear()
        self.silence = 0
        self.voiced = max(self.onset, ONSET_BLOCKS)
        self.last_voiced = len(self.buf)
        self.voiced_avg = self.start_thr * 1.5
        self.onset = 0
        self._reset_barge_watch()
        if barge:
            events.append(("barge",))
        events.append(("start",))

    def _finish(self, events):
        np = self.np
        end = min(len(self.buf), self.last_voiced + TAIL_BLOCKS)
        audio = np.concatenate(self.buf[:end]) if end else np.zeros(0, dtype=np.float32)
        if audio.size:
            audio = self._denoiser.process(audio)
        voiced_s = self.voiced * self.block / self.rate
        self.reset()
        events.append(("segment", audio) if voiced_s >= MIN_VOICED_S and len(audio) else ("noise",))

    def _barge_check(self, lvl, kira_level):
        """While Kira talks: is this clearly louder than her own voice coming back through the microphone?"""
        if self._cal_n < BARGE_CAL_BLOCKS:                       # learn how much of her voice the mic picks up
            self._cal_n += 1
            self._cal_mic += lvl
            self._cal_out += kira_level
            self._cal_max = max(self._cal_max, lvl)
            return False
        echo = (self._cal_mic / self._cal_out) * kira_level if self._cal_out >= 1.0 else self._cal_max
        thr = max(self.start_thr * 1.5, echo * 2.0 + self.noise * 2.0)
        self._loud = self._loud + 1 if lvl > thr else max(0, self._loud - 1)
        return self._loud >= BARGE_BLOCKS
