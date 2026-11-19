"""Microphone listener: local-only Qwen3-ASR / whisper.cpp Vulkan / faster-whisper plus segmentation (kira/vad.py).

Behaviour (see vad.py / speech_text.py for the details):
  * less sensitive to room noise: speech-band level, measured noise floor, onset check, hysteresis;
  * colloquial Persian: a colloquial `initial_prompt`, stricter filtering of Whisper's invented text, text clean-up;
  * pauses between sentences: a finished piece of speech is held for a short grace time (longer after a comma or a
    connecting word like "و / که / ولی"); if the person goes on talking, the pieces are joined into ONE message;
  * end of speech: trailing silence is trimmed and the end is judged relative to how loud this person speaks;
  * barge-in: while Kira talks the microphone keeps listening; the person's voice, clearly louder than Kira's own
    voice coming back through the microphone, emits `interrupted` and the sentence is still transcribed.
"""
import queue
import time

from PySide6.QtCore import QThread, Signal

from .speech_fixes import SpeechFixes
from .speech_text import clean_transcript, grace_for, initial_prompt, is_hallucination, merge_text
from .vad import BLOCK, RATE, Segmenter

MAX_HOLD_S = 40.0               # a message is never held longer than this, however many pauses there were


class Listener(QThread):
    heard = Signal(str)
    state = Signal(str)     # loading | listening | hearing | transcribing
    error = Signal(str)
    interrupted = Signal()  # the person started talking while Kira was speaking
    note = Signal(str)      # non-fatal information from local speech engines

    def __init__(self, model_name="small", language="fa", parent=None, sensitivity=100, barge_in=True, settings=None):
        super().__init__(parent)
        # Qwen is preferred; whisper.cpp Vulkan is the first fallback and faster-whisper is the CPU floor.
        selected_model = str(model_name or "small").strip()
        self.model_name = "small" if selected_model.casefold().startswith("qwen/") else selected_model
        self.language = None if language in ("", "auto") else language
        self.sensitivity = sensitivity
        self.settings = settings if settings is not None else {}
        self.barge_in = bool(barge_in)
        self.muted = False
        self.kira_speaking = False      # set by the window while Kira's voice is playing
        self.kira_level = 0.0           # her current output level 0..1 (the lip-sync envelope), used to tell her echo from a person
        self.barge_capturing = False    # an interruption is being recorded right now (the mic must not be muted under it)
        self._run = True
        self.engine = None
        self._sr = None
        self._seg = None
        self.fixes = SpeechFixes()      # the user's dictionary (hotwords + word fixes), re-read when the file changes
        self._model = None              # faster-whisper model, loaded only when the local fallback is needed
        self.via = ""                   # local:qwen3-asr or local:whisper
        self._local_asr_failed = False  # avoid retrying a broken local model for every segment
        self._whisper_cpp_failed = False  # keep a broken Vulkan runtime from retrying on every segment
        self._hotwords_ok = True        # becomes False if the installed faster-whisper does not know `hotwords`
        self._pending, self._pending_until, self._pending_since = "", 0.0, 0.0

    # ---- called by the window ----
    def begin_kira_speech(self):
        """Kira starts talking: keep listening for an interruption, or mute completely when barge-in is off."""
        self.kira_level = 0.0
        if self.barge_in:
            self.kira_speaking, self.muted = True, False
        else:
            self.muted = True

    def end_kira_speech(self):
        """Kira stopped. The window unmutes shortly after (room echo), except when the person is already talking."""
        self.kira_speaking = False
        if not self.barge_capturing:
            self.muted = True

    def _input_device(self, sd):
        """Index of the microphone chosen in the settings (by name), or None = the Windows default."""
        wanted = str(getattr(self, "settings", {}).get("mic_device") or "").strip()
        if not wanted:
            return None
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0 and dev.get("name") == wanted:
                return idx
        return None                                          # that microphone is not connected now: use the default

    def stop(self):
        # Never block the GUI thread for the old 4-second wait. The owner keeps the
        # QThread reference until finished and the window's close handler defers shutdown.
        self._run = False

    def _close_stream(self, stream):
        """Stop and release the microphone independently so one cleanup error cannot leak the device."""
        try:
            stream.stop()
        except Exception as exc:
            self.note.emit(f"بستن ورودی میکروفن: {type(exc).__name__}")
        try:
            stream.close()
        except Exception as exc:
            self.note.emit(f"آزادسازی ورودی میکروفن: {type(exc).__name__}")

    # ---- thread ----
    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:
            self.error.emit(f"بسته‌ی لازم نصب نیست: {e.name}. دوباره install.bat را اجرا کن.")
            return
        self.state.emit("loading")
        self.engine = None
        if not self._run:
            return
        local_ready = False
        if bool(self.settings.get("local_voice_asr", True)):
            try:
                from . import local_voice
                local_ready = local_voice.asr_ready()
            except Exception:
                local_ready = False
        if local_ready:
            try:
                from . import local_voice
                selected_asr = str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B")
                local_voice.load_asr(selected_asr)
            except Exception as exc:
                local_ready = False
                self._local_asr_failed = True
                self.note.emit(f"بارگذاری Qwen3-ASR ناموفق بود؛ تلاش برای Whisper محلی. ({type(exc).__name__})")
        if not self._run:
            return
        if not local_ready and not self._load_local():
            return
        model = self._model

        q = queue.Queue()

        try:
            gain = max(0.5, min(3.0, float(self.settings.get("mic_gain", 100)) / 100.0))
        except (TypeError, ValueError):
            gain = 1.0

        def callback(indata, frames, t, status):
            block = indata[:, 0].copy()
            if gain != 1.0:                                  # microphone gain is independent of the speaker volume
                block = np.clip(block * gain, -1.0, 1.0)
            q.put(block)

        stream = None
        try:
            device = self._input_device(sd)
            stream = sd.InputStream(
                samplerate=RATE, channels=1, dtype="float32",
                blocksize=BLOCK, callback=callback, device=device,
            )
            stream.start()
        except Exception as exc:
            if stream is not None:
                self._close_stream(stream)
            self.error.emit(f"میکروفون باز نشد: {exc}")
            return

        if not self._run:
            self._close_stream(stream)
            return

        seg = self._seg = Segmenter(self.sensitivity)
        try:
            while self._run:                                             # ~0.38 s: measure room noise first
                first = self._next_block(q)
                if first is None or not seg.calibrate(first):
                    break
            if not self._run:
                return
            self.state.emit("listening")
            while self._run:
                try:
                    blk = q.get(timeout=0.2)
                except queue.Empty:
                    self._flush_pending()
                    continue
                self._flush_pending()
                if self.muted:
                    seg.reset()
                    self.barge_capturing = False
                    self._flush_pending(force=True)             # never lose text that was waiting when Kira started to talk
                    continue
                for ev in seg.feed(blk, self.kira_speaking, self.kira_level):
                    self._on_event(ev, model)
        finally:
            self._close_stream(stream)
            self._seg = None
            if self.engine == "whisper_cpp":
                try:
                    from . import whisper_cpp
                    whisper_cpp.stop()
                except Exception as exc:
                    self.note.emit(f"توقف موتور whisper.cpp: {type(exc).__name__}")

    def _load_whisper_cpp(self):
        """Select the managed Vulkan engine when installed; process startup is lazy."""
        if self._whisper_cpp_failed or not bool(self.settings.get("whisper_cpp_enabled", True)):
            return False
        try:
            from . import whisper_cpp
            if not whisper_cpp.is_ready():
                return False
            self.engine = "whisper_cpp"
            self._model = None
            return True
        except Exception as exc:
            self.note.emit(f"بررسی موتور whisper.cpp Vulkan ناموفق بود؛ مسیر CPU امتحان می‌شود. ({type(exc).__name__})")
            return False

    def _load_local(self):
        """Prefer whisper.cpp Vulkan, then use faster-whisper as the final CPU fallback."""
        if self.engine == "whisper_cpp":
            return True
        if self.engine == "whisper" and self._model is not None:
            return True
        if self._load_whisper_cpp():
            return True
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            self.error.emit("هیچ موتور STT محلی نصب نیست. از تنظیمات صدا، Qwen3-ASR یا whisper.cpp Vulkan را نصب کن.")
            return False
        try:
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self.engine = "whisper"
            return True
        except Exception as exc:
            self.error.emit(f"بارگذاری Whisper محلی ناموفق بود: {type(exc).__name__}: {exc}")
            return False

    def _transcribe_whisper_cpp(self, audio):
        """Run local whisper.cpp on Vulkan, with the same Persian prompt/hotword context."""
        from . import whisper_cpp

        self.fixes.refresh()
        return whisper_cpp.transcribe(
            audio,
            RATE,
            self.language or "fa",
            initial_prompt(self.language, self.fixes.hotwords_text()),
            threads=int(self.settings.get("asr_threads", 4) or 4),
        )

    def _next_block(self, q):
        while self._run:
            try:
                return q.get(timeout=0.2)
            except queue.Empty:
                continue
        return None

    def _on_event(self, ev, model):
        kind = ev[0]
        if kind == "barge":
            self.barge_capturing = True
            self.interrupted.emit()
        elif kind == "start":
            self.state.emit("hearing")
        elif kind == "noise":
            self.barge_capturing = False
            if self._run:
                self.state.emit("listening")
        elif kind == "segment":
            self.barge_capturing = False
            self.state.emit("transcribing")
            text = self._transcribe(model, ev[1])
            if text and not is_hallucination(text):
                self._pending = merge_text(self._pending, text)
                now = time.monotonic()
                self._pending_since = self._pending_since or now
                self._pending_until = now + grace_for(self._pending)     # wait a little: the person may only be pausing
            if self._run:
                self.state.emit("listening")

    def _flush_pending(self, force=False):
        """Hand the collected text over once the pause after it was long enough (or when forced)."""
        if not self._pending:
            return
        now = time.monotonic()
        if not force:
            if self._seg is not None and self._seg.speaking:
                return                                          # still talking: wait for the end of that sentence
            if now < self._pending_until and now - self._pending_since < MAX_HOLD_S:
                return
        self.fixes.refresh()
        text = clean_transcript(self._pending, self.language, self.fixes)
        self._pending, self._pending_since = "", 0.0
        if len(text) > 1:
            self.heard.emit(text)

    # ---- local recognition: return the transcript or an empty string ----
    def _transcribe_local_qwen(self, audio):
        """Run Qwen3-ASR locally; None means the local Whisper fallback may run."""
        if self._local_asr_failed or not bool(self.settings.get("local_voice_asr", True)):
            return None
        try:
            from . import local_voice
            if not local_voice.asr_ready():
                return None
            self.fixes.refresh()
            text = local_voice.transcribe(
                audio, RATE, self.language or "fa",
                initial_prompt(self.language, self.fixes.hotwords_text()),
                str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B"),
            )
            # An empty Qwen result is not a successful transcription: let local Whisper try.
            return str(text or "").strip() or None
        except Exception as exc:
            self._local_asr_failed = True
            self.note.emit(f"STT محلی Qwen3-ASR در دسترس نبود؛ Whisper محلی امتحان می‌شود. ({type(exc).__name__})")
            return None

    def _transcribe_whisper(self, audio):
        """Offline faster-whisper recognition."""
        model = self._model
        self.fixes.refresh()
        hot = self.fixes.hotwords_text()
        # Segmenter has already detected speech boundaries and trimmed silence before this
        # method is called. Running Whisper's internal VAD a second time can discard
        # almost the entire short utterance (especially Persian phrases).
        kw = dict(language=self.language, beam_size=3, vad_filter=False,
                  condition_on_previous_text=False, initial_prompt=initial_prompt(self.language, hot),
                  no_speech_threshold=0.55, compression_ratio_threshold=2.2, log_prob_threshold=-1.0)
        try:
            if hot and self._hotwords_ok:
                kw["hotwords"] = hot
            try:
                segs, _ = model.transcribe(audio, **kw)
            except TypeError:
                if "hotwords" not in kw:
                    raise
                self._hotwords_ok = False
                kw.pop("hotwords")
                segs, _ = model.transcribe(audio, **kw)
            parts = [seg.text.strip() for seg in segs if seg.no_speech_prob < 0.55 and seg.avg_logprob > -1.25]
        except Exception as exc:
            self.error.emit(f"تشخیص گفتار ناموفق بود: {exc}")
            return ""
        return " ".join(part for part in parts if part).strip()

    def _transcribe(self, model, audio):
        """Use Qwen3-ASR, then Vulkan whisper.cpp, then CPU faster-whisper. Audio stays local."""
        text = self._transcribe_local_qwen(audio)
        if text is not None and not is_hallucination(text):
            self.via = "local:qwen3-asr"
            return text
        if text is not None:
            self.note.emit("خروجی Qwen شبیه متن ساختگی بود؛ موتور پشتیبان امتحان می‌شود.")
        if self.engine is None and not self._load_local():
            return ""
        if self.engine == "whisper_cpp":
            try:
                text = self._transcribe_whisper_cpp(audio)
                if text and not is_hallucination(text):
                    self.via = "local:whisper.cpp-vulkan"
                    return text
            except Exception as exc:
                self._whisper_cpp_failed = True
                try:
                    from . import whisper_cpp
                    whisper_cpp.stop()
                except Exception:
                    pass
                self.note.emit(
                    f"whisper.cpp Vulkan در دسترس نبود؛ faster-whisper روی CPU امتحان می‌شود. ({type(exc).__name__})"
                )
                self.engine = None
                self._model = None
            if self.engine == "whisper_cpp":
                # A VAD-confirmed segment that Vulkan cannot decode gets one CPU retry.
                self._whisper_cpp_failed = True
                try:
                    from . import whisper_cpp
                    whisper_cpp.stop()
                except Exception:
                    pass
                self.note.emit("خروجی Vulkan خالی یا نامعتبر بود؛ این نشست به faster-whisper روی CPU منتقل می‌شود.")
                self.engine = None
                self._model = None
        if self.engine is None and not self._load_local():
            return ""
        if self.engine == "whisper":
            self.via = "local:faster-whisper-cpu"
            return self._transcribe_whisper(audio)
        return ""
