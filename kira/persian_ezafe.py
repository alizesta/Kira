"""Optional ONNX ALBERT preprocessing for Persian ezafe in local TTS.

The detector is deliberately isolated from Piper. Its weights are downloaded lazily
into Kira's Hugging Face cache, inference runs on CPU, and any failure leaves the
original text untouched so voice output remains available.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

_MODEL_ID = "abreza/persian-ezafe-albert"
_MODEL_FILE = Path("quantized") / "model_quantized.onnx"
_MAX_TOKENS = 512
_EZAFE = "\u0650"
_TRAILING_PUNCTUATION = frozenset("،؛:,.!?؟…)]}»\"'")
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})

_lock = threading.RLock()
_predictor = None
_load_attempted = False
_last_error = ""


def is_enabled() -> bool:
    """Whether neural ezafe insertion is enabled (enabled by default)."""
    return str(os.environ.get("KIRA_TTS_EZAFE", "1")).strip().casefold() not in _FALSE_VALUES


def _load_predictor():
    """Load the quantized ONNX model and its matching tokenizer once per process."""
    global _predictor, _load_attempted, _last_error
    with _lock:
        if _predictor is not None:
            return _predictor
        if _load_attempted:
            raise RuntimeError(_last_error or "ALBERT initialization already failed in this process")
        _load_attempted = True

        try:
            return _initialize_predictor()
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            raise


def _initialize_predictor():
        global _predictor, _last_error
        from huggingface_hub import snapshot_download
        import numpy as np
        import onnxruntime as ort
        from transformers import AutoTokenizer

        cache_dir = os.environ.get("HF_HUB_CACHE")
        kwargs = {
            "repo_id": _MODEL_ID,
            "allow_patterns": ["quantized/*"],
        }
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
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

        _predictor = (tokenizer, session, input_names, np)
        _last_error = ""
        return _predictor


def _word_spans(text: str):
    return list(re.finditer(r"\S+", text, flags=re.UNICODE))


def _insert_marks(text: str, spans, offsets, predictions) -> str:
    """Map first-subtoken labels back to whitespace-delimited Persian words."""
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
        # Keep existing vowel marks attached to their base letter and avoid
        # inserting a duplicate kasra.
        insertions.append(mark_at)

    result = text
    for position in reversed(insertions):
        result = result[:position] + _EZAFE + result[position:]
    return result


def add_persian_ezafe(text: str) -> str:
    """Insert predicted kasra-ezafe marks; return the original text on any failure."""
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
        logits = session.run(None, inputs)[0]
        predictions = np.asarray(logits).argmax(axis=-1)[0]
        spans = _word_spans(source)
        # Avoid modifying words beyond the tokenizer's truncation boundary.
        covered_end = max((end for start, end in offsets if end > start), default=0)
        covered_spans = [span for span in spans if span.start() < covered_end]
        return _insert_marks(source, covered_spans, offsets, predictions)
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        return source


def warmup() -> bool:
    """Load the optional detector in a background warmup without blocking Piper."""
    global _last_error
    if not is_enabled():
        return False
    try:
        _load_predictor()
        return True
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        return False


def status() -> dict:
    """Return a small, non-loading diagnostic snapshot."""
    return {
        "enabled": is_enabled(),
        "loaded": _predictor is not None,
        "model": _MODEL_ID if _predictor is not None else "",
        "error": _last_error[:240],
    }
