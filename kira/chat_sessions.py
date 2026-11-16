"""One independent chat session per character (Qt-free helpers so they can be tested without a GUI).

Every character (Kira / Ren / Mika / custom) has its own ChatSession: its own saved history, chat view, model router,
generation worker, pending-message queue and stream state. Several sessions can therefore generate at the same time.

MainWindow keeps its familiar attribute names (busy, worker, _stream_text, ...): they are properties that read/write the
session that is *current* while an event is handled (see MainWindow._as). Things that exist once per computer - the
voice, the face animation, the companion bubble, the status line - belong to the visible (front) session only; while a
background session handles an event they are replaced by `NOOP` / `Muted` so a background reply never speaks, moves the
face or overwrites the status of the character you are looking at.
"""
from __future__ import annotations

# name -> default factory. Everything a single request / conversation needs lives here.
SESSION_FIELDS = {
    "busy": lambda: False,
    "worker": lambda: None,
    "_stream_text": lambda: "",
    "_stream_pos": lambda: None,
    "_stream_dirty": lambda: False,
    "_stream_mood": lambda: None,
    "_partial_saved": lambda: False,
    "_emotion_applied": lambda: False,
    "_body_done": lambda: [],             # body command names already performed for the message being answered (no repeats)
    "_t_req": lambda: None,
    "_t_first": lambda: None,
    "_speech_live": lambda: False,
    "_turn_extra": lambda: None,
    "_turn_attach_kinds": lambda: [],
    "_turn_voice": lambda: False,
    "_turn_mode": lambda: None,
    "_tool_plan": lambda: None,
    "_brain": lambda: None,
    "_brain_user_text": lambda: "",
    "_brain_mode_name": lambda: None,
    "_plain_retry": lambda: False,
    "_web_found": lambda: None,
    "_image_search_turn": lambda: False,
    "_search_token": lambda: 0,
    "_search_worker": lambda: None,
    "_search_base": lambda: None,
    "_route_info": lambda: None,
    "_badge_phase": lambda: "idle",
    "application_request_id": lambda: None,
}


class ChatSession:
    def __init__(self, character_id: str):
        self.cid = str(character_id)
        for name, factory in SESSION_FIELDS.items():
            setattr(self, name, factory())
        self.view = None            # QTextBrowser of this chat
        self.timer = None           # QTimer that paints the streamed text of this chat
        self.client = None          # HybridRouter of this chat (own cancel flag, so Stop stops only this character)
        self.relay = None           # SessionRelay: receives this chat's worker signals on the GUI thread
        self.badge = ("idle", None)  # last route-indicator state (shown when this chat is in front)
        self.theme = None
        self.draft = ""             # text typed but not sent yet
        self.unread = False         # a reply arrived while another tab was in front
        self.loaded = False         # history shown in the view

    def __repr__(self):
        return f"<ChatSession {self.cid} busy={self.busy}>"


class _Noop:
    """Swallows any call / attribute chain and is falsy: stands in for a widget or service of the front chat."""
    def __call__(self, *a, **k):
        return None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())


NOOP = _Noop()


class Muted:
    """Like NOOP, but a few pure (side-effect free) attributes of the real object still work (e.g. director.parse_reply)."""
    def __init__(self, real, pure=()):
        self._real = real
        self._pure = frozenset(pure)

    def __getattr__(self, name):
        if name in self._pure and self._real is not None:
            return getattr(self._real, name)
        return NOOP

    def __bool__(self):
        return False


def session_property(name):
    return property(lambda self: getattr(self.cur, name), lambda self, value: setattr(self.cur, name, value))


def front_only_property(name, pure=None):
    """Attribute that exists once (a widget / service). Reads give the real object while the front session handles
    an event, and a muted stand-in while a background session does."""
    key = "_real_" + name

    def get(self):
        real = self.__dict__.get(key)
        if real is None or self.cur is self.front:
            return real
        return Muted(real, pure) if pure else NOOP

    def set_(self, value):
        self.__dict__[key] = value

    return property(get, set_)
