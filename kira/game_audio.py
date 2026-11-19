"""Windows game-audio loopback listener.

Captures the default WASAPI output (game + system audio), segments speech locally,
and emits transcripts. It never records to disk or uploads audio to a cloud STT API.
"""
from __future__ import annotations


import numpy as np
from PySide6.QtCore import QThread, Signal

from .speech_text import is_hallucination
from .vad import BLOCK, RATE, Segmenter

from .game_audio_policy import is_important_game_audio


class GameAudioListener(QThread):
    transcript = Signal(str)
    error = Signal(str)
    state = Signal(str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else {}
        self._run = True

    def stop(self):
        # Request shutdown without freezing the GUI thread. The window retains
        # this QThread and defers close until its finished signal is delivered.
        self._run = False

    def run(self):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            self.error.emit("برای شنیدن صدای بازی، PyAudioWPatch نصب نیست. install.bat را اجرا کن.")
            return

        self.state.emit("starting")
        audio = pyaudio.PyAudio()
        stream = None
        try:
            try:
                wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            except Exception as exc:
                raise RuntimeError("WASAPI در ویندوز در دسترس نیست.") from exc
            speakers = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if not speakers.get("isLoopbackDevice"):
                loopback = next(
                    (item for item in audio.get_loopback_device_info_generator()
                     if speakers["name"] in item["name"]),
                    None,
                )
                if loopback is None:
                    raise RuntimeError("دستگاه Loopback متناظر با خروجی پیش‌فرض پیدا نشد.")
                speakers = loopback

            try:
                from faster_whisper import WhisperModel
                recognizer = WhisperModel(
                    self.settings.get("whisper_model", "small"), device="cpu",
                    compute_type="int8", cpu_threads=1, num_workers=1,
                )
            except Exception as exc:
                raise RuntimeError(f"موتور محلی faster-whisper آماده نشد: {exc}") from exc

            if not self._run:
                return
            rate = int(speakers["defaultSampleRate"])
            channels = max(1, min(2, int(speakers["maxInputChannels"])))
            stream = audio.open(
                format=pyaudio.paInt16, channels=channels, rate=rate,
                input=True, input_device_index=speakers["index"],
                frames_per_buffer=1024,
            )
            language = self.settings.get("stt_language", "fa")
            language = None if language in ("", "auto") else language
            segmenter = Segmenter(self.settings.get("mic_sensitivity", 100))
            pending = np.empty(0, dtype=np.float32)
            self.state.emit("listening")

            while self._run:
                raw = stream.read(1024, exception_on_overflow=False)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    samples = samples.reshape(-1, channels).mean(axis=1)
                if rate != RATE:
                    old_x = np.arange(len(samples), dtype=np.float32)
                    new_len = max(1, round(len(samples) * RATE / rate))
                    new_x = np.linspace(0, max(0, len(samples) - 1), new_len, dtype=np.float32)
                    samples = np.interp(new_x, old_x, samples).astype(np.float32)
                pending = np.concatenate((pending, samples))
                while len(pending) >= BLOCK and self._run:
                    block = pending[:BLOCK]
                    pending = pending[BLOCK:]
                    if segmenter.calibrating:
                        segmenter.calibrate(block)
                        continue
                    for event in segmenter.feed(block):
                        if event[0] != "segment":
                            continue
                        self.state.emit("transcribing")
                        try:
                            segments, _ = recognizer.transcribe(
                                event[1], language=language, beam_size=1,
                                vad_filter=True, condition_on_previous_text=False,
                                no_speech_threshold=0.60, compression_ratio_threshold=2.2,
                            )
                            text = " ".join(
                                item.text.strip() for item in segments if item.no_speech_prob < 0.6
                            ).strip()
                            if text and not is_hallucination(text):
                                self.transcript.emit(text)
                        except Exception as exc:
                            self.error.emit(f"تشخیص صدای بازی ناموفق بود: {exc}")
                        self.state.emit("listening")
        except Exception as exc:
            if self._run:
                self.error.emit(f"صدای بازی/سیستم دریافت نشد: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            audio.terminate()
            self.state.emit("stopped")
