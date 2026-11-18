"""Lifecycle behavior mixin for the desktop window."""
from .main_window_lifecycle_support import (
    OllamaTaskWorker,
    QApplication,
    QDesktopServices,
    QIcon,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QTimer,
    QUrl,
    ROOT,
    SOUNDS_DIR,
    SpeechFixes,
    build_style,
    clamp_num_ctx,
    clamp_num_predict,
    model_installed,
    parse_keep_alive,
    save_settings,
    winfx,
)


from .window_feature_controller import WindowFeatureController


class LifecycleMixin(WindowFeatureController):
    def showEvent(self, event):
        super().showEvent(event)
        winfx.apply_effect(self.winId(), self._effect)
        QTimer.singleShot(0, self.update_bubble)

    def update_window_effect(self, wanted):
        """Settings changed: restyle now. Switching glass on/off at runtime needs a restart to be fully clean."""
        new = winfx.active_effect(wanted)
        old, self._effect = self._effect, new
        QApplication.instance().setStyleSheet(build_style(new, self.settings.get("appearance", {})))
        self.apply_chat_theme()
        winfx.apply_effect(self.winId(), new)
        if (old == "off") != (new == "off"):
            self.add_chat("system", "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.")

    def apply_settings(self):
        s = self.settings
        s.update({
            "assistant_name": self.name.text().strip() or "Kira",
            "model": self.model.text().strip() or "qwen2.5:3b",
            "ollama_url": self.url.text().strip() or "http://localhost:11434",
            "persona": self.persona.toPlainText().strip(), "active_modes": self.modes_chk.isChecked(),
            "temperature": float(self.temp.currentText()),
            "speak_replies": self.voice_page.speak_chk.isChecked(), "stream_speech": self.voice_page.stream_chk.isChecked(),
            "voice_rate": self.voice_page.rate.value(),
            "voice_volume": self.voice_page.volume.value() / 100.0,
            "output_device": self.voice_page.out_device.currentData() or "", "mic_device": self.voice_page.mic_device.currentData() or "",
            "mic_gain": self.voice_page.mic_gain.value(),
            "stt_language": self.voice_page.stt_lang.currentText(), "whisper_model": self.voice_page.whisper.currentText().strip() or "small",
            "wake_timeout": self.voice_page.wake_timeout.value(),
            "mic_sensitivity": self.voice_page.mic_sens.value(), "barge_in": self.voice_page.barge_chk.isChecked(),
            "companion_height": self.character_page.size_sl.value(),
            "follow_strength": self.character_page.follow_sl.value() / 100.0,
            "motion_strength": self.character_page.motion_sl.value() / 100.0,
            "click_reactions": self.character_page.react_chk.isChecked(), "idle_talk": self.character_page.idle_chk.isChecked(), "always_on_top": self.character_page.top_chk.isChecked(),
            "minimize_to_tray": self.character_page.tray_min_chk.isChecked(), "close_to_tray": self.character_page.tray_close_chk.isChecked(),
            "ui_lang": self.ui_lang.currentData(),
            "window_effect": self.appearance_page.window_effect.currentData(),
            "tavily_api_key": self.tavily_key.text().strip(),
            "web_depth": self.web_depth.currentData(),
            "web_fallback": self.web_fallback_chk.isChecked(),
        })
        # Qwen3-ASR enablement is controlled independently in Local Models;
        # this picker only selects the offline faster-whisper fallback.
        self.collect_provider_settings()
        self.provider_application_service.ensure_routes(s)
        primary = self.provider_application_service.find_route(s, "ollama")
        if primary and primary["model"] != s["model"]:
            self.provider_application_service.update_route(s, "ollama", model=s["model"])  # primary local route
        ocfg = s.setdefault("providers", {}).setdefault("ollama", {})
        keep_value, keep_ok = parse_keep_alive(self.keep_alive.currentText())
        if not keep_ok:
            self.add_chat("system", self.t("o_keep_bad"))
        ocfg.update({"enabled": self.route_ollama_enabled.isChecked(), "num_ctx": clamp_num_ctx(self.num_ctx.value()),
                     "num_predict": clamp_num_predict(self.num_predict.value()),
                     "keep_alive": str(keep_value), "model": s["model"], "base_url": s["ollama_url"]})
        s["providers"]["ollama"]["enabled"] = self.route_ollama_enabled.isChecked()
        try:
            save_settings(s)
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ذخیره تنظیمات", f"تنظیمات ذخیره نشدند:\n{exc}")
            return
        # Construct all routers before replacing any live Session router.
        self.provider_application_service.rebuild_session_routers(
            s, self.sessions.values(), previous_router=self.client
        )
        self.runtime_settings_application_service.apply(s, tool_agent=self.tool_agent)
        self.ollama_client = self.provider_application_service.create_ollama_client(s)
        self.refresh_route_list()
        self.set_badge("idle", self.client.preview_route())
        self.apply_runtime()
        self.apply_character_voice_settings()
        self.apply_appearance(save=False)
        self.retranslate()
        self.check_status()
        if self.mic_btn.isChecked():
            self.start_listener()
        self.add_chat("system", self.t("saved"))

    # ---- System Tray ----

    def update_tray(self):
        """Create / remove the tray icon to match the two tray settings. Safe to call repeatedly."""
        s = self.settings
        wanted = bool(s.get("minimize_to_tray") or s.get("close_to_tray")) and QSystemTrayIcon.isSystemTrayAvailable()
        tray = getattr(self, "tray", None)
        self.tray = tray                                             # always defined (no system tray = None)
        if wanted and tray is None:
            icon = QIcon(str(ROOT / "assets" / "kira_character.png"))
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip("Kira")
            menu = QMenu()
            menu.aboutToShow.connect(self.refresh_tray_menu)          # filled when it opens, so states are current
            tray.setContextMenu(menu)
            tray.activated.connect(lambda reason: self.toggle_main_window()
                                   if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
            self._tray_menu = menu                                   # keep alive
            self.tray = tray
            tray.show()
        elif not wanted and tray is not None:
            tray.hide()
            tray.deleteLater()
            self.tray = None
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(self.tray is None)         # with a tray icon the app lives on while hidden

    def refresh_tray_menu(self):
        """Rebuilt every time the menu opens, so model / web / mic states are always current."""
        menu = self._tray_menu
        menu.clear()
        menu.addAction("نمایش / مخفی کردن Kira", self.toggle_main_window)
        menu.addAction("نمایش / مخفی کردن شخصیت", self.toggle_companion)
        menu.addSeparator()
        models = menu.addMenu("تعویض مدل")
        models.setStyleSheet("QMenu { menu-scrollable: 1; }")
        manual = self.settings.get("manual_route_id", "")
        auto = models.addAction("خودکار (بر اساس اولویت)")
        auto.setCheckable(True)
        auto.setChecked(not manual)
        auto.triggered.connect(lambda checked=False: self.select_route(""))
        routes = self.client.available_routes()
        shown = routes[: self.MENU_ROUTES]
        chosen = next((r for r in routes if r["route_id"] == manual), None)
        if chosen is not None and chosen not in shown:
            shown = shown[:-1] + [chosen]
        for info in shown:
            model = info["model"] if len(info["model"]) <= 34 else info["model"][:33] + "…"
            act = models.addAction(f"{'☁' if info['kind'] == 'cloud' else '⌂'}  {info['label']} / {model}")
            act.setCheckable(True)
            act.setChecked(info["route_id"] == manual)
            act.triggered.connect(lambda checked=False, rid=info["route_id"]: self.select_route(rid))
        if not routes:
            models.addAction("هیچ Route فعالی نیست").setEnabled(False)
        web = menu.addAction("جست‌وجوی وب")
        web.setCheckable(True)
        web.setChecked(self.web_btn.isChecked())
        web.triggered.connect(lambda checked=False: self.web_btn.setChecked(not self.web_btn.isChecked()))
        mic = menu.addAction("میکروفن")
        mic.setCheckable(True)
        mic.setChecked(self.mic_btn.isChecked())
        mic.triggered.connect(self.tray_toggle_mic)
        menu.addSeparator()
        menu.addAction("خروج", self.quit_app)

    def tray_toggle_mic(self, checked=False):
        self.mic_btn.setChecked(not self.mic_btn.isChecked())
        self.toggle_mic()

    def update_bubble(self):
        """The chat bubble is shown beside Kira only while the main window is out of the way (in the tray)."""
        bubble = getattr(self, "bubble", None)
        if bubble is None:
            return
        away = getattr(self, "tray", None) is not None and (not self.isVisible() or self.isMinimized())
        if away and self.companion.isVisible() and not self._closing:
            bubble.place_beside(self.companion)
            if not bubble.isVisible():
                bubble.show()
        else:
            bubble.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        QTimer.singleShot(0, self.update_bubble)

    def hide_to_tray(self):
        self.hide()
        if not self.companion.isVisible():
            self.companion.show()                                    # she stays on the desktop while the window is hidden
        self.update_bubble()
        if getattr(self, "tray", None) is not None and not getattr(self, "_tray_hinted", False):
            self._tray_hinted = True
            self.tray.showMessage("Kira", "Kira هنوز در System Tray فعال است. برای باز کردن روی آیکون کلیک کن.",
                                  QSystemTrayIcon.Information, 3500)

    def toggle_main_window(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def quit_app(self):
        self._quitting = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == event.Type.WindowStateChange and self.isMinimized()
                and getattr(self, "tray", None) is not None and self.settings.get("minimize_to_tray")):
            QTimer.singleShot(0, self.hide_to_tray)

    def apply_runtime(self):
        s = self.settings
        self.update_tray()
        self.animator.rig.intensity = float(s["motion_strength"]) * self.animator.motion_gain
        self.animator.follow_strength = float(s["follow_strength"])
        self.animator.auto_bored = True
        self.companion.set_height(int(s["companion_height"]))
        self.companion.set_on_top(bool(s["always_on_top"]))

    def look_anchor(self):
        w = self.companion if self.companion.isVisible() else self.avatar
        return w.mapToGlobal(w.rect().center())

    def open_speech_fixes(self):
        """Opens the word dictionary (hotwords + fixes) for speech recognition; it is created with an example first."""
        try:
            path = SpeechFixes().ensure_file()
        except OSError as exc:
            self.add_chat("error", f"فایل اصلاح واژه‌ها ساخته نشد: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_sounds(self):
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SOUNDS_DIR)))

    def _form_client(self):
        keep, _ = parse_keep_alive(self.keep_alive.currentText())
        return self.provider_application_service.create_ollama_client_from_values(
            self.url.text().strip(),
            self.model.text().strip(),
            num_ctx=self.num_ctx.value(),
            keep_alive=keep,
            num_predict=self.num_predict.value(),
        )

    def _run_ollama_task(self, fn, busy_text):
        for b in (self.conn_btn, self.load_btn, self.unload_btn, self.speed_btn):
            b.setEnabled(False)
        self.conn_lbl.setText(busy_text)
        self._ollama_worker = OllamaTaskWorker(fn)
        self._ollama_worker.done.connect(self.on_ollama_task_done)
        self._ollama_worker.start()

    def on_ollama_task_done(self, ok, text):
        models = getattr(self, "_found_models", None)
        if models:
            self.model.set_models(models)
        self._found_models = None
        for b in (self.conn_btn, self.load_btn, self.unload_btn, self.speed_btn):
            b.setEnabled(True)
        self.conn_lbl.setText(("✓ " if ok else "✕ ") + text)

    def test_connection(self):
        client = self._form_client()

        def task():
            ok, text = client.describe()
            listed, models = client.status()
            self._found_models = models if listed else None
            return ok, text
        self._run_ollama_task(task, self.t("o_busy"))

    def speed_test(self):
        client = self._form_client()
        self._run_ollama_task(client.benchmark, self.t("o_busy_long"))

    def load_local_model(self):
        client = self._form_client()
        def task():
            client.preload()
            return client.describe()
        self._run_ollama_task(task, self.t("o_busy"))

    def unload_local_model(self):
        client = self._form_client()
        def task():
            client.unload()
            return client.describe()
        self._run_ollama_task(task, self.t("o_busy"))

    # ---------- chat ----------

    def check_status(self):
        st = self.client.status()
        configured = []
        for x in st:
            label = self.provider_application_service.provider_label(x["provider"], self.settings.get("providers", {}).get(x["provider"]))
            if x["provider"] != "ollama" and x["enabled"] and label not in configured:
                configured.append(label)
        local_on = any(x["provider"] == "ollama" and x["enabled"] for x in st) or \
            bool(self.settings.get("providers", {}).get("ollama", {}).get("enabled", True)) and not st
        if configured:
            self.set_status("st_cloud_active" if local_on else "st_cloud_only", providers=", ".join(configured))
            return
        if not local_on:
            self.set_status("st_local_disabled")
            return
        ok, detail = self.ollama_client.status()
        m = self.settings["model"]
        if ok:
            self.model.set_models(detail)
            self._ollama_models = list(detail)
            self.set_status("st_ok" if model_installed(detail, m) else "st_nomodel", m=m)
        else:
            self.set_status("st_off")
