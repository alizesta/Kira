"""Kira local-only speech output: Piper synthesis and Qt audio playback."""
import atexit
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import wave

from .config import DATA_DIR
from .speech_split import StreamSplitter, split_sentences, strip_think
from .leak_guard import strip_blocks, scrub_lines
from .voice_prosody import apply_audio_effects, resolve_prosody, split_comma_clauses, join_wavs_with_pauses, prepend_wav_silence
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QElapsedTimer, QBuffer, QByteArray, QIODevice
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

SR = 24000
PIPER_FA = "Mana Persian Piper"
CACHE_DIR = DATA_DIR / "voice_cache"
CACHE_DIR.mkdir(exist_ok=True)
HOP_MS = 40
_CACHE_LOCK = threading.RLock()
_CACHE_VERSION = "local-persian-piper-emotion-v6"


def _valid_cached_envelope(envelope, frames, sample_rate):
    """Reject truncated, malformed, non-finite, or out-of-range lip-sync metadata."""
    if not isinstance(envelope, list) or frames <= 0 or sample_rate <= 0:
        return False
    hop = max(1, sample_rate * HOP_MS // 1000)
    expected = (frames + hop - 1) // hop
    return len(envelope) == expected and all(
        isinstance(value, (int, float)) and math.isfinite(value) and 0.0 <= value <= 1.0
        for value in envelope
    )


def _load_cached_audio(wav_path, meta_path):
    """Load a cache entry only when the envelope matches the exact WAV payload."""
    try:
        with open(wav_path, "rb") as stream:
            payload = stream.read()
        with wave.open(io.BytesIO(payload), "rb") as existing:
            frames = existing.getnframes()
            sample_rate = existing.getframerate()
        with open(meta_path, encoding="utf-8") as stream:
            metadata = json.load(stream)
        envelope = metadata.get("envelope") if isinstance(metadata, dict) else None
        if (
            isinstance(metadata, dict)
            and metadata.get("version") == 1
            and metadata.get("wav_sha256") == hashlib.sha256(payload).hexdigest()
            and metadata.get("frames") == frames
            and metadata.get("sample_rate") == sample_rate
            and _valid_cached_envelope(envelope, frames, sample_rate)
        ):
            return envelope
    except (OSError, ValueError, TypeError, EOFError, wave.Error, json.JSONDecodeError):
        return None
    return None


def _atomic_write(path, payload):
    """Publish a completed cache file atomically so readers never see partial output."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".kira-tts-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


PLAYBACK_START_TIMEOUT_MS = 8000   # a sentence that has not become audible by then is skipped


def _envelope(pcm, rate):
    """Loudness per 40 ms (0..1) from 16-bit samples; drives the mouth."""
    import numpy as np
    a = pcm.astype(np.float32) / 32768.0
    hop = max(1, rate * HOP_MS // 1000)
    n = max(1, (len(a) + hop - 1) // hop)
    # Pad the final hop so even a very short valid utterance cannot fail reshape().
    padded = np.pad(a, (0, n * hop - len(a)))
    env = np.sqrt((padded.reshape(n, hop) ** 2).mean(axis=1))
    ref = float(np.percentile(env, 95)) or 1.0
    return (np.clip(env / ref, 0, 1) ** 0.8).tolist()


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")


def clean_for_speech(text):
    text = scrub_lines(strip_blocks(text))                          # analysis blocks / echoed notes are never spoken
    text = re.sub(r"\[(neutral|happy|excited|sad|bored|angry|shy|surprised|thinking)\]", "", text, flags=re.I)
    text = re.sub(r"https?://\S+", "", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_`#>~|]", "", text)
    return re.sub(r"\s+", " ", text).strip()



PREFETCH = 2                    # sentences made ahead of the one that is playing
STREAM_MARGIN = 40              # (reserved) characters kept back; the splitter itself waits for a safe boundary



class _PcmPlayer(QObject):
    """Plays one 16-bit PCM .wav straight through QAudioSink (no media demuxer, so it starts almost at once).

    The whole sentence is loaded into memory (Piper sentences are a few hundred KB at most) and pulled by the sink.
    Emits playingChanged(True) when audio really flows and playingChanged(False) when the buffer is used up."""
    playingChanged = Signal(bool)
    failed = Signal(str)

    def __init__(self, path, device, volume, parent=None):
        super().__init__(parent)
        with wave.open(path, "rb") as w:
            params, frames = w.getparams(), w.readframes(w.getnframes())
        if params.comptype != "NONE" or params.sampwidth != 2 or params.nframes <= 0:
            raise ValueError("فقط WAV خام ۱۶ بیتی پشتیبانی می‌شود")
        fmt = QAudioFormat()
        fmt.setSampleRate(int(params.framerate))
        fmt.setChannelCount(int(params.nchannels))
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            raise RuntimeError("دستگاه خروجی این قالب صدا را پشتیبانی نمی‌کند")
        self.duration_ms = int(1000 * params.nframes / max(1, params.framerate))
        self._active = False
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(frames))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = QAudioSink(device, fmt, self)
        self._sink.setVolume(max(0.0, min(1.0, float(volume))))
        self._sink.stateChanged.connect(self._on_state)

    def start(self):
        self._sink.start(self._buffer)

    def isPlaying(self):
        return self._active

    def _on_state(self, state):
        if state == QAudio.State.ActiveState and not self._active:
            self._active = True
            self.playingChanged.emit(True)
        elif state in (QAudio.State.IdleState, QAudio.State.StoppedState):
            if self._sink.error() != QAudio.Error.NoError:
                self.failed.emit(f"خطای خروجی صدا ({self._sink.error().name})")
            elif self._active:
                self._active = False
                self.playingChanged.emit(False)

    def stop(self):
        try:
            self._sink.stateChanged.disconnect(self._on_state)      # a stop() from Speaker must not re-enter Speaker
        except (RuntimeError, TypeError):
            pass
        self._active = False
        self._sink.stop()


def _silent_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass

class _Session:
    """One spoken reply: its sentences in order, what is already synthesized, and how far playback is."""

    def __init__(self, gen, rate=0, pitch=0, cache=False, keep=False, prosody=None):
        self.gen, self.rate, self.pitch, self.cache, self.keep = gen, rate, pitch, cache, keep
        self.prosody = dict(prosody or resolve_prosody())
        self.splitter = StreamSplitter()
        self.consumed = ""              # cleaned reply text already handed to the splitter (streaming mode)
        self.sentences = []             # texts, in speaking order
        self.paths = {}                 # index -> already existing audio file (play_file)
        self.ready = {}                 # index -> (path, envelope) waiting for its turn; (None, []) = this sentence failed
        self.next_play = 0
        self.input_done = False
        self.playing = False
        self.worker = None
        self.cond = threading.Condition()
        self.error_sent = False
        self.streaming = False          # fed while the reply is still being written


class Speaker(QObject):
    """Speaks a reply sentence by sentence: the first sentence is made and played while the following ones are already
    being made (PREFETCH ahead), so speech starts after ONE short sentence instead of after the whole reply.

    started / finished / level are emitted once for the whole reply (the microphone logic depends on that)."""
    started = Signal()
    finished = Signal()
    cancelled = Signal()
    level = Signal(float)
    error = Signal(str)
    _ready = Signal(int, int, str, list)
    _failed = Signal(int, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings            # shared dict, read on every call
        self._tmp = tempfile.mkdtemp(prefix="kira_tts_")
        atexit.register(shutil.rmtree, self._tmp, True)      # do not leave kira_tts_* folders in %TEMP% after every launch
        self._gen = 0
        self._session = None
        self._worker_lock = threading.Lock()
        self._worker_threads = set()
        self._fx = None
        self._out = None
        self._env = []
        self._began = False                 # audio of this reply has started (and not finished yet)
        self._item_began = False            # the current sentence is audible
        self._wav = None
        self._keep = False
        self._prosody = resolve_prosody()  # direct/non-streaming speech must start with a defined neutral profile
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(HOP_MS)
        self._timer.timeout.connect(self._tick)
        self._ready.connect(self._on_ready)
        self._failed.connect(self._on_failed)
        # Windows can invalidate the audio device (headset/Bluetooth/driver change, a game taking the device):
        # "AUDCLNT_E_DEVICE_INVALIDATED". Keeping a QMediaDevices alive lets Qt notice the change; each new
        # sentence is then bound to the CURRENT default output instead of a stale one.
        self._devices = None            # created lazily on first playback (needs a working audio backend)
        self._prefer_default_output = False  # do not reuse a stale endpoint after Windows invalidates it
        self._stream_dead = False       # a live reply was stopped (barge-in / stop / device change): its rest is NOT spoken
        self._tts_warmup_timer = None
        if bool(self.settings.get("local_voice_tts", True)):
            # Let the window paint and the event loop settle before optional model warm-up.
            self._tts_warmup_timer = QTimer(self)
            self._tts_warmup_timer.setSingleShot(True)
            self._tts_warmup_timer.timeout.connect(self._warmup_local_tts)
            self._tts_warmup_timer.start(10000)

    def _warmup_local_tts(self):
        self._tts_warmup_timer = None
        if not bool(self.settings.get("local_voice_tts", True)):
            return
        try:
            from . import local_voice
            selected_tts = str(self.settings.get("local_voice_tts_model") or "").strip()

            def prepare_local_tts():
                # First-run setup (Piper package + default Mana voice) is intentionally
                # performed off the Qt thread. ensure_tts_ready stores diagnostics on failure.
                try:
                    local_voice.ensure_tts_ready(selected_tts)
                except Exception:
                    pass

            threading.Thread(
                target=prepare_local_tts,
                daemon=True,
                name="kira-tts-setup",
            ).start()
        except Exception:
            pass

    def _watch_devices(self):
        if self._devices is None:
            try:
                self._devices = QMediaDevices(self)
                self._devices.audioOutputsChanged.connect(self._on_devices_changed)
            except Exception:
                self._devices = None

    def _default_output(self):
        """The speaker Kira uses: the one chosen in the settings (if it is still connected), otherwise the Windows default."""
        try:
            wanted = "" if self._prefer_default_output else str(self.settings.get("output_device") or "").strip()
            if wanted:
                for dev in QMediaDevices.audioOutputs():
                    if dev.description() == wanted:
                        return dev
            device = QMediaDevices.defaultAudioOutput()
            if not device.isNull():
                return device
            # Some Windows audio backends report a null default briefly while
            # enumerated endpoints are already available (e.g. after a headset
            # reconnect). Use a real enumerated endpoint instead of silently
            # constructing an output with no device.
            outputs = QMediaDevices.audioOutputs()
            return outputs[0] if outputs else None
        except Exception:
            return None

    def _on_devices_changed(self):
        # Windows may invalidate an endpoint without removing its friendly name.
        # Prefer the system default after a device-change notification.
        self._prefer_default_output = True
        if self._fx is not None:
            self.error.emit("دستگاه خروجی صدا تغییر کرد؛ پخش فعلی متوقف شد و از خروجی پیش‌فرض ویندوز استفاده می‌شود.")
        self.stop()

    # ---- public ----
    def speak(self, text, rate=None, pitch=None, cache=False):
        """Speak a complete text (split into sentences). rate / pitch are added to the user's settings (per-area click voices)."""
        try:
            pieces = [c for c in (clean_for_speech(x) for x in split_sentences(text)) if c]
            if not pieces:
                return
            prosody = dict(self._prosody)
            self.stop()
            self._prosody = prosody
            sess = self._new_session(rate, pitch, cache)
            sess.sentences = pieces
            sess.input_done = True
            self._start_worker(sess)
        except Exception as e:                # a voice problem must never break the chat
            self._report(f"شروع صدا ناموفق بود: {type(e).__name__}: {e}")

    def stream_active(self):
        s = self._session
        return s is not None and not s.input_done

    def stream_text(self, full_text, final=False):
        """Speak a reply WHILE it is being written. `full_text` is the cleaned reply so far (it only grows); every sentence that is
        complete is queued at once, the unfinished tail waits. final=True also speaks the tail."""
        try:
            if self._stream_dead:
                return
            s = self._session
            if s is None or s.input_done:
                prosody = dict(self._prosody)
                self.stop()
                self._prosody = prosody
                s = self._new_session(None, None, False)
                s.streaming = True
            full_text = strip_think(full_text or "")
            delta = full_text[len(s.consumed):] if len(full_text) > len(s.consumed) else ""
            s.consumed = full_text if len(full_text) >= len(s.consumed) else s.consumed
            pieces = s.splitter.push(delta)
            if final:
                pieces += s.splitter.flush()
                s.input_done = True
            self._enqueue(s, pieces)
            if final:
                with s.cond:
                    s.cond.notify_all()
                self._pump()
        except Exception as e:
            self._report(f"شروع صدا ناموفق بود: {type(e).__name__}: {e}")

    def stream_reset(self):
        """A new reply starts with neutral prosody until its emotion tag is parsed."""
        self._stream_dead = False
        self.set_emotion((), 0)

    def set_emotion(self, emotions=(), intensity=None):
        """Bind parsed reply emotion to the current and upcoming sentence synthesis."""
        self._prosody = resolve_prosody(emotions, intensity)
        session = self._session
        if session is not None and session.streaming:
            # Share the lock used by synthesis when it snapshots a sentence profile.
            # Running synthesis remains consistent; queued sentences get the new emotion.
            with session.cond:
                session.prosody = dict(self._prosody)

    def stream_end(self):
        """The reply is complete: speak what is left, then finish."""
        if self._session is not None and not self._session.input_done:
            self.stream_text(self._session.consumed, final=True)

    def play_file(self, path):
        """Play a user-supplied audio file (wav / mp3 / ogg) with approximate lip-sync."""
        try:
            self.stop()
            sess = self._new_session(None, None, False, keep=True)
            sess.sentences = [""]
            sess.paths[0] = str(path)
            sess.input_done = True
            self._start_worker(sess)
        except Exception as e:
            self._report(f"پخش فایل صدا ناموفق بود: {type(e).__name__}: {e}")

    def _report(self, message):
        """Tell the UI about a voice problem without ever raising (the UI shows it at most once per 10 minutes)."""
        try:
            self.error.emit(message)
        except Exception:
            pass

    def _drop_player(self, fx, out):
        """Detach and release a player. Tolerates a C++ object that is already gone or a half-initialised player."""
        if fx is not None:
            # QObject destruction disconnects its signals. Avoid manually disconnecting
            # PySide bound slots after Qt may already have invalidated the wrapper.
            for call in ("stop", "deleteLater"):
                try:
                    getattr(fx, call)()
                except Exception:
                    pass
        if out is not None:
            try:
                out.deleteLater()
            except Exception:
                pass

    def stop(self):
        """Stop everything: the sentence that plays, the ones already made and the ones still being made. Safe to call any number
        of times, with nothing playing, and from inside a player signal.

        The player is taken out of `self._fx` BEFORE it is stopped: stopping a player may emit a state signal that
        calls stop() again, and the inner call used to set `self._fx = None` under the outer one (-> NoneType.deleteLater)."""
        self._gen += 1
        try:
            self._timer.stop()
        except Exception:
            pass
        sess, self._session = self._session, None
        if sess is not None:
            self.cancelled.emit()
        if sess is not None and sess.streaming and not sess.input_done:
            self._stream_dead = True                            # do not restart the same reply from the middle
        if sess is not None:
            with sess.cond:
                sess.cond.notify_all()                          # wakes the worker: it sees the new generation and exits
            for path, _env in list(sess.ready.values()):        # sentences that were made but never played
                self._remove_temp(path)
            sess.ready.clear()
        fx, out = self._fx, self._out
        self._fx = None
        self._out = None
        self._drop_player(fx, out)
        try:
            self._end()
        except Exception:
            pass

    # ---- sessions ----
    def _new_session(self, rate, pitch, cache, keep=False):
        self._gen += 1
        s = _Session(self._gen, int(rate or 0), int(pitch or 0), bool(cache), keep, self._prosody)
        self._session = s
        return s

    def _enqueue(self, s, pieces):
        pieces = [c for c in (clean_for_speech(x) for x in pieces) if c]
        if not pieces:
            return
        with s.cond:
            s.sentences.extend(pieces)
            s.cond.notify_all()
        self._start_worker(s)

    def _start_worker(self, s):
        with self._worker_lock:
            self._worker_threads = {
                worker for worker in self._worker_threads if worker.is_alive()
            }
            if s.worker is not None and s.worker.is_alive():
                return

            worker = threading.Thread(
                target=self._run_session,
                args=(s,),
                daemon=True,
                name=f"kira-tts-{s.gen}",
            )
            s.worker = worker
            self._worker_threads.add(worker)
            try:
                worker.start()
            except Exception:
                self._worker_threads.discard(worker)
                s.worker = None
                raise

    def is_idle(self):
        """Return True only after every synthesis thread has actually exited."""
        with self._worker_lock:
            self._worker_threads = {
                worker for worker in self._worker_threads if worker.is_alive()
            }
            return not self._worker_threads

    def _remove_temp(self, path):
        try:
            if path and path.startswith(self._tmp):
                os.remove(path)
        except OSError:
            pass

    # ---- worker thread: makes the sentences in order, never more than PREFETCH ahead of playback ----
    def _run_session(self, s):
        idx = 0
        try:
            while True:
                with s.cond:
                    while True:
                        if s.gen != self._gen:
                            return
                        if idx < len(s.sentences) and idx <= s.next_play + PREFETCH:
                            break
                        if s.input_done and idx >= len(s.sentences):
                            return
                        s.cond.wait(0.25)
                    text = s.sentences[idx]
                try:
                    result = (s.paths[idx], []) if idx in s.paths else self._synth(s, idx, text)
                except Exception as exc:
                    result = None
                    if s.gen == self._gen:
                        self._failed.emit(
                            s.gen, f"ساخت صدا ناموفق بود: {type(exc).__name__}: {exc}"
                        )
                if s.gen != self._gen:
                    if result:
                        self._remove_temp(result[0])
                    return
                self._ready.emit(
                    s.gen, idx, result[0] if result else "", result[1] if result else []
                )
                idx += 1
        finally:
            pass

    def _synth(self, s, idx, text):
        """Synthesize one sentence with emotion prosody, clause pauses and cache isolation."""
        from . import local_voice
        from .voice_prosody import expand_persian_numbers

        if self._use_kitten(text):
            return self._synth_kitten(s, idx, text)
        model_path = str(self.settings.get("local_voice_tts_model") or "").strip()
        if not bool(self.settings.get("local_voice_tts", True)):
            raise RuntimeError("استفاده از TTS محلی غیرفعال است؛ از بخش مدل‌های Local آن را فعال کن.")
        # The first response may arrive before the delayed background setup finishes.
        # Install only the runtime here; default voice download/load remains inside Piper's
        # synthesis worker, while an explicitly selected missing custom voice is reported.
        if not local_voice.tts_ready():
            local_voice.ensure_piper_runtime()
        if model_path and not local_voice.tts_ready(model_path):
            raise RuntimeError("مدل Piper انتخاب‌شده آماده نیست؛ فایل ONNX و فایل تنظیمات JSON آن را بررسی کن یا مدل پیش‌فرض را انتخاب کن.")

        spoken_text = expand_persian_numbers(local_voice.normalize_persian_tts_text(text))
        if not spoken_text:
            raise RuntimeError("متن قابل‌خواندن برای تولید صدا باقی نمانده است.")
        rate = max(-50, min(50, int(self.settings.get("voice_rate", 0)) + s.rate))
        with s.cond:
            prosody = dict(s.prosody or resolve_prosody())
        prosody["pitch_semitones"] = max(
            -0.55,
            min(0.55, float(prosody.get("pitch_semitones", 0.0)) + float(s.pitch or 0) * 0.03),
        )
        identity = local_voice.tts_cache_identity(model_path) if s.cache else model_path
        prosody_key = json.dumps(prosody, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        cache_key = hashlib.sha1(
            f"{_CACHE_VERSION}|{identity!r}|{rate}|{prosody_key}|leading-pause={int(idx > 0)}|{spoken_text}".encode("utf-8")
        ).hexdigest()[:20]
        tag = f"kira_{s.gen}_{idx}"
        base = str(CACHE_DIR) if s.cache else self._tmp
        wav_path = os.path.join(base, cache_key + ".wav")
        meta_path = os.path.join(base, cache_key + ".json")

        with _CACHE_LOCK:
            if s.cache and os.path.isfile(wav_path) and os.path.isfile(meta_path):
                envelope = _load_cached_audio(wav_path, meta_path)
                if envelope is not None:
                    return wav_path, envelope
                for stale in (wav_path, meta_path):
                    try:
                        os.remove(stale)
                    except OSError:
                        pass

            clauses = split_comma_clauses(spoken_text)
            audio_parts = []
            for clause_index, clause in enumerate(clauses):
                audio = local_voice.synthesize_persian(
                    clause, model_path, rate, prosody=prosody, postprocess=False
                )
                pause = prosody["pause_comma_ms"] if clause_index < len(clauses) - 1 else 0
                audio_parts.append((audio, pause))
            audio = join_wavs_with_pauses(audio_parts)
            # Put inter-sentence silence at the START of each subsequent sentence.
            # This avoids an unremovable trailing pause when a live stream ends
            # before another sentence arrives.
            if idx > 0:
                audio = prepend_wav_silence(audio, prosody["pause_sentence_ms"])
            try:
                audio = apply_audio_effects(audio, prosody)
            except Exception:
                self._report("پس‌پردازش اختیاری صدای احساسی انجام نشد؛ خروجی اصلی Piper حفظ شد.")
            return self._save_local_wav(tag, audio, s.cache, wav_path, meta_path)

    _ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")

    def _use_kitten(self, text):
        """KittenTTS is English-only: a sentence with Persian/Arabic letters always goes to Piper."""
        return (str(self.settings.get("tts_engine") or "piper").lower() == "kitten"
                and not self._ARABIC_SCRIPT.search(str(text)))

    def _synth_kitten(self, s, idx, text):
        """One English sentence with KittenTTS 2 (CPU ONNX); same file/envelope contract as the Piper path."""
        from . import kitten_tts
        model = str(self.settings.get("kitten_model") or "mini").lower()
        if not kitten_tts.runtime_installed():
            raise RuntimeError("KittenTTS نصب نیست؛ از تنظیمات صدا دکمه «نصب و تست KittenTTS» را بزن.")
        spoken = clean_for_speech(text)
        if not spoken:
            raise RuntimeError("متن قابل‌خواندن برای تولید صدا باقی نمانده است.")
        cache_key = hashlib.sha1(f"kitten|{model}|{idx > 0}|{spoken}".encode("utf-8")).hexdigest()[:20]
        base = str(CACHE_DIR) if s.cache else self._tmp
        wav_path = os.path.join(base, cache_key + ".wav")
        meta_path = os.path.join(base, cache_key + ".json")
        with _CACHE_LOCK:
            if s.cache and os.path.isfile(wav_path) and os.path.isfile(meta_path):
                envelope = _load_cached_audio(wav_path, meta_path)
                if envelope is not None:
                    return wav_path, envelope
            audio = kitten_tts.synthesize(spoken, model)
            if idx > 0:
                prosody = s.prosody or resolve_prosody()
                audio = prepend_wav_silence(audio, prosody["pause_sentence_ms"])
            return self._save_local_wav(f"kira_{s.gen}_{idx}", audio, s.cache, wav_path, meta_path)

    def _save_local_wav(self, tag, audio, cache, wav_path, meta_path):
        """Validate Piper WAV output, calculate lip-sync data, and publish cache atomically."""
        import numpy as np

        if not isinstance(audio, (bytes, bytearray)) or not bytes(audio).startswith(b"RIFF"):
            raise RuntimeError("مدل Piper خروجی WAV معتبر تولید نکرد.")
        payload = bytes(audio)
        try:
            with wave.open(io.BytesIO(payload), "rb") as wav:
                channels = max(1, int(wav.getnchannels()))
                sample_rate = int(wav.getframerate())
                frames = int(wav.getnframes())
                pcm = np.frombuffer(wav.readframes(frames), dtype=np.int16)
                if channels > 1:
                    pcm = pcm[::channels]
                if pcm.size == 0 or sample_rate <= 0 or frames <= 0:
                    raise RuntimeError("مدل Piper فایل صوتی خالی یا نامعتبر تولید کرد.")
                if pcm.size != frames:
                    raise RuntimeError("ساختار کانال‌های WAV با تعداد فریم‌ها سازگار نیست.")
                envelope = _envelope(pcm, sample_rate)
        except (OSError, wave.Error) as exc:
            raise RuntimeError(f"خواندن خروجی WAV ناموفق بود: {exc}") from exc

        path = wav_path if cache else os.path.join(self._tmp, f"{tag}.wav")
        if cache:
            _atomic_write(path, payload)
            metadata = {
                "version": 1,
                "wav_sha256": hashlib.sha256(payload).hexdigest(),
                "frames": frames,
                "sample_rate": sample_rate,
                "envelope": envelope,
            }
            _atomic_write(
                meta_path,
                json.dumps(metadata, separators=(",", ":"), allow_nan=False).encode("utf-8"),
            )
        else:
            with open(path, "wb") as stream:
                stream.write(payload)
        return path, envelope


    # ---- GUI thread ----
    @Slot(int, str)
    def _on_failed(self, gen, msg):
        if gen == self._gen:
            self.error.emit(msg)

    @Slot(int, int, str, list)
    def _on_ready(self, gen, idx, path, env):
        s = self._session
        if s is None or gen != self._gen or s.gen != gen:
            self._remove_temp(path)                                # an old reply: drop its audio
            return
        s.ready[idx] = (path or None, env)
        self._pump()

    def _advance(self, s):
        with s.cond:
            s.next_play += 1
            s.cond.notify_all()                                    # lets the worker make the next sentence

    def _pump(self):
        """Start the next sentence when the current one is over; finish the reply when nothing is left."""
        try:
            while True:
                s = self._session
                if s is None or s.playing:
                    return
                if s.next_play in s.ready:
                    path, env = s.ready.pop(s.next_play)
                    if not path:                                   # this sentence could not be made: skip it
                        self._advance(s)
                        continue
                    s.playing = True
                    self._start_playback(s, path, env)
                    return
                if s.input_done and s.next_play >= len(s.sentences):
                    self._session = None
                    self._end()                                    # emits finished once for the whole reply
                return
        except Exception as e:
            self.stop()
            self._report(f"پخش صدا ناموفق بود: {type(e).__name__}: {e}")

    def _start_playback(self, s, wav, env):
        """Play one made sentence through QAudioSink on the chosen (or default) output device."""
        self._wav, self._env, self._item_began = wav, env, False
        self._keep = s.keep or not wav.startswith(self._tmp)
        self._watch_devices()
        if not str(wav).lower().endswith(".wav"):
            self._on_player_failed(None, "فقط فایل WAV پشتیبانی می‌شود (mp3 و ogg دیگر پخش نمی‌شوند).")
            return
        device = self._default_output()
        if device is None:
            self._on_player_failed(None, "هیچ دستگاه خروجی صدایی در ویندوز در دسترس نیست.")
            return
        try:
            volume = float(self.settings.get("voice_volume", 0.9))
        except (TypeError, ValueError):
            volume = 0.9
        try:
            player = _PcmPlayer(wav, device, volume, self)
        except Exception as exc:
            self._on_player_failed(None, f"{type(exc).__name__}: {exc}")
            return
        self._out = None
        self._fx = player
        player.playingChanged.connect(self._on_playing)
        player.failed.connect(lambda message, p=player: self._on_player_failed(p, message))
        player.start()
        if self._fx is not player:
            return
        # Safety nets: a sentence that never becomes audible is skipped, and one that never reports its end is closed.
        QTimer.singleShot(PLAYBACK_START_TIMEOUT_MS, lambda p=player: self._on_player_failed(p, "پخش صدا شروع نشد."))
        QTimer.singleShot(player.duration_ms + 1500, lambda p=player: self._on_playing_end(p))

    def _on_playing_end(self, player):
        if player is self._fx and self._item_began:
            self._item_finished()

    def _on_player_failed(self, player, message=""):
        """The sentence that should be playing never started (or failed): report it and go on with the next one."""
        if player is not self._fx or self._item_began:
            return
        self._report(f"پخش صدا ناموفق بود: {message or 'خطای پخش'}")
        self._item_finished()

    def _item_started(self):
        self._item_began = True
        self._clock.start()
        self._timer.start()
        if not self._began:
            self._began = True
            self.started.emit()

    def _item_finished(self):
        """The sentence that was playing is over: release it and go on with the next (or finish the reply)."""
        s = self._session
        fx, out = self._fx, self._out
        self._fx = None
        self._out = None
        self._item_began = False
        try:
            self._timer.stop()
        except Exception:
            pass
        self._drop_player(fx, out)
        self.level.emit(0.0)
        if self._wav and not self._keep:
            self._remove_temp(self._wav)
        self._wav = None
        if s is not None and s is self._session:
            s.playing = False
            self._advance(s)
            self._pump()

    def _on_playing(self, playing: bool | None = None):
        # PySide/Qt builds differ: playingChanged may invoke Python slots with
        # the bool argument or with no arguments. Support both signal signatures.
        fx = self._fx
        if fx is None:
            return
        if playing is None:
            try:
                playing = bool(fx.isPlaying())
            except (AttributeError, RuntimeError):
                return
        if playing:
            if not self._item_began:
                self._item_started()
        elif self._item_began:
            self._item_finished()

    def _tick(self):
        i = self._clock.elapsed() // HOP_MS
        if not self._env:
            t = self._clock.elapsed() / 1000.0
            self.level.emit(abs(math.sin(t * 11)) * 0.6 * (0.6 + 0.4 * math.sin(t * 3.1)) + 0.1)
        else:
            self.level.emit(self._env[i] if i < len(self._env) else 0.0)

    def _end(self):
        self._prosody = resolve_prosody()
        if self._began:
            self._began = False
            self.level.emit(0.0)
            self.finished.emit()
        if self._wav and not self._keep:
            self._remove_temp(self._wav)
            self._wav = None
