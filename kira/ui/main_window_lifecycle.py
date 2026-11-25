"""Window lifecycle feature controller."""
from PySide6.QtCore import Slot
from .companion_session import session_marker
from .main_window_lifecycle_support import (
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


class LifecycleController(WindowFeatureController):
    def showEvent(self, event):
        self.qt_super_event("showEvent", event)
        winfx.apply_effect(self.window.winId(), self.context.state._effect)
        QTimer.singleShot(0, self.update_bubble)

    def update_window_effect(self, wanted):
        """Settings changed: restyle now. Switching glass on/off at runtime needs a restart to be fully clean."""
        new = winfx.active_effect(wanted)
        old, self.context.state._effect = self.context.state._effect, new
        QApplication.instance().setStyleSheet(build_style(new, self.context.services.settings.get("appearance", {})))
        self.feature_controller("session").apply_chat_theme()
        winfx.apply_effect(self.window.winId(), new)
        if (old == "off") != (new == "off"):
            self.feature_controller("session").add_chat("system", "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.")

    def apply_settings(self):
        ensure_settings_tab = getattr(self.window, "_ensure_settings_tab", None)
        if callable(ensure_settings_tab):
            for index in (1, 2, 3, 4, 5):
                if not ensure_settings_tab(index):
                    QMessageBox.warning(
                        self.window,
                        "تنظیمات",
                        "یکی از صفحات تنظیمات بارگذاری نشد؛ تغییرات ذخیره نشدند.",
                    )
                    return
        s = self.context.services.settings
        s.update({
            "assistant_name": self.context.views.name.text().strip() or "Kira",
            "model": self.context.views.model.text().strip() or self.context.services.settings.get("model"),
            "ollama_url": self.context.views.url.text().strip() or "http://localhost:11434",
            "persona": self.context.views.persona.toPlainText().strip(), "active_modes": self.context.views.modes_chk.isChecked(),
            "temperature": float(self.context.views.temp.currentText()),
            "speak_replies": self.context.views.voice_page.speak_chk.isChecked(), "stream_speech": self.context.views.voice_page.stream_chk.isChecked(),
            "voice_rate": self.context.views.voice_page.rate.value(),
            "voice_volume": self.context.views.voice_page.volume.value() / 100.0,
            "output_device": self.context.views.voice_page.out_device.currentData() or "", "mic_device": self.context.views.voice_page.mic_device.currentData() or "",
            "mic_gain": self.context.views.voice_page.mic_gain.value(),
            "stt_language": self.context.views.voice_page.stt_lang.currentText(), "whisper_model": self.context.views.voice_page.whisper.currentText().strip() or "small",
            "wake_timeout": self.context.views.voice_page.wake_timeout.value(),
            "mic_sensitivity": self.context.views.voice_page.mic_sens.value(), "barge_in": self.context.views.voice_page.barge_chk.isChecked(),
            "companion_height": self.context.views.character_page.size_sl.value(),
            "follow_strength": self.context.views.character_page.follow_sl.value() / 100.0,
            "motion_strength": self.context.views.character_page.motion_sl.value() / 100.0,
            "click_reactions": self.context.views.character_page.react_chk.isChecked(), "idle_talk": self.context.views.character_page.idle_chk.isChecked(), "always_on_top": self.context.views.character_page.top_chk.isChecked(),
            "companion_perch": self.context.views.character_page.perch_chk.isChecked(), "companion_hang": self.context.views.character_page.hang_chk.isChecked(),
            "auto_dance": self.context.views.character_page.dance_chk.isChecked(),
            "minimize_to_tray": self.context.views.character_page.tray_min_chk.isChecked(), "close_to_tray": self.context.views.character_page.tray_close_chk.isChecked(),
            "ui_lang": self.context.views.ui_lang.currentData(),
            "window_effect": self.context.views.appearance_page.window_effect.currentData(),
            "tavily_api_key": self.context.views.tavily_key.text().strip(),
            "web_depth": self.context.views.web_depth.currentData(),
            "web_fallback": self.context.views.web_fallback_chk.isChecked(),
        })
        # Qwen3-ASR enablement is controlled independently in Local Models;
        # this picker only selects the offline faster-whisper fallback.
        self.feature_controller("provider_settings").collect_provider_settings()
        self.context.services.provider_application_service.ensure_routes(s)
        primary = self.context.services.provider_application_service.find_route(s, "ollama")
        if primary and primary["model"] != s["model"]:
            self.context.services.provider_application_service.update_route(s, "ollama", model=s["model"])  # primary local route
        ocfg = s.setdefault("providers", {}).setdefault("ollama", {})
        keep_value, keep_ok = parse_keep_alive(self.context.views.keep_alive.currentText())
        if not keep_ok:
            self.feature_controller("session").add_chat("system", self.feature_controller("session").t("o_keep_bad"))
        ocfg.update({"enabled": self.context.views.route_ollama_enabled.isChecked(), "num_ctx": clamp_num_ctx(self.context.views.num_ctx.value()),
                     "num_predict": clamp_num_predict(self.context.views.num_predict.value()),
                     "keep_alive": str(keep_value), "model": s["model"], "base_url": s["ollama_url"]})
        s["providers"]["ollama"]["enabled"] = self.context.views.route_ollama_enabled.isChecked()
        try:
            save_settings(s)
        except Exception as exc:
            QMessageBox.critical(self.window, "خطا در ذخیره تنظیمات", f"تنظیمات ذخیره نشدند:\n{exc}")
            return
        # Build replacements before touching live routers. Vision keeps its own
        # request/cancellation channel, and an old analysis is cancelled against
        # that channel only.
        provider_service = self.context.services.provider_application_service
        previous_vision_router = self.context.services.vision_router
        replacement_vision_router = provider_service.create_isolated_router(
            s, previous_router=previous_vision_router
        )
        provider_service.rebuild_session_routers(
            s, self.context.state.sessions.values(), previous_router=self.context.session.client
        )
        self.feature_controller("attachments_vision")._cancel_vision_worker()
        previous_vision_router.cancel()
        self.context.services.vision_router = replacement_vision_router
        self.context.services.runtime_settings_application_service.apply(s, tool_agent=self.context.services.tool_agent)
        self.context.services.ollama_client = self.context.services.provider_application_service.create_ollama_client(s)
        self.feature_controller("provider_settings").refresh_route_list()
        self.feature_controller("runtime").set_badge("idle", self.context.session.client.preview_route())
        self.apply_runtime()
        self.context.adapters.appearance_runtime.apply_character_voice_settings()
        self.context.adapters.appearance_runtime.apply_appearance(save=False)
        self.feature_controller("session").retranslate()
        self.check_status()
        if self.context.views.mic_btn.isChecked():
            self.feature_controller("runtime").start_listener()
        self.feature_controller("session").add_chat("system", self.feature_controller("session").t("saved"))

    # ---- System Tray ----

    def update_tray(self):
        """Create / remove the tray icon to match the two tray settings. Safe to call repeatedly."""
        s = self.context.services.settings
        wanted = bool(s.get("minimize_to_tray") or s.get("close_to_tray")) and QSystemTrayIcon.isSystemTrayAvailable()
        tray = getattr(self.context.views, "tray", None)
        self.context.views.tray = tray                                             # always defined (no system tray = None)
        if wanted and tray is None:
            icon = QIcon(str(ROOT / "assets" / "kira_icon.png"))
            tray = QSystemTrayIcon(icon, self.window)
            tray.setToolTip("Kira")
            menu = QMenu()
            menu.aboutToShow.connect(self.refresh_tray_menu)          # filled when it opens, so states are current
            tray.setContextMenu(menu)
            tray.activated.connect(lambda reason: self.toggle_main_window()
                                   if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
            self._tray_menu = menu                                   # keep alive
            self.context.views.tray = tray
            tray.show()
        elif not wanted and tray is not None:
            tray.hide()
            tray.deleteLater()
            self.context.views.tray = None
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(self.context.views.tray is None)         # with a tray icon the app lives on while hidden

    def _tray_button(self, name):
        """Chat-composer button by name; None when the view is not available."""
        try:
            return getattr(self.context.views, name, None)
        except Exception:                                          # noqa: BLE001 - view access is allow-listed per controller
            return None

    def refresh_tray_menu(self):
        """Rebuilt every time the menu opens, so model / web / mic states are always current.
        Each section is guarded: one failing section can no longer cut the rest (or "Exit") off the menu."""
        menu = self._tray_menu
        menu.clear()
        menu.addAction("نمایش / مخفی کردن Kira", self.toggle_main_window)
        menu.addAction("نمایش / مخفی کردن شخصیت", self.feature_controller("runtime").toggle_companion)
        menu.addSeparator()
        try:
            models = menu.addMenu("تعویض مدل")
            models.setStyleSheet("QMenu { menu-scrollable: 1; }")
            manual = self.context.services.settings.get("manual_route_id", "")
            auto = models.addAction("خودکار (بر اساس اولویت)")
            auto.setCheckable(True)
            auto.setChecked(not manual)
            auto.triggered.connect(lambda checked=False: self.feature_controller("runtime").select_route(""))
            routes = self.context.session.client.available_routes()
            # Keep tray selection in sync with the chat picker: list all routes
            # using provider/model names, without a removed UI-only limit or truncation.
            for info in routes:
                provider = str(info.get("label") or info.get("provider") or "Provider").strip()
                model = str(info.get("model") or "").strip()
                label = f"{provider} / {model}" if model else provider
                act = models.addAction(label)
                act.setCheckable(True)
                act.setChecked(info["route_id"] == manual)
                act.triggered.connect(lambda checked=False, rid=info["route_id"]: self.feature_controller("runtime").select_route(rid))
            if not routes:
                models.addAction("هیچ Route فعالی نیست").setEnabled(False)
        except Exception:                                          # noqa: BLE001
            pass
        web_btn = self._tray_button("web_btn")
        if web_btn is not None:
            web = menu.addAction("جست‌وجوی وب")
            web.setCheckable(True)
            web.setChecked(web_btn.isChecked())
            web.triggered.connect(lambda checked=False, b=web_btn: b.setChecked(not b.isChecked()))
        mic_btn = self._tray_button("mic_btn")
        if mic_btn is not None:
            mic = menu.addAction("میکروفن")
            mic.setCheckable(True)
            mic.setChecked(mic_btn.isChecked())
            mic.triggered.connect(self.tray_toggle_mic)
        menu.addSeparator()
        exit_action = menu.addAction("خروج")
        # Defer shutdown until the native tray menu has finished closing.
        exit_action.triggered.connect(lambda checked=False: QTimer.singleShot(100, self.quit_app))

    def tray_toggle_mic(self, checked=False):
        self.context.views.mic_btn.setChecked(not self.context.views.mic_btn.isChecked())
        self.feature_controller("runtime").toggle_mic()

    def update_bubble(self):
        """Show a short latest-message preview beside Kira while the main window is in the tray."""
        bubble = getattr(self.context.adapters, "bubble", None)
        if bubble is None:
            return
        companion = self.context.adapters.companion
        if not getattr(companion, "_bubble_chat_button_connected", False):
            companion.chat_requested.connect(lambda b=bubble, c=companion: b.open_composer(c))
            companion._bubble_chat_button_connected = True
        away = getattr(self.context.views, "tray", None) is not None and (not self.window.isVisible() or self.window.isMinimized())
        if away and companion.isVisible() and not self.context.state._closing:
            session = self.context.session
            marker = session_marker(session)
            if getattr(bubble, "session_id", None) != marker:
                try:
                    self.feature_controller("session").sync_bubble_history(bubble)
                except Exception:
                    # The companion must remain usable if history restoration is temporarily unavailable.
                    pass
            if not bubble.isVisible():
                bubble.show_preview(companion)
            else:
                bubble.follow_companion(companion)
        else:
            bubble.disable_preview()

    def hideEvent(self, event):
        self.qt_super_event("hideEvent", event)
        QTimer.singleShot(0, self.update_bubble)

    def hide_to_tray(self):
        self.window.hide()
        if not self.context.adapters.companion.isVisible():
            self.context.adapters.companion.show()                                    # she stays on the desktop while the window is hidden
        self.update_bubble()
        if getattr(self.context.views, "tray", None) is not None and not getattr(self, "_tray_hinted", False):
            self._tray_hinted = True
            self.context.views.tray.showMessage("Kira", "Kira هنوز در System Tray فعال است. برای باز کردن روی آیکون کلیک کن.",
                                  QSystemTrayIcon.Information, 3500)

    def toggle_main_window(self):
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
        else:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def quit_app(self):
        # closeEvent owns the shutdown protocol. Keep the tray icon and Qt's
        # last-window policy unchanged until closeEvent has accepted shutdown.
        self.context.state._quitting = True
        self.window.close()

    def changeEvent(self, event):
        self.qt_super_event("changeEvent", event)
        if (event.type() == event.Type.WindowStateChange and self.window.isMinimized()
                and getattr(self.context.views, "tray", None) is not None and self.context.services.settings.get("minimize_to_tray")):
            QTimer.singleShot(0, self.hide_to_tray)

    def apply_runtime(self):
        s = self.context.services.settings
        self.update_tray()
        self.context.adapters.animator.rig.intensity = float(s["motion_strength"]) * self.context.adapters.animator.motion_gain
        self.context.adapters.animator.follow_strength = float(s["follow_strength"])
        self.context.adapters.animator.auto_bored = True
        self.context.adapters.companion.set_height(int(s["companion_height"]))
        self.context.adapters.companion.set_on_top(bool(s["always_on_top"]))

    def look_anchor(self):
        w = self.context.adapters.companion if self.context.adapters.companion.isVisible() else self.context.views.avatar
        return w.mapToGlobal(w.rect().center())

    def open_speech_fixes(self):
        """Opens the word dictionary (hotwords + fixes) for speech recognition; it is created with an example first."""
        try:
            path = SpeechFixes().ensure_file()
        except OSError as exc:
            self.feature_controller("session").add_chat("error", f"فایل اصلاح واژه‌ها ساخته نشد: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_sounds(self):
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SOUNDS_DIR)))

    def _form_client(self):
        keep, _ = parse_keep_alive(self.context.views.keep_alive.currentText())
        return self.context.services.provider_application_service.create_ollama_client_from_values(
            self.context.views.url.text().strip(),
            self.context.views.model.text().strip(),
            num_ctx=self.context.views.num_ctx.value(),
            keep_alive=keep,
            num_predict=self.context.views.num_predict.value(),
        )

    def _run_ollama_task(self, fn, busy_text):
        from .workers import OllamaTaskWorker

        for b in (self.context.views.conn_btn, self.context.views.load_btn, self.context.views.unload_btn, self.context.views.speed_btn):
            b.setEnabled(False)
        self.context.views.conn_lbl.setText(busy_text)
        self.context.state._ollama_worker = OllamaTaskWorker(fn)
        self.context.state._ollama_worker.done.connect(self.on_ollama_task_done)
        self.context.state._ollama_worker.start()

    @Slot(bool, str)
    def on_ollama_task_done(self, ok, text):
        models = getattr(self, "_found_models", None)
        if models:
            self.context.views.model.set_models(models)
        self._found_models = None
        for b in (self.context.views.conn_btn, self.context.views.load_btn, self.context.views.unload_btn, self.context.views.speed_btn):
            b.setEnabled(True)
        self.context.views.conn_lbl.setText(("✓ " if ok else "✕ ") + text)

    def test_connection(self):
        client = self._form_client()

        def task():
            ok, text = client.describe()
            listed, models = client.status()
            self._found_models = models if listed else None
            return ok, text
        self._run_ollama_task(task, self.feature_controller("session").t("o_busy"))

    def speed_test(self):
        client = self._form_client()
        self._run_ollama_task(client.benchmark, self.feature_controller("session").t("o_busy_long"))

    def load_local_model(self):
        client = self._form_client()
        def task():
            client.preload()
            return client.describe()
        self._run_ollama_task(task, self.feature_controller("session").t("o_busy"))

    def unload_local_model(self):
        client = self._form_client()
        def task():
            client.unload()
            return client.describe()
        self._run_ollama_task(task, self.feature_controller("session").t("o_busy"))

    # ---------- chat ----------

    def check_status(self):
        st = self.context.session.client.status()
        configured = []
        for x in st:
            label = self.context.services.provider_application_service.provider_label(x["provider"], self.context.services.settings.get("providers", {}).get(x["provider"]))
            if x["provider"] != "ollama" and x["enabled"] and label not in configured:
                configured.append(label)
        local_on = any(x["provider"] == "ollama" and x["enabled"] for x in st) or \
            bool(self.context.services.settings.get("providers", {}).get("ollama", {}).get("enabled", True)) and not st
        if configured:
            self.feature_controller("session").set_status("st_cloud_active" if local_on else "st_cloud_only", providers=", ".join(configured))
            return
        if not local_on:
            self.feature_controller("session").set_status("st_local_disabled")
            return
        ok, detail = self.context.services.ollama_client.status()
        m = self.context.services.settings["model"]
        if ok:
            model_widget = getattr(self.context.views, "model", None)
            if model_widget is not None:
                model_widget.set_models(detail)
            self.context.state._ollama_models = list(detail)
            self.feature_controller("session").set_status("st_ok" if model_installed(detail, m) else "st_nomodel", m=m)
        else:
            self.feature_controller("session").set_status("st_off")


# Backward-compatible import name for callers migrating from mixin composition.
LifecycleMixin = LifecycleController
