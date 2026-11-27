"""Window-level appearance and character-art effects, independent of Settings pages."""
from __future__ import annotations

import logging

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QToolButton, QWidget

from .. import winfx
from ..config import ROOT, save_settings
from ..theme import build_style
from ..ui_icons import make_icon, set_glow_intensity
from ..settings_schema import DEFAULTS as SETTINGS_DEFAULTS


class AppearanceRuntime:
    """Apply persisted visual preferences without loading CharacterSettingsController."""

    def __init__(self, context) -> None:
        self.context = context
        self._neon_widget_effects = {}

    def _session(self):
        return self.context.controllers.require("session")

    def apply_character_voice_settings(self):
        """Apply an isolated voice-settings snapshot for the active character."""
        settings = self.context.services.settings
        character_id = self.context.services.character_service.active_id(settings)
        override = (settings.get("character_voice") or {}).get(character_id) or {}
        if getattr(self.context.adapters, "speaker", None) is not None:
            self.context.services.voice_application_service.apply_character_settings(
                settings, override
            )

    def apply_character_art(self):
        services = self.context.services
        profile = services.character_service.active(services.settings)
        animator = self.context.adapters.animator
        animator.set_character_art(services.character_service.avatar_file(profile, ROOT))
        animator.rig.intensity = (
            float(services.settings.get("motion_strength", animator.rig.intensity))
            * animator.motion_gain
        )
        animator.touch()

    def apply_appearance(self, save: bool = False):
        page = getattr(self.context.views, "appearance_page", None)
        previous = getattr(self.context.state, "_effect", "off")
        settings = self.context.services.settings
        stored = settings.get("appearance") or {}
        color = (
            (page.background_color if page is not None else "")
            or stored.get("background_color")
            or SETTINGS_DEFAULTS["appearance"]["background_color"]
        )
        appearance = {
            "background_color": color,
            "brightness": (
                page.appearance_brightness.value() if page is not None
                else int(stored.get("brightness", SETTINGS_DEFAULTS["appearance"]["brightness"]))
            ),
            "glow": (
                page.appearance_glow.value() if page is not None
                else int(stored.get("glow", SETTINGS_DEFAULTS["appearance"]["glow"]))
            ),
            "transparency": (
                page.appearance_transparency.value() if page is not None
                else int(stored.get("transparency", SETTINGS_DEFAULTS["appearance"]["transparency"]))
            ),
        }
        settings["appearance"] = appearance
        wanted = (
            page.window_effect.currentData() if page is not None
            else settings.get("window_effect", SETTINGS_DEFAULTS["window_effect"])
        ) or SETTINGS_DEFAULTS["window_effect"]
        current = winfx.active_effect(wanted)
        self.context.state._effect = current
        set_glow_intensity(appearance["glow"] / 100.0)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_style(current, appearance))
        if hasattr(self.context.views, "glow_effects"):
            self._session().apply_chat_theme()
        self._refresh_icon_glow()
        self._apply_neon_glow_effects(appearance)
        winfx.apply_effect(self.context.host.winId(), current)
        if page is not None:
            page.set_background_color(color)
        if (
            (previous == "off") != (current == "off")
            and previous != current
            and getattr(self.context.host, "isVisible", lambda: False)()
        ):
            self._session().add_chat(
                "system",
                "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.",
            )
        try:
            from .chat_shell import apply_chat_shell
            from .dashboard_chat import apply_dashboard_chat
            apply_chat_shell(self.context)                      # the three columns; once per chat page
            apply_dashboard_chat(self.context)                  # bubbles, composer pill, portrait; after the columns exist
        except Exception:                                       # noqa: BLE001 - a skin problem must never break the app
            logging.getLogger("kira.ui").exception("Chat shell could not be applied")
        if save:
            save_settings(settings)

    def _apply_neon_glow_effects(self, appearance=None):
        settings = self.context.services.settings
        appearance = appearance if isinstance(appearance, dict) else (settings.get("appearance") or {})
        intensity = max(0, min(100, int(appearance.get("glow", SETTINGS_DEFAULTS["appearance"]["glow"]))))
        character_id = self.context.services.character_service.active_id(settings)
        profiles = self.context.services.character_service.all_profiles(settings)
        palette = self._session().theme_for_character(
            character_id, profiles.get(character_id, {})
        )
        targets = []
        for name in (
            "menu_btn", "mic_btn", "wake_btn", "voice_btn", "stop_btn",
            "send_btn", "gen_stop_btn",
        ):
            widget = getattr(self.context.views, name, None)
            # QAction objects (for example wake_btn) are not QWidgets and cannot
            # own a QGraphicsEffect. Only visual widgets support this glow.
            if isinstance(widget, QWidget):
                targets.append((widget, palette["second"], 7 + intensity * 0.06, 5 + intensity * 0.14))
        save_button = getattr(self.context.views, "save_btn", None)
        if isinstance(save_button, QWidget):
            targets.append((save_button, palette["main"], 7 + intensity * 0.06, 5 + intensity * 0.12))
        for widget, colour, blur, alpha in targets:
            effect = self._neon_widget_effects.get(widget)
            if effect is None:
                effect = QGraphicsDropShadowEffect(widget)
                effect.setOffset(0, 0)
                widget.setGraphicsEffect(effect)
                self._neon_widget_effects[widget] = effect
            effect.setBlurRadius(blur)
            tint = QColor(colour)
            tint.setAlpha(round(alpha if widget.isEnabled() else alpha * 0.22))
            effect.setColor(tint)

    def _refresh_icon_glow(self):
        settings = self.context.services.settings
        character_id = self.context.services.character_service.active_id(settings)
        profiles = self.context.services.character_service.all_profiles(settings)
        palette = self._session().theme_for_character(
            character_id, profiles.get(character_id, {})
        )
        for button in self.context.host.findChildren(QToolButton):
            name = button.property("kiraIconName")
            if not name:
                continue
            button.setIcon(make_icon(
                name, normal=palette["second"], hover="#FFFFFF",
                checked=palette["main"], disabled="#52617B",
            ))
