"""Managed local whisper.cpp Vulkan ASR runtime for Windows AMD/Intel GPUs.

The runtime is a pinned, checksum-verified whisper.cpp build. Audio is sent only
to a loopback HTTP server owned by this process; no network speech service is used.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import wave
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

RUNTIME_URL = (
    "https://github.com/fahrim/whisper-vulkan-win/releases/download/"
    "engine-vulkan-b5454-static/whisper-vulkan-win-x64-v1.9.5.zip"
)
RUNTIME_SHA256 = "105b03c51d38583b333c7f116c5c12e8ce72c443f3a614204425f617e9ecbdde"
MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    "ggml-large-v3-turbo-q5_0.bin"
)
MODEL_SHA256 = "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"
MODEL_FILENAME = "ggml-large-v3-turbo-q5_0.bin"
RUNTIME_FILES = ("whisper-server.exe", "whisper-server-cpu.exe", "vcomp140.dll")
DEFAULT_THREADS = 4
_STARTUP_TIMEOUT = 90.0
_REQUEST_TIMEOUT = 180.0

_lock = threading.RLock()
_server: subprocess.Popen | None = None
_server_port: int | None = None
_server_log_handle = None
_server_backend = ""


def _data_root() -> Path:
    from .storage import default_data_dir
    return Path(default_data_dir(Path(__file__).resolve().parents[1])).expanduser().resolve()


def runtime_dir() -> Path:
    return _data_root() / "whisper_cpp" / "runtime"


def model_path() -> Path:
    return _data_root() / "whisper_cpp" / "models" / MODEL_FILENAME


def is_ready() -> bool:
    """True only when the verified runtime files and multilingual model exist."""
    root = runtime_dir()
    return (
        (root / "whisper-server.exe").is_file()
        and (root / "whisper-server-cpu.exe").is_file()
        and (root / "vcomp140.dll").is_file()
        and model_path().is_file()
    )


def status() -> dict[str, Any]:
    root = runtime_dir()
    model = model_path()
    return {
        "ready": is_ready(),
        "vulkan_binary": str(root / "whisper-server.exe"),
        "cpu_binary": str(root / "whisper-server-cpu.exe"),
        "model": str(model) if model.is_file() else "",
        "model_size": model.stat().st_size if model.is_file() else 0,
        "running": _server is not None and _server.poll() is None,
        "backend": _server_backend,
        "port": _server_port,
    }


def _cancelled(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _download_verified(url: str, destination: Path, expected_sha256: str, cancel_event=None) -> Path:
    import requests

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=(20, 90), allow_redirects=True) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if _cancelled(cancel_event):
                        raise RuntimeError("دانلود موتور تشخیص گفتار لغو شد.")
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
        if digest.hexdigest().casefold() != expected_sha256.casefold():
            raise RuntimeError(
                f"اعتبارسنجی SHA-256 فایل ناموفق بود: {destination.name}"
            )
        os.replace(partial, destination)
        return destination
    except Exception:
        try:
            partial.unlink()
        except OSError:
            pass
        raise


def _extract_runtime(archive: Path, destination: Path, cancel_event=None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".whisper-vulkan-", dir=str(destination.parent)))
    found = set()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if _cancelled(cancel_event):
                    raise RuntimeError("نصب موتور تشخیص گفتار لغو شد.")
                if info.is_dir():
                    continue
                member = PurePosixPath(info.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise RuntimeError("مسیر ناامن داخل بسته موتور Whisper شناسایی شد.")
                name = member.name.casefold()
                expected = next((item for item in RUNTIME_FILES if item.casefold() == name), None)
                if expected is None:
                    continue
                if info.file_size <= 0 or info.file_size > 100 * 1024 * 1024:
                    raise RuntimeError(f"اندازه فایل runtime نامعتبر است: {expected}")
                with bundle.open(info) as source, (staging / expected).open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                found.add(expected)
        missing = set(RUNTIME_FILES) - found
        if missing:
            raise RuntimeError("فایل‌های لازم در بسته Whisper وجود ندارند: " + ", ".join(sorted(missing)))
        for name in RUNTIME_FILES:
            os.replace(staging / name, destination / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install(*, cancel_event=None) -> str:
    """Download the pinned Vulkan runtime and multilingual model into Kira's data folder."""
    if os.name != "nt":
        raise RuntimeError("بسته آماده Vulkan فعلاً فقط برای Windows x64 ارائه شده است.")
    root = runtime_dir()
    model = model_path()
    root.mkdir(parents=True, exist_ok=True)
    archive = root.parent / "whisper-vulkan-win-x64-v1.9.5.zip"
    if not all((root / name).is_file() for name in RUNTIME_FILES):
        if not archive.is_file() or _sha256_file(archive) != RUNTIME_SHA256:
            _download_verified(RUNTIME_URL, archive, RUNTIME_SHA256, cancel_event)
        _extract_runtime(archive, root, cancel_event)
    if _cancelled(cancel_event):
        raise RuntimeError("نصب موتور تشخیص گفتار لغو شد.")
    if not model.is_file() or _sha256_file(model) != MODEL_SHA256:
        _download_verified(MODEL_URL, model, MODEL_SHA256, cancel_event)
    if not is_ready():
        raise RuntimeError("نصب Whisper.cpp کامل نشد؛ فایل‌های runtime یا مدل ناقص‌اند.")
    return str(model)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wav_bytes(audio, sample_rate: int) -> bytes:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        raise ValueError("برای تشخیص گفتار، صدای خالی قابل پردازش نیست.")
    if not 8000 <= int(sample_rate) <= 48000:
        raise ValueError(f"نرخ نمونه‌برداری پشتیبانی نمی‌شود: {sample_rate}")
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


def parse_transcription_response(result: Any) -> str:
    """Extract text from whisper.cpp JSON responses without trusting response shape."""
    if not isinstance(result, dict):
        return ""
    text = result.get("text", "")
    if not text and isinstance(result.get("segments"), list):
        text = " ".join(
            str(segment.get("text") or "").strip()
            for segment in result["segments"] if isinstance(segment, dict)
        )
    return " ".join(str(text or "").split()).strip()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_executable() -> tuple[Path, str]:
    root = runtime_dir()
    vulkan = root / "whisper-server.exe"
    cpu = root / "whisper-server-cpu.exe"
    return (vulkan, "vulkan") if vulkan.is_file() else (cpu, "cpu")


def _read_log_tail() -> str:
    if _server_log_handle is None:
        return ""
    try:
        _server_log_handle.flush()
        path = Path(_server_log_handle.name)
        return path.read_text(encoding="utf-8", errors="replace")[-5000:]
    except OSError:
        return ""


def _start_server(language: str, threads: int) -> None:
    global _server, _server_port, _server_log_handle, _server_backend
    import requests

    with _lock:
        if _server is not None and _server.poll() is None and _server_port is not None:
            return
        stop()
        if not is_ready():
            raise RuntimeError("Whisper.cpp Vulkan نصب نشده است؛ از تنظیمات صدا آن را نصب کن.")
        executable, backend = _server_executable()
        port = _free_loopback_port()
        log_path = runtime_dir().parent / "whisper-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("ab")
        command = [
            str(executable), "--model", str(model_path()),
            "--host", "127.0.0.1", "--port", str(port),
            "--language", language or "fa",
            "--threads", str(max(1, min(8, int(threads)))),
            "--processors", "1",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(runtime_dir()),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except Exception:
            log_handle.close()
            raise
        _server, _server_port, _server_log_handle, _server_backend = process, port, log_handle, backend
        deadline = time.monotonic() + _STARTUP_TIMEOUT
        url = f"http://127.0.0.1:{port}/"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = _read_log_tail()
                stop()
                raise RuntimeError(f"اجرای whisper.cpp ناموفق بود: {detail[-1200:]}")
            try:
                response = requests.get(url, timeout=1.5)
                if response.ok and "whisper.cpp" in response.text.casefold():
                    startup_log = _read_log_tail()
                    if backend == "vulkan" and "Found 0 Vulkan devices" in startup_log:
                        stop()
                        raise RuntimeError(
                            "درایور Vulkan هیچ GPU سازگاری گزارش نکرد؛ faster-whisper روی CPU استفاده می‌شود."
                        )
                    return
            except requests.RequestException:
                pass
            time.sleep(0.25)
        detail = _read_log_tail()
        stop()
        raise RuntimeError(f"موتور whisper.cpp در زمان مجاز آماده نشد: {detail[-1200:]}")


def transcribe(audio, sample_rate=16000, language="fa", prompt="", *, threads=DEFAULT_THREADS) -> str:
    """Transcribe one speech segment through a loopback-only whisper.cpp Vulkan server."""
    import requests

    lang = str(language or "fa").casefold()
    if lang in ("persian", "farsi"):
        lang = "fa"
    if lang not in ("fa", "en", "ar", "auto"):
        lang = "auto"
    _start_server(lang, threads)
    payload = _wav_bytes(audio, sample_rate)
    url = f"http://127.0.0.1:{_server_port}/inference"
    fields = {
        "temperature": "0.0",
        "temperature_inc": "0.2",
        "no_speech_thold": "0.55",
        "response_format": "json",
        "prompt": str(prompt or "")[:1000],
    }
    try:
        response = requests.post(
            url,
            files={"file": ("kira-segment.wav", payload, "audio/wav")},
            data=fields,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"whisper.cpp transcription failed: {type(exc).__name__}: {exc}") from exc
    return parse_transcription_response(result)


def stop() -> None:
    """Stop only the child server process started by this module."""
    global _server, _server_port, _server_log_handle, _server_backend
    with _lock:
        process, log_handle = _server, _server_log_handle
        _server, _server_port, _server_log_handle, _server_backend = None, None, None, ""
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if log_handle is not None:
            try:
                log_handle.close()
            except OSError:
                pass
