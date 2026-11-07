"""Ollama client tuned for a gaming PC: bounded context, short keep-alive, clear errors.

Diagnostics:  .venv\\Scripts\\python.exe -m kira.ollama_client
"""
from __future__ import annotations

import json
import re
import requests

DEFAULT_NUM_CTX = 4096
DEFAULT_KEEP_ALIVE = "2m"
DEFAULT_NUM_PREDICT = 512          # max reply length in tokens: stops a runaway/slow generation
MIN_NUM_CTX, MAX_NUM_CTX = 1024, 32768
REPLY_RESERVE_TOKENS = 768          # room kept free for the model's answer
CHARS_PER_TOKEN = 2.0               # conservative for Persian text


class OllamaError(RuntimeError):
    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind


_DURATION_RE = re.compile(r"^\d+(\.\d+)?(ms|s|m|h)$", re.I)


def parse_keep_alive(value):
    """Return (value_for_api, valid). Accepts 2m / 30s / 1h / 0 / -1 / plain seconds."""
    if value is None or str(value).strip() == "":
        return DEFAULT_KEEP_ALIVE, False
    text = str(value).strip().lower()
    if re.fullmatch(r"-?\d+", text):
        return int(text), True
    if _DURATION_RE.match(text):
        return text, True
    return DEFAULT_KEEP_ALIVE, False


def clamp_num_ctx(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_NUM_CTX
    return max(MIN_NUM_CTX, min(MAX_NUM_CTX, value))


def _family(name):
    """'qwen3.5:4b' / 'Qwen3.5:latest' / 'qwen35:latest' -> 'qwen35' (letters and digits of the part before ':')."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").split(":")[0].lower())


def resolve_model(models, wanted):
    """Pick the installed model name that matches the wanted one, or None.

    1. exact name; 2. no tag given (qwen3.5) -> qwen3.5:latest or any tag; 3. the same model family installed under
    the ':latest' tag (qwen3.5:4b wanted, qwen3.5:latest installed -- what `ollama create`/a local GGUF import gives).
    A different explicit size is never substituted (qwen3.5:9b is not accepted for qwen3.5:4b)."""
    wanted = (wanted or "").strip()
    if not wanted:
        return None
    for name in models:
        if name == wanted:
            return name
    if ":" not in wanted:
        tagged = [n for n in models if n.split(":")[0] == wanted]
        if tagged:
            return next((n for n in tagged if n.endswith(":latest")), tagged[0])
    family = _family(wanted)
    for name in models:
        if name.endswith(":latest") and _family(name) == family:
            return name
    return None


def clamp_num_predict(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_NUM_PREDICT
    return max(32, min(4096, value))


def model_installed(models, wanted):
    return resolve_model(models, wanted) is not None


def fit_messages(messages, system_prompt, num_ctx, reserve=REPLY_RESERVE_TOKENS):
    """Keep the newest messages that fit the context budget (system prompt always kept)."""
    budget = max(200, int((clamp_num_ctx(num_ctx) - reserve) * CHARS_PER_TOKEN) - len(system_prompt or ""))
    kept, used = [], 0
    for item in reversed(messages):
        content = str(item.get("content") or "")
        if kept and used + len(content) > budget:
            break
        if not kept and len(content) > budget:          # newest message alone is too long: trim its start
            content = content[-budget:]
        entry = {"role": item["role"], "content": content}
        if item.get("images"):                              # Ollama vision models take a plain list of base64 strings
            entry["images"] = [i["b64"] for i in item["images"] if isinstance(i, dict) and i.get("b64")]
        kept.append(entry)
        used += len(content)
    return list(reversed(kept))


class OllamaClient:
    def __init__(self, base_url, model, num_ctx=DEFAULT_NUM_CTX, keep_alive=DEFAULT_KEEP_ALIVE, timeout=180,
                 num_predict=DEFAULT_NUM_PREDICT):
        self.base_url = str(base_url or "http://localhost:11434").rstrip("/")
        self.model = str(model or "").strip()
        self.num_ctx = clamp_num_ctx(num_ctx)
        self.keep_alive, _ = parse_keep_alive(keep_alive)
        self.timeout = max(10, int(timeout or 180))
        self.num_predict = clamp_num_predict(num_predict)
        self._no_think = False
        self._resolved = None            # installed name actually used when it differs from the configured one
        self.last_stats = None           # filled after a streamed answer: load/eval durations and token counts
        self._stream_resp = None

    @property
    def active_model(self):
        return self._resolved or self.model

    def resolve_installed(self):
        """Look at what is installed and remember the matching name. Returns it (or None)."""
        ok, models = self.status()
        if not ok:
            return None
        name = resolve_model(models, self.model)
        self._resolved = name if name and name != self.model else None
        return name

    @classmethod
    def from_settings(cls, settings):
        cfg = (settings.get("providers") or {}).get("ollama") or {}
        return cls(settings.get("ollama_url") or cfg.get("base_url") or "http://localhost:11434",
                   settings.get("model") or cfg.get("model") or "qwen3.5:4b",
                   cfg.get("num_ctx", DEFAULT_NUM_CTX), cfg.get("keep_alive", DEFAULT_KEEP_ALIVE),
                   cfg.get("timeout", 180), cfg.get("num_predict", DEFAULT_NUM_PREDICT))

    # ---------- helpers ----------
    def _offline(self, exc):
        return OllamaError(f"Ollama در دسترس نیست (آدرس {self.base_url}). برنامه Ollama را اجرا کن؛ "
                           f"در ویندوز از منوی Start، یا در CMD دستور «ollama serve».", "offline")

    def _missing(self):
        ok, models = self.status()
        have = ("؛ مدل‌های نصب‌شده: " + ", ".join(models)) if ok and models else ""
        return OllamaError(f"مدل «{self.model}» روی این کامپیوتر نصب نیست{have}. در Kira نام یکی از مدل‌های نصب‌شده را انتخاب کن "
                           f"یا در CMD اجرا کن: ollama pull {self.model}", "missing")

    @staticmethod
    def _error_text(response):
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                return str(data["error"])[:300]
        except ValueError:
            pass
        return (response.text or "")[:300].replace("\n", " ")

    def _get(self, path, timeout=3):
        try:
            return requests.get(f"{self.base_url}{path}", timeout=timeout)
        except requests.ConnectionError as exc:
            raise self._offline(exc) from exc
        except requests.Timeout as exc:
            raise OllamaError("Ollama در زمان مناسب پاسخ نداد.", "timeout") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"خطای شبکه در ارتباط با Ollama: {exc}", "network") from exc

    def _post(self, path, payload, timeout):
        try:
            return requests.post(f"{self.base_url}{path}", json=payload, timeout=timeout)
        except requests.ConnectionError as exc:
            raise self._offline(exc) from exc
        except requests.Timeout as exc:
            raise OllamaError("Ollama پاسخ نداد. اگر مدل تازه بارگذاری می‌شود، بار اول چند ده ثانیه طول می‌کشد؛ دوباره امتحان کن.",
                              "timeout") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"خطای شبکه در ارتباط با Ollama: {exc}", "network") from exc

    # ---------- status / resources ----------
    def status(self):
        """(True, [installed model names]) or (False, readable error). Never raises."""
        try:
            r = self._get("/api/tags", timeout=2)
            r.raise_for_status()
            return True, [m.get("name", "") for m in r.json().get("models", [])]
        except OllamaError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)

    def version(self):
        r = self._get("/api/version")
        r.raise_for_status()
        return str(r.json().get("version", "?"))

    def running(self):
        """Models currently loaded in memory (from /api/ps)."""
        r = self._get("/api/ps")
        r.raise_for_status()
        return r.json().get("models", []) or []

    def describe(self):
        """(ok, multi-line text) summary for the settings page. Never raises."""
        try:
            ver = self.version()
            ok, models = self.status()
            lines = [f"Ollama {ver} روشن است."]
            if ok:
                found = resolve_model(models, self.model)
                if found == self.model:
                    lines.append(f"مدل «{self.model}» نصب است.")
                elif found:
                    lines.append(f"مدل «{self.model}» با همین نام نصب نیست، اما «{found}» نصب است و از آن استفاده می‌شود.")
                else:
                    have = (" نصب‌شده‌ها: " + ", ".join(models)) if models else ""
                    lines.append(f"مدل «{self.model}» نصب نیست؛ دستور: ollama pull {self.model}.{have}")
            for m in self.running():
                size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
                where = "نامشخص"
                if size:
                    pct = round(100 * vram / size)
                    where = f"{pct}٪ روی GPU" + ("" if pct >= 100 else " (بقیه روی CPU/RAM؛ هنگام بازی ممکن است سنگین باشد)")
                lines.append(f"در حافظه: {m.get('name')} | {size / 1e9:.1f}GB | {where} | انقضا: {m.get('expires_at', '?')}")
            if len(lines) == (2 if ok else 1):
                lines.append("هیچ مدلی الان در حافظه بارگذاری نیست (منابع GPU آزاد است).")
            return True, "\n".join(lines)
        except OllamaError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"خطا: {exc}"

    def preload(self):
        self.resolve_installed()
        r = self._post("/api/generate", {"model": self.active_model, "keep_alive": self.keep_alive,
                                          "options": {"num_ctx": self.num_ctx}}, self.timeout)
        if r.status_code == 404:
            raise self._missing()
        if r.status_code >= 400:
            raise OllamaError(f"بارگذاری مدل ناموفق بود: {self._error_text(r)}", "load")

    def unload(self):
        self.resolve_installed()
        r = self._post("/api/generate", {"model": self.active_model, "keep_alive": 0}, 15)
        if r.status_code == 404:
            return                      # not installed -> nothing is loaded
        if r.status_code >= 400:
            raise OllamaError(f"آزادسازی مدل ناموفق بود: {self._error_text(r)}", "unload")

    def benchmark(self):
        """One tiny real generation; reports load time, speed (tokens/s) and GPU share. Never raises. (ok, text)"""
        try:
            self.resolve_installed()
            payload = {"model": self.active_model, "stream": False, "keep_alive": self.keep_alive,
                       "messages": [{"role": "system", "content": "Answer very briefly."},
                                    {"role": "user", "content": "سلام"}],
                       "options": {"num_ctx": self.num_ctx, "num_predict": 24, "temperature": 0.3}}
            if not self._no_think:
                payload["think"] = False
            r = self._post("/api/chat", payload, 600)
            if r.status_code == 400 and "think" in r.text.lower():
                payload.pop("think")
                self._no_think = True
                r = self._post("/api/chat", payload, 600)
            if r.status_code == 404:
                raise self._missing()
            if r.status_code >= 400:
                return False, f"خطای Ollama ({r.status_code}): {self._error_text(r)}"
            d = r.json()
            sec = lambda k: (d.get(k) or 0) / 1e9
            pe_n, ev_n = d.get("prompt_eval_count") or 0, d.get("eval_count") or 0
            pe_s, ev_s, load_s, total_s = sec("prompt_eval_duration"), sec("eval_duration"), sec("load_duration"), sec("total_duration")
            gen_speed = ev_n / ev_s if ev_s else 0
            lines = [f"زمان کل: {total_s:.1f}s | بارگذاری مدل: {load_s:.1f}s",
                     f"پردازش پرسش: {pe_n} توکن در {pe_s:.1f}s" + (f" ({pe_n / pe_s:.0f} توکن/ثانیه)" if pe_s else ""),
                     f"تولید پاسخ: {ev_n} توکن" + (f" با سرعت {gen_speed:.1f} توکن/ثانیه" if ev_s else "")]
            try:
                for m in self.running():
                    size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
                    if size:
                        lines.append(f"روی GPU: {round(100 * vram / size)}٪")
            except OllamaError:
                pass
            if ev_s and gen_speed < 5:
                lines.append("⚠ سرعت خیلی پایین است؛ احتمالاً مدل روی CPU اجرا می‌شود. پاسخ‌های واقعی چند دقیقه طول می‌کشند.")
            elif ev_s and gen_speed < 12:
                lines.append("سرعت متوسط است؛ پاسخ‌های بلند چند ده ثانیه طول می‌کشند.")
            return True, "\n".join(lines)
        except OllamaError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"خطا: {exc}"

    # ---------- chat ----------
    def chat(self, messages, system_prompt, temperature=0.7):
        from .hybrid_ai import normalize_messages          # local import: avoids a circular import
        clean = fit_messages(normalize_messages(messages), system_prompt, self.num_ctx)
        if not clean:
            raise OllamaError("هیچ پیام کاربری برای ارسال وجود ندارد.", "request")
        payload = {
            "model": self.active_model,
            "messages": [{"role": "system", "content": system_prompt}, *clean],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": float(temperature), "num_ctx": self.num_ctx, "num_predict": self.num_predict},
        }
        if not self._no_think:
            payload["think"] = False     # thinking models (qwen3.5 ...) otherwise answer inside "thinking"
        r = self._post("/api/chat", payload, self.timeout)
        if r.status_code == 400 and "think" in r.text.lower() and "think" in payload:
            payload.pop("think")         # model has no thinking support
            self._no_think = True
            r = self._post("/api/chat", payload, self.timeout)
        if r.status_code == 404 and self.resolve_installed() and self.active_model != payload["model"]:
            payload["model"] = self.active_model         # e.g. configured qwen3.5:4b, installed as qwen3.5:latest
            r = self._post("/api/chat", payload, self.timeout)
        if r.status_code == 404:
            raise self._missing()
        if r.status_code >= 400:
            detail = self._error_text(r)
            kind = "memory" if "memory" in detail.lower() else "error"
            raise OllamaError(f"خطای Ollama ({r.status_code}): {detail}", kind)
        try:
            data = r.json()
        except ValueError as exc:
            raise OllamaError("پاسخ Ollama قابل خواندن نبود.", "response") from exc
        msg = data.get("message") or {}
        content = msg.get("content") or data.get("response") or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S)
        content = re.sub(r"<think>.*$", "", content, flags=re.S).strip()
        if not content:
            detail = msg.get("thinking") or data.get("error") or "The model returned no visible content."
            raise OllamaError("مدل پاسخ مفیدی نداد (خالی بود). " + str(detail)[:240], "empty")
        return content

    # ---------- streaming ----------
    def abort(self):
        """Close the open HTTP stream (called from another thread when the user presses Stop)."""
        resp = getattr(self, "_stream_resp", None)
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def _open_stream(self, payload):
        """POST /api/chat with stream=True. Same 400(think)/404(alias) recovery as chat(). Returns the open response."""
        timeout = (min(10, self.timeout), self.timeout)           # (connect, wait-between-chunks)
        try:
            r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout, stream=True)
        except requests.ConnectionError as exc:
            raise self._offline(exc) from exc
        except requests.Timeout as exc:
            raise OllamaError("Ollama پاسخ نداد. اگر مدل تازه بارگذاری می‌شود، بار اول چند ده ثانیه طول می‌کشد.", "timeout") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"خطای شبکه در ارتباط با Ollama: {exc}", "network") from exc
        return r

    def stream(self, messages, system_prompt, temperature=0.7, on_connect=None, max_tokens=None):
        """Yield visible text chunks as Ollama produces them (NDJSON). Raises OllamaError. Fills self.last_stats at the end."""
        from .hybrid_ai import normalize_messages, ThinkFilter
        clean = fit_messages(normalize_messages(messages), system_prompt, self.num_ctx)
        if not clean:
            raise OllamaError("هیچ پیام کاربری برای ارسال وجود ندارد.", "request")
        payload = {
            "model": self.active_model,
            "messages": [{"role": "system", "content": system_prompt}, *clean],
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {"temperature": float(temperature), "num_ctx": self.num_ctx,
                        "num_predict": clamp_num_predict(max_tokens) if max_tokens else self.num_predict},
        }
        if not self._no_think:
            payload["think"] = False
        self.last_stats = None
        r = self._open_stream(payload)
        if r.status_code == 400 and "think" in (r.text or "").lower() and "think" in payload:
            r.close()
            payload.pop("think")
            self._no_think = True
            r = self._open_stream(payload)
        if r.status_code == 404 and self.resolve_installed() and self.active_model != payload["model"]:
            r.close()
            payload["model"] = self.active_model
            r = self._open_stream(payload)
        if r.status_code == 404:
            r.close()
            raise self._missing()
        if r.status_code >= 400:
            detail = self._error_text(r)
            r.close()
            kind = "memory" if "memory" in detail.lower() else "error"
            raise OllamaError(f"خطای Ollama ({r.status_code}): {detail}", kind)
        self._stream_resp = r
        if on_connect:
            on_connect()
        flt = ThinkFilter()
        try:
            for raw in r.iter_lines():
                if not raw:
                    continue
                try:
                    data = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
                except ValueError:
                    continue
                if data.get("error"):
                    raise OllamaError(f"خطای Ollama: {str(data['error'])[:300]}", "error")
                piece = flt.feed((data.get("message") or {}).get("content") or data.get("response") or "")
                if piece:
                    yield piece
                if data.get("done"):
                    self.last_stats = {"load_ms": int((data.get("load_duration") or 0) / 1e6),
                                       "prompt_tokens": data.get("prompt_eval_count") or 0,
                                       "eval_tokens": data.get("eval_count") or 0,
                                       "eval_ms": int((data.get("eval_duration") or 0) / 1e6),
                                       "total_ms": int((data.get("total_duration") or 0) / 1e6)}
                    break
            tail = flt.flush()
            if tail:
                yield tail
        except requests.Timeout as exc:
            raise OllamaError("Ollama وسط پاسخ ساکت شد (Timeout).", "timeout") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"ارتباط با Ollama وسط پاسخ قطع شد: {exc}", "network") from exc
        finally:
            self._stream_resp = None
            try:
                r.close()
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    from .config import load_settings
    client = OllamaClient.from_settings(load_settings())
    print(f"آدرس: {client.base_url} | مدل: {client.model} | num_ctx={client.num_ctx} | keep_alive={client.keep_alive}")
    ok, text = client.describe()
    print(text)
    sys.exit(0 if ok else 1)
