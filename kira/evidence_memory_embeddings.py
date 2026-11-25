"""Replaceable embedding-provider adapters and validated embedding execution."""
from __future__ import annotations
import contextlib
import math
import time
from typing import Protocol
from .evidence_memory_models import EvidenceVector

INDEX_VERSION = 1
EMBED_BATCH = 16
EMBED_FAIL_COOLDOWN = 600
QUERY_FAIL_COOLDOWN = 60
EMBED_TIMEOUT = (4, 20)
QUERY_TIMEOUT = (1.5, 3.0)

class EmbeddingProvider(Protocol):
    """Return one finite, same-dimensional vector per input text."""
    def embed(self, texts: list[str], config: dict, settings: dict, timeout) -> tuple[list[list[float]], int | None]:
        ...

class OllamaEmbeddingProvider:
    def embed(self, texts: list[str], config: dict, settings: dict, timeout):
        import requests
        response = requests.post(config["url"], json={"model": config["model"], "input": texts, "keep_alive": "2m"}, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        return body.get("embeddings"), body.get("prompt_eval_count")

class OpenAICompatibleEmbeddingProvider:
    """Adapter for configured Kira providers exposing an OpenAI-compatible embeddings endpoint."""
    def embed(self, texts: list[str], config: dict, settings: dict, timeout):
        import requests
        from .hybrid_ai import provider_class
        provider_id = config["pid"]
        provider_config = (settings.get("providers") or {}).get(provider_id) or {}
        provider_type = provider_class(provider_id, provider_config)
        if provider_type is None or not provider_config.get("enabled", True):
            raise RuntimeError("embedding provider is not usable")
        provider = provider_type(provider_config, provider_id)
        base = provider._base() if hasattr(provider, "_base") else ""
        if not base or (provider.needs_key and not provider.secret):
            raise RuntimeError("embedding provider has no endpoint or key")
        headers = {"Content-Type": "application/json"}
        if provider.secret:
            headers["Authorization"] = f"Bearer {provider.secret}"
        response = requests.post(base + "/embeddings", json={"model": config["model"], "input": texts},
                                 headers=headers, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        data = sorted(body.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in data]
        tokens = (body.get("usage") or {}).get("prompt_tokens")
        return vectors, tokens

def build_embedding_config(settings) -> dict | None:
    settings = settings if isinstance(settings, dict) else {}
    backend = str(settings.get("embedding_backend", "off")).lower()
    model = str(settings.get("embedding_model", "")).strip()
    if backend not in ("ollama", "provider") or not model:
        return None
    if backend == "ollama":
        provider_config = (settings.get("providers") or {}).get("ollama") or {}
        base_url = str(provider_config.get("base_url") or settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
        provider_id, url, kind = "ollama", base_url + "/api/embed", "ollama"
    else:
        provider_id = str(settings.get("embedding_provider", "")).strip()
        if not provider_id:
            return None
        url, kind = None, "provider"
    # Provider/model identity and index format are part of the key; changed models never reuse stale vectors.
    tag = f"kira-index-v{INDEX_VERSION}:{kind}:{provider_id}:{model}"
    return {"kind": kind, "model": model, "pid": provider_id if kind == "provider" else "",
            "url": url, "provider": provider_id, "tag": tag, "index_version": INDEX_VERSION}

class EmbeddingService:
    """Runs replaceable adapters without owning or mutating evidence storage."""
    def __init__(self, providers=None):
        self.providers = providers or {"ollama": OllamaEmbeddingProvider(), "provider": OpenAICompatibleEmbeddingProvider()}

    @staticmethod
    def _validated(vectors, expected_count: int) -> list[list[float]]:
        if not isinstance(vectors, list) or len(vectors) != expected_count:
            raise ValueError("embedding response count does not match input count")
        normalized, dimensions = [], set()
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding response contains an empty vector")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
                raise ValueError("embedding response contains a non-numeric value")
            values = [float(value) for value in vector]
            if any(not math.isfinite(value) for value in values):
                raise ValueError("embedding response contains a non-finite value")
            dimensions.add(len(values))
            normalized.append(values)
        if len(dimensions) > 1:
            raise ValueError("embedding response contains inconsistent dimensions")
        return normalized

    @staticmethod
    def report(config, started, ok, usage_hook=None, tokens=None, error=None) -> None:
        if usage_hook is None:
            return
        with contextlib.suppress(Exception):
            usage_hook({"role": "embedding", "provider": config.get("provider"), "model": config.get("model"),
                        "status": "success" if ok else "failed", "total_ms": int((time.monotonic() - started) * 1000),
                        "tokens_in": tokens, "error_kind": error,
                        "kind": "local" if config.get("kind") == "ollama" else "cloud"})

    def embed(self, texts: list[str], *, config: dict | None, settings: dict, query: bool,
              cooldown_until: float, set_cooldown, usage_hook=None):
        if config is None or not texts or time.time() < cooldown_until:
            return None
        started = time.monotonic()
        try:
            adapter = self.providers.get(config.get("kind"))
            if adapter is None:
                raise RuntimeError("embedding adapter is not registered")
            vectors, token_count = adapter.embed(texts, config, settings, QUERY_TIMEOUT if query else EMBED_TIMEOUT)
            result = self._validated(vectors, len(texts))
            self.report(config, started, True, usage_hook=usage_hook,
                        tokens=token_count if isinstance(token_count, int) else None)
            return result
        except Exception as exc:  # provider errors must not affect persisted evidence
            from time import time as current_time
            set_cooldown(current_time() + (QUERY_FAIL_COOLDOWN if query else EMBED_FAIL_COOLDOWN))
            self.report(config, started, False, usage_hook=usage_hook, error=type(exc).__name__)
            return None

def pack_vector(vector) -> bytes:
    return EvidenceVector.create("packing", "packing", vector).to_blob()

def unpack_vector(blob) -> list[float]:
    import array
    values = array.array("f")
    values.frombytes(bytes(blob))
    return list(values)

def cosine_similarity(left, right) -> float | None:
    if len(left) != len(right) or not left:
        return None
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if not left_norm or not right_norm:
        return None
    return sum(float(a) * float(b) for a, b in zip(left, right)) / (left_norm * right_norm)
