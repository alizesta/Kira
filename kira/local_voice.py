"""Optional offline Persian speech engines used before Cloud Voice.

ASR: Qwen3-ASR 0.6B via the official qwen-asr package.
TTS: Mana Persian Piper via persian-speech.
This module performs speech conversion only; it contains no chat or agent logic.
"""
from __future__ import annotations

import gc
import io
import os
import threading
import wave
from pathlib import Path

# Keep model/runtime caches beside Kira's persistent data, not on C: or
# inside the replaceable application folder.
from .storage import configure_cache_environment, default_data_dir

_DATA_ROOT = default_data_dir(Path(__file__).resolve().parents[1])
configure_cache_environment(_DATA_ROOT)

_asr_lock = threading.RLock()
_tts_lock = threading.RLock()
_asr = None
_asr_model_name = None
_tts = None
_asr_error = None
_tts_error = None


def asr_ready() -> bool:
    try:
        import qwen_asr  # noqa: F401
        return True
    except ImportError:
        return False


def tts_ready(model_path="") -> bool:
    if model_path:
        if not Path(str(model_path)).is_file():
            return False
        try:
            import piper  # noqa: F401
            return True
        except ImportError:
            return False
    try:
        import persian_speech_runtime  # noqa: F401
        return True
    except ImportError:
        return False


def load_asr(model_name="Qwen/Qwen3-ASR-0.6B"):
    """Load the selected Qwen3-ASR model; a changed model id/path replaces the previous instance."""
    global _asr, _asr_error, _asr_model_name
    selected = str(model_name or "Qwen/Qwen3-ASR-0.6B")
    with _asr_lock:
        if _asr is not None and _asr_model_name == selected:
            return True
        try:
            import torch
            from qwen_asr import Qwen3ASRModel
            old_model, _asr = _asr, None
            _asr_model_name = None
            if old_model is not None:
                del old_model
                gc.collect()
            _asr = Qwen3ASRModel.from_pretrained(
                selected,
                dtype=torch.float32,
                device_map="cpu",
                max_inference_batch_size=1,
                max_new_tokens=256,
            )
            _asr_model_name = selected
            _asr_error = None
        except Exception as exc:
            _asr = None
            _asr_model_name = None
            _asr_error = exc
            raise RuntimeError(f"Qwen3-ASR load failed: {type(exc).__name__}: {exc}") from exc
    return True


def transcribe(audio, sample_rate=16000, language="fa", prompt="", model_name="Qwen/Qwen3-ASR-0.6B") -> str:
    """Transcribe one mono float32 numpy segment locally. Model loading is lazy."""
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return ""
    load_asr(model_name)
    with _asr_lock:
        lang = {"fa": "Persian", "en": "English", "ar": "Arabic"}.get(language, None)
        results = _asr.transcribe(
            audio=(samples, int(sample_rate)),
            language=lang,
            prompt=(prompt or None),
        )
        if not results:
            return ""
        return str(getattr(results[0], "text", "") or "").strip()


def synthesize_persian(text: str, model_path="", rate=0) -> bytes:
    """Return WAV from a chosen Piper ONNX voice or the bundled Persian engine."""
    global _tts, _tts_error
    clean = str(text or "").strip()
    if not clean:
        return b""
    selected = str(model_path or "").strip()
    with _tts_lock:
        if selected:
            path = Path(selected).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() != ".onnx":
                raise RuntimeError(f"Custom Piper model does not exist: {path}")
            try:
                voice = _custom_tts.get(str(path))
                if voice is None:
                    from piper import PiperVoice
                    voice = PiperVoice.load(str(path))
                    _custom_tts.clear()
                    _custom_tts[str(path)] = voice
                output = io.BytesIO()
                with wave.open(output, "wb") as wav_file:
                    voice.synthesize_wav(clean, wav_file)
                payload = output.getvalue()
                _tts_error = None
            except Exception as exc:
                _tts_error = exc
                raise RuntimeError(f"Custom Piper synthesis failed: {type(exc).__name__}: {exc}") from exc
        else:
            if _tts is None:
                try:
                    from persian_speech_runtime import PiperSpeechEngine
                    _tts = PiperSpeechEngine()
                    _tts_error = None
                except Exception as exc:
                    _tts_error = exc
                    raise RuntimeError(f"Persian Piper load failed: {type(exc).__name__}: {exc}") from exc
            try:
                payload = _tts.stream(clean)
            except Exception as exc:
                raise RuntimeError(f"Persian Piper synthesis failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, (bytes, bytearray)) or not payload.startswith(b"RIFF"):
        raise RuntimeError("Persian Piper returned invalid WAV data")
    # Piper exposes a stable WAV stream. Adjust its playback sample rate so per-character
    # speed also applies when the selected offline voice is used (pitch changes slightly).
    speed = max(0.5, min(1.5, 1.0 + float(rate or 0) / 100.0))
    if abs(speed - 1.0) > 0.001:
        try:
            with wave.open(io.BytesIO(payload), "rb") as source:
                params = source.getparams()
                frames = source.readframes(source.getnframes())
            output = io.BytesIO()
            with wave.open(output, "wb") as target:
                target.setnchannels(params.nchannels)
                target.setsampwidth(params.sampwidth)
                target.setframerate(max(8000, min(96000, round(params.framerate * speed))))
                target.setcomptype(params.comptype, params.compname)
                target.writeframes(frames)
            payload = output.getvalue()
        except (wave.Error, OSError, ValueError):
            pass
    return bytes(payload)


def cache_directory() -> str:
    """Return the effective Hugging Face model cache location."""
    return str(Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface"))


def status(model_path="") -> dict:
    """Small diagnostic snapshot; does not load either model."""
    return {
        "asr_installed": asr_ready(),
        "tts_installed": tts_ready(model_path),
        "asr_loaded": _asr is not None,
        "asr_model": _asr_model_name or "",
        "tts_loaded": _tts is not None or bool(_custom_tts),
        "tts_model": next(iter(_custom_tts), "") or ("bundled" if _tts is not None else ""),
        "asr_error": str(_asr_error)[:240] if _asr_error else "",
        "tts_error": str(_tts_error)[:240] if _tts_error else "",
    }

def discover_cached_models() -> dict:
    """Find cached Qwen ASR snapshots and Piper ONNX voices without downloading anything."""
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
                if any(token in signature for token in ("qwen3-asr", "qwen3asr", "qwen_asr")):
                    if repo_id.casefold() not in seen_asr:
                        asr_models.append({"id": repo_id, "path": str(snapshot)})
                        seen_asr.add(repo_id.casefold())
                for onnx in snapshot.glob("*.onnx"):
                    key = str(onnx.resolve()).casefold()
                    if key not in seen_tts:
                        tts_models.append({"name": onnx.stem, "path": str(onnx)})
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
                    tts_models.append({"name": onnx.stem, "path": str(onnx)})
                    seen_tts.add(key)
        except OSError:
            continue
    asr_models.sort(key=lambda item: (item["id"].casefold() != "qwen/qwen3-asr-0.6b", item["id"].casefold()))
    tts_models.sort(key=lambda item: item["name"].casefold())
    return {"asr": asr_models, "tts": tts_models}
