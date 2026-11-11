"""Windows game-audio loopback listener.

Captures the default WASAPI output (game + system audio), segments speech locally,
and emits transcripts. It never records to disk or uploads audio to a cloud STT API.
"""
from __future__ import annotations

import queue
import re

import numpy as np
from PySide6.QtCore import QThread, Signal

from .listener import Listener
from .speech_text import is_hallucination
from .vad import BLOCK, RATE, Segmenter

IMPORTANT_GAME_AUDIO = re.compile(
    r"\b(low\s+health|critical\s+health|health\s+low|low\s+hp|"
    r"mission\s+complete|quest\s+complete|objective\s+complete|"
    r"mission\s+failed|objective\s+failed|achievement\s+unlocked|"
    r"victory|you\s+win|you\s+have\s+been\s+defeated|game\s+over|"
    r"boss\s+(?:fight|battle|incoming)|incoming\s+(?:enemy|attack)|"
    r"warning|danger|critical\s+damage|enemy\s+spotted)\b|"
    r"سلامتی.{0,12}(?:کم|پایین)|خونت\s+کم|جونت\s+کم|"
    r"مرحله\s+(?:تموم|تمام)|ماموریت\s+(?:تموم|تمام|شکست)|"
    r"هدف\s+(?:انجام|تکمیل)|موفق\s+شد[یی]|شکست\s+خورد[یی]|"
    r"دشمن\s+(?:نزدیک|پیدا)|حمله\s+(?:شد|در\s+راه)|"
    r"خطر|هشدار|باس\s+(?:اومد|آمد)|دستاورد",
    re.I,
)


def is_important_game_audio(text: str) -> bool:
    """Conservative local keyword filter; ordinary dialogue stays silent."""
    return bool(IMPORTANT_GAME_AUDIO.search(str(text or "").strip()))


class GameAudioListener(QThread):
    transcript = Signal(str)
    error = Signal(str)
    state = Signal(str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else {}
        self._run = True

    def stop(self):
        self._run = False
        self.wait(4000)

    @staticmethod
    def _wasapi_output(sd):
        default = sd.default.device
        output_index = default[1] if isinstance(default, (tuple, list)) else -1
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        candidates = []
        if isinstance(output_index, int) and output_index >= 0:
            candidates.append(output_index)
        candidates.extend(
            i for i, dev in enumerate(devices)
            if dev.get("max_output_channels", 0) > 0
            and "wasapi" in hostapis[dev["hostapi"]]["name"].lower()
            and i not in candidates
        )
        for index in candidates:
            dev = devices[index]
            api = hostapis[dev["hostapi"]]["name"].lower()
            if dev.get("max_output_channels", 0) > 0 and "wasapi" in api:
                return index, dev
        raise RuntimeError("خروجی صدای WASAPI پیدا نشد؛ خروجی ویندوز باید روی دستگاهی با WASAPI باشد.")

    def run(self):
        try:
            import sounddevice as sd
        except ImportError:
            self.error.emit("برای شنیدن صدای بازی، بسته sounddevice نصب نیست. install.bat را اجرا کن.")
            return

        self.state.emit("starting")
        try:
            device, info = self._wasapi_output(sd)
            rate = int(info.get("default_samplerate") or 48000)
            channels = max(1, min(2, int(info.get("max_output_channels") or 2)))
            extra = sd.WasapiSettings(loopback=True)
            blocks = queue.Queue(maxsize=80)

            def callback(indata, frames, timing, status):
                if not self._run:
                    return
                try:
                    blocks.put_nowait(indata.copy())
                except queue.Full:
                    try:
                        blocks.get_nowait()
                        blocks.put_nowait(indata.copy())
                    except queue.Empty:
                        pass

            stream = sd.InputStream(
                device=device, samplerate=rate, channels=channels, dtype="float32",
                blocksize=1024, callback=callback, extra_settings=extra,
            )
            stream.start()
        except Exception as exc:
            self.error.emit(f"صدای بازی/سیستم دریافت نشد: {exc}")
            return

        recognizer = Listener(
            self.settings.get("whisper_model", "small"),
            self.settings.get("stt_language", "fa"),
            settings=self.settings,
        )
        if not recognizer._load_local() or recognizer.engine != "whisper":
            stream.stop()
            stream.close()
            self.error.emit("برای تشخیص صدای بازی، موتور محلی faster-whisper لازم است. صدای بازی به سرویس ابری ارسال نمی‌شود.")
            return

        segmenter = Segmenter(self.settings.get("mic_sensitivity", 100))
        pending = np.empty(0, dtype=np.float32)
        calibrated = False
        self.state.emit("listening")
        try:
            while self._run:
                try:
                    raw = blocks.get(timeout=0.25)
                except queue.Empty:
                    continue
                mono = raw.mean(axis=1) if raw.ndim > 1 else raw
                if rate != RATE:
                    old_x = np.arange(len(mono), dtype=np.float32)
                    new_len = max(1, round(len(mono) * RATE / rate))
                    new_x = np.linspace(0, max(0, len(mono) - 1), new_len, dtype=np.float32)
                    mono = np.interp(new_x, old_x, mono).astype(np.float32)
                pending = np.concatenate((pending, mono.astype(np.float32, copy=False)))
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
                            segments, _ = recognizer._model.transcribe(
                                event[1], language=recognizer.language, beam_size=1,
                                vad_filter=True, condition_on_previous_text=False,
                                no_speech_threshold=0.60, compression_ratio_threshold=2.2,
                            )
                            text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
                            if text and not is_hallucination(text):
                                self.transcript.emit(text)
                        except Exception as exc:
                            self.error.emit(f"تشخیص صدای بازی ناموفق بود: {exc}")
                        self.state.emit("listening")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            self.state.emit("stopped")
