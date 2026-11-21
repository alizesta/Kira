"""Explicit host facade for CodeChat.

CodeChat predates the controller split and talks to "the window". MainWindow is
now an empty Qt host, so this adapter exposes exactly the surface CodeChat uses
and routes each name to the state, view or controller that owns it today.
"""
from __future__ import annotations

_STATE = frozenset({"sessions", "cur", "front", "_closing"})
_VIEWS = frozenset({"status", "gen_stop_btn", "kode_activity"})
_SESSION = frozenset({"busy", "_voice_next"})
_CONTROLLERS = {
    "_as": "session",
    "accent": "session",
    "add_chat": "session",
    "set_status": "session",
    "save_message": "runtime",
    "finish_request": "runtime",
    "_send_next_pending": "runtime",
    "submit": "chat",
}


class CodeChatHost:
    def __init__(self, context, widget_parent) -> None:
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_widget_parent", widget_parent)

    @property
    def widget(self):
        return self._widget_parent

    @property
    def settings(self):
        return self._context.services.settings

    @property
    def tool_agent(self):
        # CodeChat must use the same command guard as the regular chat path.
        return self._context.services.tool_agent

    def __getattr__(self, name: str):
        ctx = self._context
        if name in _STATE:
            return getattr(ctx.state, name)
        if name in _VIEWS:
            return getattr(ctx.views, name)
        if name in _SESSION:
            return getattr(ctx.session, name)
        if name == "chat":
            return ctx.session.view
        feature = _CONTROLLERS.get(name)
        if feature is not None:
            return getattr(ctx.require_peer(feature), name)
        raise AttributeError(f"CodeChat host has no member {name!r}")

    def __setattr__(self, name: str, value) -> None:
        ctx = self._context
        if name in _STATE:
            setattr(ctx.state, name, value)
        elif name in _VIEWS:
            setattr(ctx.views, name, value)
        elif name in _SESSION:
            setattr(ctx.session, name, value)
        else:
            raise AttributeError(f"CodeChat host cannot set {name!r}")
