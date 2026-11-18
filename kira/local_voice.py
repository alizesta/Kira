"""Offline speech engines used by Kira. No network recognition or synthesis fallback lives here.

ASR: Qwen3-ASR 0.6B and faster-whisper (managed by Listener).
TTS: Piper ONNX or the bundled Persian Piper runtime.
"""
from __future__ import annotations

import gc
import io
import logging
import os
import threading
import wave
from pathlib import Path

# Keep model/runtime caches beside Kira's persistent data, not on C: or
# inside the replaceable application folder.
from .storage import configure_cache_environment, default_data_dir

logger = logging.getLogger(__name__)

_DATA_ROOT = default_data_dir(Path(__file__).resolve().parents[1])
configure_cache_environment(_DATA_ROOT)

_asr_lock = threading.RLock()
_tts_lock = threading.RLock()
_asr = None
_asr_model_name = None
_tts = None  # Keep only the currently selected voice in memory.
_tts_model_path = ""
_tts_model_signature = None
_tts_model_label = ""
_asr_error = None
_tts_error = None


def asr_ready() -> bool:
    try:
        import qwen_asr  # noqa: F401
        return True
    except ImportError:
        return False


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


def _sanitize_asr_generation_config(asr) -> None:
    """Remove inactive sampling flags and set explicit padding for greedy Qwen ASR."""
    model = getattr(asr, "model", None)
    generation = getattr(model, "generation_config", None)
    if generation is None:
        return
    # Qwen3-ASR checkpoints ship temperature=1e-6 while do_sample=False.
    # Transformers warns on every generate() call because temperature is unused.
    if getattr(generation, "do_sample", False) is False and hasattr(generation, "temperature"):
        generation.temperature = None
    # Avoid repeatedly inferring pad_token_id from eos_token_id on every decode.
    if getattr(generation, "pad_token_id", None) is None:
        processor = getattr(asr, "processor", None)
        tokenizer = getattr(processor, "tokenizer", None)
        pad_id = getattr(tokenizer, "pad_token_id", None)
        if pad_id is None:
            config = getattr(model, "config", None)
            pad_id = getattr(config, "pad_token_id", None)
        if pad_id is None:
            eos_id = getattr(generation, "eos_token_id", None)
            pad_id = eos_id[0] if isinstance(eos_id, (list, tuple)) and eos_id else eos_id
        if pad_id is not None:
            generation.pad_token_id = int(pad_id)


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
            try:
                torch.set_num_threads(max(1, min(8, int(os.environ.get("KIRA_ASR_THREADS", "4")))))
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
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
            _sanitize_asr_generation_config(_asr)
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


def _load_tts_voice(model_path=""):
    """Load one active Piper voice and guard against unsafe two-model memory peaks."""
    global _tts, _tts_model_path, _tts_model_label, _tts_model_signature

    path, label = _resolve_tts_model_path(model_path)
    key = str(path)
    stat = path.stat()
    signature = (key, stat.st_size, stat.st_mtime_ns)

    if _tts is not None and _tts_model_signature == signature:
        return _tts

    if _tts is not None:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError(
                "psutil is required for safe Piper voice switching; "
                "install requirements-voice-local.txt"
            ) from exc

        # Piper's ONNX runtime can use several times the serialized model size.
        # Keep the current voice resident unless a conservative budget indicates
        # that the replacement can be loaded without exhausting RAM.
        required_bytes = max(256 * 1024 * 1024, stat.st_size * 3)
        available_bytes = int(psutil.virtual_memory().available)
        if available_bytes < required_bytes:
            raise MemoryError(
                "Insufficient memory to switch Piper voice safely "
                f"({available_bytes} available; approximately "
                f"{required_bytes} required)"
            )

    from piper import PiperVoice

    voice = PiperVoice.load(str(path))
    # Swap only after successful loading so a failed switch preserves the old voice.
    _tts = voice
    _tts_model_path = key
    _tts_model_label = label
    _tts_model_signature = signature
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
        if not persian_ezafe.warmup():
            state = persian_ezafe.status()
            if state.get("enabled") and state.get("error"):
                logger.warning("Optional Persian ezafe warmup unavailable: %s", state["error"])
    except Exception:
        logger.exception("Optional Persian ezafe warmup failed; Piper remains available")
    return ready


def synthesize_persian(text: str, model_path="", rate=0) -> bytes:
    """Synthesize Persian speech with Piper's native timing controls.

    Piper's length_scale changes phoneme duration directly. Altering only the WAV
    sample-rate header changes both speed and pitch, so the active voice now uses
    the same native synthesis path for Mana and user-selected ONNX models.
    """
    global _tts_error
    clean = str(text or "").strip()
    if not clean:
        return b""

    # Insert context-predicted Persian ezafe marks before Piper phonemization.
    # The detector has its own lazy ONNX cache and safely returns the source
    # text unchanged whenever it is disabled or unavailable.
    try:
        from .persian_ezafe import add_persian_ezafe
        clean = add_persian_ezafe(clean)
    except Exception:
        logger.exception("Persian ezafe preprocessing failed; synthesizing the original text")

    selected = str(model_path or "").strip()
    speed = max(0.5, min(1.5, 1.0 + float(rate or 0) / 100.0))

    try:
        with _tts_lock:
            voice = _load_tts_voice(selected)
            from piper import SynthesisConfig

            output = io.BytesIO()
            config = SynthesisConfig(length_scale=1.0 / speed)
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
    """Diagnostic snapshot for Piper and optional Persian preprocessing."""
    try:
        from . import persian_ezafe
        ezafe_state=persian_ezafe.status()
    except Exception as exc:
        ezafe_state={"enabled":False,"loaded":False,"model":"","error":str(exc)[:240]}
    return {
        "asr_installed": asr_ready(), "tts_installed": tts_ready(model_path),
        "asr_loaded": _asr is not None, "asr_model": _asr_model_name or "",
        "tts_loaded": _tts is not None, "tts_model": _tts_model_label if _tts is not None else "",
        "asr_error": str(_asr_error)[:240] if _asr_error else "",
        "tts_error": str(_tts_error)[:240] if _tts_error else "", "ezafe": ezafe_state,
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
    asr_models.sort(key=lambda item: (item["id"].casefold() != "qwen/qwen3-asr-0.6b", item["id"].casefold()))
    tts_models.sort(key=lambda item: item["name"].casefold())
    return {"asr": asr_models, "tts": tts_models}
