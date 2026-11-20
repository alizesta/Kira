import unittest

import numpy as np

from kira.music_dance import BeatAnalyzer

RATE = 48000


def kick_train(seconds, bpm, rate=RATE):
    n = int(seconds * rate)
    out = np.zeros(n, dtype=np.float32)
    period = int(60 / bpm * rate)
    t = np.arange(int(0.12 * rate)) / rate
    burst = (np.sin(2 * np.pi * 60 * t) * np.exp(-t * 28)).astype(np.float32) * 0.6
    for start in range(0, n - len(burst), period):
        out[start:start + len(burst)] += burst
    return out


def feed_all(analyzer, signal, chunk=2048):
    state = {}
    for i in range(0, len(signal), chunk):
        state = analyzer.feed(signal[i:i + chunk])
    return state


class BeatAnalyzerTests(unittest.TestCase):
    def test_regular_kick_is_music_with_matching_tempo(self):
        state = feed_all(BeatAnalyzer(RATE), kick_train(14, 120))
        self.assertTrue(state["on"], state)
        self.assertTrue(110 <= state["bpm"] <= 130, state)
        self.assertGreater(state["beats"], 15)

    def test_silence_is_not_music(self):
        state = feed_all(BeatAnalyzer(RATE), np.zeros(RATE * 8, dtype=np.float32))
        self.assertFalse(state["on"])

    def test_irregular_bursts_like_speech_are_not_music(self):
        rng = np.random.default_rng(3)
        n = RATE * 14
        signal = np.zeros(n, dtype=np.float32)
        pos = 0
        while pos < n - 6000:
            length = int(rng.uniform(0.05, 0.4) * RATE)
            signal[pos:pos + length] = rng.normal(0, 0.12, min(length, n - pos)).astype(np.float32)
            pos += length + int(rng.uniform(0.1, 0.9) * RATE)
        state = feed_all(BeatAnalyzer(RATE), signal)
        self.assertFalse(state["on"], state)

    def test_music_stops_a_few_seconds_after_the_song_ends(self):
        analyzer = BeatAnalyzer(RATE)
        feed_all(analyzer, kick_train(12, 110))
        self.assertTrue(analyzer.playing)
        state = feed_all(analyzer, np.zeros(RATE * 9, dtype=np.float32))
        self.assertFalse(state["on"])


if __name__ == "__main__":
    unittest.main()
