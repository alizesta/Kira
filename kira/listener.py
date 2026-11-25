"""Microphone listener: local-only Shenava speech recognition plus speech segmentation (kira/vad.py).

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

from .asr_manager import ASRManager, ASRError
from .speech_fixes import SpeechFixes
from .speech_text import clean_transcript, grace_for, is_hallucination, merge_text
from .vad import BLOCK, RATE, Segmenter

MAX_HOLD_S = 40.0               # a message is never held longer than this, however many pauses there were
PARTIAL_INTERVAL_S = 0.85       # decode the active utterance periodically; the full hypothesis may revise earlier words
PARTIAL_MIN_AUDIO_S = 0.55
PARTIAL_MIN_GROWTH_S = 0.35


class Listener(QThread):
    heard = Signal(str)
    partial_heard = Signal(str)  # replaceable full hypothesis while the user is still speaking
    state = Signal(str)     # loading | listening | hearing | transcribing
    error = Signal(str)
    interrupted = Signal()  # the person started talking while Kira was speaking
    note = Signal(str)      # non-fatal information from local speech engines

    def __init__(self, model_name="small", language="fa", parent=None, sensitivity=100, barge_in=True, settings=None, asr_manager=None):
        super().__init__(parent)
        self.language = None if language in ("", "auto") else language
        self.sensitivity = sensitivity
        self.settings = settings if settings is not None else {}
        self.barge_in = bool(barge_in)
        self.muted = False
        self.kira_speaking = False      # set by the window while Kira's voice is playing
        self.kira_level = 0.0           # her current output level 0..1 (the lip-sync envelope), used to tell her echo from a person
        self.barge_capturing = False    # an interruption is being recorded right now (the mic must not be muted under it)
        self._run = True
        self.asr_manager = asr_manager if asr_manager is not None else ASRManager()
        self.engine = ""
        self.engine_name = ""
        self._asr_initialized = False
        try:
            selected_engine, _selected_model = self.asr_manager.select(self.settings)
            self.engine = selected_engine
            self.engine_name = self.asr_manager.selected_engine_label(self.settings)
            self.via = f"local:{selected_engine}"
        except ASRError:
            # Preserve unsupported saved choices; never select an implicit fallback.
            self.via = ""
        self._sr = None
        self._seg = None
        self.fixes = SpeechFixes()      # the user's dictionary (hotwords + word fixes), re-read when the file changes
        self._pending, self._pending_until, self._pending_since = "", 0.0, 0.0
        self._partial_last_at = 0.0
        self._partial_last_samples = 0
        self._partial_last_text = ""
        self._segment_partial_text = ""
        self._partial_decode_count = 0  # Shenava is offline: every preview decodes the full utterance again.

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
        """Resolve the exact host-API endpoint; empty/legacy settings remain supported."""
        from .audio_devices import resolve_input_device

        wanted = str(getattr(self, "settings", {}).get("mic_device") or "").strip()
        return resolve_input_device(sd, wanted)

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
        except ImportError as exc:
            self.error.emit(f"بسته‌ی لازم نصب نیست: {exc.name}. دوباره install.bat را اجرا کن.")
            return
        except OSError as exc:
            self.error.emit(f"کتابخانه‌ی صوتی PortAudio پیدا نشد: {exc}")
            return

        self.state.emit("loading")
        if not self._run:
            return
        try:
            state = self.asr_manager.initialize(self.settings)
            self.engine = str(state.get("engine_id") or self.asr_manager.active_engine_id)
            self.engine_name = str(state.get("engine_name") or self.asr_manager.selected_engine_label(self.settings))
            self.via = f"local:{self.engine}"
            self._asr_initialized = True
        except ASRError as exc:
            self.error.emit(f"آماده‌سازی ASR ناموفق بود [{exc.code}]: {exc}")
            return
        except Exception as exc:
            self.error.emit(f"آماده‌سازی ASR ناموفق بود [initialization_failed]: {type(exc).__name__}: {exc}")
            return

        if not self._run:
            try:
                self.asr_manager.shutdown()
            finally:
                self._asr_initialized = False
            return

        q = queue.Queue(maxsize=64)  # bounded: partial ASR cannot create an ever-growing audio backlog
        try:
            gain = max(0.5, min(3.0, float(self.settings.get("mic_gain", 100)) / 100.0))
        except (TypeError, ValueError):
            gain = 1.0

        def callback(indata, frames, t, status):
            block = indata[:, 0].copy()
            if gain != 1.0:
                block = np.clip(block * gain, -1.0, 1.0)
            try:
                q.put_nowait(block)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(block)
                except queue.Full:
                    pass

        stream = None
        try:
            try:
                device = self._input_device(sd)
                stream = sd.InputStream(
                    samplerate=RATE, channels=1, dtype="float32",
                    blocksize=BLOCK, callback=callback, device=device,
                )
                stream.start()
            except Exception as exc:
                self.error.emit(f"میکروفون باز نشد: {type(exc).__name__}: {exc}")
                return

            if not self._run:
                return

            seg = self._seg = Segmenter(self.sensitivity)
            try:
                while self._run:
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
                        self._flush_pending(force=True)
                        continue
                    for event in seg.feed(blk, self.kira_speaking, self.kira_level):
                        self._on_event(event, None)
                    if seg.speaking:
                        self._maybe_emit_partial(seg, None)
            finally:
                self._seg = None
        finally:
            if stream is not None:
                self._close_stream(stream)
            if self._asr_initialized:
                self._asr_initialized = False
                try:
                    self.asr_manager.shutdown()
                except ASRError as exc:
                    self.error.emit(f"بستن موتور ASR ناموفق بود [{exc.code}]: {exc}")
                except Exception as exc:
                    self.error.emit(f"بستن موتور ASR ناموفق بود: {type(exc).__name__}: {exc}")


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
            self._partial_last_at = 0.0
            self._partial_last_samples = 0
            self._partial_decode_count = 0
            self._segment_partial_text = ""
            self.state.emit("hearing")
        elif kind == "noise":
            self.barge_capturing = False
            self._segment_partial_text = ""
            if not self._pending:
                self._emit_partial("")
            if self._run:
                self.state.emit("listening")
        elif kind == "segment":
            self.barge_capturing = False
            self.state.emit("transcribing")
            text = self._transcribe(model, ev[1])
            if not text or is_hallucination(text):
                text = self._segment_partial_text
            if text and not is_hallucination(text):
                self._pending = merge_text(self._pending, text)
                self._emit_partial(clean_transcript(self._pending, self.language, self.fixes))
                now = time.monotonic()
                self._pending_since = self._pending_since or now
                self._pending_until = now + grace_for(self._pending)     # wait a little: the person may only be pausing
            if self._run:
                self.state.emit("listening")

    def _emit_partial(self, text):
        """Publish a replaceable transcript snapshot; never append hypotheses together."""
        value = str(text or "").strip()
        if value == self._partial_last_text:
            return
        self._partial_last_text = value
        self.partial_heard.emit(value)

    def _maybe_emit_partial(self, segmenter, model):
        """Emit one live preview per utterance; Shenava's offline decoder reprocesses all buffered audio."""
        if self._partial_decode_count >= 1:
            return
        now = time.monotonic()
        audio_samples = len(segmenter.buf) * segmenter.block
        if audio_samples < int(RATE * PARTIAL_MIN_AUDIO_S):
            return
        if now - self._partial_last_at < PARTIAL_INTERVAL_S:
            return
        if audio_samples - self._partial_last_samples < int(RATE * PARTIAL_MIN_GROWTH_S):
            return
        self._partial_last_at = now
        self._partial_last_samples = audio_samples
        audio = segmenter.snapshot()
        if not len(audio):
            return
        self._partial_decode_count += 1
        hypothesis = self._transcribe(model, audio)
        if not hypothesis or is_hallucination(hypothesis):
            return
        self.fixes.refresh()
        cleaned = clean_transcript(hypothesis, self.language, self.fixes)
        if cleaned:
            self._segment_partial_text = cleaned
            self._emit_partial(merge_text(self._pending, cleaned))

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
            self.partial_heard.emit("")
            self._partial_last_text = ""
            self._segment_partial_text = ""
            self.heard.emit(text)
        else:
            self._segment_partial_text = ""
            self._emit_partial("")

    # ---- local recognition: return the transcript or an empty string ----
    def _transcribe(self, model, audio):
        """Delegate all transcript hypotheses to the selected ASR adapter."""
        try:
            return self.asr_manager.transcribe(audio, RATE, self.settings)
        except ASRError as exc:
            self.error.emit(f"تشخیص گفتار ناموفق بود [{exc.code}]: {exc}")
            return ""
        except Exception as exc:
            self.error.emit(f"تشخیص گفتار ناموفق بود [inference_failed]: {type(exc).__name__}: {exc}")
            return ""
