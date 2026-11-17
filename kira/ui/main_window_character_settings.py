"""Character settings behavior mixin for the desktop window."""
from .main_window_character_settings_support import *  # noqa: F401,F403


class CharacterSettingsMixin:
    def build_characters_tab(self):
        """Compose the independent Characters page and delegate actions to the host."""
        self.character_page = CharactersPage(
            self.settings,
            self.t,
            base_traits=BASE_TRAITS,
            moods=MOODS,
            parent=self,
        )
        page = self.character_page
        page.character_selected.connect(self.select_character)
        page.add_character_requested.connect(self.add_character)
        page.edit_character_requested.connect(self.edit_character)
        page.delete_character_requested.connect(self.delete_character)
        page.choose_theme_color_requested.connect(self.choose_character_theme_color)
        page.reset_theme_color_requested.connect(self.reset_character_theme_color)
        page.preview_requested.connect(
            lambda mood: self.animator.set_expression(mood, hold=8)
        )
        page.open_sounds_requested.connect(self.open_sounds)
        page.save_requested.connect(lambda: self.save_character_settings(silent=True))
        page.save_personality_requested.connect(self.save_personality_profile)
        self.tabs.addTab(page, "")
        self.refresh_character_choices()
        self.refresh_character_card()
        self.refresh_personality_controls()

    def build_personality_tab(self):
        """Compatibility entry point; personality controls are owned by CharactersPage."""
        return self.character_page.character_subtabs.widget(1)

    def refresh_character_controls(self):
        cid = self.character_service.active_id(self.settings)
        voice = (self.settings.get("character_voice") or {}).get(cid) or {}
        self.character_page.char_voice_rate.blockSignals(True)
        self.character_page.char_voice_rate.setValue(int(voice.get("voice_rate", self.settings.get("voice_rate", 0))))
        self.character_page.char_voice_rate.blockSignals(False)
        self.character_page.char_voice_volume.blockSignals(True)
        self.character_page.char_voice_volume.setValue(round(float(voice.get("voice_volume", self.settings.get("voice_volume", 0.9))) * 100))
        self.character_page.char_voice_volume.blockSignals(False)
        resources = (self.settings.get("character_resources") or {}).get(cid) or {}
        for widget, key in ((self.character_page.char_skills_edit, "skills"), (self.character_page.char_mcp_edit, "mcp"),
                            (self.character_page.char_connectors_edit, "connectors")):
            widget.blockSignals(True)
            value = resources.get(key) or []
            widget.setText(", ".join(value) if isinstance(value, (list, tuple)) else str(value))
            widget.blockSignals(False)
        notes = (self.settings.get("character_notes") or {}).get(cid) or ""
        if hasattr(self.character_page, "character_notes_edit"):
            self.character_page.character_notes_edit.blockSignals(True)
            self.character_page.character_notes_edit.setPlainText(str(notes))
            self.character_page.character_notes_edit.blockSignals(False)
        self.apply_character_voice_settings()

    def _flush_character_autosave(self):
        timer = getattr(self, "_character_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
            self.save_character_settings(silent=True)

    def save_character_settings(self, silent=False):
        cid = self.character_service.active_id(self.settings)
        self.settings.setdefault("character_voice", {})[cid] = {
            "voice_rate": self.character_page.char_voice_rate.value(),
            "voice_volume": self.character_page.char_voice_volume.value() / 100.0,
        }
        def split(value):
            return [part.strip() for part in re.split(r"[,;\\n]+", value or "") if part.strip()]
        self.settings.setdefault("character_resources", {})[cid] = {
            "skills": split(self.character_page.char_skills_edit.text()),
            "mcp": split(self.character_page.char_mcp_edit.text()),
            "connectors": split(self.character_page.char_connectors_edit.text()),
        }
        if hasattr(self.character_page, "character_notes_edit"):
            self.settings.setdefault("character_notes", {})[cid] = self.character_page.character_notes_edit.toPlainText().strip()
        self.apply_character_voice_settings()
        self.save_now()

    def apply_character_voice_settings(self):
        """Give the speaker an isolated settings snapshot for the active character."""
        cid = self.character_service.active_id(self.settings)
        override = (self.settings.get("character_voice") or {}).get(cid) or {}
        effective = dict(self.settings)
        effective.update({k: v for k, v in override.items() if k in ("voice_rate", "voice_volume")})
        if getattr(self, "speaker", None) is not None:
            self.speaker.settings = effective

    def refresh_personality_controls(self):
        if not getattr(getattr(self, "character_page", None), "personality_sliders", None):
            return
        self.refresh_character_controls()
        traits = self.character_traits(self.active_character().get("id", "kira")) or BASE_TRAITS
        for key, slider in self.character_page.personality_sliders.items():
            slider.blockSignals(True)
            slider.setValue(int(round(float(traits.get(key, BASE_TRAITS.get(key, 0.5))) * 100)))
            slider.blockSignals(False)

    def save_personality_profile(self, silent=False):
        profile = self.active_character()
        cid = profile.get("id", "kira")
        traits = {key: slider.value() / 100.0 for key, slider in self.character_page.personality_sliders.items()}
        try:
            self.settings.setdefault("character_traits", {})[cid] = traits
            mood.set_active_character(cid, traits)
            if hasattr(self.character_page, "character_notes_edit"):
                self.settings.setdefault("character_notes", {})[cid] = self.character_page.character_notes_edit.toPlainText().strip()
            self.save_character_settings(silent=True)
            self.refresh_personality_controls()
            if not silent:
                self.save_now()
                self.add_chat("system", self.t("character_traits_saved", name=profile.get("name", cid)))
            return True
        except Exception as exc:                            # noqa: BLE001
            if not silent:
                QMessageBox.warning(self, self.t("character_error_title"), str(exc))
            return False

    def refresh_character_choices(self):
        current = self.character_service.active_id(self.settings)
        self.character_page.character_combo.blockSignals(True)
        self.character_page.character_combo.clear()
        profiles = self.character_service.all_profiles(self.settings)
        for cid in ("kira", "ren", "mika"):
            if cid in profiles:
                p = profiles[cid]
                self.character_page.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        for cid, p in profiles.items():
            if cid not in ("kira", "ren", "mika"):
                self.character_page.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        self.character_page.character_combo.setCurrentIndex(max(0, self.character_page.character_combo.findData(current)))
        self.character_page.character_combo.blockSignals(False)
        self.character_page.character_edit_btn.setEnabled(current != "kira")
        self.character_page.character_delete_btn.setEnabled(current != "kira")
        self._refresh_character_theme_preview()

    def _refresh_character_theme_preview(self):
        if not hasattr(self.character_page, "character_theme_color_preview"):
            return
        cid = self.character_service.active_id(self.settings)
        colour = self.theme_for_character(cid)["main"]
        self.character_page.character_theme_color_preview.setText(colour)
        self.character_page.character_theme_color_preview.setStyleSheet(
            f"QLabel {{ background: {colour}; color: white; border: 1px solid rgba(255,255,255,0.5); "
            "border-radius: 7px; padding: 5px; }"
        )

    def choose_character_theme_color(self):
        cid = self.character_service.active_id(self.settings)
        current = QColor(self.theme_for_character(cid)["main"])
        selected = QColorDialog.getColor(current, self, "رنگ تم شخصیت")
        if not selected.isValid():
            return
        self.settings.setdefault("character_theme_colors", {})[cid] = selected.name()
        for session in self.sessions.values():
            session.theme = self.theme_for_character(session.cid)
        self._refresh_character_theme_preview()
        self.apply_chat_theme()
        self.refresh_navigation_icons()
        self._refresh_icon_glow()
        self.save_now()

    def reset_character_theme_color(self):
        cid = self.character_service.active_id(self.settings)
        self.settings.setdefault("character_theme_colors", {}).pop(cid, None)
        for session in self.sessions.values():
            session.theme = self.theme_for_character(session.cid)
        self._refresh_character_theme_preview()
        self.apply_chat_theme()
        self.refresh_navigation_icons()
        self._refresh_icon_glow()
        self.save_now()

    def refresh_character_card(self, character_id=None):
        profile = self.character_service.all_profiles(self.settings).get(character_id or self.character_service.active_id(self.settings), self.character_service.all_profiles(self.settings).get("kira", {}))
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
        self.character_page.character_portrait.setPixmap(pixmap)
        self.character_page.character_description.setText(profile.get("description", ""))

    def _fit_portrait(self, pixmap):
        """Fill the portrait frame without stretching: pictures whose proportions differ from the frame are
        cropped (centred, biased toward the face). A picture that already fits (Kira's SVG) is left untouched."""
        if pixmap.isNull():
            return pixmap
        size = self.character_page.character_portrait.size()
        if abs(pixmap.width() / pixmap.height() - size.width() / size.height()) < 0.03:
            return pixmap
        x, y, w, h = avatar_art.cover_crop(pixmap.width(), pixmap.height(), size.width(), size.height())
        crop = pixmap.copy(int(round(x)), int(round(y)), int(round(w)), int(round(h)))
        return crop.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def apply_character_art(self):
        """Chat page + floating companion show the active character: Kira's own animated PNG, or the character's
        full-body picture (a profile without one falls back to Kira's art). Called at start-up and on every change."""
        profile = self.character_service.active(self.settings)
        self.animator.set_character_art(self.character_service.avatar_file(profile, ROOT))
        self.animator.rig.intensity = float(self.settings.get("motion_strength", self.animator.rig.intensity)) * self.animator.motion_gain
        self.animator.touch()

    def select_character(self, index):
        character_id = self.character_page.character_combo.itemData(index)
        if not character_id:
            return
        if character_id != self.front.cid:
            self.switch_session(character_id)         # the character list in Settings and the tabs on the chat page are the same switch
            self.save_now()

    def add_character(self):
        name, ok = QInputDialog.getText(self, "شخصیت جدید", "نام:")
        if not ok or not name.strip():
            return
        description, ok = QInputDialog.getText(self, "شخصیت جدید", "توضیح کوتاه:")
        if not ok:
            return
        prompt, ok = QInputDialog.getMultiLineText(self, "شخصیت جدید", "دستور شخصیت و لحن:")
        if not ok:
            return
        cid = "custom_" + str(time.time_ns())
        profile = {"id": cid, "name": name.strip(), "name_fa": name.strip(), "gender": "unspecified",
                   "description": description.strip(), "image": "assets/characters/ren.svg", "prompt": prompt.strip()}
        self.settings.setdefault("characters", []).append(profile)
        self.settings.setdefault("character_voice", {}).setdefault(cid, {})
        self.settings.setdefault("character_notes", {}).setdefault(cid, "")
        self.settings.setdefault("character_resources", {}).setdefault(cid, {})
        self.sync_sessions()                           # a new tab with its own conversation
        self.switch_session(cid)
        self.save_now()

    def edit_character(self):
        cid = self.character_service.active_id(self.settings)
        if cid == "kira":
            return
        profile = dict(self.character_service.all_profiles(self.settings)[cid])
        name, ok = QInputDialog.getText(self, "ویرایش شخصیت", "نام:", QLineEdit.Normal, profile.get("name", ""))
        if not ok or not name.strip():
            return
        description, ok = QInputDialog.getText(self, "ویرایش شخصیت", "توضیح:", QLineEdit.Normal, profile.get("description", ""))
        if not ok:
            return
        prompt, ok = QInputDialog.getMultiLineText(self, "ویرایش شخصیت", "دستور شخصیت و لحن:", profile.get("prompt", ""))
        if not ok:
            return
        profile.update({"name": name.strip(), "name_fa": name.strip(), "description": description.strip(), "prompt": prompt.strip()})
        custom = self.settings.setdefault("characters", [])
        custom[:] = [x for x in custom if x.get("id") != cid]
        custom.append(profile)
        self.sync_sessions()
        self.apply_chat_theme()
        self.refresh_character_choices()
        self.refresh_character_card(cid)
        self.save_now()

    def delete_character(self):
        cid = self.character_service.active_id(self.settings)
        if cid == "kira":
            return
        if QMessageBox.question(self, "حذف شخصیت", "این شخصیت حذف شود؟") != QMessageBox.Yes:
            return
        if self.character_service.is_builtin(cid):
            hidden = self.settings.setdefault("deleted_character_ids", [])
            if cid not in hidden:
                hidden.append(cid)
        else:
            self.settings["characters"] = [x for x in self.settings.get("characters", []) if x.get("id") != cid]
        self.settings["active_character_id"] = "kira"
        for key in ("character_voice", "character_notes", "character_resources", "character_traits"):
            self.settings.get(key, {}).pop(cid, None)
        self.sync_sessions()                           # its tab (and conversation view) goes away
        self.switch_session("kira")
        self.save_now()

    def build_appearance_tab(self):
        """Compose the independent appearance page and connect controller actions."""
        self.appearance_page = AppearancePage(
            self.settings,
            self.t,
            glass_supported=winfx.supported(),
            parent=self,
        )
        self.appearance_page.appearance_apply_requested.connect(self.apply_appearance)
        self.appearance_page.choose_color_requested.connect(self.choose_appearance_color)
        self.appearance_page.reset_requested.connect(self.reset_appearance)
        self.tabs.addTab(self.appearance_page, "")

    def _set_appearance_color_preview(self, value):
        """Compatibility helper; AppearancePage owns its colour preview."""
        self.appearance_page.set_background_color(value)

    def choose_appearance_color(self):
        current = QColor(self.appearance_page.background_color)
        selected = QColorDialog.getColor(current, self, "رنگ پس‌زمینه")
        if selected.isValid():
            self.appearance_page.set_background_color(selected.name())
            self.schedule_appearance()

    def reset_appearance(self):
        page = self.appearance_page
        page.set_background_color("#0A0A1C")
        page.window_effect.setCurrentIndex(max(0, page.window_effect.findData("acrylic")))
        page.appearance_brightness.setValue(100)
        page.appearance_glow.setValue(58)
        page.appearance_transparency.setValue(28)
        page.schedule_appearance()

    def schedule_appearance(self, *_):
        page = getattr(self, "appearance_page", None)
        if page is not None:
            page.schedule_appearance()

    def apply_appearance(self, save=False):
        """Apply the current Appearance controls immediately; persist only after the short debounce."""
        if not hasattr(self, "appearance_page"):
            return
        previous = getattr(self, "_effect", "off")
        color = self.appearance_page.background_color or (self.settings.get("appearance") or {}).get("background_color", "#0A0A1C")
        appearance = {
            "background_color": color,
            "brightness": self.appearance_page.appearance_brightness.value(),
            "glow": self.appearance_page.appearance_glow.value(),
            "transparency": self.appearance_page.appearance_transparency.value(),
        }
        # Reduce the old high default once; subsequent values are entirely user-controlled.
        if not self.settings.get("appearance_glow_adjusted"):
            appearance["glow"] = min(int(appearance["glow"]), 18)
            self.appearance_page.appearance_glow.blockSignals(True)
            self.appearance_page.appearance_glow.setValue(appearance["glow"])
            self.appearance_page.appearance_glow.blockSignals(False)
            self.settings["appearance_glow_adjusted"] = True
        # One-time migration from the restrained glow to the Neon Shooter bloom level.
        # Preserve stronger user-selected values; only lift the old low default.
        if not self.settings.get("appearance_neon_shooter_v1"):
            if int(appearance["glow"]) < 42:
                appearance["glow"] = 58
            self.appearance_page.appearance_glow.blockSignals(True)
            self.appearance_page.appearance_glow.setValue(int(appearance["glow"]))
            self.appearance_page.appearance_glow.blockSignals(False)
            self.settings["appearance_neon_shooter_v1"] = True
        self.settings["appearance"] = appearance
        wanted = self.appearance_page.window_effect.currentData() or "acrylic"
        current = winfx.active_effect(wanted)
        self._effect = current
        set_glow_intensity(appearance["glow"] / 100.0)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_style(current, appearance))
        if hasattr(self, "glow_effects"):
            self.apply_chat_theme()
        self._refresh_icon_glow()
        self._apply_neon_glow_effects(appearance)
        winfx.apply_effect(self.winId(), current)
        self.appearance_page.set_background_color(color)
        if (previous == "off") != (current == "off") and previous != current and getattr(self, "isVisible", lambda: False)():
            self.add_chat("system", "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.")
        if save:
            save_settings(self.settings)

    def _apply_neon_glow_effects(self, appearance=None):
        """Bloom the glass panels and action controls without touching animated avatar widgets."""
        appearance = appearance if isinstance(appearance, dict) else (self.settings.get("appearance") or {})
        intensity = max(0, min(100, int(appearance.get("glow", 58))))
        cid = self.character_service.active_id(self.settings)
        palette = self.theme_for_character(cid, self.character_service.all_profiles(self.settings).get(cid, {}))
        if not hasattr(self, "_neon_widget_effects"):
            self._neon_widget_effects = {}

        # Panel borders are handled by the stylesheet; avoid effects on containers because
        # Qt may composite their child text and inputs into the shadow source.
        # Shadow effects on every settings button force Qt to re-render dozens of
        # controls. Keep the expensive bloom on the persistent primary actions only.
        targets = []
        for name in ("menu_btn", "mic_btn", "wake_btn", "voice_btn", "stop_btn",
                     "send_btn", "gen_stop_btn"):
            widget = getattr(self, name, None)
            if widget is not None:
                targets.append((widget, palette["second"], 10 + intensity * 0.12, 14 + intensity * 0.38))
        save_button = getattr(self, "save_btn", None)
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
        cid = self.character_service.active_id(self.settings)
        palette = self.theme_for_character(cid, self.character_service.all_profiles(self.settings).get(cid, {}))
        for button in self.findChildren(QToolButton):
            name = button.property("kiraIconName")
            if not name:
                continue
            button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))

    def build_general_tab(self):
        """Compose preferences and help pages; the preferences widget owns its controls."""
        self.preferences_page = PreferencesPage(
            self.settings,
            self.t,
            web_depths=tuple(websearch.DEPTHS.items()),
            about_rows=about.about_rows(VERSION),
            parent=self,
        )
        for name in (
            "ui_lang", "tavily_key", "web_depth", "web_fallback_chk", "web_test_btn",
            "restore_chat_btn", "memory_btn", "import_chat_btn", "about_labels",
        ):
            setattr(self, name, getattr(self.preferences_page, name))

        self.preferences_page.web_search_test_requested.connect(self.test_web_search)
        self.preferences_page.clear_history_requested.connect(self.clear_chat)
        self.preferences_page.restore_history_requested.connect(self.restore_cleared_chat)
        self.preferences_page.open_memory_requested.connect(self.open_memory_dialog)
        self.preferences_page.import_history_requested.connect(self.import_old_chat)

        subtabs = QTabWidget()
        subtabs.addTab(self.preferences_page, "")
        subtabs.addTab(self.build_help_tab(), "")
        self.general_subtabs = subtabs
        self.reg(lambda text: subtabs.setTabText(0, text), "tab_preferences")
        self.reg(lambda text: subtabs.setTabText(1, text), "tab_help")
        self.tabs.addTab(self.page(subtabs), "")

    def build_help_tab(self):
        """Build the standalone Help/About page; it owns its content and translations."""
        self.help_page = HelpPage(
            self.t,
            app_name=APP_NAME,
            version=VERSION,
            releases_url=RELEASES_URL,
            project_url=PROJECT_URL,
        )
        return self.help_page

    def build_mcp_registry_group(self, parent_layout):
        """Mount the independent MCP registry panel and connect application actions."""
        self.mcp_registry_panel = McpRegistryPanel(parent=self)
        self.mcp_registry_query = self.mcp_registry_panel.query_edit
        self.mcp_registry_search_btn = self.mcp_registry_panel.search_btn
        self.mcp_registry_list = self.mcp_registry_panel.results
        self.mcp_registry_add_btn = self.mcp_registry_panel.add_btn
        self.mcp_registry_refresh_btn = self.mcp_registry_panel.refresh_btn
        self.mcp_registry_status = self.mcp_registry_panel.status
        self.mcp_registry_panel.search_requested.connect(self.search_mcp_registry)
        self.mcp_registry_panel.add_requested.connect(self.add_mcp_registry_server)
        self.mcp_registry_panel.refresh_models_requested.connect(self.refresh_model_catalogs)
        parent_layout.addWidget(self.mcp_registry_panel)
        QTimer.singleShot(1200, self.search_mcp_registry)

    def search_mcp_registry(self):
        from ..mcp.registry import RegistrySearchWorker
        worker = getattr(self, "_mcp_registry_worker", None)
        if worker is not None and worker.isRunning():
            return
        self.mcp_registry_panel.set_searching(True)
        self._mcp_registry_worker = RegistrySearchWorker(self.mcp_registry_panel.query(), self)
        self._mcp_registry_worker.completed.connect(self._on_mcp_registry_results)
        self._mcp_registry_worker.start()

    def _on_mcp_registry_results(self, records, error):
        self.mcp_registry_panel.show_results(records, error)

    def add_mcp_registry_server(self):
        record = self.mcp_registry_panel.selected_record()
        if record is None:
            self.mcp_registry_panel.set_status("اول یک سرور از فهرست انتخاب کن.")
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
                self.mcp_registry_panel.set_status(f"سرور «{name}» از قبل ثبت شده است.")
                return
            servers[name] = cfg
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            hub = getattr(self.tool_agent, "mcp", None)
            if hub is not None:
                hub.refresh_async()
            self.mcp_registry_panel.set_status(f"سرور «{name}» ثبت شد؛ Kira در حال اتصال و کشف خودکار ابزارهاست.")
        except Exception as exc:
            self.mcp_registry_panel.set_status("افزودن سرور ناموفق بود: " + str(exc)[:240])
