"""Cloud Voice: speech-to-text (STT) and text-to-speech (TTS) through Google AI Studio, Groq, ElevenLabs and MiniMax.

Rules this module keeps:
  * Voice models are NOT chat models: their keys, models and priority are stored here (cloud_voice.json), separate from the chat routes.
    The settings screen shows them inside the Route section, next to the chat Providers, but nothing is mixed: a voice model is never
    used for chat and a chat route is never used for speech.
  * What a provider can do is read from the provider itself (its model list with the user's own key); a capability that
    no valid key has is reported as unsupported, so the UI never shows it as available. ElevenLabs does not list its
    speech-to-text models, so those come from a small built-in catalogue and are marked as such.
  * Every provider can have any number of API keys. A key has its own label, switch, status, order and cool-down.
    The same model found through several keys of one provider is listed once but remembers every key that has it.
  * A request walks: providers in the user's order -> keys of that provider in the user's order. A rate-limit or quota
    answer (HTTP 429 and friends) puts THAT key on a cool-down (the provider's own Retry-After when it sends one) and the
    next key is tried. Nothing is added up: a model keeps the limits the provider gives it, one key at a time.
  * When every cloud service failed, the caller falls back to the local engine (Whisper / Edge + Windows voices).
  * The file lives in Kira's data folder (outside the program folder); API keys are protected with Windows DPAPI.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import time
import uuid
import wave
from copy import deepcopy
from pathlib import Path

import requests

from .secret_store import protect, unprotect

FILE_NAME = "cloud_voice.json"
PROVIDERS = ("groq", "google", "elevenlabs", "minimax")
LABELS = {"groq": "Groq", "google": "Google AI Studio", "elevenlabs": "ElevenLabs", "minimax": "MiniMax"}
KEY_URLS = {"groq": "https://console.groq.com/keys", "google": "https://aistudio.google.com/apikey",
            "elevenlabs": "https://elevenlabs.io/app/settings/api-keys", "minimax": "https://platform.minimax.io/user-center/basic-information/interface-key"}
KINDS = ("stt", "tts")

GOOGLE_BASE = "https://generativelanguage.googleapis.com/v1beta"
GROQ_BASE = "https://api.groq.com/openai/v1"
ELEVEN_BASE = "https://api.elevenlabs.io/v1"
MINIMAX_BASE = "https://api.minimax.io/v1"
MINIMAX_MODELS = ("speech-2.8-turbo", "speech-2.8-hd")
MINIMAX_DEFAULT_VOICE = "female-shaonv"

# ElevenLabs does not list its speech-to-text models through the API: this small catalogue is used and labelled as such.
ELEVEN_STT_CATALOG = ["scribe_v2", "scribe_v1"]
# Voices the providers document but do not list through the API (Google and Groq); the person may type any other name.
GOOGLE_VOICES = ["Kore", "Puck", "Zephyr", "Charon", "Fenrir", "Aoede", "Leda", "Orus"]
GROQ_VOICES = {"canopylabs/orpheus-v1-english": ["autumn", "diana", "hannah", "austin", "daniel", "troy"],
               "canopylabs/orpheus-arabic-saudi": ["fahad", "abdullah", "noura"]}
# Speaking styles. Only engines that can really follow them show the option (see tts_caps).
STYLE_PROMPTS = {"warm": "in a warm, friendly tone", "cheerful": "cheerfully", "calm": "in a calm, soothing voice",
                 "energetic": "with energy and excitement", "serious": "in a serious, composed tone", "soft": "softly and gently",
                 "whisper": "in a whisper"}
STYLE_LABELS = {"": "پیش‌فرض", "warm": "گرم و صمیمی", "cheerful": "شاد", "calm": "آرام", "energetic": "پرانرژی", "serious": "جدی",
                "soft": "نرم", "whisper": "نجوا"}


def tts_caps(provider: str, model: str = "") -> set:
    """What a cloud TTS provider/model really honours: 'rate', 'style' (style presets), 'style_degree' (how strong the style is).
    Pitch is not supported by any of them. Volume is applied by Kira's own player and always works."""
    model = str(model or "").lower()
    if provider == "google":
        return {"style"}
    if provider == "minimax":
        return {"rate", "style"}
    if provider == "elevenlabs":
        caps = {"rate"} if any(t in model for t in ("multilingual_v2", "turbo_v2_5", "flash_v2_5", "turbo_v2", "flash_v2")) else set()
        if "multilingual_v2" in model:
            caps |= {"style", "style_degree"}
        return caps
    return set()


GROQ_TTS_MAX_CHARS = 180                 # Orpheus takes short inputs; longer replies are cut at sentence ends and joined

COOLDOWN_RATE = 30.0                     # seconds, when the provider gives no Retry-After
COOLDOWN_QUOTA = 3600.0                  # the quota is used up: look again in an hour
COOLDOWN_MAX = 6 * 3600.0
HTTP_TIMEOUT = 25
LANG_NAMES = {"fa": "Persian (Farsi)", "en": "English", "ja": "Japanese", "ar": "Arabic"}


class CVError(Exception):
    """One failed request. kind: rate | quota | auth | model | server | network | other."""

    def __init__(self, kind, message, retry_after=None):
        super().__init__(message)
        self.kind, self.retry_after = kind, retry_after


class AllFailed(Exception):
    """No cloud service could do it (or none is configured); the caller continues with the local engine."""

    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


# ---------------------------------------------------------------- small helpers
def mask(key: str) -> str:
    key = str(key or "")
    return "•" * 6 + key[-4:] if len(key) > 8 else "•" * len(key)


def detect_lang(text: str) -> str:
    """fa | en | ja. Arabic script counts as Persian (Kira's main language); Latin-dominant text is English."""
    if re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text or ""):
        return "ja"
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    arabic = len(re.findall(r"[\u0600-\u06FF]", text or ""))
    return "en" if latin > arabic else "fa"


def wav_bytes(samples, rate: int) -> bytes:
    """float32 (-1..1) or int16 numpy samples, mono -> WAV file bytes (16-bit PCM)."""
    import numpy as np
    a = np.asarray(samples)
    if a.dtype != np.int16:
        a = (np.clip(a.astype(np.float32), -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(a.tobytes())
    return buf.getvalue()


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm)
    return buf.getvalue()


def concat_wavs(parts: list[bytes]) -> bytes:
    if len(parts) == 1:
        return parts[0]
    frames, params = [], None
    for blob in parts:
        with wave.open(io.BytesIO(blob), "rb") as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(params)
        out.writeframes(b"".join(frames))
    return buf.getvalue()


def chunk_text(text: str, limit: int) -> list[str]:
    """Cut at sentence ends (then spaces) so no piece is longer than `limit`."""
    pieces, cur = [], ""
    # Sentence ends include U+3002 (ideographic full stop), U+FF01 (fullwidth "!") and U+FF1F (fullwidth "?").
    for sent in re.split(r"(?<=[.!?؟۔\u3002\uff01\uff1f\n])\s*", text.strip()):
        if not sent:
            continue
        while len(sent) > limit:
            cut = sent.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if len(cur) + len(sent) + 1 <= limit:
            cur = (cur + " " + sent).strip()
        else:
            if cur:
                pieces.append(cur)
            cur = sent
    if cur:
        pieces.append(cur)
    return [p for p in pieces if p]


def _scrub(text: str, secret: str = "") -> str:
    text = str(text or "")
    if secret:
        text = text.replace(secret, "…")
    return re.sub(r"(AIza[0-9A-Za-z_\-]{10,}|gsk_[0-9A-Za-z]{10,}|sk_[0-9a-f]{10,})", "…", text)[:300]


def classify(provider: str, status: int, body: str, headers=None) -> tuple[str, float | None]:
    """HTTP answer -> (kind, retry_after seconds)."""
    low = (body or "").lower()
    retry = None
    try:
        retry = float((headers or {}).get("retry-after") or (headers or {}).get("Retry-After") or "")
    except (TypeError, ValueError):
        retry = None
    if status == 401 and "quota" in low:
        return "quota", retry                                    # ElevenLabs: quota_exceeded comes as 401
    if status in (401, 403) or (status == 400 and ("api key not valid" in low or "api_key_invalid" in low)):
        return "auth", None
    if status == 402:
        return "quota", retry
    if status == 429:
        daily = any(w in low for w in ("per day", "perday", "daily", "quota_exceeded", "insufficient_quota", "billing"))
        return ("quota" if daily else "rate"), retry
    if status == 404 or (status == 400 and ("model" in low or "terms" in low or "voice" in low)):
        return "model", None
    if status >= 500 or status == 408:
        return "server", retry
    return "other", None


def _raise_http(provider, r, secret):
    try:
        body = r.text
    except Exception:
        body = ""
    kind, retry = classify(provider, r.status_code, body, getattr(r, "headers", {}))
    msg = f"HTTP {r.status_code}"
    try:
        js = r.json()
        err = js.get("error") if isinstance(js, dict) else None
        detail = (err.get("message") if isinstance(err, dict) else err) or (js.get("detail") if isinstance(js, dict) else "")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("status") or ""
        if detail:
            msg += f": {detail}"
    except Exception:
        if body:
            msg += f": {body[:160]}"
    raise CVError(kind, _scrub(msg, secret), retry)


def _request(method, provider, url, secret, **kw):
    kw.setdefault("timeout", HTTP_TIMEOUT)
    try:
        r = requests.request(method, url, **kw) if method not in ("get", "post") else getattr(requests, method)(url, **kw)
    except requests.Timeout as exc:
        raise CVError("network", "timeout") from exc
    except requests.RequestException as exc:
        raise CVError("network", _scrub(f"{type(exc).__name__}", secret)) from exc
    if r.status_code != 200:
        _raise_http(provider, r, secret)
    return r


# ---------------------------------------------------------------- capability detection (one key)
def _google_headers(key):
    return {"x-goog-api-key": key, "Content-Type": "application/json"}


_GOOGLE_NOT_STT = ("tts", "embedding", "imagen", "image", "veo", "lyria", "aqa", "live", "robotics", "computer-use", "learnlm",
                   "native-audio", "gemma", "nano-banana")


def detect(provider: str, key: str) -> dict:
    """Ask the provider what this key can do. Returns {"stt": [...], "tts": [...], "voices": [...], "tts_langs": {...},
    "stt_source": "api"|"catalog"}; raises CVError (auth -> the key is invalid)."""
    if provider == "groq":
        r = _request("get", provider, f"{GROQ_BASE}/models", key, headers={"Authorization": f"Bearer {key}"})
        ids = [m.get("id", "") for m in (r.json().get("data") or []) if m.get("id")]
        tts = sorted(i for i in ids if "orpheus" in i.lower() or "playai-tts" in i.lower())
        voices = []
        for m in tts:
            voices += [v for v in GROQ_VOICES.get(m, []) if v not in voices]
        return {"stt": sorted(i for i in ids if "whisper" in i.lower()), "tts": tts, "voices": [{"id": v, "name": v} for v in voices],
                "tts_langs": {}, "stt_source": "api"}
    if provider == "google":
        models, token = [], ""
        for _ in range(6):                                   # the list is paged
            params = {"pageSize": 200, **({"pageToken": token} if token else {})}
            js = _request("get", provider, f"{GOOGLE_BASE}/models", key, headers=_google_headers(key), params=params).json()
            models += js.get("models") or []
            token = js.get("nextPageToken") or ""
            if not token:
                break
        stt, tts = [], []
        for m in models:
            mid = str(m.get("name", "")).removeprefix("models/")
            methods = m.get("supportedGenerationMethods") or []
            if "generateContent" not in methods or not mid:
                continue
            low = mid.lower()
            if "tts" in low:
                tts.append(mid)
            elif low.startswith("gemini") and not any(w in low for w in _GOOGLE_NOT_STT):
                stt.append(mid)                              # a Gemini model that takes audio in and writes text out
        return {"stt": sorted(set(stt)), "tts": sorted(set(tts)), "voices": [{"id": v, "name": v} for v in GOOGLE_VOICES] if tts else [],
                "tts_langs": {}, "stt_source": "api"}
    if provider == "minimax":
        # MiniMax has no dependable account-scoped TTS model/voice catalogue.
        # Probe the real TTS endpoint with a short Persian phrase; model IDs are labelled as a built-in catalogue.
        _tts_minimax(key, "speech-2.8-turbo", "سلام.", MINIMAX_DEFAULT_VOICE, "fa", {})
        return {"stt": [], "tts": list(MINIMAX_MODELS),
                "voices": [{"id": MINIMAX_DEFAULT_VOICE, "name": MINIMAX_DEFAULT_VOICE}],
                "tts_langs": {}, "tts_source": "catalog", "stt_source": "api"}
    if provider == "elevenlabs":
        r = _request("get", provider, f"{ELEVEN_BASE}/models", key, headers={"xi-api-key": key})
        data = r.json()
        data = data if isinstance(data, list) else data.get("models", [])
        tts, langs = [], {}
        for m in data:
            if m.get("can_do_text_to_speech") and m.get("model_id"):
                tts.append(m["model_id"])
                langs[m["model_id"]] = sorted({str(l.get("language_id", "")).split("-")[0] for l in (m.get("languages") or []) if l.get("language_id")})
        voices = []
        try:                                                 # a key limited to a few permissions may not be allowed to list voices
            vr = _request("get", provider, f"{ELEVEN_BASE}/voices", key, headers={"xi-api-key": key})
            voices = [{"id": v["voice_id"], "name": v.get("name") or v["voice_id"]} for v in (vr.json().get("voices") or []) if v.get("voice_id")]
        except CVError as exc:
            if exc.kind == "network":
                raise
        return {"stt": list(ELEVEN_STT_CATALOG), "tts": sorted(set(tts)), "voices": voices, "tts_langs": langs, "stt_source": "catalog"}
    raise CVError("other", f"provider {provider}?")


def validate(provider: str, key: str) -> dict:
    """-> {"status": valid|invalid|quota|error, "error": str, "detected": {...}} - never raises."""
    key = (key or "").strip()
    if not key:
        return {"status": "invalid", "error": "کلید خالی است.", "detected": {}}
    try:
        detected = detect(provider, key)
    except CVError as exc:
        status = {"auth": "invalid", "quota": "quota", "rate": "quota"}.get(exc.kind, "error")
        return {"status": status, "error": str(exc), "detected": {}}
    except Exception as exc:                                  # noqa: BLE001 - the UI must always get an answer
        return {"status": "error", "error": _scrub(f"{type(exc).__name__}: {exc}", key), "detected": {}}
    return {"status": "valid", "error": "", "detected": detected}


# ---------------------------------------------------------------- the actual STT / TTS calls (one key, one model)
def _stt_groq(key, model, wav, lang, prompt):
    data = {"model": model, "response_format": "json", "temperature": "0"}
    if lang:
        data["language"] = lang
    if prompt:
        data["prompt"] = prompt[:400]
    r = _request("post", "groq", f"{GROQ_BASE}/audio/transcriptions", key, headers={"Authorization": f"Bearer {key}"},
                 files={"file": ("speech.wav", wav, "audio/wav")}, data=data)
    return str(r.json().get("text") or "").strip()


def _stt_eleven(key, model, wav, lang, prompt):
    data = {"model_id": model, "tag_audio_events": "false"}
    if lang:
        data["language_code"] = lang
    r = _request("post", "elevenlabs", f"{ELEVEN_BASE}/speech-to-text", key, headers={"xi-api-key": key},
                 files={"file": ("speech.wav", wav, "audio/wav")}, data=data)
    return str(r.json().get("text") or "").strip()


def _stt_google(key, model, wav, lang, prompt):
    name = LANG_NAMES.get(lang or "", "the language that is spoken")
    ask = (f"Transcribe this audio exactly as spoken, in {name}. Write only the transcript text, with natural punctuation, "
           "no comments and no translation. If there is no intelligible human speech, write nothing.")
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(wav).decode()}}, {"text": ask}]}],
            "generationConfig": {"temperature": 0}}
    js = _request("post", "google", f"{GOOGLE_BASE}/models/{model}:generateContent", key, headers=_google_headers(key), json=body).json()
    parts = ((js.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return " ".join(str(p.get("text") or "") for p in parts).strip()


def _tts_groq(key, model, text, voice, lang, opts=None):
    out = []
    for piece in chunk_text(text, GROQ_TTS_MAX_CHARS):
        r = _request("post", "groq", f"{GROQ_BASE}/audio/speech", key, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                     json={"model": model, "input": piece, "voice": voice, "response_format": "wav"})
        out.append(r.content)
    if not out:
        raise CVError("other", "empty text")
    return concat_wavs(out), "wav"


def _tts_eleven(key, model, text, voice, lang, opts=None):
    body = {"text": text, "model_id": model}
    caps = tts_caps("elevenlabs", model)
    opts = opts or {}
    vs = {}
    if "rate" in caps and opts.get("rate"):
        vs["speed"] = round(max(0.7, min(1.2, 1.0 + float(opts["rate"]) / 100.0)), 2)       # ElevenLabs speed range 0.7 - 1.2
    if "style_degree" in caps and opts.get("style") and opts.get("style_degree") is not None:
        vs["style"] = round(max(0.0, min(1.0, float(opts["style_degree"]) / 100.0)), 2)
    if vs:
        body["voice_settings"] = vs
    if lang and any(t in model for t in ("flash_v2_5", "turbo_v2_5", "v3")):
        body["language_code"] = lang                           # only these models accept an explicit language
    r = _request("post", "elevenlabs", f"{ELEVEN_BASE}/text-to-speech/{voice}", key,
                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                 params={"output_format": "mp3_44100_128"}, json=body)
    return r.content, "mp3"


def _tts_minimax(key, model, text, voice, lang, opts=None):
    """MiniMax T2A v2. Returns MP3 bytes; API keys are never included in diagnostics."""
    if not text or len(text) > 9999:
        raise CVError("other", "MiniMax text must contain 1-9999 characters")
    opts = opts or {}
    speed = max(0.5, min(2.0, 1.0 + float(opts.get("rate", 0) or 0) / 100.0))
    style = str(opts.get("style") or "")
    emotion = {"cheerful": "happy", "energetic": "happy", "serious": "neutral"}.get(style)
    voice_setting = {"voice_id": voice or MINIMAX_DEFAULT_VOICE, "speed": round(speed, 2), "vol": 1.0, "pitch": 0}
    if emotion:
        voice_setting["emotion"] = emotion
    body = {
        "model": model or "speech-2.8-turbo",
        "text": text,
        "stream": False,
        "voice_setting": voice_setting,
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        "language_boost": "auto",
        "output_format": "hex",
    }
    response = _request("post", "minimax", f"{MINIMAX_BASE}/t2a_v2", key,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json=body, timeout=90).json()
    base = response.get("base_resp") or {}
    code = base.get("status_code", 0)
    if code not in (0, "0", None):
        message = _scrub(str(base.get("status_msg") or f"MiniMax error {code}"), key)
        low = message.lower()
        kind = "quota" if any(x in low for x in ("quota", "balance", "credit", "insufficient")) else (
            "auth" if any(x in low for x in ("api key", "unauthorized", "authentication")) else (
            "model" if any(x in low for x in ("model", "voice")) else "other"))
        raise CVError(kind, message)
    data = response.get("data") or {}
    audio_hex = data.get("audio") or response.get("audio")
    if not audio_hex:
        raise CVError("other", "MiniMax response contained no audio")
    try:
        audio = bytes.fromhex(audio_hex)
    except (TypeError, ValueError) as exc:
        raise CVError("other", "MiniMax returned invalid hexadecimal audio") from exc
    if not audio:
        raise CVError("other", "MiniMax returned empty audio")
    return audio, "mp3"


def _tts_google(key, model, text, voice, lang, opts=None):
    style = STYLE_PROMPTS.get(str((opts or {}).get("style") or ""), "")
    spoken = f"Say {style}: {text}" if style else text                  # Gemini TTS takes its style from a natural-language instruction
    body = {"contents": [{"parts": [{"text": spoken}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice or "Kore"}}}}}
    js = _request("post", "google", f"{GOOGLE_BASE}/models/{model}:generateContent", key, headers=_google_headers(key), json=body).json()
    for part in ((js.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            pcm = base64.b64decode(inline["data"])
            m = re.search(r"rate=(\d+)", str(inline.get("mimeType") or inline.get("mime_type") or ""))
            return pcm_to_wav(pcm, int(m.group(1)) if m else 24000), "wav"
    raise CVError("other", "Gemini audio نداد")


STT_CALLS = {"groq": _stt_groq, "elevenlabs": _stt_eleven, "google": _stt_google}
TTS_CALLS = {"groq": _tts_groq, "elevenlabs": _tts_eleven, "google": _tts_google, "minimax": _tts_minimax}


# ---------------------------------------------------------------- the store (cloud_voice.json)
def _default_data():
    return {"version": 1,
            "stt": {"use_cloud": False, "order": list(PROVIDERS), "enabled": {p: True for p in PROVIDERS}, "model": {p: "" for p in PROVIDERS}},
            "tts": {"use_cloud": False, "order": list(PROVIDERS), "enabled": {p: True for p in PROVIDERS}, "model": {p: "" for p in PROVIDERS},
                    "voice": {p: {} for p in PROVIDERS}},
            "providers": {p: {"keys": []} for p in PROVIDERS}}


class CloudVoiceStore:
    """All Cloud Voice settings and keys. Saved atomically after every change, outside the program folder."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.warnings: list[str] = []
        self.data = _default_data()
        self.load()

    # ---- file ----
    def load(self):
        with self.lock:
            self.data = _default_data()
            self.warnings = []
            if not self.path.is_file():
                return
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict):
                    raise ValueError("ساختار فایل معتبر نیست")
            except Exception as exc:                          # keep a copy, start empty, never crash
                try:
                    self.path.with_name(f"{self.path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}").write_bytes(self.path.read_bytes())
                except OSError:
                    pass
                self.warnings.append(f"فایل Cloud Voice خراب بود و خوانده نشد ({exc}). یک نسخه‌ی پشتیبان کنارش ماند.")
                return
            for kind in KINDS:
                block = saved.get(kind) if isinstance(saved.get(kind), dict) else {}
                mine = self.data[kind]
                mine["use_cloud"] = bool(block.get("use_cloud", False))
                order = [p for p in (block.get("order") or []) if p in PROVIDERS]
                mine["order"] = order + [p for p in PROVIDERS if p not in order]
                for field in ("enabled", "model"):
                    if isinstance(block.get(field), dict):
                        mine[field].update({p: v for p, v in block[field].items() if p in PROVIDERS})
                if kind == "tts" and isinstance(block.get("voice"), dict):
                    for p, v in block["voice"].items():
                        if p in PROVIDERS and isinstance(v, dict):
                            mine["voice"][p] = dict(v)
            for p in PROVIDERS:
                keys = ((saved.get("providers") or {}).get(p) or {}).get("keys") or []
                for rec in keys:
                    if not isinstance(rec, dict) or not rec.get("id"):
                        continue
                    raw = str(rec.get("key") or "")
                    try:
                        plain = unprotect(raw)
                    except Exception:
                        plain = ""
                    rec = {"id": str(rec["id"]), "label": str(rec.get("label") or ""), "key": plain, "enabled": bool(rec.get("enabled", True)),
                           "status": str(rec.get("status") or "unchecked"), "error": str(rec.get("error") or ""), "checked_at": float(rec.get("checked_at") or 0),
                           "cooldown_until": float(rec.get("cooldown_until") or 0), "detected": rec.get("detected") if isinstance(rec.get("detected"), dict) else {}}
                    if raw and not plain:
                        rec["status"], rec["error"] = "invalid", "کلید با این حساب ویندوز رمزگشایی نشد؛ دوباره وارد کن."
                    self.data["providers"][p]["keys"].append(rec)

    def save(self):
        with self.lock:
            out = deepcopy(self.data)
            for p in PROVIDERS:
                for rec in out["providers"][p]["keys"]:
                    rec["key"] = protect(rec.get("key", "")) if rec.get("key") else ""
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                if os.name != "nt":
                    os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.path)

    # ---- keys ----
    def keys(self, provider):
        return self.data["providers"][provider]["keys"]

    def find_key(self, provider, kid):
        return next((k for k in self.keys(provider) if k["id"] == kid), None)

    def add_key(self, provider, key, label="", result=None):
        with self.lock:
            n = len(self.keys(provider)) + 1
            rec = {"id": uuid.uuid4().hex[:8], "label": label.strip() or f"Key {n}", "key": key.strip(), "enabled": True,
                   "status": "unchecked", "error": "", "checked_at": 0.0, "cooldown_until": 0.0, "detected": {}}
            self.keys(provider).append(rec)
            if result:
                self._apply_result(rec, result)
            self.save()
            return rec

    def _apply_result(self, rec, result):
        rec["status"], rec["error"], rec["checked_at"] = result["status"], result.get("error", ""), time.time()
        if result["status"] == "valid":
            rec["detected"] = result.get("detected") or {}
            rec["cooldown_until"] = 0.0

    def apply_validation(self, provider, kid, result):
        with self.lock:
            rec = self.find_key(provider, kid)
            if rec:
                self._apply_result(rec, result)
                self.save()

    def update_key(self, provider, kid, **fields):
        with self.lock:
            rec = self.find_key(provider, kid)
            if rec:
                rec.update({k: v for k, v in fields.items() if k in ("label", "key", "enabled")})
                if "key" in fields:                          # a changed key is unknown again until it is validated
                    rec.update(status="unchecked", error="", detected={}, cooldown_until=0.0)
                self.save()

    def delete_key(self, provider, kid):
        with self.lock:
            self.data["providers"][provider]["keys"] = [k for k in self.keys(provider) if k["id"] != kid]
            self.save()

    def move_key(self, provider, kid, delta):
        with self.lock:
            keys = self.keys(provider)
            i = next((i for i, k in enumerate(keys) if k["id"] == kid), None)
            j = None if i is None else i + delta
            if i is not None and 0 <= j < len(keys):
                keys[i], keys[j] = keys[j], keys[i]
                self.save()

    # ---- priority / switches ----
    def set_option(self, kind, field, provider, value):
        with self.lock:
            self.data[kind][field][provider] = value
            self.save()

    def set_voice(self, provider, lang, voice):
        with self.lock:
            self.data["tts"]["voice"][provider][lang] = voice
            self.save()

    def set_use_cloud(self, kind, on):
        with self.lock:
            self.data[kind]["use_cloud"] = bool(on)
            self.save()

    def move_provider(self, kind, provider, delta):
        with self.lock:
            order = self.data[kind]["order"]
            i = order.index(provider)
            j = i + delta
            if 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
                self.save()

    # ---- capabilities (aggregated over keys) ----
    def key_usable(self, rec, now=None):
        now = now or time.time()
        return bool(rec.get("key")) and rec.get("enabled") and rec.get("status") in ("valid", "quota") and rec.get("cooldown_until", 0) <= now

    def models(self, provider, kind):
        """Unique model ids in key order -> [{"id", "keys": [key ids that have it]}]. A model found through several keys appears once."""
        seen: dict[str, list[str]] = {}
        for rec in self.keys(provider):
            if rec.get("status") not in ("valid", "quota") or not rec.get("enabled"):
                continue
            for mid in (rec.get("detected") or {}).get(kind, []):
                seen.setdefault(mid, []).append(rec["id"])
        return [{"id": m, "keys": ks} for m, ks in seen.items()]

    def voices(self, provider):
        seen: dict[str, dict] = {}
        for rec in self.keys(provider):
            if rec.get("status") not in ("valid", "quota") or not rec.get("enabled"):
                continue
            for v in (rec.get("detected") or {}).get("voices", []):
                entry = seen.setdefault(v["id"], {"id": v["id"], "name": v.get("name") or v["id"], "keys": []})
                entry["keys"].append(rec["id"])
        return list(seen.values())

    def capable(self, provider, kind):
        return bool(self.models(provider, kind))

    def reason_unsupported(self, provider, kind):
        keys = [k for k in self.keys(provider)]
        if not keys:
            return "هنوز کلیدی اضافه نشده است."
        if not any(k.get("enabled") for k in keys):
            return "همه‌ی کلیدهای این Provider غیرفعال‌اند."
        if not any(k.get("status") in ("valid", "quota") for k in keys):
            return "هیچ کلید معتبری وجود ندارد (کلیدها را اعتبارسنجی کن)."
        return "این Provider با کلیدهای فعلی " + ("تشخیص گفتار" if kind == "stt" else "تبدیل متن به گفتار") + " را پشتیبانی نمی‌کند."


# ---------------------------------------------------------------- the service used by the listener and the speaker
class CloudVoice:
    def __init__(self, store: CloudVoiceStore):
        self.store = store
        self._down: dict[str, float] = {}               # provider -> time until which it is skipped (server / network trouble)

    # ---- state ----
    def providers_in_use(self, kind):
        cfg, now = self.store.data[kind], time.monotonic()
        return [p for p in cfg["order"] if cfg["enabled"].get(p, True) and self.store.capable(p, kind)
                and self._down.get(p, 0) <= now and any(self.store.key_usable(k) for k in self.store.keys(p))]

    def ready(self, kind):
        """True when Cloud Voice is switched on for this direction and at least one provider could take the request now."""
        return bool(self.store.data[kind]["use_cloud"]) and bool(self.providers_in_use(kind))

    def stt_ready(self):
        return self.ready("stt")

    def tts_ready(self):
        return self.ready("tts")

    def tts_signature(self):
        cfg = self.store.data["tts"]
        return json.dumps([cfg["order"], cfg["enabled"], cfg["model"], cfg["voice"]], sort_keys=True, ensure_ascii=False)

    # ---- cool-downs ----
    def _cool(self, provider, rec, err: CVError):
        if err.kind == "auth":
            rec["status"], rec["error"] = "invalid", str(err)
        elif err.kind in ("rate", "quota"):
            wait = err.retry_after if err.retry_after else (COOLDOWN_QUOTA if err.kind == "quota" else COOLDOWN_RATE)
            wait = min(max(wait, 5.0), COOLDOWN_MAX)
            if err.kind == "quota":
                wait = max(wait, COOLDOWN_QUOTA if not err.retry_after else wait)
            rec["cooldown_until"] = time.time() + wait
            rec["status"], rec["error"] = "quota", f"{'سهمیه' if err.kind == 'quota' else 'محدودیت نرخ'}: {err}"
        else:
            rec["error"] = str(err)
        self.store.save()

    # ---- candidate selection ----
    def _model_order(self, provider, kind, lang):
        cfg = self.store.data[kind]
        entries = self.store.models(provider, kind)
        chosen = cfg["model"].get(provider) or ""
        entries.sort(key=lambda e: 0 if e["id"] == chosen else 1)
        if kind == "tts":
            entries = [e for e in entries if self._tts_lang_ok(provider, e["id"], lang)]
            if chosen and not any(e["id"] == chosen for e in entries):
                pass                                          # the chosen model cannot speak this language: others are tried
        return entries

    def _tts_lang_ok(self, provider, model, lang):
        if provider == "groq":
            return ("english" in model and lang == "en") or ("arabic" in model and lang == "ar") or ("playai" in model and lang == "en")
        if provider == "elevenlabs":
            langs = set()
            for rec in self.store.keys(provider):
                langs |= set(((rec.get("detected") or {}).get("tts_langs") or {}).get(model, []))
            return (not langs) or lang in langs
        return True

    def _voice_for(self, provider, model, lang):
        voices = self.store.data["tts"]["voice"][provider]
        v = voices.get(lang) or voices.get("*") or ""
        if v:
            return v
        if provider == "google":
            return "Kore"
        if provider == "minimax":
            return MINIMAX_DEFAULT_VOICE
        if provider == "groq":
            return (GROQ_VOICES.get(model) or ["autumn"])[0]
        listed = self.store.voices(provider)
        return listed[0]["id"] if listed else ""

    # ---- main loop ----
    def _run(self, kind, lang, call, budget):
        """call(provider, key_record, model, extra) -> result. Walks providers -> keys; returns (result, info)."""
        started, attempts, failovers = time.monotonic(), [], []
        providers = self.providers_in_use(kind)
        if not providers:
            raise AllFailed("هیچ سرویس Cloud Voice آماده‌ای نیست.", attempts)
        for provider in providers:
            for entry in self._model_order(provider, kind, lang):
                model = entry["id"]
                voice = self._voice_for(provider, model, lang) if kind == "tts" else ""
                if kind == "tts" and provider in ("elevenlabs",) and not voice:
                    attempts.append((provider, "-", "صدایی انتخاب یا شناسایی نشده"))
                    continue
                key_ids = set(entry["keys"])
                next_provider = False
                for rec in self.store.keys(provider):                 # the user's key order = key priority
                    if rec["id"] not in key_ids or not self.store.key_usable(rec):
                        continue
                    if kind == "tts" and provider == "elevenlabs" and voice and (rec.get("detected") or {}).get("voices") \
                            and voice not in {v["id"] for v in rec["detected"]["voices"]}:
                        continue                                     # that voice belongs to another account's key
                    if time.monotonic() - started > budget:
                        raise AllFailed("زمان مجاز Cloud Voice تمام شد.", attempts)
                    try:
                        result = call(provider, rec, model, voice)
                        return result, {"provider": provider, "key": rec["label"], "model": model, "failovers": failovers}
                    except CVError as err:
                        attempts.append((provider, rec["label"], str(err)))
                        self._cool(provider, rec, err)
                        if err.kind in ("rate", "quota", "auth"):
                            failovers.append(f"{LABELS[provider]} / {rec['label']}: "
                                             + {"rate": "محدودیت نرخ", "quota": "سهمیه تمام شد", "auth": "کلید نامعتبر"}[err.kind])
                            continue                                 # next key of the same provider
                        if err.kind == "model":
                            break                                    # this model is not usable: next model
                        next_provider = True                         # server / network trouble: do not hammer, next provider
                        self._down[provider] = time.monotonic() + 60.0       # and skip it for the next sentences for a minute
                        break
                if next_provider:
                    break
        raise AllFailed("همه‌ی سرویس‌های ابری ناموفق بودند: " + " | ".join(f"{LABELS.get(p, p)}/{k}: {m}" for p, k, m in attempts[-4:]), attempts)

    # ---- public ----
    def transcribe(self, samples, rate, language, prompt=""):
        """-> (text, info). Raises AllFailed when the local engine must take over."""
        wav = wav_bytes(samples, rate)
        lang = None if language in (None, "", "auto") else str(language)

        def call(provider, rec, model, voice):
            return STT_CALLS[provider](rec["key"], model, wav, lang, prompt)
        return self._run("stt", lang, call, budget=45)

    def synthesize(self, text, lang=None, opts=None):
        """-> (audio bytes, "wav"|"mp3", info). Raises AllFailed when the local voice must take over."""
        lang = lang or detect_lang(text)

        def call(provider, rec, model, voice):
            return TTS_CALLS[provider](rec["key"], model, text, voice, lang, opts)
        (audio, ext), info = self._run("tts", lang, call, budget=40)
        return audio, ext, info


_service: CloudVoice | None = None


def service() -> CloudVoice:
    """The one shared instance (the UI edits the same store that the listener and the speaker read)."""
    global _service
    if _service is None:
        from .config import DATA_DIR
        _service = CloudVoice(CloudVoiceStore(DATA_DIR / FILE_NAME))
    return _service
