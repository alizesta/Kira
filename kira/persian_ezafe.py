"""Optional ONNX ALBERT preprocessing for Persian ezafe in local TTS.

The detector is isolated from Piper: it shares Kira's Hugging Face cache, retries
transient initialization failures, runs on CPU, and preserves source text on failure.
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
_EZAFE = "\\u0650"
_TRAILING_PUNCTUATION = frozenset("،؛:,.!?؟…)]}»\\\"'")
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_RETRY_DELAY_SECONDS = 30.0

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_predictor = None
_next_retry_at = 0.0
_last_error = ""


def is_enabled() -> bool:
    """Whether neural ezafe insertion is enabled (enabled by default)."""
    return (
        str(os.environ.get("KIRA_TTS_EZAFE", "1")).strip().casefold()
        not in _FALSE_VALUES
    )


def _load_predictor():
    """Load once after success; retry transient failures after a short cooldown."""
    global _predictor, _next_retry_at, _last_error

    with _lock:
        if _predictor is not None:
            return _predictor

        if time.monotonic() < _next_retry_at:
            raise RuntimeError(
                _last_error or "ALBERT initialization is in retry cooldown"
            )

        try:
            predictor = _initialize_predictor()
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            _next_retry_at = time.monotonic() + _RETRY_DELAY_SECONDS
            logger.warning(
                "Optional Persian ezafe initialization failed; retry allowed "
                "after cooldown: %s",
                _last_error,
            )
            raise

        _predictor = predictor
        _last_error = ""
        _next_retry_at = 0.0
        return predictor


def _initialize_predictor():
    """Download/load ALBERT from the same cache root used by local Piper models."""
    from huggingface_hub import snapshot_download
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    from .local_voice import cache_directory

    kwargs = {
        "repo_id": _MODEL_ID,
        "cache_dir": cache_directory(),
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
        str(model_dir),
        use_fast=True,
        local_files_only=True,
    )
    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError("ALBERT tokenizer must support offset mappings")

    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    input_names = {item.name for item in session.get_inputs()}
    required_inputs = {"input_ids", "attention_mask"}
    if not required_inputs.issubset(input_names):
        raise RuntimeError(
            f"Unexpected ALBERT ONNX inputs: {sorted(input_names)}"
        )

    return tokenizer, session, input_names, np


def _word_spans(text: str):
    """Return whitespace-delimited source spans while preserving original offsets."""
    return list(re.finditer(r"\\S+", text, flags=re.UNICODE))


def _word_is_fully_covered(start: int, end: int, offsets) -> bool:
    """Reject a word if truncation or offset gaps leave any lexical characters unseen."""
    cursor = start
    spans = sorted(
        (token_start, token_end)
        for token_start, token_end in offsets
        if token_end > token_start and token_start < end and token_end > start
    )
    for token_start, token_end in spans:
        if token_start > cursor:
            return False
        cursor = max(cursor, token_end)
        if cursor >= end:
            return True
    return False


def _insert_marks(text: str, spans, offsets, predictions) -> str:
    """Map first-subtoken labels back to complete words and insert kasra-ezafe."""
    insertions = []

    for word in spans:
        start, end = word.span()
        mark_at = end
        while mark_at > start and text[mark_at - 1] in _TRAILING_PUNCTUATION:
            mark_at -= 1

        if mark_at <= start or not _word_is_fully_covered(start, mark_at, offsets):
            continue

        token_indices = [
            index
            for index, (token_start, token_end) in enumerate(offsets)
            if token_end > token_start
            and token_start < mark_at
            and token_end > start
        ]
        if not token_indices or int(predictions[token_indices[0]]) != 1:
            continue
        if _EZAFE in text[start:mark_at]:
            continue

        insertions.append(mark_at)

    result = text
    for position in reversed(insertions):
        result = result[:position] + _EZAFE + result[position:]
    return result


def add_persian_ezafe(text: str) -> str:
    """Insert predicted kasra-ezafe marks; preserve the original text on failure."""
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
        missing = input_names - set(inputs)
        if missing:
            raise RuntimeError(
                f"Tokenizer omitted required ONNX input tensors: {sorted(missing)}"
            )

        logits = session.run(None, inputs)[0]
        predictions = np.asarray(logits).argmax(axis=-1)[0]
        if len(predictions) != len(offsets):
            raise RuntimeError(
                "ALBERT output length does not match tokenizer offsets"
            )

        return _insert_marks(source, _word_spans(source), offsets, predictions)
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "Persian ezafe inference skipped; original text preserved: %s",
            _last_error,
        )
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
    """Return a thread-safe, non-loading diagnostic snapshot."""
    with _lock:
        return {
            "enabled": is_enabled(),
            "loaded": _predictor is not None,
            "model": _MODEL_ID if _predictor is not None else "",
            "error": _last_error[:240],
            "retry_in_seconds": max(
                0,
                int(_next_retry_at - time.monotonic()),
            ),
        }
