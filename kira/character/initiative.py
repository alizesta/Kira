"""Bounded initiative policy for Kira.

This module does not send messages itself. It selects a recent user-shared milestone
and decides whether an opt-in check-in is appropriate.
"""
from __future__ import annotations

import time


class InitiativeEngine:
    CANDIDATE_KINDS = {"event", "promise"}

    def __init__(self, minimum_idle_seconds=45 * 60, cooldown_seconds=4 * 3600,
                 memory_max_age_seconds=10 * 86400):
        self.minimum_idle_seconds = int(minimum_idle_seconds)
        self.cooldown_seconds = int(cooldown_seconds)
        self.memory_max_age_seconds = int(memory_max_age_seconds)
        self.last_initiative = 0.0

    def select_candidate(self, items, now=None, exclude_id=None):
        """Choose a recent remembered event/promise; jokes and static facts never trigger an unsolicited message."""
        now = time.time() if now is None else float(now)
        candidates = []
        for item in items or []:
            if not isinstance(item, dict) or item.get("group") != "moment":
                continue
            if item.get("kind") not in self.CANDIDATE_KINDS:
                continue
            if exclude_id and str(item.get("id") or "") == str(exclude_id):
                continue
            try:
                stamp = float(item.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            age = max(0.0, now - stamp)
            text = str(item.get("text") or "").strip()
            if not text or age > self.memory_max_age_seconds:
                continue
            candidates.append((stamp, item))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return dict(candidates[0][1])

    def evaluate(self, now=None, last_interaction=0, busy=False, enabled=False,
                 app_active=True, quiet_hours=False, has_relevant_memory=False):
        now = time.time() if now is None else float(now)
        idle = max(0.0, now - float(last_interaction or now))
        if not enabled or not app_active or quiet_hours or busy:
            return {"eligible": False, "reason": "policy_blocked", "idle_seconds": idle}
        if idle < self.minimum_idle_seconds:
            return {"eligible": False, "reason": "not_idle_long_enough", "idle_seconds": idle}
        if self.last_initiative > 0 and now - self.last_initiative < self.cooldown_seconds:
            return {"eligible": False, "reason": "cooldown", "idle_seconds": idle}
        if not has_relevant_memory:
            return {"eligible": False, "reason": "nothing_relevant_to_recall", "idle_seconds": idle}
        return {"eligible": True, "reason": "relevant_memory_after_idle", "idle_seconds": idle}

    def mark_sent(self, now=None):
        self.last_initiative = time.time() if now is None else float(now)
