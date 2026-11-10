"""Deterministic, provider-independent emotional runtime for Kira.

The LLM may suggest reply emotions, but this module owns persistent state,
decay, relationship drift, emotional memories, event reactions and final mood.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from ..config import DATA_DIR

STATE_FILE = "kira_emotional_state.json"
LOCK = threading.RLock()

EMOTIONS = {
    "neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised",
    "curious", "proud", "arrogant", "smug", "playful", "teasing", "tsundere",
    "bored", "frustrated", "affectionate", "flirty", "shy", "embarrassed",
    "jealous", "laughing", "annoyed", "protective", "excited", "thinking",
    "calm", "hopeful", "disappointed", "lonely", "guilty", "grateful",
    "nostalgic", "confident", "confused", "relieved", "content",
}
BEHAVIORS = {
    "playful", "teasing", "tsundere", "sarcastic", "quiet", "affectionate",
    "clingy", "stubborn", "sulking", "cheerful", "reserved", "protective",
    "focused", "flirty", "curious", "gentle", "formal", "energetic",
}
RELATIONSHIP_KEYS = ("trust", "closeness", "familiarity", "comfort", "tension")
DEFAULTS = {
    "schema": 2, "updated": 0.0, "last_interaction": 0.0,
    "emotions": {}, "behaviors": {}, "energy": 76.0,
    "relationship": {"trust": 50.0, "closeness": 28.0, "familiarity": 12.0,
                     "comfort": 45.0, "tension": 0.0},
    "memories": [], "recent_events": [], "last_user_signals": [],
}

# Mood impulse is intentionally distinct from delivery behavior.
USER_EFFECTS = {
    "down": ({"sad": 15, "affectionate": 24, "protective": 18}, {"gentle": 16, "quiet": 12}, {"playful": -12, "teasing": -18, "sarcastic": -14}),
    "stressed": ({"fearful": 5, "protective": 22, "calm": 12}, {"focused": 18, "gentle": 10}, {"teasing": -12, "sarcastic": -10}),
    "hostile": ({"angry": 16, "annoyed": 18, "sad": 5}, {"stubborn": 12, "reserved": 12, "sulking": 10}, {"affectionate": -5}),
    "frustrated": ({"frustrated": 18, "protective": 14}, {"focused": 18, "protective": 10}, {"sarcastic": -5}),
    "praise": ({"proud": 18, "happy": 10, "shy": 8}, {"cheerful": 12, "playful": 8}, {}),
    "flirt": ({"affectionate": 16, "flirty": 20, "shy": 8}, {"flirty": 18, "affectionate": 12}, {}),
    "thanks": ({"grateful": 12, "happy": 8}, {"gentle": 8, "affectionate": 8}, {}),
    "excited": ({"excited": 22, "happy": 14}, {"energetic": 14, "cheerful": 12}, {}),
    "joke": ({"laughing": 18, "playful": 16}, {"playful": 20, "teasing": 12}, {}),
    "apology": ({"relieved": 8, "affectionate": 10}, {"gentle": 12, "sulking": -14}, {"stubborn": -10}),
    "goodbye": ({"sad": 5, "affectionate": 10}, {"quiet": 8}, {}),
    "jealous": ({"jealous": 20, "annoyed": 6}, {"sulking": 16, "clingy": 10}, {}),
}

REPLY_BEHAVIORS = {
    "happy": {"cheerful": 8}, "sad": {"quiet": 8, "gentle": 10},
    "angry": {"stubborn": 6}, "fearful": {"reserved": 8, "quiet": 6},
    "disgusted": {"reserved": 5}, "proud": {"playful": 6},
    "smug": {"teasing": 9}, "playful": {"playful": 10},
    "teasing": {"teasing": 10}, "tsundere": {"tsundere": 10, "stubborn": 5},
    "affectionate": {"affectionate": 10, "gentle": 6}, "flirty": {"flirty": 10},
    "shy": {"reserved": 6}, "embarrassed": {"reserved": 6},
    "jealous": {"sulking": 8}, "laughing": {"playful": 10},
    "protective": {"protective": 10}, "excited": {"energetic": 10, "cheerful": 8},
    "thinking": {"focused": 8}, "calm": {"gentle": 6},
}
BEHAVIOR_BASELINE = {"playful": 15, "affectionate": 14, "teasing": 8, "sarcastic": 6}
EMOTION_HALF_LIFE = 22 * 60.0
BEHAVIOR_HALF_LIFE = 55 * 60.0
ENERGY_RECOVERY = 0.0032  # points/second; capped at 100
MAX_MEMORIES = 120
MAX_EVENTS = 80

def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))

def _decay(values, elapsed, half_life, baseline=None):
    factor = 0.5 ** (max(0.0, elapsed) / half_life)
    result = {}
    for key, value in values.items():
        floor = float((baseline or {}).get(key, 0.0))
        value = max(floor, float(value) * factor)
        if value >= 0.8:
            result[key] = round(value, 3)
    for key, value in (baseline or {}).items():
        result.setdefault(key, float(value))
    return result

class EmotionalRuntime:
    """Persistent emotional state. No provider, UI or Qt dependency."""
    def __init__(self, library=None, path=None, clock=time.time):
        self.library = library
        self.config = ((library.rules.get("emotional_runtime") or {}) if library else {})
        self.path = Path(path) if path else Path(DATA_DIR) / STATE_FILE
        self.clock = clock
        self._lock = LOCK
        self._state = self._load()

    def _fresh(self):
        return json.loads(json.dumps(DEFAULTS))

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return self._fresh()
            state = self._fresh()
            state.update({k: raw[k] for k in state if k in raw})
            state["emotions"] = {k: _clamp(v) for k, v in (raw.get("emotions") or {}).items() if k in EMOTIONS}
            state["behaviors"] = {k: _clamp(v) for k, v in (raw.get("behaviors") or {}).items() if k in BEHAVIORS}
            rel = raw.get("relationship") or {}
            state["relationship"] = {k: _clamp(rel.get(k, DEFAULTS["relationship"][k])) for k in RELATIONSHIP_KEYS}
            state["energy"] = _clamp(raw.get("energy", self.config.get("energy_start", 76)))
            state["memories"] = list(raw.get("memories") or [])[-int(self.config.get("memory_limit", MAX_MEMORIES)):]
            state["recent_events"] = list(raw.get("recent_events") or [])[-int(self.config.get("event_limit", MAX_EVENTS)):]
            state["last_user_signals"] = list(raw.get("last_user_signals") or [])
            state["schema"] = 2
            return state
        except (OSError, ValueError, TypeError):
            return self._fresh()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            # Emotional continuity must never make chat unavailable.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def migrate_legacy(self, legacy):
        """One-time import from the original kira_mood.json without overwriting newer runtime data."""
        if not isinstance(legacy, dict):
            return
        with self._lock:
            if self._state.get("updated") or self._state.get("emotions") or self._state.get("behaviors"):
                return
            old_emotions = legacy.get("scores") or {}
            old_behaviors = legacy.get("behavior_scores") or {}
            self._state["emotions"] = {k: _clamp(v) for k, v in old_emotions.items() if k in EMOTIONS}
            self._state["behaviors"] = {k: _clamp(v) for k, v in old_behaviors.items() if k in BEHAVIORS}
            self._state["energy"] = _clamp(legacy.get("energy", self._state["energy"]))
            self._state["updated"] = float(legacy.get("updated") or 0.0)
            self._state["last_interaction"] = float(legacy.get("last_chat") or 0.0)
            self._state["last_user_signals"] = list(legacy.get("user_states") or [])
            self._event("legacy_mood_migrated", self.clock())
            self._save()

    def _advance(self, now):
        state = self._state
        previous = float(state.get("updated") or now)
        elapsed = max(0.0, now - previous)
        state["emotions"] = _decay(state["emotions"], elapsed, float(self.config.get("emotion_half_life_s", EMOTION_HALF_LIFE)))
        state["behaviors"] = _decay(state["behaviors"], elapsed, float(self.config.get("behavior_half_life_s", BEHAVIOR_HALF_LIFE)), BEHAVIOR_BASELINE)
        state["energy"] = _clamp(state["energy"] + elapsed * float(self.config.get("energy_recovery_per_second", ENERGY_RECOVERY)))
        state["updated"] = now

    def _bump(self, bucket, key, amount):
        if key not in (EMOTIONS if bucket == "emotions" else BEHAVIORS):
            return
        values = self._state[bucket]
        values[key] = round(_clamp(values.get(key, 0) + amount), 3)

    def _event(self, name, now, detail=None):
        self._state["recent_events"].append({"name": str(name), "at": now, "detail": str(detail or "")[:180]})
        self._state["recent_events"] = self._state["recent_events"][-int(self.config.get("event_limit", MAX_EVENTS)):]

    def _memory(self, kind, text, impact, now, signal=None):
        text = str(text or "").strip()[:280]
        if not text:
            return
        # Only high-signal events become long-lived memories; ordinary chat stays in short event history.
        self._state["memories"].append({"kind": kind, "signal": signal, "text": text, "impact": _clamp(impact),
                                        "created": now, "last_recalled": 0.0, "recall_count": 0})
        self._state["memories"] = self._state["memories"][-int(self.config.get("memory_limit", MAX_MEMORIES)):]

    def on_user_message(self, text, signals=(), now=None):
        now = self.clock() if now is None else float(now)
        signals = list(dict.fromkeys(str(x) for x in signals))
        with self._lock:
            self._advance(now)
            self._state["energy"] = _clamp(self._state["energy"] - float(self.config.get("user_message_energy_cost", 0.7)))
            for signal in signals:
                effect = USER_EFFECTS.get(signal)
                if not effect:
                    continue
                emotions, behaviors, cool = effect
                for key, value in emotions.items(): self._bump("emotions", key, value)
                for key, value in behaviors.items(): self._bump("behaviors", key, value)
                for key, value in cool.items():
                    bucket = self._state["behaviors"]
                    bucket[key] = _clamp(bucket.get(key, 0) + value)
                if signal in ("down", "stressed", "excited", "apology", "goodbye"):
                    self._memory("interaction", text, 16 if signal in ("down", "stressed") else 9, now, signal=signal)
            gap = now - float(self._state.get("last_interaction") or now)
            if gap >= float(self.config.get("away_after_s", 6 * 3600)):
                self._bump("emotions", "affectionate", 12)
                self._bump("emotions", "lonely", 5)
                self._bump("behaviors", "clingy", 5)
                self._event("reunion_after_absence", now, round(gap / 3600, 1))
            self._state["last_interaction"] = now
            self._state["last_user_signals"] = signals
            self._event("user_message", now, ",".join(signals))
            # Relationship changes slowly and is bounded; no score is a reward/punishment mechanism.
            rel = self._state["relationship"]
            deltas = self.config.get("relationship_deltas", {})
            if "thanks" in signals or "praise" in signals:
                rel["closeness"] = _clamp(rel["closeness"] + float(deltas.get("thanks_closeness", 0.12)))
                rel["comfort"] = _clamp(rel["comfort"] + float(deltas.get("thanks_comfort", 0.10)))
            if "apology" in signals:
                rel["tension"] = _clamp(rel["tension"] + float(deltas.get("apology_tension", -0.8)))
                rel["trust"] = _clamp(rel["trust"] + float(deltas.get("apology_trust", 0.08)))
            if "hostile" in signals:
                rel["tension"] = _clamp(rel["tension"] + float(deltas.get("hostile_tension", 0.5)))
                rel["comfort"] = _clamp(rel["comfort"] + float(deltas.get("hostile_comfort", -0.12)))
            rel["familiarity"] = _clamp(rel["familiarity"] + float(deltas.get("familiarity_per_message", 0.025)))
            self._save()
        return self.snapshot(now)

    def on_reply(self, emotions=(), intensity=None, now=None, text=""):
        now = self.clock() if now is None else float(now)
        valid = [str(e) for e in (emotions or []) if str(e) in EMOTIONS and str(e) != "neutral"][:2]
        level = _clamp(35 if intensity is None else intensity)
        with self._lock:
            self._advance(now)
            self._state["energy"] = _clamp(self._state["energy"] - float(self.config.get("reply_energy_cost", 0.35)))
            for index, emotion in enumerate(valid):
                self._state["emotions"][emotion] = max(self._state["emotions"].get(emotion, 0), level * (0.88 if index == 0 else 0.58))
                for behavior, amount in REPLY_BEHAVIORS.get(emotion, {}).items():
                    self._bump("behaviors", behavior, amount * level / 60.0)
            self._event("kira_reply", now, "+".join(valid))
            if any(e in valid for e in ("happy", "affectionate", "grateful", "relieved")):
                self._state["relationship"]["closeness"] = _clamp(self._state["relationship"]["closeness"] + 0.025)
            if text and any(e in valid for e in ("sad", "angry", "fearful", "disappointed")):
                self._memory("kira_emotion", str(text)[:120], level * 0.25, now)
            self._save()
        return self.snapshot(now)

    def trigger(self, event, detail=None, now=None):
        now = self.clock() if now is None else float(now)
        with self._lock:
            self._advance(now)
            self._event(event, now, detail)
            # Runtime impulses are data-driven by the same event library used by the avatar.
            event_rule = (self.library.events.get(event) or {}) if self.library else {}
            for emotion, amount in (event_rule.get("runtime_emotions") or {}).items():
                self._bump("emotions", emotion, amount)
            for behavior, amount in (event_rule.get("runtime_behaviors") or {}).items():
                self._bump("behaviors", behavior, amount)
            self._save()
        return self.snapshot(now)

    def snapshot(self, now=None):
        now = self.clock() if now is None else float(now)
        with self._lock:
            self._advance(now)
            emotions = dict(self._state["emotions"])
            behaviors = dict(self._state["behaviors"])
            # Combination resolution is data-driven by the same library used by the avatar.
            ranked = sorted(emotions.items(), key=lambda x: x[1], reverse=True)
            chosen = []
            for emotion, value in ranked:
                if value < 4: continue
                if any(self.library and self.library.in_conflict(emotion, other) for other, _ in chosen):
                    continue
                chosen.append((emotion, value))
                if len(chosen) == 2: break
            if len(chosen) == 2 and self.library:
                combo = self.library.combination(chosen[0][0], chosen[1][0])
                if combo and combo.get("mode") == "replace" and combo.get("result") in EMOTIONS:
                    chosen = [(combo["result"], max(v for _, v in chosen))]
            dominant = chosen[0] if chosen else ("neutral", 0.0)
            behavior = max(behaviors.items(), key=lambda x: x[1])[0] if behaviors else "balanced"
            rel = dict(self._state["relationship"])
            return {
                "emotion": dominant[0], "intensity": int(round(dominant[1])),
                "secondary_emotions": [(e, int(round(v))) for e, v in chosen[1:]],
                "emotions": {k: int(round(v)) for k, v in emotions.items()},
                "behavior": behavior,
                "behavior_scores": {k: int(round(v)) for k, v in behaviors.items()},
                "behaviors": [(k, int(round(v))) for k, v in sorted(behaviors.items(), key=lambda x: x[1], reverse=True) if v >= 12][:4],
                "energy": int(round(self._state["energy"])),
                "energy_label": ("exhausted" if self._state["energy"] <= 15 else "tired" if self._state["energy"] <= 35 else "low" if self._state["energy"] <= 55 else "normal" if self._state["energy"] <= 75 else "active" if self._state["energy"] <= 90 else "hyper"),
                "relationship": rel, "memories": list(self._state["memories"][-8:]),
                "recent_events": list(self._state["recent_events"][-12:]),
                "user_states": list(self._state["last_user_signals"]),
                "age": max(0.0, now - float(self._state.get("last_interaction") or now)),
            }

    def build_prompt(self, mode="chat", now=None):
        if mode == "strict": return ""
        state = self.snapshot(now)
        if mode not in ("chat", "task"): return ""
        rel = state["relationship"]
        lines = [
            f"Persistent emotional state: {state['emotion']} ({state['intensity']}/100); secondary: {state['secondary_emotions'] or 'none'}.",
            f"Energy: {state['energy_label']} ({state['energy']}/100).",
            "Delivery behavior: " + ", ".join(k for k, _ in state["behaviors"][:3]) + ".",
            f"Relationship context (not a score to mention): familiarity {int(rel['familiarity'])}, comfort {int(rel['comfort'])}, tension {int(rel['tension'])}.",
            "Keep continuity with prior turns. Do not announce internal state or fabricate memories.",
        ]
        if state["memories"]:
            lines.append("Relevant emotional continuity (use only when naturally relevant): " +
                         "; ".join(m["text"] for m in state["memories"][-3:]))
        if mode == "task":
            lines = ["Practical-task delivery guidance: keep emotional flavor subtle; never reduce accuracy."] + lines[:2]
        return "\n".join(lines)

    def reset(self):
        with self._lock:
            self._state = self._fresh()
            self._save()
