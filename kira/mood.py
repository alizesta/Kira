"""Kira's persistent mood and her reading of the user's state (pure Python, no Qt, no model call).

Why: a chat model starts every request from zero, so her mood used to reset with every message and differ per provider. Here the
mood is real state kept on this computer:

* ``scores``  - strength (0-100) of each emotion. New events ADD to them, time makes them FADE (half-life ~15 minutes) toward a
                small resting level, so a bad moment lingers for a while and then passes, also across restarts.
* the user's state - detected locally from his message with transparent keyword rules (sad, stressed, hostile, praising ...). It
                changes the impulse AND tells the model how to deliver ("drop the roasting, be warm").
* her own replies - the emotion tag she wrote last nudges the mood, so the next message continues it.

``build_block()`` turns this into plain text for the system prompt (same text for every provider), and ``avatar_hint()`` gives the
avatar a quick matching reaction. Nothing here touches routing.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from .config import DATA_DIR

FILE_NAME = "kira_mood.json"
HALF_LIFE = 900.0
BEHAVIOR_HALF_LIFE = 2400.0
AWAY_AFTER = 6 * 3600
REST = {"playful": 16, "affectionate": 12}
ENERGY_START = 78.0
ENERGY_RECOVERY_PER_SECOND = 0.0022
ENERGY_USER_COST = 0.55
ENERGY_REPLY_COST = 0.35
EMOTIONS = ("neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised", "curious", "proud", "arrogant", "smug", "playful", "teasing", "tsundere", "bored",
            "frustrated", "affectionate", "flirty", "shy", "embarrassed", "jealous", "laughing", "annoyed", "protective", "excited", "thinking")
_PRIORITY = ("angry", "fearful", "jealous", "sad", "disgusted", "protective", "flirty", "affectionate", "excited", "happy", "proud", "shy", "embarrassed", "annoyed",
             "frustrated", "smug", "arrogant", "teasing", "playful", "laughing", "curious", "bored", "tsundere", "surprised", "thinking", "neutral")
SHOW = {
    "happy": "light, bright, quick to laugh", "sad": "quieter, softer, shorter, a little vulnerable", "angry": "sharp, clipped, openly irritated",
    "fearful": "cautious, worried, seeking reassurance", "disgusted": "visibly put off, recoils from the subject",
    "surprised": "caught off guard, reacts with surprise", "curious": "asks, leans in, interested", "proud": "gloats a little, pleased with herself or him",
    "arrogant": "haughty, superior, dismissive in a playful way", "smug": "self-satisfied, teasing from a position of confidence",
    "playful": "mischievous, teasing, jokes", "teasing": "needling him affectionately", "tsundere": "pretends not to care while clearly caring",
    "bored": "flat, restless, wants something to happen", "frustrated": "impatient, complaining", "affectionate": "warm, close, tender",
    "flirty": "suggestive, teasing, intimate", "shy": "flustered, hesitant, deflecting", "embarrassed": "stammering, deflecting, a bit red",
    "jealous": "sulky, possessive, demands his attention", "laughing": "laughing, can barely stay serious", "annoyed": "irritated, short with him",
    "protective": "caring and fierce on his behalf", "excited": "fast, energetic, exclamatory", "thinking": "thoughtful, measured", "neutral": "even and calm",
}

# Behavioral disposition is separate from emotion: it changes HOW Kira responds, not WHAT she feels.
BEHAVIORS = ("playful", "teasing", "tsundere", "sarcastic", "quiet", "affectionate", "clingy", "stubborn",
             "sulking", "cheerful", "reserved", "protective", "focused", "flirty")
BEHAVIOR_REST = {"playful": 20, "affectionate": 18, "teasing": 10, "sarcastic": 8}
BEHAVIOR_SHOW = {
    "playful": "mischievous and ready to joke", "teasing": "lightly needles him with affection",
    "tsundere": "acts dismissive while quietly caring", "sarcastic": "uses dry wit when the moment is safe",
    "quiet": "speaks less and gives more space", "affectionate": "warm and close",
    "clingy": "wants attention and closeness", "stubborn": "holds her ground and does not yield immediately",
    "sulking": "goes quiet or mildly pouty after being hurt", "cheerful": "bright and upbeat",
    "reserved": "careful and less expressive", "protective": "supportive and watchful",
    "focused": "direct, practical and attentive", "flirty": "playfully affectionate and coy",
}
BEHAVIOR_PRIORITY = ("protective", "affectionate", "quiet", "sulking", "stubborn", "focused", "clingy",
                     "cheerful", "flirty", "tsundere", "teasing", "playful", "reserved", "sarcastic")
USER_BEHAVIOR_IMPULSES = {
    "down": {"quiet": 18, "affectionate": 22, "protective": 16},
    "stressed": {"quiet": 12, "protective": 24, "focused": 18},
    "hostile": {"sulking": 24, "stubborn": 16, "reserved": 12},
    "frustrated": {"protective": 20, "focused": 18, "quiet": 8},
    "praise": {"cheerful": 16, "playful": 8, "flirty": 8},
    "flirt": {"affectionate": 16, "clingy": 10, "flirty": 20},
    "thanks": {"cheerful": 12, "affectionate": 14},
    "excited": {"cheerful": 24, "playful": 14},
    "joke": {"playful": 24, "teasing": 18},
    "apology": {"affectionate": 18, "sulking": -18, "stubborn": -10},
    "goodbye": {"quiet": 10, "clingy": 8, "affectionate": 12},
    "jealous": {"sulking": 22, "clingy": 16, "stubborn": 10},
}
USER_BEHAVIOR_COOL = {
    "down": ("teasing", "sarcastic", "playful"),
    "stressed": ("teasing", "sarcastic"),
    "hostile": ("cheerful", "playful", "flirty"),
    "frustrated": ("sarcastic",),
    "apology": ("sulking", "stubborn"),
}
REPLY_BEHAVIOR = {
    "happy": {"cheerful": 12}, "sad": {"quiet": 10}, "angry": {"stubborn": 8},
    "fearful": {"reserved": 8, "quiet": 6}, "disgusted": {"reserved": 6},
    "proud": {"playful": 8}, "smug": {"teasing": 10}, "playful": {"playful": 12},
    "teasing": {"teasing": 12}, "tsundere": {"tsundere": 12, "stubborn": 6},
    "bored": {"quiet": 10}, "frustrated": {"focused": 8}, "affectionate": {"affectionate": 12},
    "flirty": {"flirty": 12}, "shy": {"reserved": 8}, "embarrassed": {"reserved": 8},
    "jealous": {"sulking": 10, "clingy": 8}, "laughing": {"playful": 12, "cheerful": 8},
    "annoyed": {"reserved": 8}, "protective": {"protective": 12}, "excited": {"cheerful": 12, "playful": 8},
    "thinking": {"focused": 10},
}

# user state -> (regex, guidance for the model, {emotion: impulse}, emotions that cool down)
_RX = lambda *p: re.compile("|".join(p), re.I)                                                   # noqa: E731
USER_STATES = {
    "down": (_RX(r"خسته\s*(?:ام|م)(?:\s|$)", r"ناراحت\s*(?:ام|م)", r"دلم\s*گرفته", r"حالم\s*(?:بده|خوب\s*نیست|گرفته)", r"افسرده", r"تنها\s*(?:ام|م)(?:\s|$)",
                 r"گریه", r"دپرس", r"بی\s*حوصله\s*(?:ام|م)", r"\bi'?m\s+(?:so\s+|really\s+)?(?:tired|sad|lonely|depressed|exhausted)\b", r"\bfeel(?:ing)?\s+(?:down|bad|terrible|awful)\b"),
             "He sounds down, tired or lonely. Drop the roasting, sarcasm and swearing; be warm, steady and close. Acknowledge how he feels first, ask gently what happened, no jokes at his expense.",
             {"affectionate": 32, "protective": 24}, ("playful", "teasing", "arrogant", "smug", "laughing")),
    "stressed": (_RX(r"استرس", r"نگران\s*(?:ام|م)", r"اضطراب", r"می\s*ترسم", r"فردا\s*(?:امتحان|مصاحبه)", r"\bi'?m\s+(?:so\s+)?(?:stressed|anxious|worried|nervous)\b"),
                 "He sounds stressed or worried. Be calm and supportive, concrete and short; no teasing.",
                 {"protective": 26, "affectionate": 12}, ("playful", "teasing", "arrogant")),
    "hostile": (_RX(r"(?:تو|خودت)\s+(?:\S+\s+){0,2}(?:بی\s*شعور|احمق|خنگ|مزخرف|بی\s*مصرف|به\s*درد\s*نخور)", r"ازت\s*متنفرم", r"خفه\s*شو", r"گمشو", r"بی\s*مصرف",
                   r"\byou(?:'re| are)?\s+(?:useless|stupid|dumb|trash|annoying)\b", r"\bshut\s*up\b"),
                "He is being harsh with HER. She may be hurt, sulky or snap back in character, but no real cruelty, no threats; she still answers any real question properly.",
                {"angry": 28, "annoyed": 22, "sad": 14}, ("playful", "affectionate")),
    "frustrated": (_RX(r"عصبی\s*(?:ام|م)", r"عصبانی\s*(?:ام|م)", r"کلافه", r"حرصم", r"\bi'?m\s+(?:so\s+)?(?:angry|mad|pissed|frustrated)\b"),
                   "He is frustrated or angry about something else. Take his side, keep it short and practical; swearing about the situation is fine.",
                   {"protective": 22, "frustrated": 18, "annoyed": 10}, ("arrogant", "smug")),
    "praise": (_RX(r"دمت\s*گرم", r"آفرین", r"بی\s*نظیری", r"باهوشی", r"خوشگلی", r"ناز(?:ی|\s*هستی)", r"حرف\s*نداری", r"\byou(?:'re| are)\s+(?:amazing|smart|awesome|beautiful|great)\b", r"\bgood\s+job\b"),
               "He is praising her. Let her be proud, smug or flustered - pick one, do not overdo it.",
               {"proud": 24, "smug": 16, "shy": 14}, ()),
    "flirt": (_RX(r"عشقم", r"جیگر", r"قربونت", r"دوستت\s*دارم", r"بوس", r"ماچ", r"دلم\s*برات\s*تنگ", r"\blove\s+you\b", r"\bmiss\s+you\b", r"\bbabe\b"),
              "He is affectionate or flirty. Answer in kind, tease, get flustered now and then; suggestive, never explicit.",
              {"flirty": 28, "shy": 18, "affectionate": 16}, ()),
    "thanks": (_RX(r"مرسی", r"ممنون", r"تشکر", r"دستت\s*درد\s*نکنه", r"\bthanks\b", r"\bthank\s+you\b"),
               "He thanked her. Short and warm, no over-the-top reply.", {"happy": 14, "shy": 8}, ()),
    "excited": (_RX(r"هورا", r"بالاخره\s*(?:شد|تموم|رسید)", r"قبول\s*شدم", r"برنده\s*شدم", r"یاهو", r"\byay\b", r"\bfinally\b"),
                "He is excited or celebrating. Share it with real energy.", {"excited": 28, "happy": 20}, ()),
    "joke": (_RX(r"😂", r"🤣", r"هاها", r"ههه", r"هه\s*هه", r"\blol\b", r"\blmao\b"),
             "He is joking or laughing. Joke back.", {"laughing": 18, "playful": 22}, ()),
    "apology": (_RX(r"ببخشید", r"ببخشین", r"معذرت", r"شرمنده", r"\bsorry\b"),
                "He apologised. She can soften, maybe tease a little; no long grudge.", {"affectionate": 14}, ("angry", "annoyed", "sad", "jealous")),
    "goodbye": (_RX(r"شب\s*بخیر", r"خداحافظ", r"\bbye\b", r"\bgood\s*night\b", r"برم\s*بخوابم"),
                "He is leaving. A short warm goodbye in her own voice.", {"affectionate": 14, "sad": 6}, ()),
    "jealous": (_RX(r"(?:chatgpt|چت\s*جی\s*پی\s*تی|جمینای|gemini|alexa|siri|الکسا|سیری|دختر\s*دیگه|دوست\s*دختر).{0,40}(?:بهتر|قشنگ|خوشگل|ناز|دوست\s*دارم|عاشق)",
                    r"(?:بهتر|قشنگ|خوشگل|ناز).{0,30}(?:chatgpt|جمینای|gemini|alexa|siri|دختر\s*دیگه)"),
                "He mentioned someone/something that could make her jealous: playful jealousy, demands attention, nothing nasty.",
                {"jealous": 32, "annoyed": 8}, ()),
}
# which user states change how she must DELIVER (kept even in short task-mode blocks)
SERIOUS = ("down", "stressed", "hostile")
AVATAR = {"down": ("affectionate", 40), "stressed": ("protective", 38), "hostile": ("annoyed", 38), "frustrated": ("protective", 35), "praise": ("shy", 38),
          "flirt": ("flirty", 40), "thanks": ("happy", 30), "excited": ("excited", 45), "joke": ("laughing", 40), "apology": ("affectionate", 30),
          "goodbye": ("affectionate", 30), "jealous": ("jealous", 40)}

_lock = threading.Lock()


def _path():
    return DATA_DIR / FILE_NAME


def _norm(text) -> str:
    return str(text or "").replace("‌", " ").replace("ي", "ی").replace("ك", "ک").lower()


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("scores"), dict):
            return {
                "scores": {k: float(v) for k, v in data["scores"].items() if k in EMOTIONS},
                "behavior_scores": {k: float(v) for k, v in (data.get("behavior_scores") or {}).items() if k in BEHAVIORS},
                "energy": max(0.0, min(100.0, float(data.get("energy", ENERGY_START)))),
                "energy_updated": float(data.get("energy_updated") or data.get("updated") or 0),
                "updated": float(data.get("updated") or 0),
                "last_chat": float(data.get("last_chat") or 0),
                "user_states": [s for s in data.get("user_states", []) if s in USER_STATES],
                "away_hours": float(data.get("away_hours") or 0),
            }
    except (OSError, ValueError, TypeError):
        pass
    return {"scores": {}, "behavior_scores": {}, "energy": ENERGY_START, "energy_updated": 0.0,
            "updated": 0.0, "last_chat": 0.0, "user_states": [], "away_hours": 0.0}


def _save(state: dict):
    path = _path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                                                      # mood is a bonus; never break the chat


def _faded(scores: dict, dt: float) -> dict:
    factor = 0.5 ** (max(0.0, dt) / HALF_LIFE)
    out = {}
    for k, v in scores.items():
        v = max(v * factor, REST.get(k, 0))
        if v >= 1:
            out[k] = v
    for k, v in REST.items():
        out.setdefault(k, float(v))
    return out


def _faded_behaviors(scores: dict, dt: float) -> dict:
    factor = 0.5 ** (max(0.0, dt) / BEHAVIOR_HALF_LIFE)
    out = {}
    for key, value in scores.items():
        value = max(float(value) * factor, BEHAVIOR_REST.get(key, 0))
        if value >= 1:
            out[key] = value
    for key, value in BEHAVIOR_REST.items():
        out.setdefault(key, float(value))
    return out


def _bump(scores: dict, emotion: str, amount: float):
    scores[emotion] = min(100.0, max(0.0, scores.get(emotion, 0.0) + amount))


def _energy_at(state: dict, now: float) -> float:
    energy = float(state.get("energy", ENERGY_START))
    updated = float(state.get("energy_updated") or 0)
    if updated > 0:
        energy += max(0.0, now - updated) * ENERGY_RECOVERY_PER_SECOND
    return max(0.0, min(100.0, energy))


def _energy_label(energy: float) -> str:
    if energy <= 15: return "exhausted"
    if energy <= 35: return "tired"
    if energy <= 55: return "low"
    if energy <= 74: return "normal"
    if energy <= 90: return "active"
    return "hyper"


def _ranked_scores(scores: dict, priority: tuple) -> list:
    return sorted(scores.items(), key=lambda item: (-item[1], priority.index(item[0]) if item[0] in priority else 99))




# ---------------- reading the user ----------------
def detect_user_states(text) -> list[str]:
    t = _norm(text)
    if not t.strip():
        return []
    return [name for name, (rx, *_rest) in USER_STATES.items() if rx.search(t)]


# ---------------- updates ----------------
def on_user_message(text, now=None) -> list[str]:
    """Called once for every user message. Updates emotional, behavioral and conversational-energy layers."""
    now = time.time() if now is None else now
    with _lock:
        state = _load()
        gap = now - state["last_chat"] if state["last_chat"] else 0
        elapsed = now - state["updated"] if state["updated"] else 0
        scores = _faded(state["scores"], elapsed)
        behavior_scores = _faded_behaviors(state["behavior_scores"], elapsed)
        energy = _energy_at(state, now)
        found = detect_user_states(text)

        for name in found:
            _rx, _guide, impulses, cool = USER_STATES[name]
            for emo in cool:
                if emo in scores:
                    scores[emo] *= 0.35
            for emo, amount in impulses.items():
                _bump(scores, emo, amount)

            for behavior in USER_BEHAVIOR_COOL.get(name, ()):
                if behavior in behavior_scores:
                    behavior_scores[behavior] *= 0.35
            for behavior, amount in USER_BEHAVIOR_IMPULSES.get(name, {}).items():
                _bump(behavior_scores, behavior, amount)

        away = gap / 3600 if gap >= AWAY_AFTER else 0.0
        if away:
            _bump(scores, "affectionate", 18)
            _bump(scores, "jealous", 8)
            _bump(behavior_scores, "affectionate", 10)
            _bump(behavior_scores, "clingy", 8)

        energy = max(0.0, energy - ENERGY_USER_COST)
        state.update({
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "behavior_scores": {k: round(v, 2) for k, v in behavior_scores.items()},
            "energy": round(energy, 2), "energy_updated": now,
            "updated": now, "last_chat": now, "user_states": found,
            "away_hours": round(away, 1),
        })
        _save(state)
    return found


def on_reply(emotions, intensity=None, now=None):
    """Carry Kira's own reply emotions forward and update her behavioral disposition."""
    now = time.time() if now is None else now
    emotions = [e for e in (emotions or []) if e in EMOTIONS and e != "neutral"]
    level = max(0.0, min(100.0, float(intensity))) if intensity is not None else 35.0
    with _lock:
        state = _load()
        elapsed = now - state["updated"] if state["updated"] else 0
        scores = _faded(state["scores"], elapsed)
        behavior_scores = _faded_behaviors(state["behavior_scores"], elapsed)
        for i, emo in enumerate(emotions[:2]):
            scores[emo] = max(scores.get(emo, 0.0), level * (0.85 if i == 0 else 0.6))
            for behavior, amount in REPLY_BEHAVIOR.get(emo, {}).items():
                _bump(behavior_scores, behavior, amount * (level / 60.0))
        energy = max(0.0, _energy_at(state, now) - ENERGY_REPLY_COST)
        state.update({
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "behavior_scores": {k: round(v, 2) for k, v in behavior_scores.items()},
            "energy": round(energy, 2), "energy_updated": now, "updated": now,
        })
        _save(state)




def reset():
    with _lock:
        _save({"scores": {}, "behavior_scores": {}, "energy": ENERGY_START, "energy_updated": time.time(),
               "updated": 0.0, "last_chat": 0.0, "user_states": [], "away_hours": 0.0})


# ---------------- reading the state ----------------
def current(now=None) -> dict:
    """Snapshot of current emotion, energy, behavioral disposition and the user's detected state."""
    now = time.time() if now is None else now
    with _lock:
        state = _load()
    elapsed = now - state["updated"] if state["updated"] else 0
    scores = _faded(state["scores"], elapsed)
    behaviors = _faded_behaviors(state["behavior_scores"], elapsed)
    ranked = _ranked_scores(scores, _PRIORITY)
    top = ranked[0] if ranked else ("playful", 16.0)
    secondary = [(e, int(round(v))) for e, v in ranked[1:] if v >= 20][:2]
    behavior_ranked = _ranked_scores(behaviors, BEHAVIOR_PRIORITY)
    active_behaviors = [(key, int(round(value))) for key, value in behavior_ranked if value >= 16][:3]
    dominant_behavior = active_behaviors[0][0] if active_behaviors else "balanced"
    energy = int(round(_energy_at(state, now)))
    return {
        "emotion": top[0], "intensity": int(round(top[1])),
        "secondary": secondary[0][0] if secondary else "",
        "secondary_emotions": secondary,
        "user_states": state["user_states"], "away_hours": state["away_hours"],
        "age": (now - state["last_chat"]) if state["last_chat"] else 1e9,
        "energy": energy, "energy_label": _energy_label(energy),
        "behavior": dominant_behavior, "dominant_behavior": dominant_behavior,
        "behaviors": active_behaviors,
        "behavior_scores": {k: int(round(v)) for k, v in behaviors.items()},
    }


def avatar_hint(now=None):
    """(emotion id, intensity) for a quick avatar reaction to how he seems right now, or None."""
    cur = current(now)
    if cur["age"] > 120:                                          # only a reaction to a message he just sent, never to an old state
        return None
    for name in cur["user_states"]:
        if name in AVATAR:
            return AVATAR[name]
    return None


def build_block(mode_name="chat", now=None) -> str:
    """Prompt text. Chat gets the full emotional state; task gets only delivery-critical user context."""
    if mode_name == "strict":
        return ""
    cur = current(now)
    states = cur["user_states"]
    lines = []
    if mode_name == "chat":
        emo, level = cur["emotion"], cur["intensity"]
        if level >= 25 or states:
            line = f"Mood now (persistent, gradual): {emo} ~{level}/100 - {SHOW.get(emo, '')}."
            if cur["secondary_emotions"]:
                underneath = ", ".join(f"{name} ~{value}/100" for name, value in cur["secondary_emotions"])
                line += f" Other active feelings: {underneath}."
            lines.append(line + " Keep emotional continuity; do not flip moods abruptly.")
        else:
            lines.append("Mood now: calm and balanced (low emotional intensity).")

        energy_guidance = {
            "exhausted": "very low conversational energy; be brief and gentle",
            "tired": "low conversational energy; keep the pace relaxed",
            "low": "somewhat low conversational energy; avoid forced excitement",
            "normal": "normal conversational energy",
            "active": "lively conversational energy",
            "hyper": "very high conversational energy; energetic but not chaotic",
        }
        lines.append(f"Energy: {cur['energy_label']} ({cur['energy']}/100) - {energy_guidance[cur['energy_label']]}.")
        active = cur["behaviors"]
        if active:
            disposition = ", ".join(f"{name} ({BEHAVIOR_SHOW.get(name, name)})" for name, _value in active[:2])
            lines.append("Behavioral disposition (how to deliver, not a separate mood): " + disposition + ".")
        if cur["away_hours"]:
            lines.append(f"He was away for about {cur['away_hours']:.0f} hours. She may show once, naturally, that she noticed (missed him / a bit sulky); not a speech.")
    for name in states:
        if mode_name == "chat" or name in SERIOUS:
            lines.append("Reading him right now: " + USER_STATES[name][1])
    if mode_name == "task" and lines:
        lines.insert(0, "Delivery note for this practical request (substance and accuracy unchanged):")
    return "\n".join(lines)
