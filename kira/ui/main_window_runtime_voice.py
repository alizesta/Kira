"""Voice, Gemini Live, microphone, and speaker lifecycle mixin for RuntimeController."""
from PySide6.QtCore import QTimer, Slot

from .main_window_runtime_support import (
    Listener,
    QApplication,
    save_settings,
    time,
)


class RuntimeVoiceMixin:
    """Voice input/output, Gemini Live worker, and wake-word handlers."""

    def set_voice_enabled(self, on):
        self.context.services.settings["speak_replies"] = bool(on)
        for w in (self.context.views.voice_btn, self.context.views.voice_page.speak_chk):
            w.blockSignals(True)
            w.setChecked(bool(on))
            w.blockSignals(False)
        save_settings(self.context.services.settings)
        if not on:
            self.safe_stop_speaker()

    def on_stop_clicked(self):
        if self.context.services.voice_application_service.is_speaking():
            self.context.adapters.director.event("user_interrupt")
        self.safe_stop_speaker()

    @Slot()
    def on_speech_started(self):
        self.context.adapters.director.event("tts_started")           # real audio playback has begun
        self.context.services.voice_application_service.begin_speaking()
        self.feature_controller("session").set_status("st_speaking")

    @Slot()
    def on_speech_finished(self):
        self.context.adapters.director.event("tts_stopped")           # playback ended or was stopped
        self.context.services.voice_application_service.end_speaking()
        QTimer.singleShot(500, self.unmute)
        if self.context.listener:
            self.on_listener_state("listening")
        else:
            self.feature_controller("session").set_status("st_ready")

    @Slot(float)
    def _on_kira_level(self, level):
        if self.context.listener:
            self.context.listener.kira_level = float(level)

    @Slot()
    def on_user_barge_in(self):
        """The person started talking over Kira: she stops at once, and what they say is still heard as the next message."""
        if self.context.services.voice_application_service.is_speaking():
            self.context.adapters.director.event("user_interrupt")
        self.safe_stop_speaker()

    def unmute(self):
        self.context.services.voice_application_service.unmute_if_idle()

    def _sync_voice_mode_badge(self, state=None):
        """Show the active audio transport, not just whether a microphone is open."""
        badge = getattr(self.context.views, "voice_mode_badge", None)
        if badge is None:
            return
        mode = getattr(self, "_voice_mode", "idle")
        if mode == "gemini_connecting":
            text = "در حال اتصال · Gemini Live"
            tip = "در حال برقراری WebSocket صوتی با Gemini Live."
        elif mode == "gemini_live":
            text = "در حال گوش‌دادن · Gemini Live"
            tip = "میکروفن به‌صورت زنده به Gemini Live متصل است؛ صدای پاسخ نیز مستقیم پخش می‌شود."
        elif mode in ("local_fallback", "local_primary"):
            if state == "hearing":
                text = "در حال شنیدن گفتار · STT محلی"
            elif state == "transcribing":
                text = "در حال تبدیل گفتار · STT محلی"
            elif state == "loading":
                text = "در حال آماده‌سازی STT محلی…"
            else:
                text = "در حال گوش‌دادن · STT محلی"
            local_asr_name = (
                "Shenava" if str(self.context.services.settings.get("local_voice_asr_backend") or "qwen3") == "shenava"
                else "Qwen3-ASR"
            )
            tip = (f"اتصال Gemini Live قطع شد؛ مسیر محلی {local_asr_name}/Whisper → مدل چت → Piper فعال است."
                   if mode == "local_fallback" else
                   f"میکروفن → {local_asr_name}/Whisper → مدل چت → Piper.")
        elif mode == "local_stt":
            if state == "transcribing":
                text = "در حال تبدیل گفتار · STT محلی"
            elif state == "hearing":
                text = "در حال شنیدن گفتار · STT محلی"
            elif state == "loading":
                text = "آماده‌سازی STT محلی…"
            else:
                text = "در حال گوش‌دادن · STT محلی"
            local_asr_name = (
                "Shenava" if str(self.context.services.settings.get("local_voice_asr_backend") or "qwen3") == "shenava"
                else "Qwen3-ASR"
            )
            tip = f"مسیر فعال: میکروفن → {local_asr_name}/Whisper → مدل چت → Piper."
        elif self.context.views.mic_btn.isChecked():
            text = "میکروفن فعال · STT محلی"
            tip = "ورودی گفتار از مسیر محلی STT استفاده می‌کند."
        else:
            text = "میکروفن خاموش"
            tip = "میکروفن غیرفعال است."
        badge.setText(text)
        badge.setProperty("voiceMode", mode)
        badge.setToolTip(tip)

    def _sync_live_toggle(self, enabled):
        page = getattr(self.context.views, "voice_page", None)
        toggle = getattr(page, "live_toggle", None) if page is not None else None
        if toggle is not None:
            previous = toggle.blockSignals(True)
            toggle.setChecked(bool(enabled))
            toggle.blockSignals(previous)
            if enabled:
                toggle.setText("توقف مکالمه صوتی")
            else:
                toggle.setText(
                    "شروع مکالمه محلی"
                    if page is not None and page.voice_engine.currentData() == "local"
                    else "شروع مکالمه صوتی Gemini"
                )
        self._sync_voice_mode_badge()

    def _set_mic_checked(self, enabled):
        mic = self.context.views.mic_btn
        previous = mic.blockSignals(True)
        mic.setChecked(bool(enabled))
        mic.blockSignals(previous)

    def _selected_gemini_key(self):
        from ..gemini_live import resolve_google_api_key
        page = self.context.views.voice_page
        if not str(page.gemini_provider.currentData() or "").strip():
            page.refresh_gemini_providers(self.context.services.settings)
        provider_id = str(page.gemini_provider.currentData() or "").strip()
        self.context.services.settings["gemini_live_provider"] = provider_id
        self.save_now()
        return resolve_google_api_key(self.context.services.settings, provider_id)

    def _start_local_voice_fallback(self, reason="", *, fallback=True):
        """Start the existing local STT/chat/Piper path as fallback or selected primary."""
        if not getattr(self, "_voice_session_requested", False):
            return
        if not bool(self.context.services.settings.get("realtime_asr_enabled", True)):
            self._voice_session_requested = False
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
            self.feature_controller("session").on_voice_error(
                "تشخیص زنده‌ی محلی (Real-time ASR) خاموش است؛ برای تست مدل از گزینه «تست شنوا با فایل WAV» استفاده کن."
            )
            return
        fallback_enabled = self.context.views.voice_page.local_fallback_chk.isChecked()
        if fallback and not fallback_enabled:
            self._voice_session_requested = False
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
            self.feature_controller("session").on_voice_error(
                "اتصال Gemini Live برقرار نشد و مسیر پشتیبان محلی غیرفعال است."
                + (f" جزئیات: {reason}" if reason else "")
            )
            return
        self._voice_mode = "local_fallback" if fallback else "local_primary"
        self._set_mic_checked(True)
        try:
            self.start_listener()
            self._sync_live_toggle(True)
            self._sync_voice_mode_badge()
            message = ("اتصال Gemini Live قطع شد؛ مکالمه به STT/TTS محلی منتقل شد."
                       if fallback else "مکالمه صوتی محلی فعال شد.")
            if reason and fallback:
                message += f" ({reason})"
            self.feature_controller("session").add_chat("system", "🎙️ " + message)
        except Exception as exc:
            self._voice_session_requested = False
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
            self.feature_controller("session").on_voice_error(
                f"شروع مسیر پشتیبان محلی ناموفق بود: {type(exc).__name__}: {exc}"
            )

    def _on_gemini_state(self, state):
        worker = self.sender()
        if worker is not None and worker is not getattr(self, "_gemini_worker", None):
            return
        if state == "gemini_connecting":
            self._voice_mode = "gemini_connecting"
        elif state == "gemini_live":
            self._voice_mode = "gemini_live"
        self._sync_voice_mode_badge()
        self.update_engine_label()

    def _on_gemini_transcript(self, role, text):
        worker = self.sender()
        if worker is not None and worker is not getattr(self, "_gemini_worker", None):
            return
        value = str(text or "").strip()
        if value and not self.context.state._closing:
            self.feature_controller("session").add_chat(
                "user" if role == "user" else "assistant", value
            )

    def _on_gemini_failed(self, message):
        worker = self.sender()
        if worker is not None and worker is not getattr(self, "_gemini_worker", None):
            return
        self._gemini_failure = str(message or "اتصال Gemini Live قطع شد.")
        self._voice_mode = "gemini_connecting"
        self._sync_voice_mode_badge()

    def _on_gemini_worker_finished(self):
        worker = self.sender()
        if worker is None:
            return
        if worker is not getattr(self, "_gemini_worker", None):
            worker.deleteLater()
            return
        self._gemini_worker = None
        try:
            worker.deleteLater()
        except RuntimeError:
            pass
        failure, self._gemini_failure = getattr(self, "_gemini_failure", ""), ""
        if self.context.state._closing:
            return
        if self._voice_session_requested and failure:
            self._start_local_voice_fallback(failure)
        elif not self._voice_session_requested:
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
        elif self._voice_session_requested and not failure:
            self._start_local_voice_fallback("نشست Gemini بدون خطای مشخص بسته شد")

    def _launch_gemini_live_worker(self):
        if not self._voice_session_requested or self.context.state._closing:
            return
        page = self.context.views.voice_page
        try:
            from ..gemini_live import GeminiLiveWorker
            api_key = self._selected_gemini_key()
            if not api_key:
                self._start_local_voice_fallback("کلید معتبر Google AI در بخش اتصالات انتخاب نشده است")
                return
            worker = GeminiLiveWorker(
                api_key=api_key,
                model=page.gemini_model.currentText().strip() or "gemini-3.8-live",
                settings=self.context.services.settings,
                system_instruction=(
                    f"You are {self.context.services.character_service.display_name(self.context.services.settings)}. "
                    "You are a warm, natural voice companion. Speak directly and conversationally in the user's language. "
                    "Do not describe yourself as a text model or use local text-to-speech."
                ),
                parent=self.window,
            )
            self._gemini_worker = worker
            worker.state_changed.connect(self._on_gemini_state)
            worker.transcript.connect(self._on_gemini_transcript)
            worker.failed.connect(self._on_gemini_failed)
            worker.finished.connect(self._on_gemini_worker_finished)
            worker.start()
        except Exception as exc:
            self._gemini_failure = f"{type(exc).__name__}: {exc}"
            self._start_local_voice_fallback(self._gemini_failure)

    def set_live_listening(self, enabled):
        """Gemini Live is primary; local STT + Piper is only the configured fallback."""
        if self.context.state._closing:
            self._voice_session_requested = False
            self._pending_gemini_start = False
            self._sync_live_toggle(False)
            return
        if not enabled:
            self._voice_session_requested = False
            self._pending_gemini_start = False
            worker = getattr(self, "_gemini_worker", None)
            if worker is not None and worker.isRunning():
                worker.stop()
            if getattr(self, "_voice_mode", "") in ("local_fallback", "local_primary", "local_stt"):
                self.stop_listener()
            wake = self.context.views.wake_btn
            if wake.isChecked():
                previous = wake.blockSignals(True)
                wake.setChecked(False)
                wake.blockSignals(previous)
                self.context.views.wake_timer.stop()
                self.context.state.awake = False
                self.context.adapters.animator.set_sleeping(False)
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
            self.update_engine_label()
            return

        self._voice_session_requested = True
        wake = self.context.views.wake_btn
        if wake.isChecked():
            previous = wake.blockSignals(True)
            wake.setChecked(False)
            wake.blockSignals(previous)
            self.context.views.wake_timer.stop()
            self.context.state.awake = False
            self.context.adapters.animator.set_sleeping(False)
        self.set_voice_enabled(True)
        self.feature_controller("voice_settings").collect_voice_settings()
        self.save_now()

        page = self.context.views.voice_page
        selected_engine = str(page.voice_engine.currentData() or "gemini_live")
        if selected_engine == "local" and not bool(
            self.context.services.settings.get("realtime_asr_enabled", True)
        ):
            self._voice_session_requested = False
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
            self.feature_controller("session").on_voice_error(
                "Real-time ASR خاموش است؛ ابتدا آن را در تنظیمات میکروفن روشن کن یا از تست فایل WAV استفاده کن."
            )
            return
        if selected_engine == "local":
            self._start_local_voice_fallback(fallback=False)
            return

        if getattr(self, "_gemini_worker", None) is not None:
            if self._gemini_worker.isRunning():
                self._sync_live_toggle(True)
                return
            self._gemini_worker = None

        # Stop any local listener first. Its device handle must be released before
        # the Gemini worker opens its own full-duplex PortAudio streams.
        service = self.context.services.voice_application_service
        if service.listener is not None:
            self.stop_listener()
        self._set_mic_checked(True)
        self._voice_mode = "gemini_connecting"
        self._gemini_failure = ""
        self._sync_live_toggle(True)
        self._sync_voice_mode_badge()
        stopping = service.stopping_listener
        if stopping is not None and stopping.is_running():
            # A queued local-listener restart must not race the Gemini audio streams.
            service.restart_after_stop = False
            self._pending_gemini_start = True
            return
        self._pending_gemini_start = False
        self._launch_gemini_live_worker()

    def set_realtime_asr(self, enabled):
        """Enable/disable only local microphone ASR; Gemini Live and WAV tests are independent."""
        value = bool(enabled)
        self.context.services.settings["realtime_asr_enabled"] = value
        self.save_now()
        if value:
            return
        if getattr(self, "_voice_mode", "") in ("local_fallback", "local_primary", "local_stt"):
            self._voice_session_requested = False
            self._pending_gemini_start = False
            self.stop_listener()
            self.feature_controller("voice_settings").stop_local_stt_test(update_ui=False)
            self._voice_mode = "idle"
            self._set_mic_checked(False)
            self._sync_live_toggle(False)
            if self.context.views.wake_btn.isChecked():
                wake = self.context.views.wake_btn
                previous = wake.blockSignals(True)
                wake.setChecked(False)
                wake.blockSignals(previous)
                self.context.views.wake_timer.stop()
                self.context.state.awake = False
                self.context.adapters.animator.set_sleeping(False)
            self._sync_voice_mode_badge()
            self.feature_controller("session").add_chat(
                "system",
                "Real-time ASR محلی خاموش شد؛ تست آفلاین فایل WAV همچنان قابل استفاده است."
            )

    def toggle_mic(self, enabled=None):
        """The home microphone button starts/stops the configured primary voice engine."""
        if enabled is None:
            enabled = self.context.views.mic_btn.isChecked()
        self.set_live_listening(bool(enabled))

    def _create_voice_listener(self):
        return Listener(
            self.context.services.settings["whisper_model"],
            self.context.services.settings["stt_language"],
            self,
            sensitivity=self.context.services.settings.get("mic_sensitivity", 100),
            barge_in=self.context.services.settings.get("barge_in", True),
            settings=self.context.services.settings,
        )

    def start_listener(self):
        if not bool(self.context.services.settings.get("realtime_asr_enabled", True)):
            return
        self.context.services.voice_application_service.start_recording()

    def stop_listener(self):
        self.context.services.voice_application_service.stop_recording()
        self.feature_controller("session").set_status("st_ready")
        self.update_engine_label()

    @Slot(object, bool, bool)
    def _on_voice_listener_finished(self, listener, was_current, restart_requested):
        if was_current:
            # A local listener may be closing specifically to hand the audio
            # device to Gemini Live. Do not let its finished signal undo the
            # user's still-active microphone request or the pending handoff.
            pending_gemini = bool(
                getattr(self, "_pending_gemini_start", False)
                and getattr(self, "_voice_session_requested", False)
            )
            keep_listening = pending_gemini or (
                restart_requested and self.context.views.mic_btn.isChecked()
            )
            if not keep_listening and not restart_requested and getattr(self, "_voice_mode", "") in ("local_fallback", "local_primary"):
                self._voice_session_requested = False
                self._voice_mode = "idle"
            self._set_mic_checked(keep_listening)
            self._sync_live_toggle(keep_listening)
            self._sync_voice_mode_badge()
        self.update_engine_label()
        if getattr(self, "_pending_gemini_start", False) and self._voice_session_requested and not self.context.state._closing:
            self._pending_gemini_start = False
            QTimer.singleShot(0, self._launch_gemini_live_worker)
        if self.context.state._closing:
            return
        if restart_requested and self.context.views.mic_btn.isChecked():
            QTimer.singleShot(0, self.start_listener)
        elif was_current:
            self.feature_controller("session").set_status("st_ready")

    @Slot(str)
    def on_listener_error(self, msg):
        if getattr(self, "_voice_mode", "") in ("local_fallback", "local_primary"):
            self._voice_session_requested = False
            self._voice_mode = "idle"
        self.feature_controller("session").add_chat("error", msg)
        self.context.views.mic_btn.setChecked(False)
        self._sync_live_toggle(False)
        self._sync_voice_mode_badge()
        if self.context.views.wake_btn.isChecked():
            self.context.views.wake_btn.setChecked(False)
            self.context.adapters.animator.set_sleeping(False)
            self.context.views.wake_timer.stop()
        # Keep the worker owned until its stream has closed; stop() is non-blocking.
        self.stop_listener()

    @Slot(str)
    def on_listener_state(self, state):
        if getattr(self, "_voice_mode", "") not in ("local_fallback", "local_primary", "gemini_live", "gemini_connecting"):
            self._voice_mode = "local_stt"
        self._sync_voice_mode_badge(state)
        if state == "listening":
            self.update_engine_label()
            self.feature_controller("session").set_status("st_sleeping" if (self.context.views.wake_btn.isChecked() and not self.context.state.awake) else "st_listening")
        else:
            self.feature_controller("session").set_status({"loading": "st_loading", "hearing": "st_hearing", "transcribing": "st_transcribing"}.get(state, "st_ready"))

    def update_engine_label(self):
        mode = getattr(self, "_voice_mode", "idle")
        if mode == "gemini_connecting":
            self.context.views.voice_page.engine_lbl.setText("Gemini Live · در حال اتصال")
            return
        if mode == "gemini_live":
            self.context.views.voice_page.engine_lbl.setText("Gemini Live · Cloud")
            return
        eng = getattr(self.context.listener, "engine", None) if self.context.listener else None
        via = getattr(self.context.listener, "via", "") if self.context.listener else ""
        if via == "local:shenava":
            label = "Shenava Koochik INT8 · Local"
        elif via == "local:qwen3-asr":
            label = "Qwen3-ASR · Local"
        elif via == "local:whisper" or eng == "whisper":
            label = "Whisper · Local"
        elif self.context.listener is not None and self.context.listener.isRunning():
            label = "STT محلی"
        else:
            label = "—"
        self.context.views.voice_page.engine_lbl.setText(label)

    def toggle_wake(self):
        if (
            self.context.views.wake_btn.isChecked()
            and not bool(self.context.services.settings.get("realtime_asr_enabled", True))
        ):
            wake = self.context.views.wake_btn
            previous = wake.blockSignals(True)
            wake.setChecked(False)
            wake.blockSignals(previous)
            self.feature_controller("session").on_voice_error(
                "برای حالت بیدارباش، Real-time ASR باید روشن باشد."
            )
            return
        if self.context.views.wake_btn.isChecked():
            if not self.context.views.mic_btn.isChecked():
                self.context.views.mic_btn.setChecked(True)
                self.start_listener()
            self.go_sleep()
        else:
            self.context.views.wake_timer.stop()
            self.context.state.awake = False
            self.context.adapters.animator.set_sleeping(False)

    def go_sleep(self):
        self.context.views.wake_timer.stop()
        self.context.state.awake = False
        if self.context.views.wake_btn.isChecked():
            self.context.adapters.animator.set_sleeping(True)
            self.on_listener_state("listening")

    def wake_up(self):
        self.context.state.awake = True
        self.context.adapters.animator.set_sleeping(False)
        self.context.adapters.animator.set_expression("happy", hold=2)
        self.context.views.wake_timer.start(int(self.context.services.settings["wake_timeout"]) * 1000)

    @Slot(str)
    def on_heard(self, text):
        self.context.adapters.animator.touch()
        decision = self.context.services.voice_application_service.interpret_transcript(
            text,
            wake_enabled=self.context.views.wake_btn.isChecked(),
            awake=self.context.state.awake,
        )
        if decision.action == "ignore":
            return
        if decision.action == "wake_only":
            self.wake_up()
            self.reply_local(self.feature_controller("session").t("yes"))
            return
        if decision.action == "wake_submit":
            self.wake_up()
            text = decision.text
        elif decision.action == "sleep":
            self.feature_controller("session").add_chat("user", text)
            self.go_sleep()
            self.say(self.feature_controller("session").t("night"))
            return
        elif decision.action == "stop":
            if self.context.views.wake_btn.isChecked() and self.context.state.awake:
                self.context.views.wake_timer.start(int(self.context.services.settings["wake_timeout"]) * 1000)
            self.safe_stop_speaker()
            return
        elif self.context.views.wake_btn.isChecked() and self.context.state.awake:
            self.context.views.wake_timer.start(int(self.context.services.settings["wake_timeout"]) * 1000)
        self.context.session._voice_next = True
        self.feature_controller("chat").submit(text)

    # ---------- companion window ----------
