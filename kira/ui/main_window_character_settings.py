"""Character and appearance feature controller."""
from .main_window_character_settings_support import (
    APP_NAME,
    AppearancePage,
    BASE_TRAITS,
    CharactersPage,
    DATA_DIR,
    HelpPage,
    MOODS,
    McpRegistryPanel,
    PROJECT_URL,
    PreferencesPage,
    QApplication,
    QColor,
    QColorDialog,
    QGraphicsDropShadowEffect,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPixmap,
    QTabWidget,
    QTimer,
    QToolButton,
    Qt,
    RELEASES_URL,
    ROOT,
    VERSION,
    about,
    avatar_art,
    base64,
    build_style,
    json,
    make_icon,
    mood,
    re,
    save_settings,
    set_glow_intensity,
    time,
    websearch,
    winfx,
)


from .window_feature_controller import WindowFeatureController


class CharacterSettingsController(WindowFeatureController):
    def build_characters_tab(self):
        """Compose the independent Characters page and delegate actions to the host."""
        self.context.views.character_page = CharactersPage(
            self.context.services.settings,
            self.feature_controller("session").t,
            base_traits=BASE_TRAITS,
            moods=MOODS,
            parent=self.window,
        )
        page = self.context.views.character_page
        page.character_selected.connect(self.select_character)
        page.add_character_requested.connect(self.add_character)
        page.edit_character_requested.connect(self.edit_character)
        page.delete_character_requested.connect(self.delete_character)
        page.choose_theme_color_requested.connect(self.choose_character_theme_color)
        page.reset_theme_color_requested.connect(self.reset_character_theme_color)
        page.preview_requested.connect(
            lambda mood: self.context.adapters.animator.set_expression(mood, hold=8)
        )
        page.open_sounds_requested.connect(self.feature_controller("lifecycle").open_sounds)
        page.save_requested.connect(lambda: self.save_character_settings(silent=True))
        page.save_personality_requested.connect(self.save_personality_profile)
        self.context.views.tabs.addTab(page, "")
        self.refresh_character_choices()
        self.refresh_character_card()
        self.refresh_personality_controls()

    def build_personality_tab(self):
        """Compatibility entry point; personality controls are owned by CharactersPage."""
        return self.context.views.character_page.character_subtabs.widget(1)

    def refresh_character_controls(self):
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        initiative_settings = self.context.services.settings.get("character_initiative")
        initiative_enabled = (
            initiative_settings.get(cid, False) is True
            if isinstance(initiative_settings, dict) else False
        )
        initiative_checkbox = self.context.views.character_page.initiative_chk
        initiative_checkbox.blockSignals(True)
        initiative_checkbox.setChecked(initiative_enabled)
        initiative_checkbox.blockSignals(False)
        voice = (self.context.services.settings.get("character_voice") or {}).get(cid) or {}
        self.context.views.character_page.char_voice_rate.blockSignals(True)
        self.context.views.character_page.char_voice_rate.setValue(int(voice.get("voice_rate", self.context.services.settings.get("voice_rate", 0))))
        self.context.views.character_page.char_voice_rate.blockSignals(False)
        self.context.views.character_page.char_voice_volume.blockSignals(True)
        self.context.views.character_page.char_voice_volume.setValue(round(float(voice.get("voice_volume", self.context.services.settings.get("voice_volume", 0.9))) * 100))
        self.context.views.character_page.char_voice_volume.blockSignals(False)
        resources = (self.context.services.settings.get("character_resources") or {}).get(cid) or {}
        for widget, key in ((self.context.views.character_page.char_skills_edit, "skills"), (self.context.views.character_page.char_mcp_edit, "mcp"),
                            (self.context.views.character_page.char_connectors_edit, "connectors")):
            widget.blockSignals(True)
            value = resources.get(key) or []
            widget.setText(", ".join(value) if isinstance(value, (list, tuple)) else str(value))
            widget.blockSignals(False)
        notes = (self.context.services.settings.get("character_notes") or {}).get(cid) or ""
        if hasattr(self.context.views.character_page, "character_notes_edit"):
            self.context.views.character_page.character_notes_edit.blockSignals(True)
            self.context.views.character_page.character_notes_edit.setPlainText(str(notes))
            self.context.views.character_page.character_notes_edit.blockSignals(False)
        self.apply_character_voice_settings()

    def _flush_character_autosave(self):
        pending = False
        page = getattr(self.context.views, "character_page", None)
        for timer in (
            getattr(page, "save_timer", None),
            getattr(self, "_character_save_timer", None),
        ):
            if timer is not None and timer.isActive():
                timer.stop()
                pending = True
        if pending:
            self.save_character_settings(silent=True)

    def save_character_settings(self, silent=False):
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        initiative_settings = self.context.services.settings.get("character_initiative")
        if not isinstance(initiative_settings, dict):
            initiative_settings = {}
        initiative_settings[cid] = bool(self.context.views.character_page.initiative_chk.isChecked())
        self.context.services.settings["character_initiative"] = initiative_settings
        notes = (
            self.context.views.character_page.character_notes_edit.toPlainText().strip()
            if hasattr(self.context.views.character_page, "character_notes_edit") else None
        )
        self.context.services.character_service.save_preferences(
            self.context.services.settings,
            cid,
            voice={
                "voice_rate": self.context.views.character_page.char_voice_rate.value(),
                "voice_volume": self.context.views.character_page.char_voice_volume.value() / 100.0,
            },
            resources={
                "skills": self.context.views.character_page.char_skills_edit.text(),
                "mcp": self.context.views.character_page.char_mcp_edit.text(),
                "connectors": self.context.views.character_page.char_connectors_edit.text(),
            },
            notes=notes,
        )
        self.apply_character_voice_settings()
        self.feature_controller("runtime").save_now()

    def apply_character_voice_settings(self):
        """Give the speaker an isolated settings snapshot for the active character."""
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        override = (self.context.services.settings.get("character_voice") or {}).get(cid) or {}
        if getattr(self.context.adapters, "speaker", None) is not None:
            self.context.services.voice_application_service.apply_character_settings(self.context.services.settings, override)

    def refresh_personality_controls(self):
        if not getattr(getattr(self.context.views, "character_page", None), "personality_sliders", None):
            return
        self.refresh_character_controls()
        traits = self.feature_controller("session").character_traits(self.feature_controller("session").active_character().get("id", "kira")) or BASE_TRAITS
        for key, slider in self.context.views.character_page.personality_sliders.items():
            slider.blockSignals(True)
            slider.setValue(int(round(float(traits.get(key, BASE_TRAITS.get(key, 0.5))) * 100)))
            slider.blockSignals(False)

    def save_personality_profile(self, silent=False):
        profile = self.feature_controller("session").active_character()
        cid = profile.get("id", "kira")
        traits = {key: slider.value() / 100.0 for key, slider in self.context.views.character_page.personality_sliders.items()}
        try:
            notes = (
                self.context.views.character_page.character_notes_edit.toPlainText().strip()
                if hasattr(self.context.views.character_page, "character_notes_edit") else None
            )
            self.context.services.character_service.save_personality(
                self.context.services.settings, cid, traits=traits, notes=notes
            )
            self.context.services.mood_service.set_active_character(cid, traits)
            self.save_character_settings(silent=True)
            self.refresh_personality_controls()
            if not silent:
                self.feature_controller("runtime").save_now()
                self.feature_controller("session").add_chat("system", self.feature_controller("session").t("character_traits_saved", name=profile.get("name", cid)))
            return True
        except Exception as exc:                            # noqa: BLE001
            if not silent:
                QMessageBox.warning(self.window, self.feature_controller("session").t("character_error_title"), str(exc))
            return False

    def refresh_character_choices(self):
        current = self.context.services.character_service.active_id(self.context.services.settings)
        self.context.views.character_page.character_combo.blockSignals(True)
        self.context.views.character_page.character_combo.clear()
        profiles = self.context.services.character_service.all_profiles(self.context.services.settings)
        for cid in ("kira", "ren", "mika"):
            if cid in profiles:
                p = profiles[cid]
                self.context.views.character_page.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        for cid, p in profiles.items():
            if cid not in ("kira", "ren", "mika"):
                self.context.views.character_page.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        self.context.views.character_page.character_combo.setCurrentIndex(max(0, self.context.views.character_page.character_combo.findData(current)))
        self.context.views.character_page.character_combo.blockSignals(False)
        self.context.views.character_page.character_edit_btn.setEnabled(current != "kira")
        self.context.views.character_page.character_delete_btn.setEnabled(current != "kira")
        self._refresh_character_theme_preview()

    def _refresh_character_theme_preview(self):
        if not hasattr(self.context.views.character_page, "character_theme_color_preview"):
            return
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        colour = self.feature_controller("session").theme_for_character(cid)["main"]
        self.context.views.character_page.character_theme_color_preview.setText(colour)
        self.context.views.character_page.character_theme_color_preview.setStyleSheet(
            f"QLabel {{ background: {colour}; color: white; border: 1px solid rgba(255,255,255,0.5); "
            "border-radius: 7px; padding: 5px; }"
        )

    def choose_character_theme_color(self):
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        current = QColor(self.feature_controller("session").theme_for_character(cid)["main"])
        selected = QColorDialog.getColor(current, self, "رنگ تم شخصیت")
        if not selected.isValid():
            return
        self.context.services.settings.setdefault("character_theme_colors", {})[cid] = selected.name()
        for session in self.context.state.sessions.values():
            session.theme = self.feature_controller("session").theme_for_character(session.cid)
        self._refresh_character_theme_preview()
        self.feature_controller("session").apply_chat_theme()
        self.feature_controller("session").refresh_navigation_icons()
        self._refresh_icon_glow()
        self.feature_controller("runtime").save_now()

    def reset_character_theme_color(self):
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        self.context.services.settings.setdefault("character_theme_colors", {}).pop(cid, None)
        for session in self.context.state.sessions.values():
            session.theme = self.feature_controller("session").theme_for_character(session.cid)
        self._refresh_character_theme_preview()
        self.feature_controller("session").apply_chat_theme()
        self.feature_controller("session").refresh_navigation_icons()
        self._refresh_icon_glow()
        self.feature_controller("runtime").save_now()

    def refresh_character_card(self, character_id=None):
        profile = self.context.services.character_service.all_profiles(self.context.services.settings).get(character_id or self.context.services.character_service.active_id(self.context.services.settings), self.context.services.character_service.all_profiles(self.context.services.settings).get("kira", {}))
        image_name = str(profile.get("image") or "").strip()
        pixmap = QPixmap()
        if image_name:
            image_path = ROOT / image_name
            try:
                if image_path.suffix == ".b64":
                    image_bytes = base64.b64decode(image_path.read_text(encoding="ascii").strip(), validate=True)
                    pixmap.loadFromData(image_bytes)
                else:
                    pixmap.load(str(image_path))
            except (OSError, ValueError):
                pixmap = QPixmap()
        pixmap = self._fit_portrait(pixmap)
        self.context.views.character_page.character_portrait.setPixmap(pixmap)
        self.context.views.character_page.character_description.setText(profile.get("description", ""))

    def _fit_portrait(self, pixmap):
        """Fill the portrait frame without stretching: pictures whose proportions differ from the frame are
        cropped (centred, biased toward the face). A picture that already fits (Kira's SVG) is left untouched."""
        if pixmap.isNull():
            return pixmap
        size = self.context.views.character_page.character_portrait.size()
        if abs(pixmap.width() / pixmap.height() - size.width() / size.height()) < 0.03:
            return pixmap
        x, y, w, h = avatar_art.cover_crop(pixmap.width(), pixmap.height(), size.width(), size.height())
        crop = pixmap.copy(int(round(x)), int(round(y)), int(round(w)), int(round(h)))
        return crop.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def apply_character_art(self):
        """Chat page + floating companion show the active character: Kira's own animated PNG, or the character's
        full-body picture (a profile without one falls back to Kira's art). Called at start-up and on every change."""
        profile = self.context.services.character_service.active(self.context.services.settings)
        self.context.adapters.animator.set_character_art(self.context.services.character_service.avatar_file(profile, ROOT))
        self.context.adapters.animator.rig.intensity = float(self.context.services.settings.get("motion_strength", self.context.adapters.animator.rig.intensity)) * self.context.adapters.animator.motion_gain
        self.context.adapters.animator.touch()

    def select_character(self, index):
        character_id = self.context.views.character_page.character_combo.itemData(index)
        if not character_id:
            return
        if character_id != self.context.state.front.cid:
            self.feature_controller("session").switch_session(character_id)         # the character list in Settings and the tabs on the chat page are the same switch
            self.feature_controller("runtime").save_now()

    def add_character(self):
        name, ok = QInputDialog.getText(self.window, "شخصیت جدید", "نام:")
        if not ok or not name.strip():
            return
        description, ok = QInputDialog.getText(self.window, "شخصیت جدید", "توضیح کوتاه:")
        if not ok:
            return
        prompt, ok = QInputDialog.getMultiLineText(self.window, "شخصیت جدید", "دستور شخصیت و لحن:")
        if not ok:
            return
        profile = self.context.services.character_service.create_profile(
            self.context.services.settings, name, description, prompt
        )
        cid = profile["id"]
        self.feature_controller("session").sync_sessions()                           # a new tab with its own conversation
        self.feature_controller("session").switch_session(cid)
        self.feature_controller("runtime").save_now()

    def edit_character(self):
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        if cid == "kira":
            return
        profile = dict(self.context.services.character_service.all_profiles(self.context.services.settings)[cid])
        name, ok = QInputDialog.getText(self.window, "ویرایش شخصیت", "نام:", QLineEdit.Normal, profile.get("name", ""))
        if not ok or not name.strip():
            return
        description, ok = QInputDialog.getText(self.window, "ویرایش شخصیت", "توضیح:", QLineEdit.Normal, profile.get("description", ""))
        if not ok:
            return
        prompt, ok = QInputDialog.getMultiLineText(self.window, "ویرایش شخصیت", "دستور شخصیت و لحن:", profile.get("prompt", ""))
        if not ok:
            return
        self.context.services.character_service.update_profile(
            self.context.services.settings, cid, name=name, description=description, prompt=prompt
        )
        self.feature_controller("session").sync_sessions()
        self.feature_controller("session").apply_chat_theme()
        self.refresh_character_choices()
        self.refresh_character_card(cid)
        self.feature_controller("runtime").save_now()

    def delete_character(self):
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        if cid == "kira":
            return
        if QMessageBox.question(self.window, "حذف شخصیت", "این شخصیت حذف شود؟") != QMessageBox.Yes:
            return
        self.context.services.character_service.delete_profile(self.context.services.settings, cid)
        initiative_settings = self.context.services.settings.get("character_initiative")
        if isinstance(initiative_settings, dict):
            initiative_settings.pop(cid, None)
        initiative_history = self.context.services.settings.get("character_initiative_history")
        if isinstance(initiative_history, dict):
            initiative_history.pop(cid, None)
        self.feature_controller("session").sync_sessions()                           # its tab (and conversation view) goes away
        self.feature_controller("session").switch_session("kira")
        self.feature_controller("runtime").save_now()

    def build_appearance_tab(self):
        """Compose the independent appearance page and connect controller actions."""
        self.context.views.appearance_page = AppearancePage(
            self.context.services.settings,
            self.feature_controller("session").t,
            glass_supported=winfx.supported(),
            parent=self.window,
        )
        self.context.views.appearance_page.appearance_apply_requested.connect(self.apply_appearance)
        self.context.views.appearance_page.choose_color_requested.connect(self.choose_appearance_color)
        self.context.views.appearance_page.reset_requested.connect(self.reset_appearance)
        self.context.views.tabs.addTab(self.context.views.appearance_page, "")

    def _set_appearance_color_preview(self, value):
        """Compatibility helper; AppearancePage owns its colour preview."""
        self.context.views.appearance_page.set_background_color(value)

    def choose_appearance_color(self):
        current = QColor(self.context.views.appearance_page.background_color)
        selected = QColorDialog.getColor(current, self, "رنگ پس‌زمینه")
        if selected.isValid():
            self.context.views.appearance_page.set_background_color(selected.name())
            self.schedule_appearance()

    def reset_appearance(self):
        page = self.context.views.appearance_page
        page.set_background_color("#0A0A1C")
        page.window_effect.setCurrentIndex(max(0, page.window_effect.findData("acrylic")))
        page.appearance_brightness.setValue(100)
        page.appearance_glow.setValue(58)
        page.appearance_transparency.setValue(28)
        page.schedule_appearance()

    def schedule_appearance(self, *_):
        page = getattr(self.context.views, "appearance_page", None)
        if page is not None:
            page.schedule_appearance()

    def apply_appearance(self, save=False):
        """Apply the current Appearance controls immediately; persist only after the short debounce."""
        if not hasattr(self.context.views, "appearance_page"):
            return
        previous = getattr(self.context.state, "_effect", "off")
        color = self.context.views.appearance_page.background_color or (self.context.services.settings.get("appearance") or {}).get("background_color", "#0A0A1C")
        appearance = {
            "background_color": color,
            "brightness": self.context.views.appearance_page.appearance_brightness.value(),
            "glow": self.context.views.appearance_page.appearance_glow.value(),
            "transparency": self.context.views.appearance_page.appearance_transparency.value(),
        }
        # Reduce the old high default once; subsequent values are entirely user-controlled.
        if not self.context.services.settings.get("appearance_glow_adjusted"):
            appearance["glow"] = min(int(appearance["glow"]), 18)
            self.context.views.appearance_page.appearance_glow.blockSignals(True)
            self.context.views.appearance_page.appearance_glow.setValue(appearance["glow"])
            self.context.views.appearance_page.appearance_glow.blockSignals(False)
            self.context.services.settings["appearance_glow_adjusted"] = True
        # One-time migration from the restrained glow to the Neon Shooter bloom level.
        # Preserve stronger user-selected values; only lift the old low default.
        if not self.context.services.settings.get("appearance_neon_shooter_v1"):
            if int(appearance["glow"]) < 42:
                appearance["glow"] = 58
            self.context.views.appearance_page.appearance_glow.blockSignals(True)
            self.context.views.appearance_page.appearance_glow.setValue(int(appearance["glow"]))
            self.context.views.appearance_page.appearance_glow.blockSignals(False)
            self.context.services.settings["appearance_neon_shooter_v1"] = True
        self.context.services.settings["appearance"] = appearance
        wanted = self.context.views.appearance_page.window_effect.currentData() or "acrylic"
        current = winfx.active_effect(wanted)
        self.context.state._effect = current
        set_glow_intensity(appearance["glow"] / 100.0)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_style(current, appearance))
        if hasattr(self.context.views, "glow_effects"):
            self.feature_controller("session").apply_chat_theme()
        self._refresh_icon_glow()
        self._apply_neon_glow_effects(appearance)
        winfx.apply_effect(self.window.winId(), current)
        self.context.views.appearance_page.set_background_color(color)
        if (previous == "off") != (current == "off") and previous != current and getattr(self.window, "isVisible", lambda: False)():
            self.feature_controller("session").add_chat("system", "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.")
        if save:
            save_settings(self.context.services.settings)

    def _apply_neon_glow_effects(self, appearance=None):
        """Bloom the glass panels and action controls without touching animated avatar widgets."""
        appearance = appearance if isinstance(appearance, dict) else (self.context.services.settings.get("appearance") or {})
        intensity = max(0, min(100, int(appearance.get("glow", 58))))
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        palette = self.feature_controller("session").theme_for_character(cid, self.context.services.character_service.all_profiles(self.context.services.settings).get(cid, {}))
        if not hasattr(self, "_neon_widget_effects"):
            self._neon_widget_effects = {}

        # Panel borders are handled by the stylesheet; avoid effects on containers because
        # Qt may composite their child text and inputs into the shadow source.
        # Shadow effects on every settings button force Qt to re-render dozens of
        # controls. Keep the expensive bloom on the persistent primary actions only.
        targets = []
        for name in ("menu_btn", "mic_btn", "wake_btn", "voice_btn", "stop_btn",
                     "send_btn", "gen_stop_btn"):
            widget = getattr(self.context.views, name, None)
            if widget is not None:
                targets.append((widget, palette["second"], 10 + intensity * 0.12, 14 + intensity * 0.38))
        save_button = getattr(self.context.views, "save_btn", None)
        if save_button is not None:
            targets.append((save_button, palette["main"], 10 + intensity * 0.12, 14 + intensity * 0.34))

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
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        palette = self.feature_controller("session").theme_for_character(cid, self.context.services.character_service.all_profiles(self.context.services.settings).get(cid, {}))
        for button in self.window.findChildren(QToolButton):
            name = button.property("kiraIconName")
            if not name:
                continue
            button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))

    def build_general_tab(self):
        """Compose preferences and help pages; the preferences widget owns its controls."""
        self.context.views.preferences_page = PreferencesPage(
            self.context.services.settings,
            self.feature_controller("session").t,
            web_depths=tuple(websearch.DEPTHS.items()),
            about_rows=about.about_rows(VERSION),
            parent=self.window,
        )
        for name in (
            "ui_lang", "tavily_key", "web_depth", "web_fallback_chk", "web_test_btn",
            "restore_chat_btn", "memory_btn", "import_chat_btn", "about_labels",
        ):
            setattr(self.context.views, name, getattr(self.context.views.preferences_page, name))

        self.context.views.preferences_page.web_search_test_requested.connect(self.feature_controller("chat").test_web_search)
        self.context.views.preferences_page.clear_history_requested.connect(self.feature_controller("runtime").clear_chat)
        self.context.views.preferences_page.restore_history_requested.connect(self.feature_controller("runtime").restore_cleared_chat)
        self.context.views.preferences_page.open_memory_requested.connect(self.feature_controller("runtime").open_memory_dialog)
        self.context.views.preferences_page.import_history_requested.connect(self.feature_controller("runtime").import_old_chat)

        subtabs = QTabWidget()
        subtabs.addTab(self.context.views.preferences_page, "")
        subtabs.addTab(self.build_skills_tab(), "Skills")
        subtabs.addTab(self.build_help_tab(), "")
        self.general_subtabs = subtabs
        self.feature_controller("session").reg(lambda text: subtabs.setTabText(0, text), "tab_preferences")
        self.feature_controller("session").reg(lambda text: subtabs.setTabText(2, text), "tab_help")
        self.context.views.tabs.addTab(self.feature_controller("session").page(subtabs), "")

    def build_skills_tab(self):
        """Compose the Skills page and adapt its intents to the application service."""
        from .pages.skills_page import SkillsPage

        page = SkillsPage(parent=self.window)
        page.install_zip_requested.connect(self.install_shared_skill_zip)
        page.install_folder_requested.connect(self.install_shared_skill_folder)
        page.enable_changed.connect(self.set_shared_skill_enabled)
        page.uninstall_requested.connect(self.uninstall_shared_skill)
        self.skills_page = page
        self.refresh_shared_skills()
        return page

    def refresh_shared_skills(self):
        page = getattr(self, "skills_page", None)
        if page is None:
            return
        page.set_skills(
            self.context.services.shared_skills_application_service.list_installed(),
            self.context.services.character_service.all_profiles(self.context.services.settings),
            self.context.services.shared_skills_application_service,
        )

    def install_shared_skill_zip(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self.window, "Install Skill ZIP", "", "Skill packages (*.zip)"
        )
        if path:
            self._install_shared_skill(path)

    def install_shared_skill_folder(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(self.window, "Install Skill folder")
        if path:
            self._install_shared_skill(path)

    def _install_shared_skill(self, source):
        try:
            manifest = self.context.services.shared_skills_application_service.install(source)
            self.refresh_shared_skills()
            self.skills_page.set_status(f"Skill «{manifest.name}» نصب شد.")
        except Exception as exc:
            self.skills_page.set_status(f"نصب ناموفق بود: {exc}", error=True)

    def set_shared_skill_enabled(self, skill_id, enabled, character_id):
        try:
            self.context.services.shared_skills_application_service.set_enabled(
                skill_id, enabled, character_id=character_id
            )
            self.refresh_shared_skills()
        except Exception as exc:
            self.skills_page.set_status(f"ذخیره تنظیمات ناموفق بود: {exc}", error=True)
            self.refresh_shared_skills()

    def uninstall_shared_skill(self, skill_id):
        name = skill_id
        for item in self.context.services.shared_skills_application_service.list_installed():
            if item.skill_id == skill_id:
                name = item.name
                break
        if QMessageBox.question(
            self.window, "حذف Skill", f"«{name}» از کتابخانه مشترک حذف شود؟"
        ) != QMessageBox.Yes:
            return
        try:
            if self.context.services.shared_skills_application_service.uninstall(skill_id):
                self.refresh_shared_skills()
                self.skills_page.set_status(f"Skill «{name}» حذف شد.")
        except Exception as exc:
            self.skills_page.set_status(f"حذف ناموفق بود: {exc}", error=True)

    def build_help_tab(self):
        """Build the standalone Help/About page; it owns its content and translations."""
        self.context.views.help_page = HelpPage(
            self.feature_controller("session").t,
            app_name=APP_NAME,
            version=VERSION,
            releases_url=RELEASES_URL,
            project_url=PROJECT_URL,
        )
        return self.context.views.help_page

    def build_mcp_registry_group(self, parent_layout):
        """Mount the independent MCP registry panel and connect application actions."""
        self.context.views.mcp_registry_panel = McpRegistryPanel(parent=self.window)
        self.mcp_registry_query = self.context.views.mcp_registry_panel.query_edit
        self.mcp_registry_search_btn = self.context.views.mcp_registry_panel.search_btn
        self.mcp_registry_list = self.context.views.mcp_registry_panel.results
        self.mcp_registry_add_btn = self.context.views.mcp_registry_panel.add_btn
        self.mcp_registry_refresh_btn = self.context.views.mcp_registry_panel.refresh_btn
        self.mcp_registry_status = self.context.views.mcp_registry_panel.status
        self.context.views.mcp_registry_panel.search_requested.connect(self.search_mcp_registry)
        self.context.views.mcp_registry_panel.add_requested.connect(self.add_mcp_registry_server)
        self.context.views.mcp_registry_panel.refresh_models_requested.connect(self.feature_controller("provider_settings").refresh_model_catalogs)
        parent_layout.addWidget(self.context.views.mcp_registry_panel)
        QTimer.singleShot(1200, self.search_mcp_registry)

    def search_mcp_registry(self):
        from ..mcp.registry import RegistrySearchWorker
        worker = getattr(self, "_mcp_registry_worker", None)
        if worker is not None and worker.isRunning():
            return
        self.context.views.mcp_registry_panel.set_searching(True)
        self._mcp_registry_worker = RegistrySearchWorker(self.context.views.mcp_registry_panel.query(), self.window)
        self._mcp_registry_worker.completed.connect(self._on_mcp_registry_results)
        self._mcp_registry_worker.start()

    def _on_mcp_registry_results(self, records, error):
        self.context.views.mcp_registry_panel.show_results(records, error)

    def add_mcp_registry_server(self):
        record = self.context.views.mcp_registry_panel.selected_record()
        if record is None:
            self.context.views.mcp_registry_panel.set_status("اول یک سرور از فهرست انتخاب کن.")
            return
        from ..mcp.registry import server_config
        try:
            name, cfg = server_config(record)
            path = DATA_DIR / "kira_mcp.json"
            raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
            if not isinstance(raw, dict):
                raise ValueError("ساختار kira_mcp.json معتبر نیست")
            servers = raw.setdefault("servers", {})
            if name in servers:
                self.context.views.mcp_registry_panel.set_status(f"سرور «{name}» از قبل ثبت شده است.")
                return
            servers[name] = cfg
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            hub = getattr(self.context.services.tool_agent, "mcp", None)
            if hub is not None:
                hub.refresh_async()
            self.context.views.mcp_registry_panel.set_status(f"سرور «{name}» ثبت شد؛ Kira در حال اتصال و کشف خودکار ابزارهاست.")
        except Exception as exc:
            self.context.views.mcp_registry_panel.set_status("افزودن سرور ناموفق بود: " + str(exc)[:240])


# Backward-compatible import name for callers migrating from mixin composition.
CharacterSettingsMixin = CharacterSettingsController
