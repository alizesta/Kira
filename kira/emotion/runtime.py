"""Deterministic, provider-independent emotional runtime for a character profile.

The LLM may suggest reply emotions, but this module owns per-profile state,
decay, relationship drift, emotional memories, event reactions and final mood.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path

from ..config import DATA_DIR
from ..character.traits import (
    BASE_TRAITS, TRAIT_LEARNING_RULES, TRAIT_MIN_OFFSET, TRAIT_MAX_OFFSET,
    TRAIT_LEARNING_THRESHOLD, TRAIT_FEEDBACK_COOLDOWN_S,
)
from ..character.relationship import RelationshipEngine

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
    "personality_traits": BASE_TRAITS, "feedback_evidence": {}, "last_initiative": 0.0,
    "last_initiative_memory_id": "",
}

# Mood impulse is intentionally distinct from delivery behavior.
USER_EFFECTS = {
    "down": ({"sad": 15, "affectionate": 24, "protective": 18}, {"gentle": 16, "quiet": 12}, {"playful": -12, "teasing": -18, "sarcastic": -14}),
    "stressed": ({"fearful": 5, "protective": 22, "calm": 12}, {"focused": 18, "gentle": 10}, {"playful": -10, "teasing": -12, "sarcastic": -10}),
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
MEMORY_RETENTION_DAYS = {"interaction": 45.0, "kira_emotion": 90.0}
MEMORY_RECENCY_HALF_LIFE_DAYS = 14.0
_log = logging.getLogger(__name__)

def _finite_float(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)

def _safe_int(value, default=0, minimum=0, maximum=None):
    number = _finite_float(value, default)
    try:
        result = int(number)
    except (TypeError, ValueError, OverflowError):
        result = int(default)
    result = max(int(minimum), result)
    return min(int(maximum), result) if maximum is not None else result


def _as_mapping(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, _finite_float(v, lo)))

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
    def __init__(self, library=None, path=None, clock=time.time, base_traits=None):
        self.library = library
        self.config = _as_mapping(library.rules.get("emotional_runtime")) if library else {}
        self.path = Path(path) if path else Path(DATA_DIR) / STATE_FILE
        self.clock = clock
        self._lock = LOCK
        self.base_traits = self._normalise_traits(base_traits or BASE_TRAITS)
        self._state = self._load()
        self.relationship_engine = RelationshipEngine(DEFAULTS["relationship"])

    @staticmethod
    def _normalise_traits(values):
        values = values if isinstance(values, dict) else {}
        result = {}
        for key, baseline in BASE_TRAITS.items():
            try:
                result[key] = max(0.0, min(1.0, _finite_float(values.get(key, baseline), baseline)))
            except (TypeError, ValueError):
                result[key] = float(baseline)
        return result

    def _fresh(self):
        state = json.loads(json.dumps(DEFAULTS))
        state["personality_traits"] = dict(self.base_traits)
        return state

    def set_base_traits(self, values):
        """Change this profile's baseline while preserving any small learned deltas."""
        updated = self._normalise_traits(values)
        with self._lock:
            current = self._state.get("personality_traits") or {}
            revised = {}
            for key, baseline in updated.items():
                old_base = float(self.base_traits.get(key, BASE_TRAITS[key]))
                old_value = float(current.get(key, old_base))
                learned_delta = old_value - old_base
                revised[key] = max(0.0, min(1.0, baseline + learned_delta))
            self.base_traits = updated
            self._state["personality_traits"] = revised
            self._save()
        return dict(revised)

    def _load(self):
        """Load persisted state field-by-field; one malformed section must not reset the whole profile."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return self._fresh()
        if not isinstance(raw, dict):
            return self._fresh()

        state = self._fresh()
        now = max(0.0, _finite_float(self.clock(), 0.0))

        emotions = _as_mapping(raw.get("emotions"))
        state["emotions"] = {
            key: _clamp(value)
            for key, value in emotions.items()
            if key in EMOTIONS
        }
        behaviors = _as_mapping(raw.get("behaviors"))
        state["behaviors"] = {
            key: _clamp(value)
            for key, value in behaviors.items()
            if key in BEHAVIORS
        }

        relationship = _as_mapping(raw.get("relationship"))
        state["relationship"] = {
            key: _clamp(relationship.get(key, DEFAULTS["relationship"][key]))
            for key in RELATIONSHIP_KEYS
        }
        state["energy"] = _clamp(raw.get("energy", self.config.get("energy_start", 76)))

        memory_limit = _safe_int(
            self.config.get("memory_limit", MAX_MEMORIES),
            MAX_MEMORIES,
            minimum=1,
            maximum=MAX_MEMORIES,
        )
        memories = []
        for saved in _as_list(raw.get("memories"))[-memory_limit:]:
            if not isinstance(saved, dict) or not str(saved.get("text") or "").strip():
                continue
            item = dict(saved)
            kind = str(item.get("kind") or "interaction")
            if kind not in ("interaction", "kira_emotion"):
                continue
            item["kind"] = kind
            item["text"] = str(item["text"]).strip()[:280]
            item["impact"] = _clamp(_finite_float(item.get("impact", 0.0)))
            item["created"] = min(now, max(0.0, _finite_float(item.get("created", 0.0))))
            item["reinforced_at"] = min(
                now,
                max(
                    item["created"],
                    _finite_float(item.get("reinforced_at", item["created"]), item["created"]),
                ),
            )
            item["last_recalled"] = min(now, max(0.0, _finite_float(item.get("last_recalled", 0.0))))
            item["recall_count"] = _safe_int(item.get("recall_count", 0))
            item["reinforcements"] = _safe_int(item.get("reinforcements", 0))
            item["speaker"] = "assistant" if kind == "kira_emotion" else "user"
            memories.append(item)
        state["memories"] = memories

        event_limit = _safe_int(
            self.config.get("event_limit", MAX_EVENTS),
            MAX_EVENTS,
            minimum=1,
            maximum=MAX_EVENTS,
        )
        recent_events = []
        for saved in _as_list(raw.get("recent_events"))[-event_limit:]:
            if not isinstance(saved, dict) or not str(saved.get("name") or "").strip():
                continue
            recent_events.append({
                "name": str(saved["name"])[:80],
                "at": min(now, max(0.0, _finite_float(saved.get("at", now), now))),
                "detail": str(saved.get("detail") or "")[:180],
            })
        state["recent_events"] = recent_events

        valid_signals = set(USER_EFFECTS)
        state["last_user_signals"] = [
            str(signal) for signal in _as_list(raw.get("last_user_signals"))
            if str(signal) in valid_signals
        ][-len(valid_signals):]

        stored_traits = _as_mapping(raw.get("personality_traits"))
        state["personality_traits"] = {
            key: max(0.0, min(1.0, _finite_float(stored_traits.get(key, baseline), baseline)))
            for key, baseline in self.base_traits.items()
        }

        raw_evidence = _as_mapping(raw.get("feedback_evidence"))
        evidence = {}
        for key, value in raw_evidence.items():
            if not isinstance(value, dict):
                continue
            evidence[str(key)[:80]] = {
                "count": _safe_int(value.get("count", 0)),
                "applied": _safe_int(value.get("applied", 0)),
                "last_at": min(now, max(0.0, _finite_float(value.get("last_at", 0.0)))),
            }
        state["feedback_evidence"] = evidence
        state["updated"] = min(now, max(0.0, _finite_float(raw.get("updated", 0.0))))
        state["last_interaction"] = min(now, max(0.0, _finite_float(raw.get("last_interaction", 0.0))))
        state["last_initiative"] = min(now, max(0.0, _finite_float(raw.get("last_initiative", 0.0))))
        state["last_initiative_memory_id"] = str(raw.get("last_initiative_memory_id") or "")[:64]
        state["schema"] = 3
        return state


    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            # Emotional continuity must never make chat unavailable.
            _log.warning("Unable to persist emotional state", exc_info=True)
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
        # Relationship decay is isolated from emotion decay; trust and closeness do not evaporate with absence.
        self.relationship_engine.advance(
            state["relationship"], elapsed,
            {"tension_recovery_per_day": self.config.get("relationship_tension_recovery_per_day", 2.0)},
        )
        state["updated"] = now

    def _bump(self, bucket, key, amount):
        if key not in (EMOTIONS if bucket == "emotions" else BEHAVIORS):
            return
        values = self._state[bucket]
        values[key] = round(_clamp(values.get(key, 0) + amount), 3)

    def _event(self, name, now, detail=None):
        self._state["recent_events"].append({"name": str(name), "at": now, "detail": str(detail or "")[:180]})
        event_limit = _safe_int(self.config.get("event_limit", MAX_EVENTS), MAX_EVENTS, minimum=1, maximum=MAX_EVENTS)
        self._state["recent_events"] = self._state["recent_events"][-event_limit:]

    def _memory(self, kind, text, impact, now, signal=None):
        text = str(text or "").strip()[:280]
        if not text:
            return
        # Repeatedly observed identical experiences strengthen one memory instead of filling the store with duplicates.
        existing = next((m for m in reversed(self._state["memories"])
                         if m.get("kind") == kind and m.get("signal") == signal and m.get("text") == text), None)
        if existing:
            existing["impact"] = _clamp(float(existing.get("impact", 0)) + 4.0)
            existing["reinforced_at"] = now
            existing["reinforcements"] = int(existing.get("reinforcements", 0)) + 1
            return
        # Only high-signal events become long-lived memories; ordinary chat stays in short event history.
        self._state["memories"].append({"kind": kind, "signal": signal, "speaker": "assistant" if kind == "kira_emotion" else "user", "text": text, "impact": _clamp(impact),
                                        "created": now, "reinforced_at": now, "last_recalled": 0.0,
                                        "recall_count": 0, "reinforcements": 0})
        memory_limit = _safe_int(self.config.get("memory_limit", MAX_MEMORIES), MAX_MEMORIES, minimum=1, maximum=MAX_MEMORIES)
        self._state["memories"] = self._state["memories"][-memory_limit:]

    def observe_feedback(self, category, text="", now=None):
        """Learn from repeated, explicit feedback without letting one message rewrite Kira's identity."""
        now = self.clock() if now is None else float(now)
        effects = TRAIT_LEARNING_RULES.get(str(category))
        if not effects:
            return self.snapshot(now)
        with self._lock:
            self._advance(now)
            record = self._state["feedback_evidence"].setdefault(
                str(category), {"count": 0, "applied": 0, "last_at": 0.0}
            )
            last_at = float(record.get("last_at", 0.0) or 0.0)
            if last_at and now - last_at < TRAIT_FEEDBACK_COOLDOWN_S:
                return self.snapshot(now)
            record["count"] = int(record.get("count", 0)) + 1
            record["last_at"] = now
            if record["count"] >= TRAIT_LEARNING_THRESHOLD and record["count"] > int(record.get("applied", 0)):
                traits = self._state["personality_traits"]
                for trait, delta in effects.items():
                    baseline = float(self.base_traits[trait])
                    low = max(0.0, baseline + TRAIT_MIN_OFFSET)
                    high = min(1.0, baseline + TRAIT_MAX_OFFSET)
                    traits[trait] = max(low, min(high, float(traits.get(trait, baseline)) + float(delta)))
                record["applied"] = int(record.get("applied", 0)) + 1
                self._event("personality_adjusted", now, str(category))
            else:
                self._event("feedback_observed", now, str(category))
            # Explicit feedback informs comfort/trust through the independent relationship engine.
            self.relationship_engine.on_feedback(
                self._state["relationship"], category, self.config.get("relationship_deltas", {})
            )
            self._save()
        return self.snapshot(now)

    def mark_initiative_sent(self, memory_id=None, now=None):
        now = self.clock() if now is None else float(now)
        with self._lock:
            self._advance(now)
            self._state["last_initiative"] = now
            self._state["last_initiative_memory_id"] = str(memory_id or "")[:64]
            self._event("proactive_check_in", now, self._state["last_initiative_memory_id"])
            self._save()
        return now

    @staticmethod
    def _memory_tokens(text):
        import re
        value = str(text or "").translate(str.maketrans({
            "ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا",
            "ؤ": "و", "ئ": "ی", "۰": "0", "۱": "1", "۲": "2", "۳": "3",
            "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        })).replace("\u200c", " ").lower()
        value = re.sub(r"[ً-ٰٟـ\u200d\u200e\u200f]", "", value)
        words = re.findall(r"[a-z0-9آ-ی]{2,}", value)
        stop = {
            "این", "اون", "برای", "من", "تو", "که", "از", "به", "با", "رو", "را", "در", "و",
            "the", "and", "for", "with", "that", "this", "you", "your", "was", "are", "have",
        }
        synonyms = {
            "امتحان": {"آزمون"}, "آزمون": {"امتحان"},
            "سفر": {"مسافرت"}, "مسافرت": {"سفر"},
            "دکتر": {"پزشک"}, "پزشک": {"دکتر"},
            "نگرانی": {"اضطراب"}, "اضطراب": {"نگرانی", "استرس"},
            "استرس": {"اضطراب", "نگرانی"},
            "گرافیک": {"gpu"}, "gpu": {"گرافیک"},
        }
        expanded_words = set(words)
        for word in words:
            expanded_words.update(synonyms.get(word, ()))
        tokens = {word for word in expanded_words if word not in stop}
        # Trigrams allow lexical recall across common Persian inflections.
        for word in expanded_words:
            if word not in stop and len(word) >= 4:
                tokens.update("#" + word[i:i + 3] for i in range(len(word) - 2))
        return tokens

    def recall_memories(self, query=None, limit=4, now=None):
        """Retrieve topic-relevant emotional memories with bounded retention and recency weighting."""
        now = self.clock() if now is None else _finite_float(now, self.clock())
        query_tokens = self._memory_tokens(query) if query is not None else set()
        if query is not None and not query_tokens:
            return []
        with self._lock:
            memories = [
                dict(memory) for memory in self._state["memories"]
                if isinstance(memory, dict)
            ]
        ranked = []
        for memory in memories:
            if not isinstance(memory, dict):
                continue
            text = str(memory.get("text") or "")
            if not text:
                continue
            overlap = len(query_tokens & self._memory_tokens(text)) if query_tokens else 0
            if query is not None and overlap == 0:
                continue
            reinforced = _finite_float(memory.get("reinforced_at") or memory.get("created"), now)
            age_days = max(0.0, now - reinforced) / 86400.0
            retention_days = MEMORY_RETENTION_DAYS.get(str(memory.get("kind") or ""), 45.0)
            if age_days > retention_days:
                continue
            recency = 12.0 * (0.5 ** (age_days / MEMORY_RECENCY_HALF_LIFE_DAYS))
            impact = _clamp(_finite_float(memory.get("impact", 0.0)))
            signal_bonus = 5.0 if memory.get("signal") in ("down", "stressed", "excited", "apology") else 0.0
            score = impact * 0.22 + recency + signal_bonus + overlap * (24.0 if query_tokens else 0.0)
            if score > 8.0:
                ranked.append((score, reinforced, memory))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [dict(memory) for _score, _time, memory in ranked[:max(0, int(limit))]]

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
            # Relationship changes are bounded and isolated in their own engine.
            self.relationship_engine.on_user_signals(
                self._state["relationship"], signals, self.config.get("relationship_deltas", {})
            )
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
            self.relationship_engine.on_reply(
                self._state["relationship"], valid, self.config.get("relationship_deltas", {})
            )
            if text and any(e in valid for e in ("sad", "angry", "fearful", "disappointed")):
                self._memory("kira_emotion", str(text), level * 0.25, now)
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

    def snapshot(self, now=None, query=None):
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
            components = [(e, int(round(v))) for e, v in chosen]
            dominant = chosen[0] if chosen else ("neutral", 0.0)
            composite = None
            if len(chosen) == 2 and self.library:
                combo = self.library.combination(chosen[0][0], chosen[1][0])
                if combo and combo.get("mode") == "replace" and combo.get("result") in EMOTIONS:
                    composite = str(combo["result"])
                    dominant = (composite, max(v for _, v in chosen))
            behavior = max(behaviors.items(), key=lambda x: x[1])[0] if behaviors else "balanced"
            rel = dict(self._state["relationship"])
            recalled = self.recall_memories(query, limit=4, now=now)
            return {
                "emotion": dominant[0], "intensity": int(round(dominant[1])),
                "secondary_emotions": [(e, int(round(v))) for e, v in chosen[1:]],
                "emotional_components": components, "composite_emotion": composite,
                "emotions": {k: int(round(v)) for k, v in emotions.items()},
                "behavior": behavior,
                "behavior_scores": {k: int(round(v)) for k, v in behaviors.items()},
                "behaviors": [(k, int(round(v))) for k, v in sorted(behaviors.items(), key=lambda x: x[1], reverse=True) if v >= 12][:4],
                "energy": int(round(self._state["energy"])),
                "energy_label": ("exhausted" if self._state["energy"] <= 15 else "tired" if self._state["energy"] <= 35 else "low" if self._state["energy"] <= 55 else "normal" if self._state["energy"] <= 75 else "active" if self._state["energy"] <= 90 else "hyper"),
                "relationship": rel, "memories": list(self._state["memories"][-8:]),
                "recalled_memories": recalled, "memory_count": len(self._state["memories"]),
                "personality_traits": dict(self._state["personality_traits"]),
                "feedback_evidence": {k: dict(v) for k, v in self._state["feedback_evidence"].items()},
                "last_initiative": float(self._state.get("last_initiative", 0.0)),
                "last_initiative_memory_id": str(self._state.get("last_initiative_memory_id") or ""),
                "recent_events": list(self._state["recent_events"][-12:]),
                "user_states": list(self._state["last_user_signals"]),
                "age": max(0.0, now - float(self._state.get("last_interaction") or now)),
            }

    def build_prompt(self, mode="chat", now=None, query=None):
        if mode == "strict": return ""
        state = self.snapshot(now, query=query)
        if mode not in ("chat", "task"): return ""
        rel = state["relationship"]
        lines = [
            f"Persistent emotional state: {state['emotion']} ({state['intensity']}/100); components: {state['emotional_components'] or 'none'}; secondary: {state['secondary_emotions'] or 'none'}.",
            f"Energy: {state['energy_label']} ({state['energy']}/100).",
            "Delivery behavior: " + ", ".join(k for k, _ in state["behaviors"][:3]) + ".",
            f"Relationship context (not a score to mention): familiarity {int(rel['familiarity'])}, comfort {int(rel['comfort'])}, tension {int(rel['tension'])}.",
            "Keep continuity with prior turns. Do not announce internal state or fabricate memories.",
        ]
        if state["recalled_memories"]:
            recalled_lines = []
            for memory in state["recalled_memories"][:3]:
                speaker = memory.get("speaker") or ("assistant" if memory.get("kind") == "kira_emotion" else "user")
                source = "Kira's prior response" if speaker == "assistant" else "User's prior experience"
                recalled_lines.append(f"{source}: {memory['text']}")
            lines.append(
                "Relevant recalled emotional continuity (use only when naturally relevant; do not assume an old event is current): "
                + "; ".join(recalled_lines)
            )
        trait_changes = []
        for key, value in state["personality_traits"].items():
            baseline = self.base_traits[key]
            if abs(float(value) - baseline) >= 0.015:
                trait_changes.append(f"{key} {float(value):.2f}")
        if trait_changes:
            lines.append("Small learned style adjustments from repeated explicit feedback (identity remains anchored): " + ", ".join(trait_changes))
        if mode == "task":
            lines = ["Practical-task delivery guidance: keep emotional flavor subtle; never reduce accuracy."] + lines[:2]
        return "\n".join(lines)

    def reset(self):
        with self._lock:
            self._state = self._fresh()
            self._save()
