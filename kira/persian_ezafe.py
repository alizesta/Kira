"""Optional ONNX ALBERT preprocessing for Persian ezafe in local TTS."""
from __future__ import annotations
import logging, os, re, threading, time
from pathlib import Path

_MODEL_ID = "abreza/persian-ezafe-albert"
_MODEL_FILE = Path("quantized") / "model_quantized.onnx"
_MAX_TOKENS = 512
_EZAFE = "\u0650"
_TRAILING_PUNCTUATION = frozenset("،؛:,.!?؟…)]}»\\"'")
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_RETRY_DELAY_SECONDS = 30.0
logger = logging.getLogger(__name__)
_lock = threading.RLock()
_predictor = None
_next_retry_at = 0.0
_last_error = ""

def is_enabled() -> bool:
    return str(os.environ.get("KIRA_TTS_EZAFE", "1")).strip().casefold() not in _FALSE_VALUES

def _load_predictor():
    global _predictor, _next_retry_at, _last_error
    with _lock:
        if _predictor is not None: return _predictor
        if time.monotonic() < _next_retry_at:
            raise RuntimeError(_last_error or "ALBERT initialization is in retry cooldown")
        try:
            predictor = _initialize_predictor()
            _predictor, _last_error, _next_retry_at = predictor, "", 0.0
            return predictor
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            _next_retry_at = time.monotonic() + _RETRY_DELAY_SECONDS
            logger.warning("Optional Persian ezafe initialization failed; retry allowed after cooldown: %s", _last_error)
            raise

def _initialize_predictor():
    from huggingface_hub import snapshot_download
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer
    from .local_voice import cache_directory
    kwargs = {"repo_id": _MODEL_ID, "cache_dir": cache_directory(), "allow_patterns": ["quantized/*"]}
    try: snapshot = snapshot_download(local_files_only=True, **kwargs)
    except Exception: snapshot = snapshot_download(local_files_only=False, **kwargs)
    model_dir = Path(snapshot) / "quantized"
    model_path = model_dir / _MODEL_FILE.name
    if not model_path.is_file(): raise FileNotFoundError(f"ALBERT ONNX weights not found: {model_path}")
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), use_fast=True, local_files_only=True)
    if not getattr(tokenizer, "is_fast", False): raise RuntimeError("ALBERT tokenizer must support offset mappings")
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
    names = {item.name for item in session.get_inputs()}
    if not {"input_ids", "attention_mask"}.issubset(names):
        raise RuntimeError(f"Unexpected ALBERT ONNX inputs: {sorted(names)}")
    return tokenizer, session, names, np

def _word_spans(text: str):
    return list(re.finditer(r"\S+", text, flags=re.UNICODE))

def _insert_marks(text: str, spans, offsets, predictions) -> str:
    insertions = []
    for word in spans:
        start, end = word.span()
        mark_at=end
        while mark_at>start and text[mark_at-1] in _TRAILING_PUNCTUATION: mark_at-=1
        indices = [i for i,(a,b) in enumerate(offsets) if b>a and a<mark_at and b>start]
        # Require complete lexical coverage, but punctuation need not be tokenized.
        if not indices or max(offsets[i][1] for i in indices) < mark_at: continue
        if int(predictions[indices[0]]) != 1: continue
        if mark_at<=start or _EZAFE in text[start:mark_at]: continue
        insertions.append(mark_at)
    result=text
    for pos in reversed(insertions): result=result[:pos]+_EZAFE+result[pos:]
    return result

def add_persian_ezafe(text: str) -> str:
    global _last_error
    source=str(text or "")
    if not source.strip() or not is_enabled(): return source
    try:
        tokenizer,session,names,np=_load_predictor()
        encoded=tokenizer(source,return_tensors="np",return_offsets_mapping=True,truncation=True,max_length=_MAX_TOKENS)
        offsets=encoded.pop("offset_mapping")[0].tolist()
        inputs={name:np.asarray(encoded[name]) for name in names if name in encoded}
        if not {"input_ids","attention_mask"}.issubset(inputs):
            raise RuntimeError("Tokenizer omitted required ONNX input tensors")
        logits=session.run(None,inputs)[0]
        predictions=np.asarray(logits).argmax(axis=-1)[0]
        if len(predictions)!=len(offsets): raise RuntimeError("ALBERT output length does not match tokenizer offsets")
        return _insert_marks(source,_word_spans(source),offsets,predictions)
    except Exception as exc:
        _last_error=f"{type(exc).__name__}: {exc}"
        logger.warning("Persian ezafe inference skipped; original text preserved: %s",_last_error)
        return source

def warmup() -> bool:
    if not is_enabled(): return False
    try: _load_predictor(); return True
    except Exception: return False

def status() -> dict:
    with _lock:
        return {"enabled":is_enabled(),"loaded":_predictor is not None,
                "model":_MODEL_ID if _predictor is not None else "",
                "error":_last_error[:240],
                "retry_in_seconds":max(0,int(_next_retry_at-time.monotonic()))}
