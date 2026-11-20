"""Music detection for the dancing companion.

``BeatAnalyzer`` is pure numpy (no Qt, no audio device) so it can be tested with synthetic signals: it turns raw mono blocks into
{level, playing, bpm, beats}. ``MusicWatcher`` feeds it from the Windows loopback (what the PC is playing, PyAudioWPatch) and emits
a small state dict about 12 times a second. Nothing is recorded or stored; the audio never leaves the machine.

"playing" means loud AND rhythmic for a few seconds (a regular low-frequency pulse), which separates songs from speech, notification
sounds and silence. It turns off again after a few seconds without rhythm.
"""
from __future__ import annotations

import time
from collections import deque

import numpy as np

HOP = 1024
LEVEL_MIN = 0.004            # RMS (0..1) below this is silence
RHYTHM_ON, RHYTHM_OFF = 0.22, 0.12
ON_AFTER_S, OFF_AFTER_S = 3.0, 4.0
BASS_HZ = 220.0
HISTORY_S = 6.0


class BeatAnalyzer:
    def __init__(self, rate: int = 48000) -> None:
        self.rate = int(rate)
        self.fps = self.rate / HOP
        self._buf = np.empty(0, dtype=np.float32)
        self._window = np.hanning(HOP).astype(np.float32)
        freqs = np.fft.rfftfreq(HOP, 1.0 / self.rate)
        self._bass = freqs <= BASS_HZ
        n = int(HISTORY_S * self.fps)
        self._energy = deque(maxlen=n)
        self._novelty = deque(maxlen=n)
        self._peak = 1e-6
        self._last_beat = -1e9
        self._frames = 0
        self.level = 0.0
        self.rhythm = 0.0
        self.bpm = 0.0
        self.beats = 0
        self.playing = False
        self._since_on = 0.0
        self._since_off = 0.0

    # ------------------------------------------------------------ feeding
    def feed(self, samples) -> dict:
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        self._buf = np.concatenate((self._buf, data))
        while len(self._buf) >= HOP:
            block, self._buf = self._buf[:HOP], self._buf[HOP:]
            self._frame(block)
        return self.state()

    def _frame(self, block: np.ndarray) -> None:
        dt = 1.0 / self.fps
        self._frames += 1
        rms = float(np.sqrt(np.mean(block * block)))
        self.level += (rms - self.level) * (0.25 if rms > self.level else 0.06)
        spectrum = np.abs(np.fft.rfft(block * self._window))
        bass = float(np.sum(spectrum[self._bass] ** 2))
        history = list(self._energy)[-8:]
        base = (sum(history) / len(history)) if history else bass
        novelty = max(0.0, bass - base * 1.15)
        self._energy.append(bass)
        self._novelty.append(novelty)
        self._peak = max(novelty, self._peak * 0.995, 1e-9)
        now = self._frames * dt
        if novelty > 0.35 * self._peak and novelty > 0 and now - self._last_beat > 0.28 and rms > LEVEL_MIN:
            self._last_beat = now
            self.beats += 1
        if self._frames % max(1, int(self.fps / 2)) == 0:
            self._estimate_tempo()
        self._update_playing(dt)

    def _estimate_tempo(self) -> None:
        nov = np.asarray(self._novelty, dtype=np.float64)
        if len(nov) < int(3 * self.fps):
            self.rhythm = 0.0
            return
        nov = nov - nov.mean()
        energy0 = float(np.dot(nov, nov))
        if energy0 <= 1e-18:
            self.rhythm = 0.0
            return
        lo, hi = int(self.fps * 60 / 180), int(self.fps * 60 / 60)
        ac = np.correlate(nov, nov, mode="full")[len(nov) - 1:]
        hi = min(hi, len(ac) - 1)
        if hi <= lo:
            return
        lag = lo + int(np.argmax(ac[lo:hi + 1]))
        self.rhythm = float(max(0.0, ac[lag] / ac[0]))
        bpm = 60.0 * self.fps / lag
        while bpm < 70:
            bpm *= 2
        while bpm > 160:
            bpm /= 2
        self.bpm = bpm if not self.bpm else self.bpm + (bpm - self.bpm) * 0.35

    def _update_playing(self, dt: float) -> None:
        loud = self.level > LEVEL_MIN
        if not self.playing:
            self._since_on = self._since_on + dt if (loud and self.rhythm >= RHYTHM_ON) else 0.0
            if self._since_on >= ON_AFTER_S:
                self.playing, self._since_on, self._since_off = True, 0.0, 0.0
        else:
            quiet = (not loud) or self.rhythm < RHYTHM_OFF
            self._since_off = self._since_off + dt if quiet else 0.0
            if self._since_off >= OFF_AFTER_S:
                self.playing, self._since_on, self._since_off = False, 0.0, 0.0

    def state(self) -> dict:
        return {"on": bool(self.playing), "level": round(min(1.0, self.level * 6), 3), "bpm": round(self.bpm, 1) if self.bpm else 0.0,
                "beats": int(self.beats), "rhythm": round(self.rhythm, 3)}


# ---------------------------------------------------------------- Windows loopback (needs PyAudioWPatch, installed by install.bat)
try:                                                    # Qt is only needed by the watcher thread, never by the analyzer
    from PySide6.QtCore import QThread, Signal
except Exception:                                       # noqa: BLE001
    QThread = None

if QThread is not None:
    class MusicWatcher(QThread):
        state = Signal(dict)
        error = Signal(str)

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._run = True

        def stop(self) -> None:
            self._run = False

        def run(self) -> None:
            try:
                import pyaudiowpatch as pyaudio
            except ImportError:
                self.error.emit("PyAudioWPatch نصب نیست؛ رقص خودکار با آهنگ کار نمی‌کند.")
                return
            audio = pyaudio.PyAudio()
            stream = None
            try:
                wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
                speakers = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
                if not speakers.get("isLoopbackDevice"):
                    speakers = next((item for item in audio.get_loopback_device_info_generator()
                                     if speakers["name"] in item["name"]), None)
                    if speakers is None:
                        raise RuntimeError("دستگاه Loopback پیدا نشد.")
                rate = int(speakers["defaultSampleRate"])
                channels = max(1, min(2, int(speakers["maxInputChannels"])))
                stream = audio.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                                    input_device_index=speakers["index"], frames_per_buffer=HOP)
                analyzer = BeatAnalyzer(rate)
                last_emit = 0.0
                while self._run:
                    raw = stream.read(HOP, exception_on_overflow=False)
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    if channels > 1:
                        samples = samples.reshape(-1, channels).mean(axis=1)
                    analyzer.feed(samples)
                    now = time.monotonic()
                    if now - last_emit >= 0.08:
                        last_emit = now
                        self.state.emit(analyzer.state())
            except Exception as exc:                    # noqa: BLE001 - never take the app down for an optional animation
                if self._run:
                    self.error.emit(f"شنیدن موسیقی سیستم ممکن نشد: {exc}")
            finally:
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:                   # noqa: BLE001
                        pass
                audio.terminate()
