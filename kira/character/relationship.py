"""Independent, bounded relationship-state engine for Kira.

Relationship values are continuity signals, not scores or rewards. Updates are
small, explainable and bounded; trust and closeness do not decay merely with time.
"""
from __future__ import annotations

from typing import Mapping, MutableMapping


RELATIONSHIP_KEYS = ("trust", "closeness", "familiarity", "comfort", "tension")

DEFAULT_RELATIONSHIP = {
    "trust": 50.0,
    "closeness": 28.0,
    "familiarity": 12.0,
    "comfort": 45.0,
    "tension": 0.0,
}

DEFAULT_DELTAS = {
    "thanks_closeness": 0.12,
    "thanks_comfort": 0.10,
    "apology_tension": -0.8,
    "apology_trust": 0.08,
    "hostile_tension": 0.5,
    "hostile_comfort": -0.12,
    "familiarity_per_message": 0.025,
    "reply_closeness": 0.025,
    "liked_feedback_comfort": 0.08,
    "liked_feedback_trust": 0.04,
    "disliked_teasing_comfort": 0.10,
    "disliked_teasing_trust": 0.06,
    "disliked_teasing_tension": -0.08,
    "accuracy_correction_trust": -0.12,
    "tension_recovery_per_day": 2.0,
}


def clamp(value, minimum=0.0, maximum=100.0):
    return max(minimum, min(maximum, float(value)))


class RelationshipEngine:
    """Stateless update rules; persistence and locking remain owned by EmotionalRuntime."""

    def __init__(self, defaults=None):
        self.defaults = dict(DEFAULT_RELATIONSHIP)
        if isinstance(defaults, Mapping):
            for key in RELATIONSHIP_KEYS:
                if key in defaults:
                    self.defaults[key] = clamp(defaults[key])

    @staticmethod
    def deltas(config=None):
        values = dict(DEFAULT_DELTAS)
        if isinstance(config, Mapping):
            values.update({key: value for key, value in config.items() if key in values})
        return values

    def normalize(self, relationship):
        source = relationship if isinstance(relationship, Mapping) else {}
        return {key: clamp(source.get(key, self.defaults[key])) for key in RELATIONSHIP_KEYS}

    def advance(self, relationship: MutableMapping, elapsed_seconds, config=None):
        """Tension slowly settles; trust and closeness are deliberately unchanged by absence."""
        rel = self.normalize(relationship)
        rules = self.deltas(config)
        elapsed = max(0.0, float(elapsed_seconds or 0.0))
        recovery = elapsed * float(rules["tension_recovery_per_day"]) / 86400.0
        rel["tension"] = clamp(rel["tension"] - recovery)
        relationship.clear()
        relationship.update(rel)
        return relationship

    def on_user_signals(self, relationship, signals, config=None, *, count_message=True):
        rel = self.normalize(relationship)
        rules = self.deltas(config)
        signals = set(str(signal) for signal in (signals or ()))
        if "thanks" in signals or "praise" in signals:
            rel["closeness"] = clamp(rel["closeness"] + float(rules["thanks_closeness"]))
            rel["comfort"] = clamp(rel["comfort"] + float(rules["thanks_comfort"]))
        if "apology" in signals:
            rel["tension"] = clamp(rel["tension"] + float(rules["apology_tension"]))
            rel["trust"] = clamp(rel["trust"] + float(rules["apology_trust"]))
        if "hostile" in signals:
            rel["tension"] = clamp(rel["tension"] + float(rules["hostile_tension"]))
            rel["comfort"] = clamp(rel["comfort"] + float(rules["hostile_comfort"]))
        if count_message:                                   # a model-read signal belongs to a message that was already counted
            rel["familiarity"] = clamp(rel["familiarity"] + float(rules["familiarity_per_message"]))
        relationship.clear()
        relationship.update(rel)
        return relationship

    def on_reply(self, relationship, emotions, config=None):
        rel = self.normalize(relationship)
        rules = self.deltas(config)
        valid = set(str(emotion) for emotion in (emotions or ()))
        if valid & {"happy", "affectionate", "grateful", "relieved"}:
            rel["closeness"] = clamp(rel["closeness"] + float(rules["reply_closeness"]))
        relationship.clear()
        relationship.update(rel)
        return relationship

    def on_feedback(self, relationship, category, config=None):
        rel = self.normalize(relationship)
        rules = self.deltas(config)
        category = str(category)
        if category in ("liked_teasing", "liked_support", "liked_curiosity", "disliked_formality"):
            rel["comfort"] = clamp(rel["comfort"] + float(rules["liked_feedback_comfort"]))
            rel["trust"] = clamp(rel["trust"] + float(rules["liked_feedback_trust"]))
        elif category == "disliked_teasing":
            rel["comfort"] = clamp(rel["comfort"] + float(rules["disliked_teasing_comfort"]))
            rel["trust"] = clamp(rel["trust"] + float(rules["disliked_teasing_trust"]))
            rel["tension"] = clamp(rel["tension"] + float(rules["disliked_teasing_tension"]))
        elif category == "accuracy_correction":
            rel["trust"] = clamp(rel["trust"] + float(rules["accuracy_correction_trust"]))
        relationship.clear()
        relationship.update(rel)
        return relationship
