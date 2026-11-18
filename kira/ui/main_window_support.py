"""Shared UI adapters that are intentionally common to all MainWindow features.

Feature dependencies live in the corresponding `main_window_*_support` modules;
this module contains only cross-feature Qt signal adapters and tiny shared helpers.
"""
from __future__ import annotations

import json
from functools import wraps

from PySide6.QtCore import QObject, Signal, Slot

from ..config import ROOT


SOUNDS_DIR = ROOT / "assets" / "sounds"


def load_reactions():
    try:
        return json.loads((ROOT / "reactions.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def front_only(fn):
    """Skip shared-screen updates while a background character session is active."""

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        context = getattr(self, "context", None)
        if context is None:
            raise RuntimeError("front_only handlers require a WindowPresentationContext")
        if context.is_background_session:
            return None
        return fn(self, *args, **kwargs)

    return wrapper


class SessionRelay(QObject):
    """Marshal this session's worker/provider callbacks onto the GUI thread."""

    provider_event = Signal(object)

    _HANDLER_OWNERS = {
        "on_stream_chunk": "runtime",
        "on_stream_event": "runtime",
        "on_tool_event": "runtime",
        "on_stream_done": "runtime",
        "on_error": "runtime",
        "_stream_flush": "runtime",
        "on_web_done": "chat",
        "_on_game_vision_result": "attachments_vision",
        "_send_next_pending": "runtime",
    }

    def __init__(self, context, session):
        super().__init__(context.host)
        self.context, self.session = context, session
        self.provider_event.connect(self._handle_provider_event)

    @Slot(object)
    def _handle_provider_event(self, event):
        self.context.services.chat_application_service.handle_provider_event(event)

    def _run(self, name, *args):
        owner = self._HANDLER_OWNERS.get(name)
        if owner is None:
            raise LookupError(f"No feature owner is registered for SessionRelay handler {name!r}")
        session_controller = self.context.controllers.require("session")
        controller = self.context.controllers.require(owner)
        with session_controller._as(self.session):
            getattr(controller, name)(*args)

    @Slot(str)
    def chunk(self, piece):
        self._run("on_stream_chunk", piece)

    @Slot(dict)
    def stream_event(self, event):
        self._run("on_stream_event", event)

    @Slot(dict)
    def tool(self, event):
        self._run("on_tool_event", event)

    @Slot(dict)
    def done(self, result):
        self._run("on_stream_done", result)

    @Slot(str)
    def failed(self, error):
        self._run("on_error", error)

    @Slot()
    def tick(self):
        self._run("_stream_flush")

    @Slot(int, bool, object)
    def search_done(self, token, ok, result):
        self._run("on_web_done", token, ok, result)

    @Slot(bool, str, int)
    def game_vision_done(self, ok, result, latency_ms):
        self._run("_on_game_vision_result", ok, result, latency_ms)

    @Slot()
    def game_vision_finished(self):
        self._run("_send_next_pending")
