"""Emotion-aware Persian Piper prosody and lightweight WAV processing.

This module has no Qt/Piper dependency so profile resolution and audio assembly
can be tested independently. Emotion intensity blends gently from neutral.
"""
from __future__ import annotations

import io
import math
import re
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
        frames = source.getnframes()
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
