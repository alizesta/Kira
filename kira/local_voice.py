"""Offline speech engines used by Kira. No network recognition or synthesis fallback lives here.

ASR: Shenava Koochik INT8/FP32 only.
TTS: Piper ONNX or the bundled Persian Piper runtime.
"""
from __future__ import annotations

import gc
import io
import os
import subprocess
import re
import unicodedata
import threading
import time
import wave
from pathlib import Path

# Keep model/runtime caches beside Kira's persistent data, not on C: or
# inside the replaceable application folder.
from .storage import configure_cache_environment, default_data_dir
from .voice_prosody import apply_audio_effects, expand_persian_numbers, resolve_prosody

_DATA_ROOT = default_data_dir(Path(__file__).resolve().parents[1])
configure_cache_environment(_DATA_ROOT)

_asr_lock = threading.RLock()
_tts_lock = threading.RLock()
_piper_setup_lock = threading.Lock()
_shenava_recognizer = None
_shenava_model_path = ""
_shenava_error = None
SHENAVA_INT8_REPO_ID = "SajjadMajdi/shenava-koochik-fa-int8"
SHENAVA_FP32_REPO_ID = "Reza2kn/Shenava-Koochik-v1.0-sherpa-onnx"
# Keep the original names as aliases so older settings and integrations remain compatible.
SHENAVA_REPO_ID = SHENAVA_INT8_REPO_ID
SHENAVA_MODEL_FILENAME = "model.int8.onnx"
SHENAVA_MODEL_FILENAMES = {
    SHENAVA_INT8_REPO_ID: SHENAVA_MODEL_FILENAME,
    SHENAVA_FP32_REPO_ID: "model.onnx",
}
SHENAVA_MODEL_SIZES_MB = {
    SHENAVA_INT8_REPO_ID: 126,
    SHENAVA_FP32_REPO_ID: 459,
}
SHENAVA_SAMPLE_RATE = 16000
_tts = None  # Keep only the currently selected voice in memory.
_tts_model_path = ""
_tts_model_label = ""
_tts_model_signature = None
_tts_error = None


def asr_ready() -> bool:
    return shenava_ready()


_PERSIAN_TTS_TRANSLATION = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
    "ـ": None,
    "\u200b": None,
    "\u200d": None,
    "\u200e": None,
    "\u200f": None,
    "\u202a": None,
    "\u202b": None,
    "\u202c": None,
    "\u202d": None,
    "\u202e": None,
    "\u2066": None,
    "\u2067": None,
    "\u2068": None,
    "\u2069": None,
})

_PERSIAN_TTS_TERMS = {
    "chatgpt": "چت‌جی‌پی‌تی",
    "kira": "کیرا",
    "gemini": "جِمِنای",
    "ollama": "اُلاما",
    "elevenlabs": "اِلِوِن‌لَبز",
    "openai": "اوپن‌ای‌آی",
    "deepseek": "دیپ‌سیک",
    "vulkan": "وولکان",
    "openrouter": "اوپن‌روتر",
    "cloudflare": "کلادفلر",
    "mistral": "میسترال",
    "grok": "گراک",
    "claude": "کلود",
    "codex": "کُدِکس",
    "opencode": "اوپن‌کُد",
    "ffmpeg": "اِف‌اِف‌اِم‌پِگ",
    "onnx": "اُن‌اِن‌اِکس",
    "wav": "وَو",
    "mp3": "اِم‌پی‌تری",
    "fps": "اِف‌پی‌اِس",
    "piper": "پایپر",
    "python": "پایتون",
    "windows": "ویندوز",
    "linux": "لینوکس",
    "wi-fi": "وای‌فای",
    "gpu": "جی‌پی‌یو",
    "cpu": "سی‌پی‌یو",
    "ram": "رَم",
    "vram": "وی‌رَم",
    "api": "اِی‌پی‌آی",
    "asr": "اِی‌اِس‌آر",
    "stt": "اِس‌تی‌تی",
    "tts": "تی‌تی‌اِس",
    "llm": "اِل‌اِل‌اِم",
    "json": "جِی‌سان",
    "gui": "جی‌یو‌آی",
    "ui": "یو‌آی",
    "usb": "یو‌اِس‌بی",
    "ssd": "اِس‌اِس‌دی",
    "amd": "اِی‌اِم‌دی",
}

_PERSIAN_TTS_TERM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(
        re.escape(term) for term in sorted(_PERSIAN_TTS_TERMS, key=len, reverse=True)
    ) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def normalize_persian_tts_text(text: str) -> str:
    """Normalize Persian text and pronounce common technical names before local synthesis."""
    value = unicodedata.normalize("NFC", str(text or "")).translate(_PERSIAN_TTS_TRANSLATION)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t\u00a0\u2009]+", " ", value)
    value = re.sub(r"\s*\u200c\s*", "\u200c", value)
    value = re.sub(r"(?<!\S)(ن?می)\s+([آ-ی])", r"\1‌\2", value)
    value = re.sub(
        r"(?<=[آ-ی])\s+(ها|های|هایی|تر|ترین)(?=$|[\s،؛؟.!,:;])",
        r"‌\1",
        value,
    )
    if re.search(r"[\u0600-\u06ff]", value):
        value = _PERSIAN_TTS_TERM_PATTERN.sub(
            lambda match: _PERSIAN_TTS_TERMS[match.group(0).casefold()],
            value,
        )
        value = re.sub(r"(?<!\d),(?!\d)", "،", value)
        value = value.replace(";", "؛").replace("?", "؟")
    value = re.sub(r"\s+([،؛؟!,:;])", r"\1", value)
    value = re.sub(r"([،؛؟!])(?=\S)", r"\1 ", value)
    return re.sub(r" {2,}", " ", value).strip()


def tts_ready(model_path="") -> bool:
    """Check the local Piper runtime and, for custom voices, the selected ONNX file."""
    if model_path:
        path = Path(str(model_path)).expanduser()
        if not path.is_file() or path.suffix.lower() != ".onnx":
            return False
        if not Path(str(path) + ".json").is_file():
            return False
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_piper_runtime(cancel_event=None) -> bool:
    """Install Piper into Kira's active environment on demand, exactly once.

    The installer uses the project's pinned dependency constraints and verifies
    the resulting environment with pip check. This function is safe to call from
    the background warm-up and from the first synthesis request concurrently.
    """
    global _tts_error
    if tts_ready():
        return True
    with _piper_setup_lock:
        if tts_ready():
            return True
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("نصب Piper به‌دلیل لغو عملیات متوقف شد.")
        try:
            _install_voice_package("piper-tts>=1.3.0,<2", cancel_event)
            if not tts_ready():
                raise RuntimeError("Piper پس از نصب در محیط فعال Python قابل بارگذاری نیست.")
            _tts_error = None
            return True
        except Exception as exc:
            _tts_error = exc
            raise RuntimeError(f"نصب خودکار موتور Piper ناموفق بود: {type(exc).__name__}: {exc}") from exc

def _resolve_shenava_model_files(model_path=""):
    """Resolve either supported Shenava HF variant, a snapshot folder, or a direct ONNX file."""
    selected = str(model_path or SHENAVA_REPO_ID).strip()
    candidate = Path(selected).expanduser()
    expected_filename = SHENAVA_MODEL_FILENAMES.get(selected)
    if not candidate.exists() and expected_filename is None:
        raise ValueError(f"مخزن شنوا پشتیبانی نمی‌شود: {selected}")

    if candidate.is_file():
        model_file = candidate
        snapshot = candidate.parent
    elif candidate.is_dir():
        snapshot = candidate
        names = (expected_filename, SHENAVA_MODEL_FILENAME, "model.onnx")
        model_file = next(
            (snapshot / name for name in dict.fromkeys(name for name in names if name)
             if (snapshot / name).is_file()),
            snapshot / (expected_filename or SHENAVA_MODEL_FILENAME),
        )
    else:
        repo_dir = selected.replace("/", "--")
        hub_root = Path(
            os.environ.get("HF_HUB_CACHE")
            or (Path(_DATA_ROOT) / "huggingface" / "hub")
        )
        snapshots = hub_root / f"models--{repo_dir}" / "snapshots"
        choices = []
        try:
            choices = [item for item in snapshots.iterdir() if item.is_dir()]
        except OSError:
            choices = []
        choices.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        snapshot = next(
            (item for item in choices
             if (item / expected_filename).is_file() and (item / "tokens.txt").is_file()),
            None,
        )
        if snapshot is None:
            raise RuntimeError(
                "فایل‌های شنوا در کش پیدا نشد؛ ابتدا نسخهٔ انتخاب‌شده را دانلود کن."
            )
        model_file = snapshot / expected_filename

    tokens_file = snapshot / "tokens.txt"
    if not model_file.is_file() or not tokens_file.is_file():
        raise RuntimeError(
            f"فایل مدل یا tokens.txt شنوا ناقص است: {snapshot}"
        )
    return model_file, tokens_file


def shenava_ready() -> bool:
    """Check whether the optional sherpa-onnx runtime is installed."""
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def load_shenava(model_path=""):
    """Load the selected Persian Shenava CTC model (INT8 or FP32) on CPU."""

    global _shenava_recognizer, _shenava_model_path, _shenava_error
    model_file, tokens_file = _resolve_shenava_model_files(model_path)
    selected = str(model_file)
    with _asr_lock:
        if _shenava_recognizer is not None and _shenava_model_path == selected:
            return True
        try:
            import gc
            import sherpa_onnx

            # Release any previously held recognizer before loading Shenava.
            try:
                threads = max(1, min(8, int(os.environ.get("KIRA_ASR_THREADS", "4"))))
            except (TypeError, ValueError):
                threads = 4
            old_recognizer, _shenava_recognizer = _shenava_recognizer, None
            _shenava_model_path = ""
            if old_recognizer is not None:
                del old_recognizer
                gc.collect()

            _shenava_recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=str(model_file),
                tokens=str(tokens_file),
                num_threads=threads,
                sample_rate=SHENAVA_SAMPLE_RATE,
                feature_dim=80,
                provider="cpu",
                debug=False,
            )
            _shenava_model_path = selected
            _shenava_error = None
        except Exception as exc:
            _shenava_recognizer = None
            _shenava_model_path = ""
            _shenava_error = exc
            raise RuntimeError(
                f"بارگذاری شنوا ناموفق بود: {type(exc).__name__}: {exc}"
            ) from exc
    return True


def _resample_mono_float32(audio, sample_rate, target_rate=SHENAVA_SAMPLE_RATE):
    """Normalize mono audio and linearly resample it to Shenava's 16 kHz input."""
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    if samples.size == 0:
        return samples
    source_rate = int(sample_rate or target_rate)
    if source_rate <= 0:
        raise ValueError("نرخ نمونه‌برداری فایل صوتی معتبر نیست.")
    if source_rate != target_rate:
        count = max(1, int(round(samples.size * target_rate / source_rate)))
        old_positions = np.arange(samples.size, dtype=np.float64)
        new_positions = np.arange(count, dtype=np.float64) * source_rate / target_rate
        samples = np.interp(new_positions, old_positions, samples).astype(np.float32)
    return np.clip(samples, -1.0, 1.0)


def unload_shenava():
    """Release the active recognizer and clear its model identity."""
    import gc

    global _shenava_recognizer, _shenava_model_path, _shenava_error
    with _asr_lock:
        previous, _shenava_recognizer = _shenava_recognizer, None
        _shenava_model_path = ""
        _shenava_error = None
        if previous is not None:
            try:
                close = getattr(previous, "close", None)
                if callable(close):
                    close()
            finally:
                del previous
                gc.collect()


def transcribe_shenava(audio, sample_rate=SHENAVA_SAMPLE_RATE, model_path=""):
    """Transcribe one mono audio segment locally with the selected Shenava model."""
    import numpy as np

    samples = _resample_mono_float32(audio, sample_rate)
    if samples.size == 0:
        return ""
    load_shenava(model_path)
    with _asr_lock:
        stream = _shenava_recognizer.create_stream()
        stream.accept_waveform(SHENAVA_SAMPLE_RATE, np.ascontiguousarray(samples))
        _shenava_recognizer.decode_stream(stream)
        result = stream.result
        return str(getattr(result, "text", "") or "").strip()


def read_pcm_wav(path, target_rate=SHENAVA_SAMPLE_RATE):
    """Read an uncompressed PCM WAV, convert channels to mono, and resample it."""
    import numpy as np

    try:
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise ValueError("فقط فایل WAV بدون فشرده‌سازی پشتیبانی می‌شود.")
            channels = int(wav_file.getnchannels())
            width = int(wav_file.getsampwidth())
            rate = int(wav_file.getframerate())
            frames = int(wav_file.getnframes())
            if channels < 1 or rate < 1 or frames < 1:
                raise ValueError("فایل WAV خالی یا دارای مشخصات نامعتبر است.")
            if frames / rate > 600:
                raise ValueError("برای آزمایش مدل، فایل WAV باید حداکثر ۱۰ دقیقه باشد.")
            payload = wav_file.readframes(frames)
    except (OSError, wave.Error) as exc:
        raise ValueError(f"خواندن فایل WAV ناموفق بود: {exc}") from exc

    if width == 1:
        pcm = np.frombuffer(payload, dtype=np.uint8).astype(np.float32)
        samples = (pcm - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        raw = np.frombuffer(payload, dtype=np.uint8)
        if raw.size % 3:
            raise ValueError("داده‌ی WAV بیست‌وچهاربیتی ناقص است.")
        raw = raw.reshape(-1, 3).astype(np.int32)
        pcm = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        pcm = (pcm ^ 0x800000) - 0x800000
        samples = pcm.astype(np.float32) / 8388608.0
    elif width == 4:
        samples = np.frombuffer(payload, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"عمق نمونه‌ی {width * 8} بیتی WAV پشتیبانی نمی‌شود.")

    if samples.size % channels:
        raise ValueError("تعداد نمونه‌های WAV با تعداد کانال‌ها سازگار نیست.")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return _resample_mono_float32(samples, rate, target_rate)


def transcribe_shenava_file(path, model_path=""):
    """Transcribe a local PCM WAV file for offline model testing (no microphone required)."""
    samples = read_pcm_wav(path)
    return transcribe_shenava(samples, SHENAVA_SAMPLE_RATE, model_path=model_path)


def install_and_download_shenava_asr(repo_id=SHENAVA_REPO_ID, *, cancel_event=None):
    """Install sherpa-onnx and download only the selected Shenava model and its required assets."""
    selected = str(repo_id or SHENAVA_REPO_ID).strip()
    model_filename = SHENAVA_MODEL_FILENAMES.get(selected)
    if not model_filename:
        raise ValueError(f"مخزن شنوا پشتیبانی نمی‌شود: {selected}")
    if not shenava_ready():
        _install_voice_package("sherpa-onnx>=2.0.2,<3", cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("دانلود شنوا به‌دلیل خروج برنامه لغو شد.")
    from huggingface_hub import snapshot_download

    cache_dir = os.environ.get("HF_HUB_CACHE") or str(Path(_DATA_ROOT) / "huggingface" / "hub")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    allow_patterns = [
        model_filename,
        "tokens.txt",
        "README.md",
        "*.json",
    ]
    try:
        snapshot = snapshot_download(
            repo_id=selected,
            cache_dir=cache_dir,
            allow_patterns=allow_patterns,
            local_files_only=True,
        )
    except Exception:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("دانلود شنوا به‌دلیل خروج برنامه لغو شد.")
        snapshot = snapshot_download(
            repo_id=selected,
            cache_dir=cache_dir,
            allow_patterns=allow_patterns,
            local_files_only=False,
        )
    _resolve_shenava_model_files(snapshot)
    return str(Path(snapshot).absolute())


def _resolve_tts_model_path(model_path="") -> tuple[Path, str]:
    """Resolve either the selected Piper ONNX file or Kira's bundled Mana model.

    Keep the Hugging Face snapshot path (do not resolve its Windows symlink); Piper
    can fail to open a resolved blob target on Windows.
    """
    selected = str(model_path or "").strip()
    if selected:
        path = Path(selected).expanduser().absolute()
        if not path.is_file() or path.suffix.lower() != ".onnx":
            raise RuntimeError(f"Custom Piper model does not exist: {path}")
        if not Path(str(path) + ".json").is_file():
            raise RuntimeError(f"Custom Piper model configuration is missing: {path}.json")
        return path, str(path)

    repo_id = "MahtaFetrat/Mana-Persian-Piper"
    filename = "fa_IR-mana-medium.onnx"
    cache_dir = os.environ.get("HF_HUB_CACHE") or str(Path(_DATA_ROOT) / "huggingface" / "hub")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("برای صدای پیش‌فرض Mana به huggingface_hub نیاز است.") from exc

    # Reuse the model already prepared by Kira when offline; download only when
    # the snapshot is genuinely absent or incomplete.
    try:
        snapshot = snapshot_download(repo_id=repo_id, cache_dir=cache_dir, local_files_only=True)
    except Exception:
        snapshot = snapshot_download(repo_id=repo_id, cache_dir=cache_dir, local_files_only=False)
    path = Path(snapshot) / filename
    if not path.is_file():
        raise RuntimeError(f"مدل پیش‌فرض Mana در snapshot پیدا نشد: {path}")
    if not Path(str(path) + ".json").is_file():
        raise RuntimeError(f"فایل پیکربندی مدل Mana پیدا نشد: {path}.json")
    return path, "bundled"


def _file_signature(path: Path):
    try:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except OSError:
        # Tests and some virtual filesystems may not expose stat metadata.
        return (None, None, None)


def _model_file_signature(path: Path):
    """Invalidate the active voice when the ONNX weights or Piper sidecar change."""
    sidecar = Path(str(path) + ".json")
    return (str(path), _file_signature(path), _file_signature(sidecar))


def tts_cache_identity(model_path=""):
    """Return a stable cache identity that changes with model weights or voice metadata."""
    if not model_path and _tts is not None and _tts_model_path:
        path = Path(_tts_model_path)
    else:
        path, _label = _resolve_tts_model_path(model_path)
    return _model_file_signature(path)


def _is_memory_pressure(exc: BaseException) -> bool:
    message = str(exc).casefold()
    return isinstance(exc, MemoryError) or any(
        token in message
        for token in ("out of memory", "memory allocation", "not enough memory", "failed to allocate",
                      "cannot allocate memory", "bad_alloc", "not enough system resources")
    )


def _load_tts_voice(model_path=""):
    """Load one active Piper voice, retrying memory-starved switches without retaining two models."""
    global _tts, _tts_model_path, _tts_model_label, _tts_model_signature, _tts_error
    path, label = _resolve_tts_model_path(model_path)
    key = str(path)
    signature = _model_file_signature(path)
    if _tts is not None and _tts_model_path == key and _tts_model_signature == signature:
        return _tts

    from piper import PiperVoice
    previous = (_tts, _tts_model_path, _tts_model_label, _tts_model_signature)
    previous_path, previous_label, previous_signature = previous[1], previous[2], previous[3]
    try:
        voice = PiperVoice.load(str(path))
    except Exception as first_error:
        if previous[0] is None or not _is_memory_pressure(first_error):
            raise

        # Keep the previous voice on ordinary load failures. Only a memory-pressure
        # failure justifies releasing it and retrying the requested model.
        _tts = None
        _tts_model_path = ""
        _tts_model_label = ""
        _tts_model_signature = None
        del previous
        gc.collect()
        try:
            voice = PiperVoice.load(str(path))
        except Exception as retry_error:
            # Best-effort restoration preserves the old voice whenever its source
            # file is still available. The original failure is retained as context.
            try:
                if not previous_path:
                    raise RuntimeError("Previous voice path is unavailable")
                restored = PiperVoice.load(str(previous_path))
            except Exception as restore_error:
                _tts_error = RuntimeError(
                    f"Voice switch ran out of memory and previous voice could not be restored: {restore_error}"
                )
                raise RuntimeError(
                    f"Voice switch failed after memory recovery attempt: {retry_error}"
                ) from first_error
            _tts = restored
            _tts_model_path = previous_path
            _tts_model_label = previous_label
            _tts_model_signature = previous_signature
            raise RuntimeError(
                f"Voice switch failed after releasing previous model; previous voice restored: {retry_error}"
            ) from first_error

    _tts = voice
    _tts_model_path = key
    _tts_model_label = label
    _tts_model_signature = signature
    _tts_error = None
    return voice


def preload_tts(model_path="") -> bool:
    """Load the selected local Piper ONNX voice before the first spoken response."""
    global _tts_error
    try:
        with _tts_lock:
            _load_tts_voice(model_path)
            _tts_error = None
        return True
    except Exception as exc:
        _tts_error = exc
        raise RuntimeError(f"Piper preload failed: {type(exc).__name__}: {exc}") from exc


def warmup_tts(model_path="") -> bool:
    """Warm Piper and the optional Persian ezafe detector without making either failure fatal."""
    global _tts_error
    try:
        ready = bool(preload_tts(model_path))
    except Exception as exc:
        _tts_error = exc
        return False

    # ALBERT is optional and runs independently of Piper. A missing model or
    # unavailable network must never disable the working TTS engine.
    try:
        from . import persian_ezafe
        persian_ezafe.warmup()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Optional Persian ezafe warmup failed")
    return ready


def ensure_tts_ready(model_path="", cancel_event=None) -> bool:
    """Install Piper if needed, load the selected/default Persian voice and warm it up."""
    global _tts_error
    ensure_piper_runtime(cancel_event=cancel_event)
    selected = str(model_path or "").strip()
    if selected:
        path = Path(selected).expanduser()
        if not path.is_file() or path.suffix.lower() != ".onnx":
            raise RuntimeError(f"مدل Piper انتخاب‌شده وجود ندارد یا ONNX نیست: {path}")
        if not Path(str(path) + ".json").is_file():
            raise RuntimeError(f"فایل تنظیمات مدل Piper پیدا نشد: {path}.json")
    if not warmup_tts(selected):
        detail = str(_tts_error) if _tts_error else "علت مشخصی گزارش نشد."
        raise RuntimeError(f"آماده‌سازی صدای محلی Piper ناموفق بود: {detail}")
    return True

def synthesize_persian(text: str, model_path="", rate=0, prosody=None, postprocess=True) -> bytes:
    """Synthesize Persian speech with Piper's native timing controls.

    Piper's length_scale changes phoneme duration directly. Altering only the WAV
    sample-rate header changes both speed and pitch, so the active voice now uses
    the same native synthesis path for Mana and user-selected ONNX models.
    """
    global _tts_error
    clean = expand_persian_numbers(normalize_persian_tts_text(text))
    if not clean:
        return b""

    # Insert context-predicted Persian ezafe marks before Piper phonemization.
    # The detector has its own lazy ONNX cache and safely returns the source
    # text unchanged whenever it is disabled or unavailable.
    if re.search(r"[\u0600-\u06ff]", clean):
        try:
            from .persian_ezafe import add_persian_ezafe
            clean = add_persian_ezafe(clean)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Optional Persian ezafe preprocessing failed; using normalized source text"
            )

    selected = str(model_path or "").strip()
    speed = max(0.5, min(1.5, 1.0 + float(rate or 0) / 100.0))
    profile = resolve_prosody() if prosody is None else dict(prosody)
    length_scale = max(0.5, min(1.5, float(profile.get("length_scale", 1.0)) / speed))
    noise_scale = max(0.5, min(0.9, float(profile.get("noise_scale", 0.667))))
    noise_w = max(0.6, min(0.95, float(profile.get("noise_w", 0.8))))

    try:
        with _tts_lock:
            voice = _load_tts_voice(selected)
            from piper import SynthesisConfig

            output = io.BytesIO()
            config = SynthesisConfig(
                length_scale=length_scale,
                noise_scale=noise_scale,
                noise_w_scale=noise_w,
            )
            with wave.open(output, "wb") as wav_file:
                voice.synthesize_wav(clean, wav_file, syn_config=config)
            payload = output.getvalue()
            _tts_error = None
    except Exception as exc:
        _tts_error = exc
        model_label = selected or "Mana Persian Piper"
        raise RuntimeError(
            f"Piper synthesis failed for {model_label}: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(payload, (bytes, bytearray)) or not payload.startswith(b"RIFF"):
        raise RuntimeError("Persian Piper returned invalid WAV data")
    if not postprocess:
        return bytes(payload)
    try:
        return apply_audio_effects(bytes(payload), profile)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Optional emotional audio post-processing failed; using native Piper audio")
        return bytes(payload)


def _terminate_process_tree(process) -> None:
    """Stop an installer and its descendants without opening a Windows console."""
    if process.poll() is None and os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=5, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
                process.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass


def _run_install_command(command, *, timeout: float, cancel_event=None):
    """Run pip invisibly on Windows and terminate it promptly when UI shutdown requests cancellation."""
    import subprocess

    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("عملیات نصب موتور صوتی لغو شد.")
    options = {}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **options,
    )
    deadline = time.monotonic() + float(timeout)
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_process_tree(process)
            raise RuntimeError("عملیات نصب موتور صوتی به‌دلیل خروج برنامه لغو شد.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_tree(process)
            raise subprocess.TimeoutExpired(command, timeout)
        try:
            stdout, stderr = process.communicate(timeout=min(0.25, remaining))
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def _dependency_constraint_args(*filenames: str) -> list[str]:
    """Build pip constraint arguments from the shared, shipped dependency contracts."""
    root = Path(__file__).resolve().parents[1]
    selected = filenames or ("constraints.txt", "constraints-voice.txt")
    args = []
    for filename in selected:
        path = root / filename
        if not path.is_file():
            raise RuntimeError(f"فایل محدودیت وابستگی پیدا نشد: {path}")
        args.extend(["--constraint", str(path)])
    return args


def _run_dependency_install(
    requirements,
    *,
    extra_args=(),
    constraints_files=("constraints.txt", "constraints-voice.txt"),
    timeout=3600,
    cancel_event=None,
    check=True,
):
    """Resolve a complete optional voice graph before installing it, then verify pip's environment."""
    import sys
    import tempfile

    constraints = _dependency_constraint_args(*constraints_files)
    base = [
        sys.executable, "-m", "pip", "install",
        "--retries", "5", "--timeout", "60",
        *constraints,
    ]
    requested = [str(item) for item in requirements]
    options = [str(item) for item in extra_args]

    with tempfile.TemporaryDirectory(prefix="kira-voice-resolution-") as temp_dir:
        report = str(Path(temp_dir) / "resolution.json")
        preflight = _run_install_command(
            [*base, "--dry-run", "--report", report, *options, *requested],
            timeout=timeout,
            cancel_event=cancel_event,
        )
        if preflight.returncode:
            detail = (preflight.stderr or preflight.stdout or "dependency resolution failed")[-3500:]
            raise RuntimeError(f"حل تعارض وابستگی‌های صوتی ناموفق بود: {detail}")

        result = _run_install_command(
            [*base, *options, *requested],
            timeout=timeout,
            cancel_event=cancel_event,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or "pip installation failed")[-3500:]
            raise RuntimeError(f"نصب وابستگی‌های صوتی ناموفق بود: {detail}")

        if check:
            checked = _run_install_command(
                [sys.executable, "-m", "pip", "check"],
                timeout=min(180, timeout),
                cancel_event=cancel_event,
            )
            if checked.returncode:
                detail = (checked.stdout or checked.stderr or "pip check failed")[-3500:]
                raise RuntimeError(f"پس از نصب، ناسازگاری وابستگی‌ها شناسایی شد: {detail}")

    return result


def _ensure_pillow_compatible(cancel_event=None) -> None:
    """Force Gradio-compatible Pillow into Kira's active Python and verify it."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("Pillow")
    except PackageNotFoundError:
        installed = ""

    try:
        if installed and int(installed.split(".", 1)[0]) < 13:
            return
    except (TypeError, ValueError):
        pass

    # Repair only Pillow, but resolve its chosen version against shared constraints.
    _run_dependency_install(
        ["Pillow>=8,<13"],
        extra_args=("--force-reinstall", "--no-deps"),
        timeout=1800,
        cancel_event=cancel_event,
    )

    try:
        fixed = version("Pillow")
        if int(fixed.split(".", 1)[0]) >= 13:
            raise RuntimeError(f"نسخه ناسازگار Pillow هنوز نصب است: {fixed}")
    except PackageNotFoundError as exc:
        raise RuntimeError("پس از نصب، Pillow در محیط پایتون Kira پیدا نشد.") from exc


def _install_voice_package(package: str, cancel_event=None) -> None:
    """Install a voice runtime, then enforce Gradio's Pillow<13 requirement."""
    # Apply both the shared core pins and the voice-specific Hugging Face/Pillow
    # constraints before touching the active environment.
    _run_dependency_install([package], timeout=3600, cancel_event=cancel_event)
    _ensure_pillow_compatible(cancel_event)


def _download_voice_repo(repo_id: str) -> str:
    from huggingface_hub import snapshot_download

    selected = str(repo_id or "").strip()
    if "/" not in selected or "\\" in selected:
        raise ValueError("شناسه مدل باید به شکل owner/repository باشد.")
    cache_dir = os.environ.get("HF_HUB_CACHE") or str(Path(_DATA_ROOT) / "huggingface" / "hub")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    return str(Path(snapshot_download(
        repo_id=selected, cache_dir=cache_dir, local_files_only=False,
    )).resolve())


def install_and_download_piper_voice(repo_id: str, *, cancel_event=None) -> str:
    """Install Piper runtime and download a Piper ONNX voice."""
    _ensure_pillow_compatible(cancel_event)
    try:
        import piper  # noqa: F401
    except ImportError:
        _install_voice_package("piper-tts>=1.3.0,<2", cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("دانلود مدل به‌دلیل خروج برنامه لغو شد.")
    return _download_voice_repo(repo_id)



def download_hf_model(repo_id: str) -> str:
    """Download a public speech model into Kira's configured Hugging Face cache."""
    return _download_voice_repo(repo_id)


def cache_directory() -> str:
    """Return the exact directory where Hugging Face model snapshots are stored."""
    return str(Path(os.environ.get("HF_HUB_CACHE") or (Path(_DATA_ROOT) / "huggingface" / "hub")).resolve())


def status(model_path="") -> dict:
    """Small diagnostic snapshot; does not load either model."""
    return {
        "asr_installed": asr_ready(),
        "shenava_installed": shenava_ready(),
        "shenava_loaded": _shenava_recognizer is not None,
        "shenava_model": _shenava_model_path,
        "shenava_error": str(_shenava_error)[:240] if _shenava_error else "",
        "tts_installed": tts_ready(model_path),
        "tts_loaded": _tts is not None,
        "tts_model": _tts_model_label if _tts is not None else "",
        "tts_error": str(_tts_error)[:240] if _tts_error else "",
        "tts_model_signature": _tts_model_signature,
        "tts_ezafe": _ezafe_status(),
    }


def _ezafe_status() -> dict:
    """Expose optional ezafe availability and retry diagnostics to voice settings."""
    try:
        from . import persian_ezafe
        return persian_ezafe.status()
    except Exception as exc:
        return {"enabled": True, "loaded": False, "error": f"{type(exc).__name__}: {exc}"[:240]}

def discover_cached_models() -> dict:
    """Find supported Shenava ASR snapshots and Piper ONNX voices without downloading."""
    data_root = Path(_DATA_ROOT)
    hub_root = Path(os.environ.get("HF_HUB_CACHE") or (data_root / "huggingface" / "hub"))
    asr_models, tts_models = [], []
    seen_asr, seen_tts = set(), set()
    try:
        for model_dir in hub_root.glob("models--*"):
            repo_id = model_dir.name[len("models--"):].replace("--", "/")
            snapshots = model_dir / "snapshots"
            if not snapshots.is_dir():
                continue
            for snapshot in snapshots.iterdir():
                if not snapshot.is_dir():
                    continue
                config = {}
                config_path = snapshot / "config.json"
                try:
                    if config_path.is_file():
                        import json
                        config = json.loads(config_path.read_text(encoding="utf-8", errors="replace"))
                except (OSError, ValueError, TypeError):
                    pass
                signature = " ".join((repo_id.lower(), str(config.get("model_type") or "").lower(),
                    " ".join(str(x).lower() for x in (config.get("architectures") or []))))
                has_weights = any(
                    next(snapshot.glob(pattern), None) is not None
                    for pattern in ("*.safetensors", "*.bin", "*.gguf", "*.onnx")
                ) or (snapshot / "model.safetensors.index.json").is_file()
                if not has_weights:
                    continue
                shenava_filename = next((filename for model_id, filename in SHENAVA_MODEL_FILENAMES.items() if model_id.casefold() == repo_id.casefold()), None)
                is_shenava = bool(
                    shenava_filename
                    and (snapshot / shenava_filename).is_file()
                    and (snapshot / "tokens.txt").is_file()
                )
                if is_shenava and repo_id.casefold() not in seen_asr:
                    asr_models.append({
                        "id": repo_id,
                        "path": str(snapshot),
                        "backend": "shenava",
                    })
                    seen_asr.add(repo_id.casefold())
                for onnx in snapshot.glob("*.onnx"):
                    key = str(onnx.absolute()).casefold()
                    if key not in seen_tts:
                        display_name = "Mana Persian Piper" if "mana" in onnx.stem.casefold() or "mana-persian-piper" in repo_id.casefold() else onnx.stem
                        tts_models.append({"name": display_name, "path": str(onnx.absolute()), "repo_id": repo_id})
                        seen_tts.add(key)
    except OSError:
        pass
    # Piper downloads may be placed in Kira's data folder, the package-managed
    # working-directory "models" folder, or alongside the runtime package.
    search_roots = [
        data_root / "voice_models",
        data_root / "voice_cache",
        data_root / "models",
        Path(__file__).resolve().parents[1] / "models",
        Path.cwd() / "models",
    ]
    try:
        import importlib.util
        spec = importlib.util.find_spec("persian_speech_runtime")
        if spec and spec.origin:
            search_roots.append(Path(spec.origin).resolve().parent)
    except (ImportError, ValueError, OSError):
        pass
    visited_roots = set()
    for root in search_roots:
        try:
            resolved_root = root.resolve()
            if resolved_root in visited_roots or not resolved_root.is_dir():
                continue
            visited_roots.add(resolved_root)
            for onnx in resolved_root.rglob("*.onnx"):
                key = str(onnx.resolve()).casefold()
                if key not in seen_tts:
                    display_name = "Mana Persian Piper" if "mana" in onnx.stem.casefold() else onnx.stem
                    tts_models.append({"name": display_name, "path": str(onnx.absolute()), "repo_id": ""})
                    seen_tts.add(key)
        except OSError:
            continue
    asr_models.sort(key=lambda item: item["id"].casefold())
    tts_models.sort(key=lambda item: item["name"].casefold())
    return {"asr": asr_models, "tts": tts_models}
