"""Loads and validates the external emotion library (JSON only, versioned, no code execution)."""
import json
from pathlib import Path

SUPPORTED_SCHEMA = 1
FACE_KEYS = ("lid", "raise", "open", "blush", "smile")
NEUTRAL_FACE = {"lid": 0.0, "raise": 0.0, "open": 0.0, "blush": 0.0, "smile": 0.35}
BASE_MOODS = ("neutral", "happy", "excited", "sad", "bored", "angry", "shy", "surprised", "thinking")
DEFAULT_LIBRARY_DIR = Path(__file__).resolve().parent.parent.parent / "emotion_library"

DEFAULT_RULES = {
    "min_hold_s": 1.6, "preempt_priority_margin": 20,
    "switch_budget": {"window_s": 10.0, "max_switches": 4}, "pending_ttl_s": 4.0,
    "max_blend": 2, "same_emotion_refresh_mix": 0.6, "default_duration_s": 6.0,
    "min_visible_intensity": 6, "hold_while_speaking": True,
    "keyword_intensity": {"base": 30, "per_hit": 8, "max": 55, "min_hits": 1},
    "speaking_fade_in_s": 0.15,
}
# Legacy mood names used elsewhere in the application (face.EXPRESSIONS / reactions.json).
LEGACY_ALIASES = {"excited": "excited", "bored": "bored", "thinking": "thinking", "shy": "shy",
                  "surprised": "surprised", "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry"}


class Emotion:
    __slots__ = ("id", "name", "category", "aliases", "meaning", "default_intensity", "priority", "duration",
                 "reaction", "animation", "t_in", "t_out", "fallback", "keywords", "_raw")

    def __init__(self, d):
        self._raw = d
        self.id = str(d["id"]).strip().lower()
        self.name = str(d.get("name") or self.id)
        self.category = str(d.get("category") or "other")
        self.aliases = [str(a).strip().lower() for a in d.get("aliases", [])]
        self.meaning = str(d.get("meaning") or "")
        self.default_intensity = max(0, min(100, int(d.get("default_intensity", 50))))
        self.priority = int(d.get("priority", 20))
        dur = d.get("duration")
        self.duration = None if dur is None else max(0.2, float(dur))
        self.reaction = str(d.get("reaction") or "neutral")
        self.animation = dict(d.get("animation") or {})
        tr = d.get("transition") or {}
        self.t_in = max(0.03, float(tr.get("in", 0.35)))
        self.t_out = max(0.05, float(tr.get("out", 0.8)))
        self.fallback = str(d.get("fallback") or "neutral").lower()
        kw = d.get("keywords") or {}
        self.keywords = [str(k).lower() for lang in kw.values() for k in lang if str(k).strip()]


class Library:
    def __init__(self):
        self.version = "builtin"
        self.warnings = []
        self.emotions = {}
        self.reactions = {}
        self.gestures = {}
        self.pulses = {}
        self.combinations = {}          # frozenset(member ids) -> combination dict
        self.conflicts = set()          # frozenset({a, b})
        self.events = {}
        self.rules = dict(DEFAULT_RULES)
        self.profile = {"technology": "png_softbody", "capabilities": {}}
        self._names = {}

    # ---------- lookup ----------
    def resolve_name(self, text):
        """Emotion id for an id / alias / display name (case-insensitive), else None."""
        key = str(text or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not key:
            return None
        if key in self.emotions:
            return key
        return self._names.get(key) or self._names.get(key.replace("_", " "))

    def get(self, emotion_id):
        return self.emotions.get(emotion_id)

    def capability(self, name):
        return bool((self.profile.get("capabilities") or {}).get(name))

    def reaction_for(self, emotion):
        """Reaction dict for an emotion, following capability gating and fallbacks. Never fails."""
        seen = set()
        e = emotion
        while e is not None and e.id not in seen:
            seen.add(e.id)
            r = self._usable_reaction(e.reaction)
            if r is not None:
                return r
            e = self.emotions.get(e.fallback)
        return self.reactions.get("neutral") or {"face": dict(NEUTRAL_FACE), "gesture": "idle", "base_mood": "neutral"}

    def _usable_reaction(self, reaction_id):
        seen = set()
        while reaction_id and reaction_id not in seen:
            seen.add(reaction_id)
            r = self.reactions.get(reaction_id)
            if r is None:
                return None
            if all(self.capability(c) for c in r.get("requires", [])):
                return r
            reaction_id = r.get("fallback")
        return None

    def gesture(self, name):
        return self.gestures.get(name) or {}

    def combination(self, a, b):
        return self.combinations.get(frozenset((a, b)))

    def in_conflict(self, a, b):
        return frozenset((a, b)) in self.conflicts

    # ---------- loading ----------
    @classmethod
    def load(cls, directory=None):
        lib = cls()
        base = Path(directory or DEFAULT_LIBRARY_DIR)
        manifest = lib._read(base / "manifest.json", "manifest")
        if not manifest:
            lib.warnings.append(f"کتابخانه‌ی احساسات پیدا یا خوانده نشد ({base}); فقط حالت خنثی فعال است.")
            lib._finish()
            return lib
        lib.version = str(manifest.get("library_version", "?"))
        files = manifest.get("files") or {}
        lib._add_emotions(lib._read(base / files.get("emotions", "emotions.json"), "emotions"), "emotions.json")
        lib._add_reactions(lib._read(base / files.get("reactions", "reactions.json"), "reactions"), "reactions.json")
        lib._add_combinations(lib._read(base / files.get("combinations", "combinations.json"), "combinations"))
        lib._add_events(lib._read(base / files.get("events", "events.json"), "events"))
        rules = lib._read(base / files.get("rules", "rules.json"), "rules")
        if rules and isinstance(rules.get("rules"), dict):
            lib.rules = _merge(lib.rules, rules["rules"])
        anims = files.get("animation") or ["animation/png_softbody.json"]
        for rel in ([anims] if isinstance(anims, str) else anims):
            pack = lib._read(base / rel, "animation_pack")
            if pack and pack.get("technology", "png_softbody") == "png_softbody":
                lib.gestures.update(pack.get("gestures") or {})
                lib.pulses.update(pack.get("pulses") or {})
        profile = lib._read(base / files.get("avatar", "avatar/profile.json"), "avatar_profile")
        if profile:
            lib.profile = profile
        packs = base / manifest.get("packs_dir", "packs")
        if packs.is_dir():
            for path in sorted(packs.glob("*.json")):
                lib._load_pack(path)
        lib._finish()
        return lib

    def _read(self, path, kind):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.warnings.append(f"فایل {Path(path).name} پیدا نشد.")
            return None
        except Exception as exc:
            self.warnings.append(f"فایل {Path(path).name} قابل خواندن نبود ({exc}).")
            return None
        if not isinstance(data, dict):
            self.warnings.append(f"ساختار {Path(path).name} معتبر نیست.")
            return None
        if data.get("schema_version", SUPPORTED_SCHEMA) != SUPPORTED_SCHEMA:
            self.warnings.append(f"{Path(path).name}: نسخه‌ی schema پشتیبانی نمی‌شود ({data.get('schema_version')}).")
            return None
        if data.get("kind", kind) != kind and kind not in ("manifest",):
            self.warnings.append(f"{Path(path).name}: نوع فایل «{data.get('kind')}» است نه «{kind}».")
            return None
        return data

    def _add_emotions(self, data, source, allow_override=False):
        for raw in (data or {}).get("emotions", []):
            try:
                emo = Emotion(raw)
            except Exception as exc:
                self.warnings.append(f"{source}: یک احساس نامعتبر نادیده گرفته شد ({exc}).")
                continue
            if emo.id in self.emotions and not (allow_override and raw.get("override")):
                self.warnings.append(f"{source}: شناسه‌ی تکراری «{emo.id}» نادیده گرفته شد.")
                continue
            self.emotions[emo.id] = emo

    def _add_reactions(self, data, source, allow_override=False):
        for rid, r in ((data or {}).get("reactions") or {}).items():
            if not isinstance(r, dict) or not isinstance(r.get("face", {}), dict):
                self.warnings.append(f"{source}: واکنش «{rid}» نامعتبر است.")
                continue
            if rid in self.reactions and not (allow_override and r.get("override")):
                self.warnings.append(f"{source}: واکنش تکراری «{rid}» نادیده گرفته شد.")
                continue
            face = dict(NEUTRAL_FACE)
            for k in FACE_KEYS:
                if k in r.get("face", {}):
                    try:
                        face[k] = float(r["face"][k])
                    except (TypeError, ValueError):
                        pass
            self.reactions[rid] = {**r, "face": face, "gesture": r.get("gesture", "idle"),
                                   "base_mood": r.get("base_mood") if r.get("base_mood") in BASE_MOODS else "neutral"}

    def _add_combinations(self, data):
        for pair in (data or {}).get("conflicts", []):
            if isinstance(pair, list) and len(pair) == 2:
                self.conflicts.add(frozenset(str(p).lower() for p in pair))
        for combo in (data or {}).get("combinations", []):
            members = [str(m).lower() for m in combo.get("members", [])]
            if len(members) == 2:
                self.combinations[frozenset(members)] = {**combo, "members": members}

    def _add_events(self, data):
        for name, ev in ((data or {}).get("events") or {}).items():
            if isinstance(ev, dict):
                self.events[name] = ev

    def _load_pack(self, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self.warnings.append(f"پک {path.name} خوانده نشد ({exc}).")
            return
        if not isinstance(data, dict) or data.get("schema_version", SUPPORTED_SCHEMA) != SUPPORTED_SCHEMA:
            self.warnings.append(f"پک {path.name} نسخه یا ساختار پشتیبانی‌شده ندارد.")
            return
        self._add_emotions(data, path.name, True)
        self._add_reactions(data, path.name, True)
        self._add_combinations(data)
        self._add_events(data)
        pack = data.get("animation") or {}
        self.gestures.update(pack.get("gestures") or {})
        self.pulses.update(pack.get("pulses") or {})

    def _finish(self):
        if "neutral" not in self.emotions:
            self.emotions["neutral"] = Emotion({"id": "neutral", "name": "Neutral", "category": "basic",
                                                "default_intensity": 0, "priority": 0, "reaction": "neutral"})
        if "neutral" not in self.reactions:
            self.reactions["neutral"] = {"face": dict(NEUTRAL_FACE), "gesture": "idle", "base_mood": "neutral"}
        self._names = {}
        for emo in self.emotions.values():
            for n in [emo.name.lower().replace(" ", "_")] + emo.aliases:
                self._names.setdefault(n.replace(" ", "_"), emo.id)
        for emo in self.emotions.values():
            if self._usable_reaction(emo.reaction) is None:
                self.warnings.append(f"احساس «{emo.id}»: واکنش «{emo.reaction}» پیدا نشد؛ از fallback استفاده می‌شود.")
            for g in [self.reaction_for(emo).get("gesture")]:
                if g and g != "idle" and g not in self.gestures:
                    self.warnings.append(f"احساس «{emo.id}»: انیمیشن «{g}» در پک انیمیشن نیست؛ فقط حالت چهره اعمال می‌شود.")


def _merge(base, extra):
    out = dict(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
