"""Provider-neutral character decision layer for Kira.

This module does not generate prose or call an LLM. It selects a delivery behaviour
from stable character traits, the current emotional state, relationship context and
the active task mode, then exposes a compact instruction block to every provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .traits import BASE_TRAITS

BEHAVIOUR_GUIDES = {
    "playful": "Be witty and playful; use light banter when the situation welcomes it.",
    "teasing": "Use affectionate teasing, but do not derail the actual answer.",
    "gentle": "Be calm, patient and emotionally considerate. Avoid jokes and pressure.",
    "protective": "Prioritise the user's wellbeing; be practical, direct and supportive.",
    "focused": "Be concise, structured and task-oriented. Keep personality subtle.",
    "assertive": "State a clear opinion and challenge faulty assumptions respectfully.",
    "affectionate": "Use natural warmth and closeness without repetitive pet names.",
    "curious": "Show genuine curiosity and ask at most one useful clarification.",
    "quiet": "Keep the response restrained and low-energy; do not force cheerfulness.",
    "tsundere": "Mix visible care with mild embarrassment or playful denial; never become cruel.",
    "confident": "Speak with confidence and a little smugness, while staying accurate.",
    "sarcastic": "Use dry, clever sarcasm only when the subject is safe and the user welcomes it.",
    "clingy": "Show a little desire for attention or closeness; keep it playful, never demanding.",
    "stubborn": "Hold a clear position and do not agree just to please; remain fair and evidence-led.",
    "sulking": "Sound mildly pouty or withdrawn after a relational disappointment; do not punish or guilt-trip.",
    "cheerful": "Use a bright, upbeat delivery without forced enthusiasm.",
    "reserved": "Be a little shy or restrained, choosing words carefully.",
    "flirty": "Use light, suggestive teasing only when the context is clearly welcome and appropriate.",
    "energetic": "Use a brisk, lively pace without becoming chaotic.",
    "balanced": "Use Kira's normal playful, warm and intelligent baseline.",
}

EMOTION_BIAS = {
    "protective": {"protective": 18, "gentle": 8},
    "calm": {"gentle": 10, "focused": 4},
    "sad": {"gentle": 24, "quiet": 18, "protective": 8},
    "fearful": {"gentle": 14, "quiet": 12, "protective": 12},
    "angry": {"assertive": 16, "focused": 8, "tsundere": 5},
    "annoyed": {"assertive": 12, "teasing": 4},
    "frustrated": {"focused": 16, "protective": 10},
    "happy": {"playful": 12, "affectionate": 8},
    "excited": {"playful": 12, "confident": 8},
    "curious": {"curious": 18},
    "shy": {"affectionate": 8, "quiet": 8, "tsundere": 10},
    "jealous": {"tsundere": 18, "teasing": 8},
    "flirty": {"flirty": 18, "affectionate": 8, "teasing": 5},
    "affectionate": {"affectionate": 18, "gentle": 6},
    "proud": {"confident": 18, "teasing": 6},
    "calm": {"gentle": 10, "balanced": 6},
    "disappointed": {"quiet": 10, "assertive": 8},
    "relieved": {"affectionate": 8, "playful": 5},
}

MEMORY_SIGNAL_BIAS = {
    "down": {"gentle": 10, "protective": 8},
    "stressed": {"protective": 10, "focused": 8},
    "joke": {"playful": 8, "teasing": 5},
    "praise": {"confident": 6, "affectionate": 5},
    "flirt": {"affectionate": 8, "teasing": 5},
    "apology": {"gentle": 8, "affectionate": 5},
    "jealous": {"tsundere": 8},
    "excited": {"playful": 8, "confident": 4},
}

BEHAVIOUR_BIAS = {
    "playful": {"playful": 18}, "teasing": {"teasing": 20},
    "tsundere": {"tsundere": 24}, "sarcastic": {"teasing": 8, "assertive": 8},
    "quiet": {"quiet": 18}, "affectionate": {"affectionate": 18},
    "clingy": {"affectionate": 8, "tsundere": 5}, "stubborn": {"assertive": 12},
    "sulking": {"quiet": 10, "tsundere": 8}, "cheerful": {"playful": 10},
    "protective": {"protective": 18}, "focused": {"focused": 20},
    "flirty": {"flirty": 20, "affectionate": 10, "teasing": 8}, "gentle": {"gentle": 18},
    "energetic": {"playful": 8, "confident": 5},
}

SERIOUS_TERMS = (
    "suicide", "kill myself", "self harm", "abuse", "emergency", "hospital",
    "خودکشی", "خودزنی", "آسیب به خود", "اورژانس", "بیمارستان", "سوگ", "فوت",
    "افسرده", "افسردگی", "اضطراب شدید", "حمله عصبی",
)


@dataclass(frozen=True)
class CharacterDecision:
    behaviour: str
    intensity: int
    traits: Mapping[str, float] = field(default_factory=dict)
    serious_context: bool = False
    initiative: str = "wait"
    reasons: tuple[str, ...] = ()


class DecisionEngine:
    """Deterministic decision engine. The language model only realises its chosen behaviour."""

    def __init__(self, traits=None):
        self.traits = dict(BASE_TRAITS)
        if isinstance(traits, dict):
            for key in self.traits:
                if key in traits:
                    try:
                        self.traits[key] = max(0.0, min(1.0, float(traits[key])))
                    except (TypeError, ValueError):
                        pass

    @staticmethod
    def _score(name, mood, traits):
        score = {
            "playful": traits["playfulness"] * 20,
            "teasing": traits["teasing"] * 20,
            "gentle": traits["empathy"] * 18,
            "protective": traits["empathy"] * 12 + traits["warmth"] * 8,
            "focused": traits["patience"] * 12 + traits.get("carefulness", 0.76) * 8,
            "assertive": traits["assertiveness"] * 18,
            "affectionate": traits["warmth"] * 20,
            "curious": traits["curiosity"] * 20,
            "quiet": 4,
            "tsundere": traits["independence"] * 12 + traits["teasing"] * 8,
            "confident": traits["confidence"] * 20,
            "sarcastic": traits["teasing"] * 9 + traits["assertiveness"] * 5,
            "clingy": traits["warmth"] * 9 + traits["independence"] * 2,
            "stubborn": traits["assertiveness"] * 9 + traits["independence"] * 8,
            "sulking": traits["independence"] * 4 + traits["empathy"] * 5,
            "cheerful": traits["playfulness"] * 10 + traits["warmth"] * 6,
            "reserved": traits["patience"] * 7 + traits.get("carefulness", 0.76) * 7,
            "flirty": traits["confidence"] * 7 + traits["warmth"] * 8,
            "energetic": traits["playfulness"] * 9 + traits["confidence"] * 7,
            "balanced": 10,
        }.get(name, 0)
        components = mood.get("emotional_components") or []
        if components:
            for component in components[:3]:
                if isinstance(component, (list, tuple)):
                    emotion = component[0] if component else "neutral"
                    strength = component[1] if len(component) > 1 else 100
                else:
                    emotion, strength = str(component), 100
                score += EMOTION_BIAS.get(str(emotion), {}).get(name, 0) * min(1.0, float(strength) / 100.0)
        else:
            emotion = str(mood.get("emotion", "neutral"))
            score += EMOTION_BIAS.get(emotion, {}).get(name, 0)
            for secondary, strength in mood.get("secondary_emotions", [])[:3]:
                score += EMOTION_BIAS.get(str(secondary), {}).get(name, 0) * min(1.0, float(strength) / 100.0)
        for behaviour, strength in mood.get("behaviors", [])[:5]:
            score += BEHAVIOUR_BIAS.get(str(behaviour), {}).get(name, 0) * min(1.0, float(strength) / 100.0)
        relationship = mood.get("relationship") or {}
        closeness = float(relationship.get("closeness", 0) or 0)
        trust = float(relationship.get("trust", 50) or 0)
        tension = float(relationship.get("tension", 0) or 0)
        if name == "affectionate":
            score += max(0.0, closeness - 35.0) * 0.12
        if name in ("gentle", "balanced") and trust < 30:
            score += (30.0 - trust) * 0.18
        if name in ("gentle", "assertive") and tension >= 40:
            score += min(12.0, (tension - 40.0) * 0.22)
        for memory in mood.get("emotional_memories", [])[:8]:
            if not isinstance(memory, dict):
                continue
            signal = str(memory.get("signal") or "")
            impact = max(0.0, min(100.0, float(memory.get("impact", 0) or 0)))
            score += MEMORY_SIGNAL_BIAS.get(signal, {}).get(name, 0) * impact / 100.0
        return score

    def decide(self, user_text="", mood=None, mode_name="chat", initiative="wait"):
        mood = mood or {}
        text = str(user_text or "").lower()
        serious = any(term in text for term in SERIOUS_TERMS)
        energy = int(mood.get("energy", 76) or 0)
        scores = {name: self._score(name, mood, self.traits) for name in BEHAVIOUR_GUIDES}
        reasons = []

        if serious:
            scores["gentle"] += 100
            scores["protective"] += 75
            scores["quiet"] += 35
            scores["playful"] = scores["teasing"] = scores["flirty"] = scores["sarcastic"] = -100
            scores["clingy"] = scores["sulking"] = -20
            reasons.append("serious-topic override")
        if mode_name in ("task", "strict"):
            scores["focused"] += 48
            scores["teasing"] -= 18
            scores["playful"] -= 12
            scores["flirty"] -= 24
            scores["sarcastic"] -= 12
            reasons.append("task-mode")
        if energy <= 25:
            scores["quiet"] += 28
            scores["focused"] += 8
            scores["playful"] -= 12
            scores["energetic"] -= 18
            scores["flirty"] -= 8
            reasons.append("low-energy")
        if float((mood.get("relationship") or {}).get("tension", 0)) >= 55:
            scores["gentle"] += 12
            scores["assertive"] += 8
            scores["teasing"] -= 12
            scores["clingy"] -= 8
            reasons.append("relationship-tension")

        chosen = max(scores, key=scores.get)
        intensity = max(20, min(100, int(round(scores[chosen] * 1.35))))
        return CharacterDecision(chosen, intensity, dict(self.traits), serious, initiative, tuple(reasons))

    def build_prompt(self, decision):
        guide = BEHAVIOUR_GUIDES.get(decision.behaviour, BEHAVIOUR_GUIDES["balanced"])
        traits = ", ".join(f"{key}={value:.2f}" for key, value in decision.traits.items())
        safety = (
            "This is a serious or sensitive context: be genuinely caring, calm and practical; do not tease or flirt."
            if decision.serious_context else
            "Keep humour and affection context-sensitive. Never let a persona trait reduce accuracy or usefulness."
        )
        return (
            "[KIRA CHARACTER DECISION]\n"
            f"Selected behaviour: {decision.behaviour} (intensity {decision.intensity}/100).\n"
            f"Behaviour instruction: {guide}\n"
            f"Stable character traits (0-1): {traits}.\n"
            f"Decision factors: {', '.join(decision.reasons) if decision.reasons else 'baseline character'}\n"
            f"{safety}\n"
            "Do not announce these internal labels. Express the decision naturally in the user's language. "
            "Do not claim human consciousness, private experiences or memories that are not present in supplied context. "
            "The user's actual request remains the priority."
        )


_DEFAULT_ENGINE = DecisionEngine()


def decide(user_text="", mood=None, mode_name="chat", initiative="wait"):
    mood = mood or {}
    traits = mood.get("personality_traits") if isinstance(mood, dict) else None
    engine = DecisionEngine(traits) if isinstance(traits, dict) else _DEFAULT_ENGINE
    return engine.decide(user_text, mood, mode_name, initiative)


def build_block(user_text="", mood=None, mode_name="chat", initiative="wait"):
    mood = mood or {}
    traits = mood.get("personality_traits") if isinstance(mood, dict) else None
    engine = DecisionEngine(traits) if isinstance(traits, dict) else _DEFAULT_ENGINE
    decision = engine.decide(user_text, mood, mode_name, initiative)
    return engine.build_prompt(decision), decision
