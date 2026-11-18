"""Optional ONNX ALBERT preprocessing for Persian ezafe in local TTS.

The detector is isolated from Piper, uses Kira's single configured Hugging Face
cache, retries transient initialization failures with bounded backoff, and
never prevents Piper from speaking the original text.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path

_MODEL_ID = "abreza/persian-ezafe-albert"
_MODEL_FILE = Path("quantized") / "model_quantized.onnx"
_MAX_TOKENS = 512
_EZAFE = "\u0650"
_TRAILING_PUNCTUATION = frozenset("،؛:,.!?؟…)]}»\\\"'")
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_RETRY_BASE_SECONDS = 5.0
_RETRY_MAX_SECONDS = 300.0

_log = logging.getLogger(__name__)
_lock = threading.RLock()
_predictor = None
_load_failures = 0
_retry_after = 0.0
_last_error = ""


def is_enabled() -> bool:
    """Whether neural ezafe insertion is enabled (enabled by default)."""
    return str(os.environ.get("KIRA_TTS_EZAFE", "1")).strip().casefold() not in _FALSE_VALUES


def _cache_directory() -> Path:
    """Return the same Hugging Face hub cache used by the rest of Kira."""
    configured = (
        os.environ.get("HF_HUB_CACHE")
        or os.environ.get("HUGGINGFACE_HUB_CACHE")
        or (str(Path(os.environ["HF_HOME"]) / "hub") if os.environ.get("HF_HOME") else "")
    )
    if configured:
        path = Path(configured).expanduser()
    else:
        # Import the central storage policy only when no cache has been configured.
        from .storage import configure_cache_environment, default_data_dir

        data_dir = default_data_dir(Path(__file__).resolve().parents[1])
        configure_cache_environment(data_dir)
        path = Path(os.environ["HF_HUB_CACHE"])
    path.mkdir(parents=True, exist_ok=True)
    # Keep all supported Hugging Face variables aligned; do not create a second cache.
    value = str(path)
    os.environ["HF_HUB_CACHE"] = value
    os.environ["HUGGINGFACE_HUB_CACHE"] = value
    return path


def _load_predictor():
    """Load the quantized ONNX model and tokenizer with retryable, serialized initialization."""
    global _predictor, _load_failures, _retry_after, _last_error
    with _lock:
        if _predictor is not None:
            return _predictor
        now = time.monotonic()
        if now < _retry_after:
            remaining = max(0.0, _retry_after - now)
            raise RuntimeError(
                f"ALBERT initialization is cooling down after a failure; retry in {remaining:.1f}s: {_last_error}"
            )
        try:
            predictor = _initialize_predictor()
            _predictor = predictor
            _load_failures = 0
            _retry_after = 0.0
            _last_error = ""
            return predictor
        except Exception as exc:
            _load_failures += 1
            delay = min(_RETRY_MAX_SECONDS, _RETRY_BASE_SECONDS * (2 ** min(_load_failures - 1, 6)))
            _retry_after = now + delay
            _last_error = f"{type(exc).__name__}: {exc}"[:500]
            _log.warning("Persian ezafe model initialization failed; retry in %.1fs: %s", delay, _last_error)
            raise


def _initialize_predictor():
    """Build the tokenizer and CPU ONNX session in Kira's shared HF cache."""
    import numpy as np
    import onnxruntime as ort
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    cache_dir = str(_cache_directory())
    kwargs = {
        "repo_id": _MODEL_ID,
        "cache_dir": cache_dir,
        "allow_patterns": ["quantized/*"],
    }
    try:
        snapshot = snapshot_download(local_files_only=True, **kwargs)
    except Exception:
        snapshot = snapshot_download(local_files_only=False, **kwargs)

    model_dir = Path(snapshot) / "quantized"
    model_path = model_dir / _MODEL_FILE.name
    if not model_path.is_file():
        raise FileNotFoundError(f"ALBERT ONNX weights not found: {model_path}")

    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir), use_fast=True, local_files_only=True
    )
    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError("ALBERT tokenizer must support offset mappings")

    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
    session = ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    input_names = {item.name for item in session.get_inputs()}
    if "input_ids" not in input_names or "attention_mask" not in input_names:
        raise RuntimeError(f"Unexpected ALBERT ONNX inputs: {sorted(input_names)}")
    return tokenizer, session, input_names, np


def _word_spans(text: str):
    return list(re.finditer(r"\S+", text, flags=re.UNICODE))


def _insert_marks(text: str, spans, offsets, predictions) -> str:
    """Map first-subtoken labels back to complete whitespace-delimited Persian words."""
    insertions = []
    for word in spans:
        start, end = word.span()
        token_indices = [
            index for index, (token_start, token_end) in enumerate(offsets)
            if token_end > token_start and token_start < end and token_end > start
        ]
        if not token_indices or int(predictions[token_indices[0]]) != 1:
            continue

        mark_at = end
        while mark_at > start and text[mark_at - 1] in _TRAILING_PUNCTUATION:
            mark_at -= 1
        if mark_at <= start:
            continue
        word_text = text[start:mark_at]
        if _EZAFE in word_text:
            continue
        insertions.append(mark_at)

    result = text
    for position in reversed(insertions):
        result = result[:position] + _EZAFE + result[position:]
    return result


def add_persian_ezafe(text: str) -> str:
    """Insert predicted kasra-ezafe marks; on any inference failure return source text."""
    global _last_error
    source = str(text or "")
    if not source.strip() or not is_enabled():
        return source

    try:
        tokenizer, session, input_names, np = _load_predictor()
        encoded = tokenizer(
            source,
            return_tensors="np",
            return_offsets_mapping=True,
            truncation=True,
            max_length=_MAX_TOKENS,
        )
        offsets = encoded.pop("offset_mapping")[0].tolist()
        inputs = {
            name: np.asarray(encoded[name])
            for name in input_names
            if name in encoded
        }
        if not inputs:
            raise RuntimeError("ALBERT tokenizer produced no supported ONNX inputs")
        logits = session.run(None, inputs)[0]
        predictions = np.asarray(logits).argmax(axis=-1)[0]
        spans = _word_spans(source)
        covered_end = max((end for start, end in offsets if end > start), default=0)
        # A tokenization boundary inside a word is not sufficient evidence to edit it.
        covered_spans = [span for span in spans if span.end() <= covered_end]
        _last_error = ""
        return _insert_marks(source, covered_spans, offsets, predictions)
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"[:500]
        _log.warning("Persian ezafe inference failed; original text will be synthesized: %s", _last_error)
        return source


def warmup() -> bool:
    """Load the optional detector without making its failure fatal to Piper."""
    if not is_enabled():
        return False
    try:
        _load_predictor()
        return True
    except Exception:
        return False


def status() -> dict:
    """Return diagnostics without triggering model loading or network access."""
    with _lock:
        retry_in = max(0.0, _retry_after - time.monotonic()) if _retry_after else 0.0
        return {
            "enabled": is_enabled(),
            "loaded": _predictor is not None,
            "model": _MODEL_ID if _predictor is not None else "",
            "error": _last_error[:240],
            "load_failures": _load_failures,
            "retry_in_seconds": round(retry_in, 1),
            "cache_dir": str(_cache_directory()) if _predictor is not None else "",
        }
