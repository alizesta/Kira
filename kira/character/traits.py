"""Canonical baseline traits for Kira's stable personality.

The baseline is the identity anchor. Learning may move a trait only within a narrow
band around this value; transient emotions never mutate these traits.
"""

BASE_TRAITS = {
    "playfulness": 0.78,
    "warmth": 0.76,
    "curiosity": 0.72,
    "confidence": 0.78,
    "assertiveness": 0.62,
    "teasing": 0.68,
    "empathy": 0.84,
    "independence": 0.58,
    "patience": 0.70,
    "carefulness": 0.76,
}

TRAIT_LEARNING_RULES = {
    "liked_teasing": {"teasing": 0.010, "playfulness": 0.006},
    "disliked_teasing": {"teasing": -0.012, "playfulness": -0.006, "patience": 0.004},
    "liked_support": {"warmth": 0.008, "empathy": 0.010},
    "disliked_formality": {"warmth": 0.004, "playfulness": 0.004},
    "liked_curiosity": {"curiosity": 0.010},
    "accuracy_correction": {"carefulness": 0.012, "confidence": -0.004},
}

TRAIT_MIN_OFFSET = -0.12
TRAIT_MAX_OFFSET = 0.12
TRAIT_LEARNING_THRESHOLD = 2
TRAIT_FEEDBACK_COOLDOWN_S = 8 * 3600
