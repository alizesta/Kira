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
_custom_tts = {}  # Cache for user-selected Piper ONNX voices.
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
        # qwen-asr's public transcribe() API does not accept a prompt
        # keyword in all released versions. Passing it raises TypeError and
        # makes Kira silently fall back to another STT engine.
        results = _asr.transcribe(
            audio=(samples, int(sample_rate)),
            language=lang,
        )
        if not results:
            return ""
        first = results[0]
        if isinstance(first, dict):
            text = first.get("text", "")
        else:
            text = getattr(first, "text", "")
        return str(text or "").strip()


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




def _ensure_pillow_compatible() -> None:
    """Force Gradio-compatible Pillow into Kira's active Python and verify it."""
    from importlib.metadata import PackageNotFoundError, version
    import subprocess
    import sys

    try:
        installed = version("Pillow")
    except PackageNotFoundError:
        installed = ""

    try:
        if installed and int(installed.split(".", 1)[0]) < 13:
            return
    except (TypeError, ValueError):
        pass

    # --upgrade alone can leave an incompatible preinstalled Pillow untouched.
    # Force-reinstall the compatible version, without allowing pip to alter
    # unrelated packages while repairing this specific conflict.
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps",
         "--retries", "5", "--timeout", "60", "Pillow>=8,<13"],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "Pillow compatibility fix failed")[-2500:]
        raise RuntimeError(f"اصلاح ناسازگاری Pillow ناموفق بود: {detail}")

    try:
        fixed = version("Pillow")
        if int(fixed.split(".", 1)[0]) >= 13:
            raise RuntimeError(f"نسخه ناسازگار Pillow هنوز نصب است: {fixed}")
    except PackageNotFoundError as exc:
        raise RuntimeError("پس از نصب، Pillow در محیط پایتون Kira پیدا نشد.") from exc


def _install_voice_package(package: str) -> None:
    """Install a voice runtime, then enforce Gradio's Pillow<13 requirement."""
    import subprocess
    import sys

    # Apply the Pillow cap during dependency resolution, not only after pip
    # finishes. Otherwise a voice package can upgrade Pillow to 13 and emit a
    # Gradio conflict before the post-install repair runs.
    constraints = Path(__file__).resolve().parents[1] / "constraints-voice.txt"
    if not constraints.is_file():
        raise RuntimeError(f"فایل محدودیت وابستگی‌های صوتی پیدا نشد: {constraints}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--retries", "5",
         "--timeout", "60", "--constraint", str(constraints), package],
        capture_output=True, text=True, timeout=3600, check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or f"pip install {package} failed")[-3500:]
        raise RuntimeError(f"نصب موتور {package} ناموفق بود: {detail}")

    # Some voice packages pull Pillow 13 as a dependency. Repair it after
    # their installation, and fail clearly if Gradio compatibility is not restored.
    _ensure_pillow_compatible()


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


def install_and_download_qwen_asr(repo_id: str = "Qwen/Qwen3-ASR-0.6B") -> str:
    """Install Qwen runtime and download the selected model into Kira's data folder."""
    _ensure_pillow_compatible()
    try:
        import qwen_asr  # noqa: F401
    except ImportError:
        _install_voice_package("qwen-asr")
    return _download_voice_repo(repo_id or "Qwen/Qwen3-ASR-0.6B")


def install_and_download_whisper(repo_id: str) -> str:
    """Install faster-whisper and download a CTranslate2 Whisper model."""
    _ensure_pillow_compatible()
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        _install_voice_package("faster-whisper")
    return _download_voice_repo(repo_id)


def install_and_download_piper_voice(repo_id: str) -> str:
    """Install Piper runtime and download a Piper ONNX voice."""
    _ensure_pillow_compatible()
    try:
        import piper  # noqa: F401
    except ImportError:
        _install_voice_package("piper-tts>=1.3.0,<2")
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
