"""Attachment and vision feature controller for the desktop window."""
from PySide6.QtCore import Slot
from ..request_trace import vision_trace
from ..vision_pipeline import CAPTURE_DETAIL_JPEG_QUALITY, wants_detail_capture
from ..perception.events import PerceptionEvent
from ..chat.attachment_content import format_desktop_context
from .main_window_attachments_vision_support import (
    AttachmentTile,
    CAPTURE_JPEG_QUALITY,
    GameAudioListener,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QSystemTrayIcon,
    QTimer,
    VisionAnalysisWorker,
    att,
    front_only,
    save_settings,
    time,
)


from .window_feature_controller import WindowFeatureController



def _game_fields(game):
    """Scalar window identity for the vision trace (exe and title only)."""
    if not game:
        return {"exe": None, "title": None}
    return {"exe": str(game.get("exe") or "")[:80]}


def _service_value(service, name):
    """Read data attributes from either a concrete service or its lazy proxy."""
    value_reader = getattr(service, "value", None)
    if callable(value_reader):
        return value_reader(name)
    return getattr(service, name)


class AttachmentsVisionController(WindowFeatureController):
    @staticmethod
    def _vision_session_id(session):
        if session is None:
            return ""
        return str(
            getattr(session, "session_id", None)
            or getattr(session, "cid", None)
            or id(session)
        )

    def _vision_runtime(self):
        provider = getattr(self.context.services, "vision_runtime_provider", None)
        if provider is None:
            raise RuntimeError("Vision runtime provider was not composed by the application root")
        return provider.get()

    def _frame_codec(self):
        return self._vision_runtime().frame_codec

    def _capture_service(self):
        return self._vision_runtime().capture_service

    def _analysis_coordinator(self):
        return self._vision_runtime().analysis_coordinator

    def _live_transport(self):
        return self._vision_runtime().live_transport

    def _live_session_manager(self):
        return self._vision_runtime().live_session_manager

    def _trace_capture_state(self, game, frame, source=None):
        """Deduplicate capture diagnostics within this controller, never across windows."""
        state = (bool(game), frame is not None and not frame.isNull(), source)
        if getattr(self, "_last_capture_state", None) == state:
            return
        self._last_capture_state = state
        vision_trace(
            "capture_state", game_detected=state[0], frame_ok=state[1], source=source,
            **_game_fields(game),
        )

    def _cancel_perception_worker(self):
        controller = getattr(
            self.context.adapters, "perception_worker_controller", None
        )
        if controller is not None:
            controller.cancel()
    def _vision_interval_ms(self):
        base = max(
            250, int(_service_value(self.context.services.vision_application_service, "policy").interval_seconds * 1000)
        )
        return 1000 if getattr(self, "_live_video_active", False) else base

    def _live_budget_values(self):
        """Return the effective Live frame budget from the session manager."""
        return self._live_session_manager().budget_values()

    def live_video_budget(self):
        """Return the effective minimum interval and rolling per-minute frame cap."""
        return self._live_budget_values()

    def _live_policy(self):
        return self._live_session_manager().policy

    def _live_selector(self):
        return self._live_session_manager().selector

    def set_live_frame_budget(self, interval_seconds, frames_per_minute):
        """Persist the Live frame budget and apply it to the active selector."""
        settings = self.context.services.settings
        settings["eye_live_min_interval_seconds"] = float(interval_seconds)
        settings["eye_live_max_frames_per_minute"] = int(frames_per_minute)
        save_settings(settings)
        self._live_session_manager().refresh_policy()

    def set_eye_mode_profile(self, profile):
        """Persist the manually chosen game profile. It never turns Eye Mode on by itself."""
        service = self.context.services.game_mode_application_service
        normalized = service.normalize_profile(profile)
        settings = self.context.services.settings
        settings["eye_mode_profile"] = normalized
        save_settings(settings)
        if self.context.state._game_mode_enabled:
            self.set_game_mode_profile(normalized)       # resets in-flight analysis, keeps Eye Mode on
        else:
            self.context.state._game_mode_profile = normalized

    def _eye_monitor_choices(self):
        return [
            (monitor.id, monitor.name + (" · اصلی" if monitor.primary else ""))
            for monitor in self._capture_service().list_monitors()
        ]

    def build_eye_vision_page(self):
        """Settings page for Eye Mode; widgets live in the page, behaviour stays in this controller."""
        from .pages.eye_vision_page import EyeVisionPage

        session = self.feature_controller("session")
        privacy = _service_value(self.context.services.vision_application_service, "desktop_capture_application_service")
        page = EyeVisionPage(session.t)
        page.set_monitors(self._eye_monitor_choices(), _service_value(privacy, "selected_monitor_id") or "")
        page.set_profile(self.context.state._game_mode_profile)
        page.set_eye_enabled(bool(self.context.state._game_mode_enabled))
        page.set_budget(*self._live_budget_values())

        game_mode_btn = self.context.views.game_mode_btn
        page.eye_mode_toggled.connect(lambda on: game_mode_btn.setChecked(bool(on)))
        game_mode_btn.toggled.connect(page.set_eye_enabled)
        page.profile_selected.connect(self.set_eye_mode_profile)
        page.frame_budget_changed.connect(self.set_live_frame_budget)

        def select_monitor(monitor_id):
            if not self.set_desktop_monitor(monitor_id):
                page.select_monitor(_service_value(privacy, "selected_monitor_id") or "")

        def refresh():
            page.set_monitors(self._eye_monitor_choices(), _service_value(privacy, "selected_monitor_id") or "")
            page.set_profile(self.context.state._game_mode_profile)
            page.set_eye_enabled(bool(self.context.state._game_mode_enabled))

        page.monitor_selected.connect(select_monitor)
        page.refresh_requested.connect(refresh)
        page.bind_translations(session.reg)
        self._eye_vision_page = page
        return page

    def _clear_live_video_state(self):
        self._live_session_manager().reset(clear_remote=True)

    def set_live_video_active(self, enabled):
        """Synchronize Live sampling with the manually enabled Eye Mode source."""
        self._live_session_manager().activate(bool(enabled))
        self._live_video_active = bool(enabled)
        source_active = bool(self.context.state._game_mode_enabled)
        timer = self.context.state._game_capture_timer
        timer.setInterval(self._vision_interval_ms())
        if source_active and not self.context.state._closing:
            if not timer.isActive():
                timer.start()
            if enabled:
                self._capture_active_vision_frame()

    def _release_live_frame_budget(self, frame_context):
        if frame_context is not None:
            self.context.services.vision_application_service.release_frame_budget(frame_context)
        return False

    def _maybe_stream_gemini_live_frame(self, frame, source, window_info, *, frame_context=None):
        """Delegate Live privacy checks, sampling and frame admission to the session manager."""
        return self._live_session_manager().stream_frame(
            frame,
            source,
            window_info,
            frame_context=frame_context,
            game_mode_enabled=bool(self.context.state._game_mode_enabled),
            game_mode_profile=self.context.state._game_mode_profile,
        )

    def _perception_worker_controller(self):
        controller = getattr(self.context.adapters, "perception_worker_controller", None)
        if controller is None:
            raise RuntimeError("Perception worker adapter was not composed by the application root")
        return controller

    def perception_worker(self):
        controller = getattr(self.context.adapters, "perception_worker_controller", None)
        return controller.worker if controller is not None else None

    def _queue_perception_ocr(self, frame, source, window_info):
        """Delegate frame observations and OCR job creation to the perception worker adapter."""
        self._perception_worker_controller().process_frame(
            frame, source, window_info
        )

    def capture_screen_attachment(self):
        """Attach an explicitly requested, privacy-approved foreground-window crop."""
        captured = self._vision_runtime().snapshot_service.capture_explicit_window()
        if not captured.allowed:
            vision_trace(
                "capture_blocked",
                exe=str((captured.window_info or {}).get("exe") or "")[:80] or None,
                reason=captured.reason,
            )
            self.feature_controller("session").add_chat(
                "system", "ثبت تصویر به‌دلیل محدودیت حریم خصوصی انجام نشد."
            )
            return
        if captured.frame is None or captured.frame.isNull():
            self.feature_controller("session").add_chat(
                "system", "ثبت تصویر پنجرهٔ فعال ناموفق بود یا پنجره روی مانیتور انتخاب‌شده نبود."
            )
            return
        self.add_pasted_image(captured.frame)
        self.feature_controller("session").add_chat(
            "system", "🖥️ تصویر پنجرهٔ فعال به پیوست‌ها اضافه شد؛ تا وقتی خودت پیام را نفرستی، برای مدل ارسال نمی‌شود."
        )

    def pick_attachments(self):
        return self.feature_controller("attachments").pick_attachments()

    def make_tile_strip(self):
        return self.feature_controller("attachments").make_tile_strip()

    def strip_add(self, strip, tile):
        return self.feature_controller("attachments").strip_add(strip, tile)

    def strip_remove(self, strip, tile):
        return self.feature_controller("attachments").strip_remove(strip, tile)

    def show_attach_error(self, messages):
        return self.feature_controller("attachments").show_attach_error(messages)

    def cancel_attachments(self):
        return self.feature_controller("attachments").cancel_attachments()

    def attach_loading(self):
        return self.feature_controller("attachments").attach_loading()

    def add_attachment_paths(self, paths):
        return self.feature_controller("attachments").add_attachment_paths(paths)

    def on_attach_progress(self, index, percent):
        return self.feature_controller("attachments").on_attach_progress(index, percent)

    def on_attach_finished(self):
        return self.feature_controller("attachments").on_attach_finished()

    def on_attach_loaded(self, index, attachment):
        return self.feature_controller("attachments").on_attach_loaded(index, attachment)

    def on_attach_failed(self, index, message):
        return self.feature_controller("attachments").on_attach_failed(index, message)

    def add_pasted_image(self, image):
        return self.feature_controller("attachments").add_pasted_image(image)

    def remove_attachment_tile(self, tile):
        return self.feature_controller("attachments").remove_attachment_tile(tile)

    def clear_attachments(self):
        return self.feature_controller("attachments").clear_attachments()

    def show_upload_tiles(self, attachments):
        return self.feature_controller("attachments").show_upload_tiles(attachments)

    def clear_upload_tiles(self, token=None):
        return self.feature_controller("attachments").clear_upload_tiles(token)

    def on_upload_event(self, phase, percent=None):
        return self.feature_controller("attachments").on_upload_event(phase, percent)

    def dragEnterEvent(self, event):
        return self.feature_controller("attachments").dragEnterEvent(event)

    def dropEvent(self, event):
        return self.feature_controller("attachments").dropEvent(event)

    def set_vision_mode(self, mode):
        """Change cadence without changing either source's manual enablement."""
        service = self.context.services.vision_application_service
        policy = service.set_mode(mode)
        self.context.services.settings["vision_mode"] = policy.name
        save_settings(self.context.services.settings)
        if hasattr(self.context.views, "vision_rate_actions"):
            for key, action in self.context.views.vision_rate_actions.items():
                action.setChecked(key == policy.name)
        self.context.state._game_capture_timer.setInterval(
            self._vision_interval_ms()
        )
        if self.context.state._game_mode_enabled:
            self._capture_desktop_frame()
            if not self.context.state._game_capture_timer.isActive():
                self.context.state._game_capture_timer.start()
        elif _service_value(_service_value(service, "desktop_capture_application_service"), "enabled"):
            self._capture_desktop_frame()
            if not self.context.state._game_capture_timer.isActive():
                self.context.state._game_capture_timer.start()
        self.context.views.game_mode_btn.setToolTip(
            f"Vision {policy.name} · هر {policy.interval_seconds:g} ثانیه"
        )

    def _set_game_vision_capture(self, allowed):
        """Eye Mode owns the only live capture source: the selected desktop monitor."""
        allowed = bool(allowed)
        privacy = _service_value(self.context.services.vision_application_service, "desktop_capture_application_service")
        privacy.set_enabled(allowed)
        self.context.adapters.game_mode.set_enabled(allowed)
        if not allowed:
            self._cancel_all_vision_workers()
            self._cancel_perception_worker()
            self._clear_live_video_state()
            self.context.services.desktop_context_application_service.clear()
            self.context.state._game_capture_timer.stop()
            self.context.state._latest_game_frame = None
            self.context.services.vision_application_service.reset()
            return
        # Drop every in-flight result before switching the window-wide capture source.
        self._cancel_all_vision_workers()
        self._cancel_perception_worker()
        self._clear_live_video_state()
        self.context.services.desktop_context_application_service.clear()
        self.context.services.vision_application_service.reset()
        self.context.state._game_capture_timer.setInterval(self._vision_interval_ms())
        self._capture_desktop_frame()
        self.context.state._game_capture_timer.start()

    def set_desktop_vision(self, enabled, *, announce=True):
        """Compatibility shim: legacy Desktop Vision requests now toggle Eye Mode."""
        return self.set_game_mode(bool(enabled), announce=announce)

    def set_desktop_monitor(self, monitor_id):
        """Persist selected display; empty value follows the foreground window's display."""
        selected = str(monitor_id or "").strip()
        available = {monitor.id for monitor in self._capture_service().list_monitors()}
        if selected and selected not in available:
            self.feature_controller("session").add_chat(
                "system", "مانیتور انتخاب‌شده دیگر در دسترس نیست."
            )
            return False
        privacy = _service_value(self.context.services.vision_application_service, "desktop_capture_application_service")
        privacy.set_selected_monitor(selected)
        self.context.services.settings["desktop_vision_monitor_id"] = selected
        save_settings(self.context.services.settings)
        self._clear_live_video_state()
        for monitor_id_value, action in self.context.views.desktop_vision_monitor_actions.items():
            action.setChecked(monitor_id_value == selected)
        self.context.views.desktop_vision_auto_action.setChecked(not selected)
        self._cancel_all_vision_workers()
        self.context.services.vision_application_service.reset()
        if _service_value(privacy, "enabled"):
            self._capture_desktop_frame()
        return True

    def allow_desktop_window(self, kind, value):
        """Persist an explicit exe/title/path privacy exception."""
        privacy = _service_value(self.context.services.vision_application_service, "desktop_capture_application_service")
        if not privacy.add_allow_rule(kind, value):
            return False
        save_settings(self.context.services.settings)
        return True

    def _capture_active_vision_frame(self):
        """Eye Mode always captures the selected desktop monitor."""
        if self.context.state._game_mode_enabled:
            self._capture_desktop_frame()

    def _cancel_vision_worker(self, session=None):
        """Invalidate an existing runtime's frame generation without creating it."""
        session = session or self.context.session
        if session is None:
            return
        provider = getattr(self.context.services, "vision_runtime_provider", None)
        runtime = provider.peek() if provider is not None else None
        if runtime is not None:
            runtime.analysis_coordinator.cancel_worker(
                session, self._vision_session_id(session)
            )

    def _cancel_all_vision_workers(self):
        """Cancel every Session because the window-wide capture policy is changing."""
        manager = getattr(self.context.services, "session_manager", None)
        if manager is not None:
            sessions = tuple(manager.list_sessions())
        else:
            sessions = tuple(getattr(self.context.state, "sessions", {}).values())
        if not sessions:
            session = self.context.session
            sessions = (session,) if session is not None else ()
        for session in sessions:
            self._cancel_vision_worker(session)

    def _stop_local_code_jobs(self):
        code_chat = getattr(self.context.views, "code_chat", None)
        session = getattr(code_chat, "session", None) if code_chat is not None else None
        if session is not None:
            with self.feature_controller("session")._as(session):
                self.context.services.coding_agent_application_service.stop_session(code_chat, session)

    def set_game_mode_profile(self, profile):
        """Apply a manually selected gameplay profile; never infer or enable it automatically."""
        previous = self.context.state._game_mode_profile
        self.context.state._game_mode_profile = self.context.services.game_mode_application_service.normalize_profile(profile)
        if self.context.state._game_mode_profile != previous:
            # An analysis started under the old profile must not deliver its result under the new one.
            self._cancel_all_vision_workers()
            self._clear_live_video_state()
            self.context.services.vision_application_service.reset()
        self.set_game_mode(True)

    def handle_game_mode_command(self, action):
        """Execute an explicit chat command against the real Game Mode controller state."""
        action = str(action or "").strip().lower()
        vision_trace("command", action=action)
        if action in ("enable", "disable"):
            enabled = action == "enable"
            self.set_game_mode(enabled, announce=False)
            if not enabled:
                return "Eye Mode خاموش شد؛ ضبط صفحه متوقف است و تصویر زنده‌ای دریافت نمی‌کنم."
        return self._game_vision_status_message()

    def _game_vision_status_message(self):
        """Compatibility status command for the unified Eye Mode."""
        if not self.context.state._game_mode_enabled:
            return "Eye Mode خاموش است؛ برای فعال‌کردن دید زنده روی آیکون چشم کلیک کن."
        self._capture_desktop_frame()
        window_info = self.context.adapters.game_mode.capture_service.foreground_window_info(
            allow_partial_identity=True
        )
        privacy = _service_value(self.context.services.vision_application_service, "desktop_capture_application_service")
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed:
            return f"Eye Mode روشن است، اما پنجرهٔ فعال به‌دلیل محدودیت حریم خصوصی مسدود شد: {reason}"
        frame = self.context.state._latest_game_frame
        if frame is None or frame.isNull():
            return "Eye Mode روشن است، اما Capture مانیتور انتخاب‌شده ناموفق بود."
        worker = getattr(self.context.session, "_vision_worker", None)
        if worker is not None and worker.isRunning():
            return "Eye Mode تصویر مانیتور انتخاب‌شده را دریافت کرده و تحلیل در حال اجراست."
        return "Eye Mode روشن است؛ تصویر مانیتور انتخاب‌شده برای تحلیل دریافت شد."

    def _vision_status(self, turn_extra=None):
        """Describe Eye Mode state and never claim a frame was attached without proof."""
        extra = turn_extra if isinstance(turn_extra, dict) else {}
        attached = extra.get("live_vision_frame_attached") is True
        source = str(extra.get("live_vision_frame_source") or "")
        if not attached and extra.get("live_game_frame_attached") is True:
            attached, source = True, "desktop"
        if attached and source in ("desktop", "game"):
            return "attached", (
                "EYE MODE STATUS: A privacy-approved frame from the user's selected monitor is attached "
                "to THIS request. Inspect only the supplied frame; do not infer hidden windows or claim "
                "continuous visual access from this single attachment."
            )
        if attached:
            return "attached_unknown_source", (
                "EYE MODE STATUS: An image is attached, but its source could not be verified. Inspect "
                "only the image actually attached."
            )
        if not self.context.state._game_mode_enabled:
            return "eye_mode_off", (
                "EYE MODE STATUS: Eye Mode is OFF. No live screen frame is available to this request. "
                "Do not claim to see the desktop. User-supplied image attachments remain separate."
            )
        privacy = _service_value(self.context.services.vision_application_service, "desktop_capture_application_service")
        window_info = self.context.adapters.game_mode.capture_service.foreground_window_info(
            allow_partial_identity=True
        )
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed:
            return "eye_mode_blocked", (
                f"EYE MODE STATUS: Capture is blocked by the privacy policy ({reason}). No current "
                "screen observation is available; do not claim to see the screen."
            )
        context_service = self.context.services.desktop_context_application_service
        if context_service.summary():
            return "eye_mode_monitoring", (
                "EYE MODE STATUS: Eye Mode is ON and periodically observing the user's selected desktop monitor. "
                "The DESKTOP CONTEXT below contains recent visual observations from that monitor. This is a "
                "separate screen-observation channel, not a user-uploaded image attachment; images_in_turn=0 "
                "is normal and does NOT mean the screen is unseen. When the user asks whether you can see "
                "their screen, answer from the latest visual observation in DESKTOP CONTEXT. Do not say "
                "that no image was sent unless the user specifically asks about a separate uploaded image. "
                "Use the structured CURRENT SCREEN STATE section as the sole source for claims about the "
                "latest known screen. Its freshness label is authoritative: for fresh observations, describe "
                "the visible state directly and naturally; for recent observations, make clear that this is "
                "the latest observation rather than a guaranteed live frame; for stale or unknown-age "
                "observations, explicitly qualify that the information may no longer match the screen. "
                "Earlier visual observations are historical context only and must never be merged into the "
                "current screen description. Do not narrate when or how you saw the screen unless the user "
                "asks. Be honest about incomplete or uncertain details. "
                "Treat these observations as private context for answering naturally; do not print internal "
                "analysis templates, risk/goal/action headings, or raw perception notes as chat messages."
            )
        return "eye_mode_waiting_for_observation", (
            "EYE MODE STATUS: Eye Mode is ON and monitoring is enabled, but no visual observation "
            "has been recorded yet. Do not claim to know what is currently on screen."
        )

    def build_chat_vision_context(self, turn_extra=None):
        """Tell the model whether a live game frame is actually present in this provider turn."""
        code, text = self._vision_status(turn_extra)
        images = turn_extra.get("images") if isinstance(turn_extra, dict) else None
        names = ",".join(str(item.get("name") or "?")[:40] for item in (images or []) if isinstance(item, dict))
        game = None
        try:
            game = self.context.adapters.game_mode.last_game
        except Exception:  # noqa: BLE001 - tracing must never break a chat turn
            pass
        desktop_context = ""
        context_service = self.context.services.desktop_context_application_service
        source_active = bool(self.context.state._game_mode_enabled)
        context_started = time.monotonic()
        if source_active:
            desktop_context = format_desktop_context(context_service.summary())
        # Eye Mode deactivation clears context at its ownership boundary. Avoid
        # materializing the deferred context service for ordinary chat turns.
        context_build_ms = (time.monotonic() - context_started) * 1000.0
        if desktop_context:
            text = text + "\n\n" + desktop_context
        vision_trace(
            "perception_context", chars=len(desktop_context),
            active=bool(source_active), build_ms=round(context_build_ms, 3),
        )
        vision_trace(
            "turn_context",
            status=code,
            game_mode=bool(self.context.state._game_mode_enabled),
            desktop_vision=bool(self.context.services.settings.get("desktop_vision_enabled", False)),
            live_frame_flag=code == "attached",
            frame_source=(
                str(turn_extra.get("live_vision_frame_source") or "")
                or ("desktop" if turn_extra.get("live_game_frame_attached") is True else "unknown")
            ) if code.startswith("attached") and isinstance(turn_extra, dict) else None,
            images_in_turn=len(images or []),
            image_names=names[:200],
            **_game_fields(game),
        )
        return text

    def set_game_mode(self, enabled, *, announce=True):
        enabled = bool(enabled)
        was_enabled = self.context.state._game_mode_enabled
        self.context.state._game_mode_enabled = enabled
        game_mode_button = self.context.views.game_mode_btn
        if game_mode_button.isChecked() != enabled:
            previous = game_mode_button.blockSignals(True)
            game_mode_button.setChecked(enabled)
            game_mode_button.blockSignals(previous)
        permissions = self.context.services.game_mode_application_service.permissions(self.context.state._game_mode_profile)
        vision_allowed = bool(permissions["vision_capture"])
        audio_allowed = bool(permissions["game_audio_loopback"])
        self.context.services.settings["desktop_vision_enabled"] = enabled
        save_settings(self.context.services.settings)
        legacy_action = getattr(self.context.views, "desktop_vision_action", None)
        if legacy_action is not None:
            previous = legacy_action.blockSignals(True)
            legacy_action.setChecked(enabled)
            legacy_action.blockSignals(previous)
        vision_trace(
            "eye_mode_set", enabled=enabled, profile=str(self.context.state._game_mode_profile),
            vision_allowed=vision_allowed, audio_allowed=audio_allowed,
        )

        # Capture is gated by the selected profile, not only by the master toggle.
        self._set_game_vision_capture(enabled and vision_allowed)
        safe_profile = enabled and self.context.services.game_mode_application_service.is_competitive_safe(self.context.state._game_mode_profile)
        self.context.services.tool_agent.set_competitive_safe_mode(safe_profile)
        # Safe mode does not keep polling foreground process metadata while an online game is running.
        if safe_profile:
            self.context.state._game_poll_timer.stop()
            self._stop_local_code_jobs()
        elif not self.context.state._game_poll_timer.isActive():
            self.context.state._game_poll_timer.start()

        if enabled:
            if not was_enabled:
                self.context.state._game_prev_mic = self.context.views.mic_btn.isChecked()
                self.context.state._game_prev_wake = self.context.views.wake_btn.isChecked()
            if not self.context.views.wake_btn.isChecked():
                self.context.views.wake_btn.setChecked(True)
                self.feature_controller("runtime").toggle_wake()
            if audio_allowed:
                self._start_game_audio_listener()
            else:
                self._stop_game_audio_listener()
        else:
            self._stop_game_audio_listener()
            if not self.context.state._game_prev_wake and self.context.views.wake_btn.isChecked():
                self.context.views.wake_btn.setChecked(False)
                self.feature_controller("runtime").toggle_wake()
            if not self.context.state._game_prev_mic and self.context.views.mic_btn.isChecked():
                self.context.views.mic_btn.setChecked(False)
                self.feature_controller("runtime").stop_listener()

        if not enabled:
            self.context.views.game_mode_btn.setToolTip("Eye Mode خاموش است؛ برای دیدن صفحه کلیک کن")
            if announce:
                self.feature_controller("session").add_chat("system", "Eye Mode خاموش شد؛ ضبط صفحه، تحلیل و ارسال فریم‌ها متوقف شدند.")
        elif self.context.services.game_mode_application_service.is_story(self.context.state._game_mode_profile):
            self.context.views.game_mode_btn.setToolTip("Eye Mode روشن است · Story audio فعال")
            if announce:
                self.feature_controller("session").add_chat("system", "Eye Mode روشن شد؛ تصویر مانیتور انتخاب‌شده به‌صورت زنده و با رعایت محدودیت‌های حریم خصوصی بررسی می‌شود.")
        else:
            self.context.views.game_mode_btn.setToolTip("Eye Mode روشن است · حالت امن")
            if announce:
                self.feature_controller("session").add_chat("system", "Eye Mode روشن شد؛ تصویر مانیتور انتخاب‌شده فقط‌خواندنی تحلیل می‌شود.")
        if enabled and vision_allowed and announce:
            self.feature_controller("session").add_chat("system", "🖥️ ضبط زنده از مانیتور انتخاب‌شده انجام می‌شود؛ برای توقف فوری Eye Mode را خاموش کن.")

    def _start_game_audio_listener(self):
        if self.context.state._closing or not self.context.state._game_mode_enabled:
            return
        permissions = self.context.services.game_mode_application_service.permissions(
            self.context.state._game_mode_profile
        )
        if not permissions["game_audio_loopback"]:
            return

        active = self.context.adapters.game_audio_listener
        if active is not None and active.isRunning():
            return

        stopping = self.context.resource("_stopping_game_audio_listener")
        if stopping is not None and stopping.isRunning():
            # A previous WASAPI stream has not released the device yet. Defer
            # restart instead of opening a second loopback stream concurrently.
            self.context.state._game_audio_restart_pending = True
            return
        self.context.state._stopping_game_audio_listener = None
        self.context.state._game_audio_restart_pending = False

        listener = GameAudioListener(self.context.services.settings, self.window)
        self.context.adapters.game_audio_listener = listener
        listener.transcript.connect(self.on_game_audio_transcript)
        listener.error.connect(self.on_game_audio_error)
        # Connect to a QObject slot so Qt queues this callback onto the
        # controller's GUI thread before it touches widgets or starts a timer.
        listener.finished.connect(self._on_game_audio_listener_finished)
        listener.start()

    def _stop_game_audio_listener(self):
        self.context.state._game_audio_restart_pending = False
        listener = self.context.adapters.game_audio_listener
        self.context.adapters.game_audio_listener = None
        if listener is None:
            return
        listener.stop()
        if listener.isRunning():
            self.context.state._stopping_game_audio_listener = listener
        else:
            listener.deleteLater()

    @Slot()
    def _on_game_audio_listener_finished(self):
        listener = self.sender()
        if listener is None:
            return
        if self.context.adapters.game_audio_listener is listener:
            self.context.adapters.game_audio_listener = None
        if self.context.state._stopping_game_audio_listener is listener:
            self.context.state._stopping_game_audio_listener = None
        listener.deleteLater()
        if self.context.state._closing or not self.context.state._game_audio_restart_pending:
            return
        self.context.state._game_audio_restart_pending = False
        if self.context.state._game_mode_enabled:
            permissions = self.context.services.game_mode_application_service.permissions(
                self.context.state._game_mode_profile
            )
            if permissions["game_audio_loopback"]:
                QTimer.singleShot(0, self._start_game_audio_listener)

    @Slot(str)
    def on_game_audio_error(self, message):
        if self.sender() is not self.context.adapters.game_audio_listener:
            return
        if (self.context.state._game_mode_enabled
                and self.context.services.game_mode_application_service.permissions(self.context.state._game_mode_profile)["game_audio_loopback"]):
            self.feature_controller("session").add_chat("system", "🎧 " + message)

    @Slot(str)
    def on_game_audio_transcript(self, text):
        if self.sender() is not self.context.adapters.game_audio_listener:
            return
        alert = self.context.services.game_mode_application_service.classify_game_audio(
            text,
            now=time.monotonic(),
            enabled=self.context.state._game_mode_enabled,
            profile=self.context.state._game_mode_profile,
            busy=self.context.session.busy,
            speaking=self.context.services.voice_application_service.is_speaking(),
        )
        if alert is not None:
            self.feature_controller("runtime").reply_local(alert.message, alert.emotion)

    def _capture_game_frame(self):
        """Capture through the policy boundary, then route the immutable frame context."""
        captured = self._capture_service().capture_game_frame(
            self.context.state._game_mode_enabled,
            self.context.state._game_mode_profile,
        )
        window_info = captured.window_info
        if not captured.allowed:
            self._clear_live_video_state()
            self.context.state._latest_game_frame = None
            if captured.stage == "privacy" and window_info:
                vision_trace(
                    "capture_blocked",
                    exe=str(window_info.get("exe") or "")[:80],
                    reason=captured.reason,
                )
            self._cancel_vision_worker()
            if captured.stage == "source":
                self._trace_capture_state(None, None)
            return

        frame = captured.frame
        self.context.state._latest_game_frame = frame
        self._trace_capture_state(
            window_info, frame, "game" if frame is not None else None
        )
        if frame is None:
            return
        frame_context, decision = self._submit_vision_frame(frame, "game", window_info)
        if decision is not None and decision.route == "live":
            self._maybe_stream_gemini_live_frame(
                None, "game", window_info, frame_context=frame_context
            )

    def _capture_desktop_frame(self):
        """Capture the selected monitor through the source/privacy capture service."""
        captured = self._capture_service().capture_desktop_frame()
        window_info = captured.window_info
        if not captured.allowed:
            self._clear_live_video_state()
            self.context.state._latest_game_frame = None
            vision_trace(
                "capture_blocked",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason=captured.reason,
            )
            self._cancel_vision_worker()
            return

        frame = captured.frame
        self.context.state._latest_game_frame = frame
        if frame is None:
            vision_trace(
                "capture_skipped",
                source="desktop",
                exe=str((window_info or {}).get("exe") or "")[:80],
                reason="selected_monitor_capture_failed",
            )
            return
        frame_context, decision = self._submit_vision_frame(
            frame, "desktop", window_info
        )
        if decision is not None and decision.route == "live":
            self._maybe_stream_gemini_live_frame(
                frame, "desktop", window_info, frame_context=frame_context
            )

    def _submit_vision_frame(self, frame, source, window_info):
        """Submit the frame to the Qt-free analysis coordinator."""
        service = self.context.services.vision_application_service
        if frame is None or frame.isNull():
            return None, None
        # Local OCR/perception remains a separate on-device capability.
        self._queue_perception_ocr(frame, source, window_info)
        enabled = self.context.state._game_mode_enabled if source == "game" else True
        profile = self.context.state._game_mode_profile if source == "game" else None
        session = self.context.session
        analysis_allowed = service.should_analyze(
            enabled=enabled,
            profile=profile,
            frame_available=True,
            worker_running=False,
            chat_busy=session.busy,
            provider_busy=session.client.busy,
            speech_active=self.context.services.voice_application_service.is_speaking(),
            source=source,
            window_info=window_info,
        )
        live_ready = bool(self.feature_controller("runtime").is_gemini_live_ready())
        session_id = self._vision_session_id(session)
        if live_ready:
            interval_seconds, max_frames_per_minute = self._live_budget_values()
        else:
            interval_seconds = max(
                0.25, float(_service_value(service, "policy").interval_seconds)
            )
            max_frames_per_minute = max(1, int(60.0 / interval_seconds))
        try:
            frame_context, decision = self._analysis_coordinator().submit_frame(
                frame,
                source,
                window_info,
                session_id=session_id,
                live_ready=live_ready,
                analysis_allowed=analysis_allowed,
                interval_seconds=interval_seconds,
                max_frames_per_minute=max_frames_per_minute,
            )
            if decision is not None and decision.route == _service_value(service, "frame_orchestrator").ANALYSIS:
                self._dispatch_next_vision_job()
            return frame_context, decision
        except Exception as exc:  # noqa: BLE001 - Vision must never interrupt chat
            vision_trace(
                "analysis_error", source=source,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.feature_controller("session").add_chat(
                "system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}"
            )
            return None, None

    def _dispatch_next_vision_job(self):
        """Provide session and Qt adapters to the Qt-free analysis coordinator."""
        session = self.context.session
        if session is None:
            return
        session_controller = self.feature_controller("session")
        self._analysis_coordinator().dispatch_next(
            session,
            session_id=self._vision_session_id(session),
            closing=bool(self.context.state._closing),
            game_mode_enabled=bool(self.context.state._game_mode_enabled),
            game_mode_profile=self.context.state._game_mode_profile,
            speech_active=self.context.services.voice_application_service.is_speaking(),
            settings=self.context.services.settings,
            worker_factory=VisionAnalysisWorker,
            attachment_factory=att.image_attachment,
            dispose_session=session_controller._dispose_chat_session,
            report_error=lambda message: session_controller.add_chat("system", message),
        )

    def _send_pending_for_session(self, session):
        if self.context.state._closing or session is None or session.cid not in self.context.state.sessions:
            return
        self.feature_controller("runtime")._send_next_pending(session)

    def _on_game_vision_result(self, ok, result, latency_ms, frame_context=None):
        """Render status; result freshness and observation policy are service-owned."""
        session = self.context.session
        outcome = self._analysis_coordinator().process_result(
            ok, result, latency_ms, session,
            session_id=self._vision_session_id(session),
            closing=bool(self.context.state._closing),
            game_mode_enabled=bool(self.context.state._game_mode_enabled),
            game_mode_profile=self.context.state._game_mode_profile,
            desktop_context_service=self.context.services.desktop_context_application_service,
            fingerprint=PerceptionEvent.fingerprint,
            frame_context=frame_context,
        )
        if outcome.stats is not None:
            stats = outcome.stats
            self.context.views.game_mode_btn.setToolTip(
                f"Vision {stats['mode']} · تحلیل: {stats['analysis_count']} · "
                f"فریم تکراری ردشده: {stats['unchanged_skips']} · "
                f"تأخیر آخرین تحلیل: {int(latency_ms or 0)}ms"
            )

    def on_game_detected(self, info):
        """Suggest Game Mode once per detected process, unless the user already enabled it."""
        if self.context.state._game_mode_enabled:
            return
        name = info.get("title") or info.get("exe") or "بازی"
        note = (f"🎮 بازی «{name[:90]}» شناسایی شد. اگر می‌خواهی Kira صفحه را ببیند، Eye Mode را روشن کن.")
        self.feature_controller("session").add_chat("system", note)
        tray = getattr(self.context.views, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage("Kira · Eye Mode", "بازی شناسایی شد. برای تحلیل زندهٔ مانیتور، Eye Mode را روشن کن.",
                             QSystemTrayIcon.Information, 7000)

    def _live_vision_attachment(self, question: str = "", *, detail: bool = False):
        """Attach a privacy-approved frame from Eye Mode's selected monitor.

        Small-text/menu/OCR questions (or detail=True, used for the single retry after an unreadable reply)
        capture at 1280x720; everything else stays at the policy size (768x432 by default).
        """
        detail = bool(detail or wants_detail_capture(question))
        captured = self._vision_runtime().snapshot_service.capture_desktop_attachment(
            source_enabled=bool(self.context.state._game_mode_enabled), detail=detail
        )
        if not captured.allowed:
            vision_trace(
                "attach_blocked",
                source="desktop",
                exe=str((captured.window_info or {}).get("exe") or "")[:80] or None,
                reason=captured.reason,
            )
            return None
        frame = captured.frame
        if frame is None or frame.isNull():
            vision_trace(
                "attach_skip",
                source="desktop",
                exe=str((captured.window_info or {}).get("exe") or "")[:80] or None,
                reason="selected_monitor_capture_failed",
            )
            return None
        try:
            policy = _service_value(self.context.services.vision_application_service, "policy")
            quality = (int(CAPTURE_DETAIL_JPEG_QUALITY) if detail
                       else min(int(policy.jpeg_quality), int(CAPTURE_JPEG_QUALITY)))
            jpeg = self._frame_codec().encode_jpeg(frame, quality)
            if not jpeg:
                raise RuntimeError("jpeg_encode_failed")
            vision_trace(
                "attach_ok",
                source="desktop",
                exe=str((captured.window_info or {}).get("exe") or "")[:80] or None,
                width=frame.width(),
                height=frame.height(),
                jpeg_bytes=len(jpeg),
            )
            return att.image_attachment(jpeg, "eye-screen.jpg", "image/jpeg")
        except Exception as exc:  # noqa: BLE001 - a failed capture must not block ordinary chat
            vision_trace(
                "attach_error",
                source="desktop",
                exe=str((captured.window_info or {}).get("exe") or "")[:80] or None,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.feature_controller("session").add_chat(
                "system", f"تصویر مانیتور انتخاب‌شده آماده نشد: {str(exc)[:180]}"
            )
            return None

    def dispose_runtime_services(self):
        """Cancel and dispose service-owned Vision and Perception work after worker drain."""
        self._cancel_all_vision_workers()
        perception_controller = getattr(
            self.context.adapters, "perception_worker_controller", None
        )
        if perception_controller is not None and not perception_controller.dispose():
            return False
        provider = getattr(self.context.services, "vision_runtime_provider", None)
        if provider is not None and not provider.dispose():
            return False
        sessions = tuple(self.context.state.sessions.values())
        return not any(
            (worker := getattr(session, "_vision_worker", None)) is not None
            and worker.isRunning()
            for session in sessions
        )

    def _game_vision_attachment(self, question: str = "", *, detail: bool = False):
        """Backward-compatible Game Mode attachment facade."""
        if not self.context.state._game_mode_enabled:
            return None
        return self._live_vision_attachment(question, detail=detail)


# Backward-compatible import name for callers migrating from mixin composition.
AttachmentsVisionMixin = AttachmentsVisionController
