"""Emotion-aware Persian Piper prosody and lightweight WAV processing.

This module has no Qt/Piper dependency so profile resolution and audio assembly
can be tested independently. Emotion intensity blends gently from neutral.
"""
from __future__ import annotations

import io
import re
from datetime import date
import shutil
import subprocess
import wave


NEUTRAL = {
    "length_scale": 1.0,
    "noise_scale": 0.667,
    "noise_w": 0.8,
    "gain_db": 0.0,
    "pitch_semitones": 0.0,
    "pause_comma_ms": 125,
    "pause_sentence_ms": 265,
}

# Profiles are intentionally subtle: the voice identity stays stable while
# timing, breath/noise variation, loudness and pitch carry the emotion.
_STYLES = {
    "bright": {
        "length_scale": 0.94, "noise_scale": 0.72, "noise_w": 0.84,
        "gain_db": 0.55, "pitch_semitones": 0.22,
        "pause_comma_ms": 105, "pause_sentence_ms": 225,
    },
    "excited": {
        "length_scale": 0.88, "noise_scale": 0.78, "noise_w": 0.90,
        "gain_db": 0.9, "pitch_semitones": 0.42,
        "pause_comma_ms": 80, "pause_sentence_ms": 185,
    },
    "sad": {
        "length_scale": 1.105, "noise_scale": 0.59, "noise_w": 0.69,
        "gain_db": -1.7, "pitch_semitones": -0.28,
        "pause_comma_ms": 190, "pause_sentence_ms": 390,
    },
    "calm": {
        "length_scale": 1.065, "noise_scale": 0.63, "noise_w": 0.73,
        "gain_db": -0.55, "pitch_semitones": -0.10,
        "pause_comma_ms": 165, "pause_sentence_ms": 340,
    },
    "angry": {
        "length_scale": 0.94, "noise_scale": 0.70, "noise_w": 0.82,
        "gain_db": 0.7, "pitch_semitones": 0.12,
        "pause_comma_ms": 90, "pause_sentence_ms": 230,
    },
    "curious": {
        "length_scale": 0.98, "noise_scale": 0.69, "noise_w": 0.82,
        "gain_db": 0.2, "pitch_semitones": 0.18,
        "pause_comma_ms": 135, "pause_sentence_ms": 280,
    },
    "warm": {
        "length_scale": 1.025, "noise_scale": 0.65, "noise_w": 0.76,
        "gain_db": 0.15, "pitch_semitones": 0.08,
        "pause_comma_ms": 150, "pause_sentence_ms": 305,
    },
    "shy": {
        "length_scale": 1.075, "noise_scale": 0.62, "noise_w": 0.72,
        "gain_db": -0.9, "pitch_semitones": 0.15,
        "pause_comma_ms": 180, "pause_sentence_ms": 355,
    },
    "thinking": {
        "length_scale": 1.045, "noise_scale": 0.64, "noise_w": 0.75,
        "gain_db": -0.25, "pitch_semitones": -0.06,
        "pause_comma_ms": 175, "pause_sentence_ms": 360,
    },
    "playful": {
        "length_scale": 0.965, "noise_scale": 0.73, "noise_w": 0.86,
        "gain_db": 0.35, "pitch_semitones": 0.28,
        "pause_comma_ms": 110, "pause_sentence_ms": 245,
    },
    "flat": {
        "length_scale": 1.045, "noise_scale": 0.60, "noise_w": 0.70,
        "gain_db": -0.9, "pitch_semitones": -0.12,
        "pause_comma_ms": 175, "pause_sentence_ms": 350,
    },
}

# Every emotion emitted by EmotionalRuntime has an explicit delivery style.
EMOTION_STYLE = {
    "neutral": "neutral",
    "happy": "bright", "sad": "sad", "angry": "angry",
    "fearful": "shy", "disgusted": "flat", "surprised": "excited",
    "curious": "curious", "proud": "bright", "arrogant": "flat",
    "smug": "playful", "playful": "playful", "teasing": "playful",
    "tsundere": "shy", "bored": "flat", "frustrated": "angry",
    "affectionate": "warm", "flirty": "warm", "shy": "shy",
    "embarrassed": "shy", "jealous": "angry", "laughing": "excited",
    "annoyed": "angry", "protective": "warm", "excited": "excited",
    "thinking": "thinking", "calm": "calm", "hopeful": "bright",
    "disappointed": "sad", "lonely": "sad", "guilty": "sad",
    "grateful": "warm", "nostalgic": "warm", "confident": "bright",
    "confused": "curious", "relieved": "calm", "content": "calm",
}
STYLE_PROFILES = {"neutral": dict(NEUTRAL), **{key: dict(value) for key, value in _STYLES.items()}}
EMOTION_PROFILES = {
    emotion: dict(STYLE_PROFILES[style])
    for emotion, style in EMOTION_STYLE.items()
}



_ONES = ("صفر", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه")
_TEENS = {10: "ده", 11: "یازده", 12: "دوازده", 13: "سیزده", 14: "چهارده", 15: "پانزده",
          16: "شانزده", 17: "هفده", 18: "هجده", 19: "نوزده"}
_TENS = {20: "بیست", 30: "سی", 40: "چهل", 50: "پنجاه", 60: "شصت", 70: "هفتاد", 80: "هشتاد", 90: "نود"}
_HUNDREDS = {100: "صد", 200: "دویست", 300: "سیصد", 400: "چهارصد", 500: "پانصد",
             600: "ششصد", 700: "هفتصد", 800: "هشتصد", 900: "نهصد"}
_SCALES = ((10**9, "میلیارد"), (10**6, "میلیون"), (10**3, "هزار"))
_JALALI_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
_GREGORIAN_MONTHS = ("ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
                     "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر")
_ORDINALS = {
    1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم", 5: "پنجم", 6: "ششم", 7: "هفتم",
    8: "هشتم", 9: "نهم", 10: "دهم", 11: "یازدهم", 12: "دوازدهم", 13: "سیزدهم",
    14: "چهاردهم", 15: "پانزدهم", 16: "شانزدهم", 17: "هفدهم", 18: "هجدهم",
    19: "نوزدهم", 20: "بیستم", 21: "بیست و یکم", 22: "بیست و دوم",
    23: "بیست و سوم", 24: "بیست و چهارم", 25: "بیست و پنجم", 26: "بیست و ششم",
    27: "بیست و هفتم", 28: "بیست و هشتم", 29: "بیست و نهم", 30: "سی‌ام", 31: "سی و یکم",
}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def persian_number_words(value):
    """Convert a bounded non-negative integer to natural Persian words."""
    number = int(value)
    if number < 0:
        return "منفی " + persian_number_words(-number)
    if number < 10:
        return _ONES[number]
    if number < 20:
        return _TEENS[number]
    if number < 100:
        tens, rest = divmod(number, 10)
        return _TENS[tens * 10] + ((" و " + persian_number_words(rest)) if rest else "")
    if number < 1000:
        hundreds = number // 100 * 100
        rest = number % 100
        return _HUNDREDS[hundreds] + ((" و " + persian_number_words(rest)) if rest else "")
    for scale, label in _SCALES:
        if number >= scale:
            quotient, remainder = divmod(number, scale)
            head = (label if quotient == 1 and scale == 1000
                    else persian_number_words(quotient) + " " + label)
            return head + ((" و " + persian_number_words(remainder)) if remainder else "")
    return str(number)


def expand_persian_numbers(text):
    """Spell out Persian-context numbers and common Jalali dates; leave Latin-only text untouched."""
    original = str(text or "")
    if not re.search(r"[آ-ی]", original):
        return original
    value = original.translate(_DIGITS)
    if not re.search(r"\d", value):
        return value

    def date_replacement(match):
        first, second, third = (int(part) for part in match.groups())
        if 1300 <= first <= 1499 and 1 <= second <= 12 and 1 <= third <= 31:
            year, month, day = first, second, third
            if day > (31 if month <= 6 else 30):
                return match.group(0)
            month_name = _JALALI_MONTHS[month - 1]
        elif 1300 <= third <= 1499 and 1 <= second <= 12 and 1 <= first <= 31:
            day, month, year = first, second, third
            if day > (31 if month <= 6 else 30):
                return match.group(0)
            month_name = _JALALI_MONTHS[month - 1]
        elif 1600 <= first <= 9999 and 1 <= second <= 12 and 1 <= third <= 31:
            year, month, day = first, second, third
            try:
                date(year, month, day)
            except ValueError:
                return match.group(0)
            month_name = _GREGORIAN_MONTHS[month - 1]
        elif 1600 <= third <= 9999 and 1 <= second <= 12 and 1 <= first <= 31:
            day, month, year = first, second, third
            try:
                date(year, month, day)
            except ValueError:
                return match.group(0)
            month_name = _GREGORIAN_MONTHS[month - 1]
        else:
            return match.group(0)
        return f"{_ORDINALS[day]} {month_name} {persian_number_words(year)}"

    value = re.sub(r"(?<!\d)(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?!\d)", date_replacement, value)
    value = re.sub(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)", date_replacement, value)
    value = re.sub(
        r"(?<!\d)(\d{1,2}):([0-5]\d)(?!\d)",
        lambda match: f"{persian_number_words(int(match.group(1)))} و "
                      f"{persian_number_words(int(match.group(2)))} دقیقه",
        value,
    )

    def number_replacement(match):
        prefix = value[:match.start()]
        suffix = value[match.end():]
        if re.search(r"[A-Za-z0-9]\s*$", prefix) or re.match(r"\s*[A-Za-z]", suffix):
            return match.group(0)
        token = match.group(0).replace(",", "")
        if "." in token:
            whole, fraction = token.split(".", 1)
            return persian_number_words(whole) + " ممیز " + " ".join(
                persian_number_words(int(digit)) for digit in fraction
            )
        number = int(token)
        return persian_number_words(number) if number <= 999_999_999_999 else match.group(0)

    return re.sub(r"(?<![\w./-])\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\w./-])|(?<![\w./-])\d{4,}(?![\w./-])",
                  number_replacement, value)


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def resolve_prosody(emotions=(), intensity=None):
    """Return a bounded, neutral-blended Piper/audio profile for one or two emotions."""
    ids = []
    for emotion in emotions or ():
        key = str(emotion or "").strip().lower()
        if key in EMOTION_PROFILES and key != "neutral" and key not in ids:
            ids.append(key)
        if len(ids) == 2:
            break
    level = _clamp(55 if intensity is None else intensity, 0, 100) / 100.0
    target = dict(NEUTRAL)
    if ids:
        primary = EMOTION_PROFILES[ids[0]]
        secondary = EMOTION_PROFILES[ids[1]] if len(ids) > 1 else None
        for key in NEUTRAL:
            value = float(primary[key])
            if secondary is not None:
                value = value * 0.78 + float(secondary[key]) * 0.22
            target[key] = float(NEUTRAL[key]) + (value - float(NEUTRAL[key])) * level
    target["length_scale"] = _clamp(target["length_scale"], 0.82, 1.22)
    target["noise_scale"] = _clamp(target["noise_scale"], 0.5, 0.9)
    target["noise_w"] = _clamp(target["noise_w"], 0.6, 0.95)
    target["gain_db"] = _clamp(target["gain_db"], -2.5, 1.5)
    target["pitch_semitones"] = _clamp(target["pitch_semitones"], -0.55, 0.55)
    target["pause_comma_ms"] = int(round(_clamp(target["pause_comma_ms"], 70, 240)))
    target["pause_sentence_ms"] = int(round(_clamp(target["pause_sentence_ms"], 140, 480)))
    target["emotion_ids"] = tuple(ids)
    target["intensity"] = int(round(level * 100))
    return target


def split_comma_clauses(text):
    """Split at written clause punctuation so Kira can insert real timed silence."""
    value = str(text or "").strip()
    if not value:
        return []
    pieces = re.split(r"(?<=[،؛;])\s*|(?<=,)(?!\d)\s*", value)
    out = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if out and len(piece) < 3:
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out or [value]


def join_wavs_with_pauses(items):
    """Join (WAV bytes, pause_ms) pairs, requiring one consistent PCM format."""
    if not items:
        return b""
    decoded = []
    spec = None
    for payload, pause_ms in items:
        with wave.open(io.BytesIO(bytes(payload)), "rb") as source:
            current = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
            if current[3] != "NONE":
                raise ValueError("Compressed WAV is not supported for speech assembly")
            frames = source.readframes(source.getnframes())
        if spec is None:
            spec = current[:3]
        elif current[:3] != spec:
            raise ValueError("Piper sentence WAV formats do not match")
        decoded.append((frames, max(0, int(pause_ms))))
    channels, sample_width, sample_rate = spec
    silence = b"\0" * sample_width * channels
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(sample_width)
        target.setframerate(sample_rate)
        for frames, pause_ms in decoded:
            target.writeframesraw(frames)
            silence_frames = round(sample_rate * pause_ms / 1000)
            if silence_frames:
                target.writeframesraw(silence * silence_frames)
    return output.getvalue()


def apply_audio_effects(payload, profile):
    """Apply subtle loudness and optional ffmpeg pitch shift; gracefully skip pitch if unavailable."""
    if not payload:
        return payload
    import numpy as np

    with wave.open(io.BytesIO(bytes(payload)), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        raw = source.readframes(frames)
        comptype = source.getcomptype()
    if comptype != "NONE" or width != 2 or not raw:
        return bytes(payload)
    gain = 10.0 ** (float(profile.get("gain_db", 0.0)) / 20.0)
    if abs(gain - 1.0) > 1e-5:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
        raw = np.clip(samples * gain, -32768, 32767).astype("<i2").tobytes()
        output = io.BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(2)
            target.setframerate(rate)
            target.writeframes(raw)
        payload = output.getvalue()

    semitones = _clamp(profile.get("pitch_semitones", 0.0), -0.55, 0.55)
    ffmpeg = shutil.which("ffmpeg")
    if abs(semitones) < 0.025 or not ffmpeg:
        return bytes(payload)
    ratio = 2.0 ** (semitones / 12.0)
    tempo = 1.0 / ratio
    audio_filter = f"asetrate={rate * ratio:.3f},aresample={rate},atempo={tempo:.8f}"
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
             "-af", audio_filter, "-f", "wav", "pipe:1"],
            input=bytes(payload), capture_output=True, timeout=8, check=False,
        )
        if result.returncode == 0 and result.stdout.startswith(b"RIFF"):
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return bytes(payload)
