"""Optional KittenTTS 2 tiny ONNX engines for isolated local evaluation.

The three models are downloaded lazily and run on CPU. They are not wired into
Kira's Persian speech path because these model families do not support Persian.
"""
from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path

from .storage import configure_cache_environment, default_data_dir

_DATA_ROOT = default_data_dir(Path(__file__).resolve().parents[1])
configure_cache_environment(_DATA_ROOT)
_CACHE_DIR = Path(os.environ.get("HF_HUB_CACHE") or (Path(_DATA_ROOT) / "huggingface" / "hub"))
_LOCK = threading.RLock()
_MODELS = {}
_MODEL_IDS = {
    "pico": "KittenML/kitten-tts-2-pico",
    "nano": "KittenML/kitten-tts-2-nano",
    "mini": "KittenML/kitten-tts-2-mini",
}
_MODEL_SIZES_MB = {"pico": 4.0, "nano": 8.8, "mini": 47.5}
_TEST_TEXT = "Hello! I am Kira. This is a local Kitten TTS voice test."


def _run(command, timeout=3600, cancel_event=None):
    """Use Kira's cancellable, hidden-window installer process."""
    from .local_voice import _run_install_command

    result = _run_install_command(command, timeout=timeout, cancel_event=cancel_event)
    if result.returncode:
        detail = (result.stderr or result.stdout or "pip failed")[-3000:]
        raise RuntimeError(f"نصب وابستگی KittenTTS ناموفق بود: {detail}")
    return result.stdout


def install_runtime(cancel_event=None):
    """Install only the ONNX runtime stack; avoid the optional multi-GB PyTorch stack."""
    import importlib.util
    from importlib.metadata import PackageNotFoundError, version

    required_modules = (
        "kittenml", "onnxruntime", "num2words", "spacy", "huggingface_hub",
    )

    def hub_version_is_compatible():
        try:
            installed = version("huggingface-hub")
        except PackageNotFoundError:
            return False
        # Kitten's transformers integration requires huggingface-hub >=0.34,<1.
        # Avoid adding packaging as another runtime dependency just for comparison.
        import re
        match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", installed)
        if not match:
            return False
        current = tuple(int(part or 0) for part in match.groups())
        return (0, 34, 0) <= current < (1, 0, 0)

    if (all(importlib.util.find_spec(name) for name in required_modules)
            and hub_version_is_compatible()):
        return True
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Kitten's default extra dependencies include PyTorch. --no-deps keeps this
    # optional CPU feature small; install its documented ONNX/text/audio runtime.
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "--retries", "4",
          "--timeout", "60", "--constraint",
          str(Path(__file__).resolve().parents[1] / "constraints-voice.txt"),
          "kittenml", "--no-deps"], cancel_event=cancel_event)
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "--retries", "4",
          "--timeout", "60", "--constraint",
          str(Path(__file__).resolve().parents[1] / "constraints-voice.txt"),
          "onnxruntime>=1.20", "numpy>=1.26", "soundfile",
          "huggingface-hub>=0.34.0,<1.0", "phonemizer", "espeakng_loader", "misaki",
          "num2words", "spacy>=3.8"], cancel_event=cancel_event)
    missing = [name for name in required_modules if not importlib.util.find_spec(name)]
    if missing:
        raise RuntimeError("پس از نصب، ماژول‌های لازم پیدا نشدند: " + ", ".join(missing))
    if not hub_version_is_compatible():
        try:
            installed = version("huggingface-hub")
        except PackageNotFoundError:
            installed = "نصب نشده"
        raise RuntimeError(
            "نسخه ناسازگار huggingface-hub پس از نصب باقی مانده است: "
            f"{installed}؛ نسخه مجاز >=0.34.0 و <1.0 است."
        )
    return True


def load_model(model="mini", cancel_event=None):
    key = str(model or "mini").strip().lower()
    if key not in _MODEL_IDS:
        raise ValueError(f"مدل KittenTTS ناشناخته است: {key}")
    with _LOCK:
        if key in _MODELS:
            return _MODELS[key]
        install_runtime(cancel_event)
        from kittenml import KittenTTS
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # INT4 ONNX is the smallest supported CPU option. Pico/Nano are
        # language-specific repositories; English is used for this first test.
        instance = KittenTTS(_MODEL_IDS[key], cache_dir=str(_CACHE_DIR),
                            backend="onnx", device="cpu", weights="int4")
        _MODELS[key] = instance
        return instance


def synthesize_test(model="mini", language="en", cancel_event=None) -> bytes:
    """Generate one English sample and return a standards-compliant PCM WAV."""
    import numpy as np
    import soundfile as sf

    instance = load_model(model, cancel_event=cancel_event)
    languages = list(getattr(instance, "languages", []) or [])
    selected_language = str(language or "en").lower()
    if languages and selected_language not in languages:
        selected_language = "en" if "en" in languages else languages[0]
    audio = np.asarray(instance.generate(_TEST_TEXT, language=selected_language), dtype=np.float32)
    if audio.size == 0 or not np.isfinite(audio).all():
        raise RuntimeError("KittenTTS خروجی صوتی معتبر تولید نکرد.")
    output = io.BytesIO()
    sf.write(output, audio, int(getattr(instance, "sample_rate", 24000)), format="WAV", subtype="PCM_16")
    payload = output.getvalue()
    if not payload.startswith(b"RIFF"):
        raise RuntimeError("خروجی KittenTTS فایل WAV معتبر نیست.")
    return payload


def model_info(model="mini"):
    key = str(model or "mini").lower()
    return {"id": _MODEL_IDS[key], "size_mb": _MODEL_SIZES_MB[key],
            "loaded": key in _MODELS}
