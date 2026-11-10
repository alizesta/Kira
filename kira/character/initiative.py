"""Bounded initiative policy for Kira.

This module decides whether a proactive turn is appropriate. It deliberately does
not send messages itself: the UI must own delivery, user opt-in and quiet hours.
"""
from __future__ import annotations

import time


class InitiativeEngine:
    def __init__(self, minimum_idle_seconds=45 * 60, cooldown_seconds=4 * 3600):
        self.minimum_idle_seconds = int(minimum_idle_seconds)
        self.cooldown_seconds = int(cooldown_seconds)
        self.last_initiative = 0.0

    def evaluate(self, now=None, last_interaction=0, busy=False, enabled=False,
                 app_active=True, quiet_hours=False, has_relevant_memory=False):
        now = time.time() if now is None else float(now)
        idle = max(0.0, now - float(last_interaction or now))
        if not enabled or not app_active or quiet_hours or busy:
            return {"eligible": False, "reason": "policy_blocked", "idle_seconds": idle}
        if idle < self.minimum_idle_seconds:
            return {"eligible": False, "reason": "not_idle_long_enough", "idle_seconds": idle}
        if now - self.last_initiative < self.cooldown_seconds:
            return {"eligible": False, "reason": "cooldown", "idle_seconds": idle}
        if not has_relevant_memory:
            return {"eligible": False, "reason": "nothing_relevant_to_recall", "idle_seconds": idle}
        return {"eligible": True, "reason": "relevant_memory_after_idle", "idle_seconds": idle}

    def mark_sent(self, now=None):
        self.last_initiative = time.time() if now is None else float(now)
