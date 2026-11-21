"""Install Kira's pinned, checksum-verified uncensored local chat model into Ollama.

The GGUF comes from the Hugging Face mradermacher mirror of the abliterated Qwen3.5-9B.
The exact file SHA-256 is pinned so a similarly named or replaced model cannot silently
be installed as Kira's local brain.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
HF_URL = (
    "https://huggingface.co/mradermacher/Qwen3.5-9B-abliterated-GGUF/"
    "resolve/main/Qwen3.5-9B-abliterated.Q4_K_M.gguf"
)
MODEL_SHA256 = "19fadda28b2f4bd939fb4590db978acf8f0d6da274ac7ea8f7f2cdc92f1470a4"
MODEL_FILE = f"Qwen3.5-9B-abliterated.Q4_K_M-{MODEL_SHA256[:12]}.gguf"
OLLAMA_MODEL = "kira-qwen3.5-9b-abliterated:q4_k_m"
OLLAMA_MIN_VERSION = (0, 40, 15)
_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").strip().rstrip("/")
OLLAMA_URL = _OLLAMA_HOST if _OLLAMA_HOST.startswith(("http://", "https://")) else "http://" + _OLLAMA_HOST
TOOL_CALL_TEST_TIMEOUT = (20, 300)


def _data_dir() -> Path:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from kira.storage import configure_cache_environment, default_data_dir

    path = default_data_dir(ROOT)
    os.environ["KIRA_DATA_DIR"] = str(path)
    configure_cache_environment(path)
    models = path / "ollama" / "models"
    models.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OLLAMA_MODELS", str(models))
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ollama_exe() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
    )
    return next((str(path) for path in candidates if path.is_file()), None)


def _parse_ollama_version(exe: str) -> tuple[int, int, int] | None:
    proc = subprocess.run([exe, "--version"], capture_output=True, text=True, check=False)
    output = (proc.stdout or "") + " " + (proc.stderr or "")
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    return tuple(map(int, found.groups())) if found else None


def _install_or_upgrade_ollama() -> str:
    exe = _ollama_exe()
    if exe:
        version = _parse_ollama_version(exe)
        if version and version >= OLLAMA_MIN_VERSION:
            print(f"Ollama {'.'.join(map(str, version))} is ready.")
            return exe
        print(f"Ollama version is older than {OLLAMA_MIN_VERSION}; attempting automatic upgrade.")
        action = "upgrade"
    else:
        print("Ollama is missing; attempting automatic installation.")
        action = "install"

    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("Ollama is missing/too old and winget is unavailable. Install current Ollama for Windows, then rerun Update.")
    cmd = [
        winget, action, "--id", "Ollama.Ollama", "--exact", "--silent",
        "--accept-package-agreements", "--accept-source-agreements",
    ]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0 and action == "upgrade":
        subprocess.run([
            winget, "install", "--id", "Ollama.Ollama", "--exact", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ], check=False)
    exe = _ollama_exe()
    if not exe:
        raise RuntimeError("Ollama installation/upgrade did not expose ollama.exe in the standard Windows locations.")
    version = _parse_ollama_version(exe)
    if not version or version < OLLAMA_MIN_VERSION:
        raise RuntimeError(f"Ollama 0.40.15 or newer is required for Qwen3.5; found: {version or 'unknown'}")
    print(f"Ollama {'.'.join(map(str, version))} installed.")
    return exe


def _wait_for_server(exe: str) -> None:
    try:
        requests.get(OLLAMA_URL + "/api/tags", timeout=2).raise_for_status()
        return
    except requests.RequestException:
        pass
    env = os.environ.copy()
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [exe, "serve"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=flags,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            requests.get(OLLAMA_URL + "/api/tags", timeout=3).raise_for_status()
            return
        except requests.RequestException:
            time.sleep(2)
    raise RuntimeError("Ollama server did not become ready at " + OLLAMA_URL)


def _download_verified(target: Path) -> Path:
    if target.is_file():
        actual = _sha256(target)
        if actual == MODEL_SHA256:
            print(f"Verified cached GGUF: {target} (SHA-256 matched).")
            return target
        target.rename(target.with_name(target.name + f".invalid-{int(time.time())}"))

    part = target.with_suffix(target.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    print(f"Downloading pinned Q4_K_M GGUF ({'resuming' if offset else 'starting'}): {HF_URL}")
    with requests.get(HF_URL, headers=headers, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        host = (urlparse(response.url).hostname or "").lower()
        if host != "huggingface.co" and not host.endswith((".huggingface.co", ".hf.co")):
            raise RuntimeError(f"Unexpected Hugging Face download host: {host}")
        append = bool(
            offset and response.status_code == 206
            and (response.headers.get("Content-Range") or "").startswith(f"bytes {offset}-")
        )
        if offset and not append:
            offset = 0
        downloaded = offset
        last_report = downloaded
        with part.open("ab" if append else "wb") as sink:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                sink.write(chunk)
                downloaded += len(chunk)
                if downloaded - last_report >= 1024 * 1024 * 1024:
                    print(f"Downloaded {downloaded / (1024 ** 3):.1f} GiB...")
                    last_report = downloaded
    actual = _sha256(part)
    if actual != MODEL_SHA256:
        raise RuntimeError(f"GGUF SHA-256 mismatch; expected {MODEL_SHA256}, got {actual}. Partial download kept for retry.")
    part.replace(target)
    print("GGUF checksum verified.")
    return target


def _run_create(exe: str, model_path: Path, data_dir: Path) -> None:
    model_dir = data_dir / "ollama" / "kira_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    modelfile = model_dir / "Modelfile"
    modelfile.write_text(
        f"FROM {model_path.resolve().as_posix()}\n"
        "PARAMETER num_ctx 8192\n"
        "PARAMETER num_predict 768\n"
        "PARAMETER temperature 0.7\n",
        encoding="utf-8",
    )
    print(f"Creating/verifying Ollama model: {OLLAMA_MODEL}")
    created = subprocess.run(
        [exe, "create", OLLAMA_MODEL, "-f", str(modelfile)],
        cwd=str(model_dir), check=False,
    )
    if created.returncode != 0:
        raise RuntimeError(f"ollama create failed with exit code {created.returncode}.")


def _verify_model() -> None:
    response = requests.post(
        OLLAMA_URL + "/api/show", json={"model": OLLAMA_MODEL, "verbose": True}, timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    details = data.get("details") or {}
    quant = str(details.get("quantization_level") or "").upper()
    if quant and quant != "Q4_K_M":
        raise RuntimeError(f"Installed model quantization is {quant}, expected Q4_K_M.")
    families = details.get("families") or []
    family = str(details.get("family") or "").lower()
    if families and not any("qwen" in str(item).lower() for item in families):
        raise RuntimeError(f"Unexpected model family in Ollama metadata: {families}")
    if family and "qwen" not in family:
        raise RuntimeError(f"Unexpected model architecture in Ollama metadata: {family}")
    print(f"Installed model metadata: {details or 'not exposed by this Ollama build'}")


def _smoke_test() -> None:
    response = requests.post(
        OLLAMA_URL + "/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": "Reply with only the number for 2 + 2."}],
            "stream": False,
            "think": False,
            "options": {"num_ctx": 2048, "num_predict": 48, "temperature": 0},
        },
        timeout=240,
    )
    response.raise_for_status()
    payload = response.json()
    content = str((payload.get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("The installed local model returned an empty answer in its smoke test.")
    print("Local model smoke test passed: " + content[:100].replace("\n", " "))


def _installed_digest() -> str:
    response = requests.get(OLLAMA_URL + "/api/tags", timeout=20)
    response.raise_for_status()
    for item in response.json().get("models") or []:
        if str(item.get("name") or "").lower() == OLLAMA_MODEL.lower():
            return str(item.get("digest") or "")
    return ""


def _cached_install_is_valid(data_dir: Path) -> bool:
    marker = data_dir / "ollama" / "kira_model" / "model.json"
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    current_digest = _installed_digest()
    return bool(
        current_digest
        and state.get("model") == OLLAMA_MODEL
        and state.get("source_sha256") == MODEL_SHA256
        and state.get("ollama_digest") == current_digest
    )


def _write_install_marker(data_dir: Path) -> None:
    marker = data_dir / "ollama" / "kira_model" / "model.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    digest = _installed_digest()
    if not digest:
        raise RuntimeError("Ollama did not list the newly created model after installation.")
    temp = marker.with_suffix(".json.tmp")
    temp.write_text(json.dumps({
        "model": OLLAMA_MODEL,
        "source_repo": "mradermacher/Qwen3.5-9B-abliterated-GGUF",
        "source_file": "Qwen3.5-9B-abliterated.Q4_K_M.gguf",
        "source_sha256": MODEL_SHA256,
        "ollama_digest": digest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(marker)


def _tool_call_smoke_test() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "A local setup verification function. Call it with value 7.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        },
    }
    print("Running native tool-calling smoke test; this may take several minutes on CPU/offloaded GPU...", flush=True)
    response = requests.post(
        OLLAMA_URL + "/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": "You must call the provided function when the user asks you to. Do not answer in plain text instead of calling it."},
                {"role": "user", "content": "Call the ping function now with value 7. Do not answer in plain text."},
            ],
            "tools": [tool],
            "stream": False,
            "think": False,
            "options": {"num_ctx": 2048, "num_predict": 128, "temperature": 0},
        },
        timeout=TOOL_CALL_TEST_TIMEOUT,
    )
    response.raise_for_status()
    message = response.json().get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        preview = str(message.get("content") or "").strip().replace("\\n", " ")[:240]
        raise RuntimeError(
            "The local model did not return native tool_calls. "
            f"Plain-text response: {preview or '[empty]'}"
        )
    function = (calls[0].get("function") or {})
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        import json
        arguments = json.loads(arguments)
    if function.get("name") != "ping" or arguments.get("value") != 7:
        raise RuntimeError("The local model produced an invalid native tool-call payload.")
    print("Native tool-calling smoke test passed.", flush=True)


def main() -> int:
    data_dir = _data_dir()
    print(f"Kira data directory: {data_dir}")
    try:
        exe = _install_or_upgrade_ollama()
        _wait_for_server(exe)
        weight_dir = data_dir / "ollama" / "gguf"
        weight_dir.mkdir(parents=True, exist_ok=True)
        if _cached_install_is_valid(data_dir):
            print("Pinned GGUF hash and installed Ollama digest both match; reusing the existing model.")
        else:
            free_bytes = shutil.disk_usage(weight_dir).free
            if free_bytes < 12 * 1024 ** 3:
                raise RuntimeError("At least 12 GiB of free disk space is required for the verified GGUF import.")
            model_path = _download_verified(weight_dir / MODEL_FILE)
            _run_create(exe, model_path, data_dir)
            _verify_model()
            _write_install_marker(data_dir)
            # Ollama has imported the verified weights into its own model store.
            # Remove the temporary GGUF copy to avoid keeping two 5.6 GiB copies.
            model_path.unlink(missing_ok=True)
        _verify_model()
        _smoke_test()
        _tool_call_smoke_test()
    except Exception as exc:
        print(f"LOCAL UNCENSORED MODEL SETUP FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"LOCAL UNCENSORED MODEL READY: {OLLAMA_MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
