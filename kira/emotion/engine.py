"""Emotion engine: turns emotion requests into one smooth, stable avatar frame.

Pure Python (no Qt), driven by explicit timestamps, so it is independent of the avatar technology.

Rules (all numbers live in emotion_library/rules.json):
* Priority      - each emotion has a priority. A new *automatic* (model-detected) emotion may replace
                  the current one only after ``min_hold_s`` or if its priority is at least
                  ``preempt_priority_margin`` higher; otherwise it waits in a single "pending" slot
                  (newest wins, dropped after ``pending_ttl_s``). A switch budget lengthens the hold
                  when emotions flip too often.
* Intensity     - 0..100. Scales how far the face / pose moves from neutral, and fades out during the
                  last ``transition.out`` seconds of an emotion's life.
* Conflicts     - pairs in combinations.json (e.g. happy+sad) cannot be shown together: the stronger
                  one (intensity weighted by priority) wins.
* Combinations  - at most ``max_blend`` emotions are blended. Named pairs can define weights or be
                  replaced by another emotion (angry+affectionate -> tsundere).
* Transitions   - everything is low-pass filtered with the dominant emotion's ``transition.in/out``.
* Idle          - when nothing is active the frame relaxes to neutral and reports ``active=False`` so
                  the host can hand control back to its own idle behaviour.
"""
import math

FACE_KEYS = ("lid", "raise", "open", "blush", "smile")
CHANNELS = ("ang", "tx", "ty", "sc")
NEVER = float("-inf")


class Entry:
    __slots__ = ("emo", "intensity", "started", "expires", "source", "group", "tag")

    def __init__(self, emo, intensity, started, expires, source, group, tag=None):
        self.emo, self.intensity, self.started, self.expires = emo, intensity, started, expires
        self.source, self.group, self.tag = source, group, tag


class Frame:
    """Result of one engine tick."""
    __slots__ = ("face", "pose", "base_mood", "active", "dominant", "members", "speaking")

    def __init__(self):
        self.face, self.pose = {}, {}
        self.base_mood = "neutral"
        self.active, self.dominant, self.members, self.speaking = False, "neutral", [], False


class EmotionEngine:
    def __init__(self, library):
        self.lib = library
        self.rules = library.rules
        self.entries = []
        self.pending = None
        self.serial = 0            # increments on every accepted request (lets a backend notice new activity)
        self._group = 0
        self.last_response_switch = NEVER
        self._switches = []
        self.speaking = False
        self._speak_gain = 0.0
        self._neutral = dict(library.reaction_for(library.get("neutral"))["face"])
        self.face = dict(self._neutral)
        self._pose = {}            # (part, channel) -> smoothed static offset
        self._osc = {}             # (part, channel, freq, phase) -> smoothed amplitude
        self._strength = 0.0
        self._pulses = []          # (name, start)
        self._last_tick = None
        self.dominant = "neutral"
        self.base_mood = "neutral"
        self._members = []

    # ------------------------------------------------------------------ requests
    def request(self, ids, intensity=None, duration="default", source="response", now=0.0, tag=None):
        """Ask for one emotion (or a combination). Returns 'applied', 'queued' or 'ignored'.

        source: 'response' (model-detected, stability rules apply), 'event' (application event) or
        'direct' (explicit command from the UI/code: applied immediately). duration: seconds, None for
        'until replaced', or 'default' for the emotion's own duration.
        """
        emos = [self.lib.get(i) for i in ids]
        emos = [e for e in emos if e is not None]
        if not emos:
            return "ignored"
        emos = emos[: max(1, int(self.rules["max_blend"]))]
        self.serial += 1
        if all(e.id == "neutral" for e in emos):
            self.release(sources=("response", "direct", "event"), now=now)
            self.pending = None
            return "applied"
        self._expire(now)
        top_prio = max(e.priority for e in emos)
        if source == "response":
            current = self._dominant_entry(now)
            same = current is not None and {e.id for e in emos} <= {x.emo.id for x in self.entries}
            if same:                                              # same feeling again: refresh, do not restart
                mix = float(self.rules["same_emotion_refresh_mix"])
                for en in self.entries:
                    if en.emo.id in {e.id for e in emos}:
                        base = en.emo.default_intensity if intensity is None else intensity
                        en.intensity = int(round((1 - mix) * en.intensity + mix * base))
                        en.expires = self._expiry(en.emo, duration, now)
                return "applied"
            if current is not None and self._blocked(top_prio, current, now):
                self.pending = dict(ids=[e.id for e in emos], intensity=intensity, duration=duration,
                                    queued=now, tag=tag)
                return "queued"
        self._apply(emos, intensity, duration, source, now, tag)
        return "applied"

    def _apply(self, emos, intensity, duration, source, now, tag):
        self._group += 1
        top_prio = max(e.priority for e in emos)
        if source == "direct":                       # explicit command: replaces everything
            self.entries = []
        elif source == "response":                   # a new reply replaces earlier replies; stronger event feelings stay
            self.entries = [en for en in self.entries if en.source == "event" and en.emo.priority > top_prio]
        else:                                        # events only replace their own earlier entry
            self.entries = [en for en in self.entries if tag is None or en.tag != tag]
        for e in emos:
            level = e.default_intensity if intensity is None else int(max(0, min(100, intensity)))
            self.entries.append(Entry(e, level, now, self._expiry(e, duration, now), source, self._group, tag))
        if source == "response":
            self.last_response_switch = now
            self._switches.append(now)
        self.pending = None

    def _expiry(self, emo, duration, now):
        if duration == "default":
            duration = emo.duration if emo.duration is not None else float(self.rules["default_duration_s"])
        return None if duration is None else now + float(duration)

    def _hold(self, now):
        budget = self.rules["switch_budget"]
        window = float(budget["window_s"])
        self._switches = [t for t in self._switches if now - t <= window]
        hold = float(self.rules["min_hold_s"])
        return hold * 2 if len(self._switches) >= int(budget["max_switches"]) else hold

    def _blocked(self, new_priority, current, now):
        if new_priority >= current.emo.priority + int(self.rules["preempt_priority_margin"]):
            return False
        if current.source != "response":          # only automatic emotions are protected by the hold
            return False
        return now - self.last_response_switch < self._hold(now)

    def release(self, sources=None, tags=None, now=0.0):
        """Remove entries by source and/or tag (None matches everything)."""
        self.entries = [e for e in self.entries
                        if not ((sources is None or e.source in sources) and (tags is None or e.tag in tags))]

    def interrupt(self, now):
        """User cut Kira off: drop automatic emotions, pending reaction and speaking at once."""
        self.release(sources=("response", "event"), now=now)
        self.pending = None
        self.set_speaking(False, hard=True)

    def set_speaking(self, on, hard=False):
        self.speaking = bool(on)
        if not on and hard:
            self._speak_gain = 0.0

    def pulse(self, name, now):
        if name in self.lib.pulses:
            self._pulses = [p for p in self._pulses if now - p[1] < 3.0][-6:] + [(name, now)]

    # ------------------------------------------------------------------ helpers
    def _expire(self, now):
        self.entries = [e for e in self.entries if e.expires is None or now < e.expires]

    def _live(self, now):
        out = []
        floor = float(self.rules["min_visible_intensity"])
        for en in self.entries:
            eff = float(en.intensity)
            if en.expires is not None:
                left = en.expires - now
                if left <= 0:
                    continue
                if left < en.emo.t_out:
                    eff *= left / en.emo.t_out
            if eff >= floor:
                out.append((en, eff))
        return out

    def _dominant_entry(self, now):
        live = self._live(now)
        if not live:
            return None
        return max(live, key=lambda x: x[1] * (1 + x[0].emo.priority / 100.0))[0]

    def resolve(self, now):
        """Final [(emotion, effective_intensity, weight)] after replacement, conflicts and blend limit."""
        live = [(en.emo, eff) for en, eff in self._live(now)]
        merged = {}
        for emo, eff in live:                                         # same emotion from several entries
            merged[emo.id] = (emo, max(eff, merged.get(emo.id, (emo, 0))[1]))
        items = list(merged.values())
        ids = [e.id for e, _ in items]
        for i, a in enumerate(ids):                                   # replacement combinations
            for b in ids[i + 1:]:
                combo = self.lib.combination(a, b)
                if combo and combo.get("mode") == "replace" and self.lib.get(combo.get("result")):
                    level = max(merged[a][1], merged[b][1])
                    res = self.lib.get(combo["result"])
                    items = [x for x in items if x[0].id not in (a, b)] + [(res, level)]
                    ids = [e.id for e, _ in items]
                    break
            else:
                continue
            break
        score = lambda x: x[1] * (1 + x[0].priority / 100.0)
        items.sort(key=score, reverse=True)
        chosen = []
        for emo, eff in items:
            if emo.id == "neutral":
                continue
            if any(self.lib.in_conflict(emo.id, c[0].id) for c in chosen):
                continue
            if len(chosen) < int(self.rules["max_blend"]):
                chosen.append((emo, eff))
        if not chosen:
            return []
        weights = None
        if len(chosen) == 2:
            combo = self.lib.combination(chosen[0][0].id, chosen[1][0].id)
            if combo and combo.get("mode", "blend") == "blend" and combo.get("weights"):
                by_id = dict(zip(combo["members"], combo["weights"]))
                weights = [float(by_id.get(c[0].id, 0.5)) for c in chosen]
        if weights is None:
            weights = [score(c) for c in chosen]
        total = sum(weights) or 1.0
        return [(emo, eff, w / total) for (emo, eff), w in zip(chosen, weights)]

    # ------------------------------------------------------------------ per-frame output
    def tick(self, now):
        dt = 0.033 if self._last_tick is None else max(0.0, min(0.25, now - self._last_tick))
        self._last_tick = now
        speaking_hold = self.speaking and self.rules.get("hold_while_speaking", True)
        if speaking_hold:
            for en in self.entries:                       # do not let a reply's emotion end mid-sentence
                if en.source == "response" and en.expires is not None:
                    en.expires += dt
        self._expire(now)
        if self.pending is not None:
            p = self.pending
            if now - p["queued"] > float(self.rules["pending_ttl_s"]):
                self.pending = None
            elif now - self.last_response_switch >= self._hold(now):
                self.pending = None
                self.request(p["ids"], p["intensity"], p["duration"], "response", now, p.get("tag"))
        members = self.resolve(now)
        face_t = dict(self._neutral)
        pose_t, osc_t = {}, {}
        strength, base = 0.0, "neutral"
        dominant = "neutral"
        tau_in, tau_out = 0.4, 0.8
        if members:
            strength = max(eff for _, eff, _ in members) / 100.0
            dominant = max(members, key=lambda m: m[2])[0].id
            tau_in = self.lib.get(dominant).t_in
            tau_out = self.lib.get(dominant).t_out
            for emo, eff, w in members:
                reaction = self.lib.reaction_for(emo)
                amount = w * strength
                for k in FACE_KEYS:
                    face_t[k] += (float(reaction["face"].get(k, self._neutral[k])) - self._neutral[k]) * amount
                g = self.lib.gesture(reaction.get("gesture"))
                for p in g.get("pose", []):
                    key = (p["part"], p["channel"])
                    pose_t[key] = pose_t.get(key, 0.0) + float(p["value"]) * amount
                for o in g.get("motion", []):
                    key = (o["part"], o["channel"], float(o["freq"]), float(o.get("phase", 0.0)))
                    osc_t[key] = osc_t.get(key, 0.0) + float(o["amp"]) * amount
                if emo.id == dominant:
                    base = reaction.get("base_mood", "neutral")
                    onset = g.get("onset")
                    if onset and dominant != self.dominant:
                        self.pulse(onset, now)
        if dominant != self.dominant:
            self.dominant = dominant
        self.base_mood = base
        self._members = members
        tau = tau_in if strength >= self._strength - 1e-3 else tau_out
        a = 1 - math.exp(-dt / max(0.03, tau))
        self._strength += (strength - self._strength) * a
        for k in FACE_KEYS:
            self.face[k] += (face_t[k] - self.face[k]) * a
        for key in set(self._pose) | set(pose_t):
            cur = self._pose.get(key, 0.0)
            self._pose[key] = cur + (pose_t.get(key, 0.0) - cur) * a
        for key in set(self._osc) | set(osc_t):
            cur = self._osc.get(key, 0.0)
            new = cur + (osc_t.get(key, 0.0) - cur) * a
            if abs(new) < 1e-3 and key not in osc_t:
                self._osc.pop(key, None)
            else:
                self._osc[key] = new
        # speaking: fades in quickly, stops at once (set_speaking(False, hard=True) zeroes the gain)
        if self.speaking:
            fade = max(0.02, float(self.rules.get("speaking_fade_in_s", 0.15)))
            self._speak_gain = min(1.0, self._speak_gain + dt / fade)
        else:
            self._speak_gain = max(0.0, self._speak_gain - dt / 0.12)
        return self._frame(now, bool(members) or self._strength > 0.02 or self._speak_gain > 0.0 or bool(self._live_pulses(now)))

    def _live_pulses(self, now):
        return [(n, s) for n, s in self._pulses if now - s < float(self.lib.pulses.get(n, {}).get("dur", 0.5))]

    def _frame(self, now, active):
        f = Frame()
        f.face = dict(self.face)
        pose = {}

        def add(part, ch, v):
            pose[(part, ch)] = pose.get((part, ch), 0.0) + v
        for (part, ch), v in self._pose.items():
            add(part, ch, v)
        for (part, ch, freq, phase), amp in self._osc.items():
            add(part, ch, amp * math.sin(2 * math.pi * freq * now + phase))
        if self._speak_gain > 0:
            for o in self.lib.gesture("speaking").get("motion", []):
                add(o["part"], o["channel"],
                    float(o["amp"]) * self._speak_gain * math.sin(2 * math.pi * float(o["freq"]) * now + float(o.get("phase", 0.0))))
        for name, start in self._live_pulses(now):
            spec = self.lib.pulses[name]
            u = (now - start) / float(spec.get("dur", 0.5))
            env = math.sin(math.pi * max(0.0, min(1.0, u)))
            for k in spec.get("kicks", []):
                add(k["part"], k["channel"], float(k["amp"]) * env)
        f.pose = pose
        f.base_mood, f.active = self.base_mood, active
        f.dominant, f.members, f.speaking = self.dominant, [(m[0].id, round(m[1]), round(m[2], 2)) for m in self._members], self.speaking
        return f

    def current_base_mood(self, now):
        members = self.resolve(now)
        if not members:
            return "neutral"
        top = max(members, key=lambda m: m[2])[0]
        return self.lib.reaction_for(top).get("base_mood", "neutral")

    def seed_face(self, face):
        for k in FACE_KEYS:
            if k in face:
                self.face[k] = float(face[k])
