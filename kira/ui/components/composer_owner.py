"""Explicit callback facade handed to ChatComposer.

MainWindow is an empty Qt host, so the composer cannot call feature methods on
it. This adapter exposes only the declared callbacks and routes each one to the
controller that owns it.
"""
from __future__ import annotations

_CALLBACK_OWNERS = {
    "add_attachment_paths": "attachments_vision",
    "add_pasted_image": "attachments_vision",
    "cancel_attachments": "attachments_vision",
    "capture_screen_attachment": "attachments_vision",
    "make_tile_strip": "attachments_vision",
    "pick_attachments": "attachments_vision",
    "set_game_mode": "attachments_vision",
    "set_game_mode_profile": "attachments_vision",
    "set_vision_mode": "attachments_vision",
    "build_badge_menu": "runtime",
    "on_stop_clicked": "runtime",
    "set_voice_enabled": "runtime",
    "toggle_mic": "runtime",
    "toggle_wake": "runtime",
    "icon_button": "session",
    "on_input_changed": "session",
    "reg": "session",
    "send_message": "chat",
    "stop_generation": "chat",
    "toggle_image_search": "chat",
    "toggle_web_search": "chat",
    "update_image_search_tip": "chat",
    "update_web_tip": "chat",
}


class ComposerOwner:
    def __init__(self, context, widget_parent, *, view_context=None) -> None:
        # Callbacks stay bound to the feature controller's restricted context.
        # Legacy window-view aliases are composition-owned, so they must be
        # published through the root presentation context rather than the
        # chat controller's narrower view capability set.
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_view_context", view_context or context)
        object.__setattr__(self, "_widget_parent", widget_parent)

    @property
    def widget(self):
        return self._widget_parent

    @property
    def code_chat_host(self):
        from .code_chat_host import CodeChatHost
        return CodeChatHost(self._context, self._widget_parent)

    @property
    def settings(self):
        return self._context.services.settings

    @property
    def _vision_gate(self):
        return self._context.services.vision_application_service

    def __getattr__(self, name: str):
        feature = _CALLBACK_OWNERS.get(name)
        if feature is None:
            raise AttributeError(f"ChatComposer owner has no callback {name!r}")
        return getattr(self._context.require_peer(feature), name)

    def __setattr__(self, name: str, value) -> None:
        views = self._view_context.views
        if name not in views._allowed:
            raise AttributeError(
                f"ChatComposer owner cannot expose undeclared window view {name!r}"
            )
        setattr(views, name, value)
