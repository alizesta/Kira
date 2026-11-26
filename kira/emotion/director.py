"""Glue between the application and the emotion engine (pure Python, no Qt).

The application calls:
  event(name)          startup / user_message / response_started / response_finished / response_failed / response_cancelled /
                       tts_started / tts_stopped / user_interrupt   (mapping lives in events.json)
  parse_reply(raw)     -> ReplyMeta (visible text + emotion metadata)
  on_reply(meta)       trigger the detected emotion
  request_direct(name) legacy set_expression() calls (UI preview, click reactions, ...)
  format_hint()        output-format instructions for the system prompt (emotion tag format + ids)
The avatar backend calls tick() every frame.
"""
import time

from .engine import EmotionEngine
from .library import Library
from .parser import parse_reply as _parse_reply


class EmotionDirector:
    def __init__(self, library=None, clock=time.monotonic):
        self.library = library or Library.load()
        self.engine = EmotionEngine(self.library)
        self.clock = clock

    @classmethod
    def from_default(cls):
        try:
            return cls()
        except Exception as exc:                         # the library must never stop the app from starting
            lib = Library()
            lib._finish()
            lib.warnings.append(f"کتابخانه‌ی احساسات بارگذاری نشد ({exc}).")
            return cls(lib)

    def _now(self, now):
        return self.clock() if now is None else now

    # ---------- prompt hint (format only; Kira's character lives in kira/personality.py) ----------
    def format_hint(self):
        ids = [e.id for e in self.library.emotions.values() if e.id != "neutral"] + ["neutral"]
        return (" OUTPUT FORMAT (needed by the avatar animation, never shown to the user): begin every reply with one "
                "emotion tag alone on the first line, written [emotion:intensity], for example [smug:70]. "
                "intensity is 0-100 and says how strongly Kira feels it in this reply. "
                "Two emotions may be combined with + , for example [shy+affectionate:55]. "
                "Allowed emotions: " + ", ".join(ids) + ". "
                "Pick what Kira actually feels in this reply, not just the topic. "
                "Write the real reply on the following line; the tag alone is not a reply. "
                "Usually 2 to 5 sentences unless the user asks for short or long. "
                "No emoji or markdown in replies that will be spoken. "
                "OPTIONAL, only when the user's last message clearly shows one of these states, even through slang, sarcasm or indirect "
                "wording - down, stressed, hostile, frustrated, praise, flirt, thanks, excited, joke, apology, goodbye, jealous - add "
                "ONE extra line right after the emotion tag, written [user:state]. Omit it when unsure; never mention it.")

    # ---------- replies ----------
    def parse_reply(self, raw):
        return _parse_reply(raw, self.library)

    def on_reply(self, meta, now=None):
        """Apply the emotion tag for a reply; stream lifecycle events are owned by the caller."""
        now = self._now(now)
        if meta is not None and meta.emotions:
            return self.engine.request(meta.emotions, meta.intensity, "default", "response", now)
        return "ignored"

    # ---------- events ----------
    def event(self, name, now=None):
        now = self._now(now)
        ev = self.library.events.get(name)
        if not ev:
            return
        if name == "user_interrupt":
            self.engine.interrupt(now)
        if ev.get("release_events"):
            self.engine.release(sources=("event",), tags=tuple(ev["release_events"]), now=now)
        if ev.get("release_responses"):
            self.engine.release(sources=("response",), now=now)
            self.engine.pending = None
        if "listening" in ev:
            self.engine.set_listening(bool(ev["listening"]))
        if "speaking" in ev and name != "user_interrupt":
            self.engine.set_speaking(bool(ev["speaking"]), hard=not ev["speaking"])
        if ev.get("pulse"):
            self.engine.pulse(ev["pulse"], now)
        if ev.get("emotion"):
            eid = self.library.resolve_name(ev["emotion"])
            if eid:
                self.engine.request([eid], ev.get("intensity"), ev.get("duration", "default"), "event", now, tag=name)

    # ---------- legacy / direct requests ----------
    def request_direct(self, name, hold=None, now=None):
        """Handle FaceAnimator.set_expression(name, hold). False if the name is not a known emotion."""
        eid = self.library.resolve_name(name)
        if eid is None:
            return False
        now = self._now(now)
        if eid == "neutral":
            self.engine.release(sources=("direct", "response"), now=now)
            self.engine.pending = None
            return True
        self.engine.request([eid], None, hold, "direct", now)
        return True

    def release_direct(self, now=None):
        self.engine.release(sources=("direct", "response"), now=self._now(now))

    def set_speaking(self, on):
        self.engine.set_speaking(on, hard=not on)

    # ---------- per frame ----------
    def tick(self, now=None):
        return self.engine.tick(self._now(now))

    def base_mood(self, now=None):
        return self.engine.current_base_mood(self._now(now))
