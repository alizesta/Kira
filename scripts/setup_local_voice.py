"""Install and prepare Kira's optional local Persian speech engines."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements-voice-local.txt"
MODEL = "Qwen/Qwen3-ASR-0.6B"
def configure_data_paths() -> Path:
    """Use the same writable persistent-data resolver as the desktop application."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from kira.storage import configure_cache_environment, default_data_dir

    data_dir = default_data_dir(ROOT)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["KIRA_DATA_DIR"] = str(data_dir)
    configure_cache_environment(data_dir)
    return data_dir


def run_install() -> bool:
    if sys.version_info[:2] not in ((3, 11), (3, 12)):
        print(f"ERROR: Kira local voice requires Python 3.11 or 3.12; current: {sys.version.split()[0]}")
        return False
    if not REQ.is_file():
        print(f"ERROR: Missing dependency file: {REQ}")
        return False
    print(f"Python: {sys.executable}")
    print(f"Installing local voice dependencies from {REQ.name} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--retries", "5", "--timeout", "60", "-r", str(REQ)],
        cwd=ROOT,
    )
    if result.returncode:
        print(f"ERROR: pip exited with code {result.returncode}")
        return False
    return True


def prepare_asr() -> bool:
    try:
        from huggingface_hub import snapshot_download
        print(f"Downloading/checking ASR model: {MODEL}")
        path = snapshot_download(repo_id=MODEL)
        print(f"ASR model is cached at: {path}")
        return True
    except Exception as exc:
        print(f"ASR MODEL ERROR: {type(exc).__name__}: {exc}")
        print("Check Hugging Face access, DNS/VPN, free disk space and HF_HOME.")
        return False


def prepare_tts() -> bool:
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from kira import local_voice
        print("Preparing Mana Persian Piper and generating a short test WAV ...")
        wav = local_voice.synthesize_persian("سلام. صدای فارسی محلی کیرا آماده است.")
        if not isinstance(wav, (bytes, bytearray)) or not wav.startswith(b"RIFF"):
            raise RuntimeError("Piper did not return valid WAV bytes")
        out = Path(os.environ["KIRA_DATA_DIR"]) / "voice_cache" / "local_persian_setup_test.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(wav)
        print(f"TTS test succeeded: {out}")
        return True
    except Exception as exc:
        print(f"TTS MODEL ERROR: {type(exc).__name__}: {exc}")
        print("Check internet access for the first model download and available disk space.")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="install packages into the active Python environment")
    parser.add_argument("--prepare-models", action="store_true", help="download/check ASR and TTS model files")
    args = parser.parse_args()
    if not args.install and not args.prepare_models:
        args.install = True
    data_dir = configure_data_paths()
    print(f"Kira data directory: {data_dir}")
    print(f"HF_HOME: {os.environ['HF_HOME']}")
    ok = True
    if args.install:
        ok = run_install() and ok
    if args.prepare_models:
        asr_ok = prepare_asr()
        tts_ok = prepare_tts()
        ok = asr_ok and tts_ok and ok
    print("\nLOCAL VOICE SETUP " + ("SUCCEEDED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
