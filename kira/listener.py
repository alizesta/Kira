"""Microphone listener: speech segmentation (kira/vad.py) + faster-whisper (local, CPU) or the Google web recognizer.

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

from . import cloud_voice
from .speech_fixes import SpeechFixes
from .speech_text import clean_transcript, grace_for, initial_prompt, is_hallucination, merge_text
from .vad import BLOCK, RATE, Segmenter

MAX_HOLD_S = 40.0               # a message is never held longer than this, however many pauses there were


class Listener(QThread):
    heard = Signal(str)
    state = Signal(str)     # loading | listening | hearing | transcribing
    error = Signal(str)
    interrupted = Signal()  # the person started talking while Kira was speaking
    note = Signal(str)      # non-fatal information (Cloud Voice switched key/provider or fell back to the local engine)

    def __init__(self, model_name="small", language="fa", parent=None, sensitivity=100, barge_in=True, settings=None):
        super().__init__(parent)
        self.model_name = model_name
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
        self._model = None              # the local engine's model, loaded lazily when Cloud Voice is first in line
        self.via = ""                   # "cloud:<provider>" or "local" - what recognised the last sentence
        self._cloud_failed = False      # last cloud attempt failed (the note is sent once per streak)
        self._local_asr_failed = False  # avoid retrying a broken local model for every segment
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
        self._run = False
        self.wait(4000)

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
        local_ready = False
        if bool(self.settings.get("local_voice_asr", True)):
            try:
                from . import local_voice
                local_ready = local_voice.asr_ready()
            except Exception:
                local_ready = False
        if not local_ready and not self._cloud_ready() and not self._load_local():
            return
        model = self._model

        q = queue.Queue()

        gain = max(0.5, min(3.0, float(self.settings.get("mic_gain", 100)) / 100.0)) if hasattr(self, "settings") else 1.0

        def callback(indata, frames, t, status):
            block = indata[:, 0].copy()
            if gain != 1.0:                                  # microphone gain is independent of the speaker volume
                block = np.clip(block * gain, -1.0, 1.0)
            q.put(block)

        try:
            device = self._input_device(sd)
            stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, callback=callback, device=device)
            stream.start()
        except Exception as e:
            self.error.emit(f"میکروفون باز نشد: {e}")
            return

        seg = self._seg = Segmenter(self.sensitivity)
        try:
            while self._run:                                             # ~0.8 s: measure the room noise first
                first = self._next_block(q)
                if first is None or not seg.calibrate(first):
                    break
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
            stream.stop()
            stream.close()

    def _cloud_ready(self):
        try:
            return cloud_voice.service().stt_ready()
        except Exception:
            return False

    def _load_local(self):
        """Load the local engine (faster-whisper, else the Google web recognizer). False + `error` when none works."""
        if self.engine is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self.engine = "whisper"
        except ImportError:
            pass
        except Exception as e:
            self.error.emit(f"بارگذاری مدل گفتار ناموفق بود (بار اول اینترنت لازم است): {e}")
            return False
        if self.engine is None:
            try:
                import speech_recognition as sr
                self._sr = sr
                self.engine = "google"
            except ImportError:
                self.error.emit("هیچ موتور تشخیص گفتار نصب نیست. install.bat را دوباره اجرا کن.")
                return False
        return True

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

    # ---- recognition: both return the text (or "") ----
    def _transcribe_google(self, audio):
        """Fallback when faster-whisper is unavailable: free Google web recognizer (online)."""
        import numpy as np
        sr = self._sr
        lang = {"fa": "fa-IR", "en": "en-US"}.get(self.language or "fa", "fa-IR")
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
        try:
            return sr.Recognizer().recognize_google(sr.AudioData(pcm, RATE, 2), language=lang).strip()
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            self.error.emit(f"تشخیص گفتار آنلاین ناموفق بود (اینترنت لازم است): {e}")
            return ""

    def _transcribe_cloud(self, audio):
        """Cloud Voice (user's provider/key order). -> text, or None when the local engine must take over."""
        try:
            svc = cloud_voice.service()
            if not svc.stt_ready():
                return None
            self.fixes.refresh()
            text, info = svc.transcribe(audio, RATE, self.language, initial_prompt(self.language, self.fixes.hotwords_text()))
        except cloud_voice.AllFailed as e:
            if not self._cloud_failed:
                self.note.emit(f"Cloud Voice (STT) ناموفق بود؛ با موتور محلی ادامه می‌دهم. ({str(e)[:160]})")
            self._cloud_failed = True
            return None
        except Exception as e:                                  # noqa: BLE001 - never lose speech because of the cloud layer
            if not self._cloud_failed:
                self.note.emit(f"Cloud Voice (STT) خطا داد؛ موتور محلی جای آن را می‌گیرد: {type(e).__name__}")
            self._cloud_failed = True
            return None
        self._cloud_failed = False
        self.via = f"cloud:{info['provider']}"
        if info.get("failovers"):
            self.note.emit("Cloud Voice (STT): " + " ← ".join(info["failovers"]) + f" → {info['provider']} / {info['key']}")
        return text

    def _transcribe_local_qwen(self, audio):
        """Qwen3-ASR is the first STT engine; None means use the next engine."""
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
            # An empty Qwen result is not a successful transcription: let Whisper / Cloud Voice try.
            return str(text or "").strip() or None
        except Exception as exc:
            self._local_asr_failed = True
            self.note.emit(f"STT محلی Qwen3-ASR در دسترس نبود؛ موتور جایگزین بعدی امتحان می‌شود. ({type(exc).__name__})")
            return None

    def _transcribe_whisper(self, audio):
        """Legacy offline Whisper fallback, tried before Cloud Voice when installed."""
        model = self._model
        self.fixes.refresh()
        hot = self.fixes.hotwords_text()
        kw = dict(language=self.language, beam_size=3, vad_filter=True,
                  vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 200},
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
        # First choice: the dedicated offline multilingual ASR.
        text = self._transcribe_local_qwen(audio)
        if text is not None:
            self.via = "local:qwen3-asr"
            return text

        # Second choice: the existing offline Whisper engine, if installed.
        if self.engine is None:
            try:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
                self.engine = "whisper"
            except ImportError:
                pass
            except Exception as exc:
                self.note.emit(f"Whisper محلی در دسترس نبود؛ موتور بعدی امتحان می‌شود. ({type(exc).__name__})")
        if self.engine == "whisper":
            self.via = "local:whisper"
            return self._transcribe_whisper(audio)

        # Cloud Voice is tried only after the installed local ASR engines.
        text = self._transcribe_cloud(audio)
        if text is not None:
            return text

        # Last legacy fallback: Google recognizer, only if no local ASR or Cloud Voice worked.
        if not self._load_local():
            return ""
        if self.engine == "google":
            self.via = "google"
            return self._transcribe_google(audio)
        if self.engine == "whisper":
            self.via = "local:whisper"
            return self._transcribe_whisper(audio)
        return ""
