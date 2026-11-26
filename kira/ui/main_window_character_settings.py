"""Character and appearance feature controller."""
from PySide6.QtCore import Slot
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
    re,
    save_settings,
    set_glow_intensity,
    time,
    websearch,
    winfx,
)


from kira.settings_schema import DEFAULTS as SETTINGS_DEFAULTS

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
        from .pages.news_feed_page import NewsFeedPage
        from ..news_feed import NewsFeedService
        self._news_feed_service = NewsFeedService(lambda: self.context.services.settings, DATA_DIR)
        self.context.views.news_page = NewsFeedPage(
            self._news_feed_service, self.context.services.settings, parent=self.window
        )
        news_page = self.context.views.news_page
        news_page.refresh_requested.connect(self.refresh_news_character)
        news_page.region_confirm_requested.connect(self.confirm_news_region)
        news_page.location_detection_requested.connect(self.detect_news_region)
        self.context.views.tabs.addTab(news_page, "اخبار")
        self._news_feed_service.start()
        region = self.context.services.settings.get("news_health_region") or {}
        if not (isinstance(region, dict) and region.get("confirmed") is True):
            self.detect_news_region()
        assistant_page = getattr(self.context.views, "assistant_page", None)
        if assistant_page is not None:
            page.attach_identity_box(assistant_page.identity_box)      # name / persona / modes / temperature sit under the character card
        self.context.views.tabs.addTab(page, "")
        self.refresh_character_choices()
        self.refresh_character_card()
        self.refresh_personality_controls()

    def refresh_news_character(self, character_id):
        service = getattr(self, "_news_feed_service", None)
        if service is None:
            return
        cid = str(character_id or "kira")
        service.refresh_character_async(cid)
        page = getattr(self.context.views, "news_page", None)
        if page is not None:
            page.show_refreshing(cid)

    def detect_news_region(self):
        service = getattr(self, "_news_feed_service", None)
        page = getattr(self.context.views, "news_page", None)
        if service is None or page is None:
            return
        page.detect_button.setEnabled(False)
        service.detect_region_async(
            lambda city, country, error: page.location_suggestion_ready.emit(city, country, error)
        )

    def confirm_news_region(self, value):
        parts = [part.strip() for part in str(value or "").split(",", 1)]
        if len(parts) != 2 or not all(parts):
            QMessageBox.information(
                self.window, "موقعیت میکا",
                "شهر و کشور را با این قالب وارد کن: Frankfurt am Main, Germany",
            )
            return
        from datetime import datetime, timezone
        city, country = parts
        self.context.services.settings["news_health_region"] = {
            "city": city[:100], "country": country[:100], "confirmed": True,
            "source": "user_confirmed",
            "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        save_settings(self.context.services.settings)
        service = getattr(self, "_news_feed_service", None)
        if service is not None:
            service.clear_local_alerts()
        page = getattr(self.context.views, "news_page", None)
        if page is not None:
            page.set_region_confirmed(city, country)
        self.refresh_news_character("mika")

    def build_personality_tab(self):
        """Compatibility entry point; personality controls are owned by CharactersPage."""
        return self.context.views.character_page

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
        self.context.views.character_page.char_voice_rate.setValue(int(voice.get("voice_rate", self.context.services.settings.get("voice_rate", SETTINGS_DEFAULTS["voice_rate"]))))
        self.context.views.character_page.char_voice_rate.blockSignals(False)
        self.context.views.character_page.char_voice_volume.blockSignals(True)
        self.context.views.character_page.char_voice_volume.setValue(round(float(voice.get("voice_volume", self.context.services.settings.get("voice_volume", SETTINGS_DEFAULTS["voice_volume"]))) * 100))
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
        return self.context.adapters.appearance_runtime.apply_character_voice_settings()

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
        self.context.views.character_page.sync_character_tabs()
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
        selected = QColorDialog.getColor(current, self.window, "رنگ تم شخصیت")
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
        return self.context.adapters.appearance_runtime.apply_character_art()

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
        selected = QColorDialog.getColor(current, self.window, "رنگ پس‌زمینه")
        if selected.isValid():
            self.context.views.appearance_page.set_background_color(selected.name())
            self.schedule_appearance()

    def reset_appearance(self):
        page = self.context.views.appearance_page
        appearance_defaults = SETTINGS_DEFAULTS["appearance"]
        page.set_background_color(appearance_defaults["background_color"])
        page.window_effect.setCurrentIndex(
            max(0, page.window_effect.findData(SETTINGS_DEFAULTS["window_effect"]))
        )
        page.appearance_brightness.setValue(int(appearance_defaults["brightness"]))
        page.appearance_glow.setValue(int(appearance_defaults["glow"]))
        page.appearance_transparency.setValue(int(appearance_defaults["transparency"]))
        page.schedule_appearance()

    def schedule_appearance(self, *_):
        page = getattr(self.context.views, "appearance_page", None)
        if page is not None:
            page.schedule_appearance()

    def apply_appearance(self, save=False):
        return self.context.adapters.appearance_runtime.apply_appearance(save=save)

    def _apply_neon_glow_effects(self, appearance=None):
        return self.context.adapters.appearance_runtime._apply_neon_glow_effects(appearance)

    def _refresh_icon_glow(self):
        return self.context.adapters.appearance_runtime._refresh_icon_glow()

    def _save_ui_design_guidance(self, enabled):
        self.context.services.settings["ui_design_guidance_enabled"] = bool(enabled)
        save_settings(self.context.services.settings)

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
            "ui_design_guidance_chk", "restore_chat_btn", "memory_btn", "import_chat_btn", "about_labels",
        ):
            setattr(self.context.views, name, getattr(self.context.views.preferences_page, name))

        self.context.views.preferences_page.web_search_test_requested.connect(self.feature_controller("chat").test_web_search)
        self.context.views.preferences_page.ui_design_guidance_changed.connect(self._save_ui_design_guidance)
        self.context.views.preferences_page.clear_history_requested.connect(self.feature_controller("runtime").clear_chat)
        self.context.views.preferences_page.restore_history_requested.connect(self.feature_controller("runtime").restore_cleared_chat)
        self.context.views.preferences_page.open_memory_requested.connect(self.feature_controller("runtime").open_memory_dialog)
        self.context.views.preferences_page.import_history_requested.connect(self.feature_controller("runtime").import_old_chat)

        subtabs = QTabWidget()
        subtabs.addTab(self.context.views.preferences_page, "")
        subtabs.addTab(self.build_skills_tab(), "مهارت‌ها")
        subtabs.addTab(self.build_help_tab(), "")
        self.general_subtabs = subtabs
        self.feature_controller("session").reg(lambda text: subtabs.setTabText(0, text), "tab_preferences")
        self.feature_controller("session").reg(lambda text: subtabs.setTabText(2, text), "tab_help")
        self.context.views.tabs.addTab(self.feature_controller("session").page(subtabs), "")

    def build_skills_tab(self):
        """Compose the Skills page and adapt its intents to the application service."""
        from .pages.skills_page import SkillsPage

        page = SkillsPage(parent=self.window)
        self.context.views.skills_page = page
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
        self.mcp_registry_status = self.context.views.mcp_registry_panel.status
        self.context.views.mcp_registry_panel.search_requested.connect(self.search_mcp_registry)
        self.context.views.mcp_registry_panel.add_requested.connect(self.add_mcp_registry_server)
        parent_layout.addWidget(self.context.views.mcp_registry_panel)
        # The registry search is a network request: run it the first time the panel is actually shown
        # (Connections tab opened), not on every start-up, where it competed with the avatar for the interpreter.
        from PySide6.QtCore import QEvent, QObject
        panel = self.context.views.mcp_registry_panel
        owner = self

        class _FirstShow(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Show:
                    obj.removeEventFilter(self)
                    QTimer.singleShot(0, owner.search_mcp_registry)
                return False

        self._mcp_registry_first_show = _FirstShow(panel)
        panel.installEventFilter(self._mcp_registry_first_show)

    def search_mcp_registry(self):
        if self.context.state._closing:
            return
        from ..mcp.registry import RegistrySearchWorker

        worker = self.context.resource("_mcp_registry_worker")
        if worker is not None and worker.isRunning():
            return
        self.context.views.mcp_registry_panel.set_searching(True)
        worker = RegistrySearchWorker(
            self.context.views.mcp_registry_panel.query(), self.window
        )
        self.context.state._mcp_registry_worker = worker
        worker.completed.connect(self._on_mcp_registry_results)
        worker.finished.connect(self._clear_mcp_registry_worker)
        worker.start()

    @Slot()
    def _clear_mcp_registry_worker(self):
        worker = self.sender()
        if self.context.state._mcp_registry_worker is worker:
            self.context.state._mcp_registry_worker = None
        if worker is not None:
            worker.deleteLater()

    @Slot(object, str)
    def _on_mcp_registry_results(self, records, error):
        worker = self.sender()
        if (
            worker is None
            or self.context.state._mcp_registry_worker is not worker
            or self.context.state._closing
        ):
            return
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
