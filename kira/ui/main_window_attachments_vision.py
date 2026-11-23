"""Attachment and vision feature controller for the desktop window."""
from PySide6.QtCore import Slot
from ..request_trace import vision_trace
from .main_window_attachments_vision_support import (
    AttachmentTile,
    CAPTURE_JPEG_QUALITY,
    GameAudioListener,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QImage,
    QSystemTrayIcon,
    QTimer,
    Qt,
    VisionAnalysisWorker,
    att,
    front_only,
    save_settings,
    time,
)


from .window_feature_controller import WindowFeatureController

# Last (game_detected, frame_ok, source) tuple written to the vision trace; the capture timer
# only logs when this changes so the log is not flooded every few seconds.
_LAST_CAPTURE_STATE = {}

# Where the frame attached to the most recent chat turn came from: "game" (the detected
# game window) or "screen" (the whole primary screen, used when no game window is captured).
_FRAME_SOURCE = {"value": None}
_FRAME_WINDOW_INFO = {"value": None}


def _game_fields(game):
    """Scalar window identity for the vision trace (exe and title only)."""
    if not game:
        return {"exe": None, "title": None}
    return {"exe": str(game.get("exe") or "")[:80]}


def _trace_capture_state(game, frame, source=None):
    state = (bool(game), frame is not None and not frame.isNull(), source)
    if _LAST_CAPTURE_STATE.get("value") == state:
        return
    _LAST_CAPTURE_STATE["value"] = state
    vision_trace(
        "capture_state", game_detected=state[0], frame_ok=state[1], source=source,
        **_game_fields(game),
    )


class AttachmentsVisionController(WindowFeatureController):
    def capture_screen_attachment(self):
        """Attach an explicitly requested, privacy-approved foreground-window crop."""
        capture = self.context.adapters.game_mode.capture_service
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        window_info = capture.foreground_window_info()
        allowed, reason = privacy.evaluate_window(window_info, explicit=True)
        if not allowed:
            vision_trace(
                "capture_blocked",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason=reason,
            )
            self.feature_controller("session").add_chat(
                "system", "ثبت تصویر به‌دلیل محدودیت حریم خصوصی انجام نشد."
            )
            return
        policy = self.context.services.vision_application_service.policy
        pixmap = capture.capture_window(
            window_info,
            monitor_id=privacy.selected_monitor_id or None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        if pixmap is None or pixmap.isNull():
            self.feature_controller("session").add_chat(
                "system", "ثبت تصویر پنجرهٔ فعال ناموفق بود یا پنجره روی مانیتور انتخاب‌شده نبود."
            )
            return
        self.add_pasted_image(pixmap.toImage())
        self.feature_controller("session").add_chat(
            "system", "🖥️ تصویر پنجرهٔ فعال به پیوست‌ها اضافه شد؛ تا وقتی خودت پیام را نفرستی، برای مدل ارسال نمی‌شود."
        )

    # ---- attachments (images and files) ----

    def pick_attachments(self):
        exts = " ".join("*" + e for e in sorted(att.IMAGE_TYPES))
        paths, _ = QFileDialog.getOpenFileNames(
            self.window, "انتخاب عکس یا فایل", "",
            f"عکس و فایل‌های پشتیبانی‌شده ({exts} *.txt *.md *.json *.csv *.log *.py *.js *.html *.xml *.yaml *.yml *.ini *.docx *.pdf *.zip);;همه‌ی فایل‌ها (*)")
        if paths:
            self.add_attachment_paths(paths)

    # -- tile strips --

    @staticmethod
    def make_tile_strip():
        frame = QFrame()
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        frame.row = row
        frame.hide()
        return frame

    @staticmethod
    def strip_add(strip, tile):
        strip.row.insertWidget(strip.row.count() - 1, tile)
        strip.show()

    @staticmethod
    def strip_remove(strip, tile):
        strip.row.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()
        strip.setVisible(strip.row.count() > 1)

    def show_attach_error(self, messages):
        self.feature_controller("chat").attachment_controller.show_error(messages)

    def cancel_attachments(self):
        self.feature_controller("chat").attachment_controller.cancel()

    def attach_loading(self):
        return self.feature_controller("chat").attachment_controller.is_loading()

    def add_attachment_paths(self, paths):
        self.feature_controller("chat").attachment_controller.add_paths(paths)

    def on_attach_progress(self, index, percent):
        self.feature_controller("chat").attachment_controller.on_progress(index, percent)

    def on_attach_finished(self):
        self.feature_controller("chat").attachment_controller.on_finished()

    def on_attach_loaded(self, index, attachment):
        self.feature_controller("chat").attachment_controller.on_loaded(index, attachment)

    def on_attach_failed(self, index, message):
        self.feature_controller("chat").attachment_controller.on_failed(index, message)

    def add_pasted_image(self, image):
        self.feature_controller("chat").attachment_controller.add_image(image)

    def remove_attachment_tile(self, tile):
        self.feature_controller("chat").attachment_controller.remove_tile(tile)

    def clear_attachments(self):
        self.feature_controller("chat").attachment_controller.clear()

    # -- sending: cards with the upload percentage --

    @front_only
    def show_upload_tiles(self, attachments):
        self.clear_upload_tiles()
        self.context.state._upload_token += 1
        self.context.state._upload_done = False
        for a in attachments or []:
            tile = AttachmentTile(a["name"])
            tile.set_attachment(a)
            tile.set_removable(False)
            tile.set_progress(-1)                               # '…' until the first real percentage arrives
            self.context.state._upload_tiles.append(tile)
            self.strip_add(self.context.views.send_strip, tile)

    @front_only
    def clear_upload_tiles(self, token=None):
        if token is not None and token != self.context.state._upload_token:
            return
        for tile in self.context.state._upload_tiles:
            self.strip_remove(self.context.views.send_strip, tile)
        self.context.state._upload_tiles = []

    @front_only
    def on_upload_event(self, phase, percent=None):
        if not self.context.state._upload_tiles:
            return
        if phase == "uploading":
            self.context.state._upload_done = False
            for tile in self.context.state._upload_tiles:
                tile.set_progress(min(99, int(percent or 0)))
        elif phase in ("waiting", "streaming") and not self.context.state._upload_done:
            self.context.state._upload_done = True                            # the model has the request: show ✓, then remove the cards
            for tile in self.context.state._upload_tiles:
                tile.set_progress(100)
            QTimer.singleShot(1500, lambda tok=self.context.state._upload_token: self.clear_upload_tiles(tok))
        elif phase == "failover":
            for tile in self.context.state._upload_tiles:
                tile.set_progress(-1)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_attachment_paths(paths)
            event.acceptProposedAction()

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
            max(250, int(policy.interval_seconds * 1000))
        )
        if self.context.state._game_mode_enabled:
            self._capture_game_frame()
            if not self.context.state._game_capture_timer.isActive():
                self.context.state._game_capture_timer.start()
        elif service.desktop_capture_application_service.enabled:
            self._capture_desktop_frame()
            if not self.context.state._game_capture_timer.isActive():
                self.context.state._game_capture_timer.start()
        self.context.views.game_mode_btn.setToolTip(
            f"Vision {policy.name} · هر {policy.interval_seconds:g} ثانیه"
        )

    def _set_game_vision_capture(self, allowed):
        """Keep timer ownership source-aware and cancel analysis when permission closes."""
        allowed = bool(allowed)
        desktop_policy = self.context.services.vision_application_service.desktop_capture_application_service
        if allowed and desktop_policy.enabled:
            self.set_desktop_vision(False, announce=False)
        self.context.adapters.game_mode.set_enabled(allowed)
        if allowed:
            self.context.state._game_capture_timer.setInterval(
                max(250, int(self.context.services.vision_application_service.policy.interval_seconds * 1000))
            )
            self._capture_game_frame()
            self.context.state._game_capture_timer.start()
        else:
            if not desktop_policy.enabled:
                self.context.state._game_capture_timer.stop()
            self.context.state._latest_game_frame = None
            self.context.services.vision_application_service.reset()
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            self._cancel_vision_worker()

    def set_desktop_vision(self, enabled, *, announce=True):
        """Manually enable/stop Live Desktop Vision; it always starts off after app launch."""
        service = self.context.services.vision_application_service
        privacy = service.desktop_capture_application_service
        enabled = bool(enabled)
        if enabled and self.context.state._game_mode_enabled:
            enabled = False
            if announce:
                self.feature_controller("session").add_chat(
                    "system", "برای جلوگیری از تداخل، ابتدا Game Mode را خاموش کن."
                )
        privacy.set_enabled(enabled)
        self.context.services.settings["desktop_vision_enabled"] = enabled
        save_settings(self.context.services.settings)
        action = self.context.views.desktop_vision_action
        if action.isChecked() != enabled:
            previous = action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(previous)
        service.reset()
        self._cancel_vision_worker()
        self.context.state._latest_game_frame = None
        _FRAME_SOURCE["value"] = None
        _FRAME_WINDOW_INFO["value"] = None
        if enabled:
            self.context.state._game_capture_timer.setInterval(
                max(250, int(service.policy.interval_seconds * 1000))
            )
            self._capture_desktop_frame()
            self.context.state._game_capture_timer.start()
            if announce:
                self.feature_controller("session").add_chat(
                    "system",
                    "🖥️ Live Desktop Vision روشن شد. فقط پنجرهٔ فعال و مجاز روی مانیتور انتخاب‌شده بررسی می‌شود؛ برای توقف فوری همین گزینه را خاموش کن."
                )
        else:
            if not self.context.state._game_mode_enabled:
                self.context.state._game_capture_timer.stop()
            if announce:
                self.feature_controller("session").add_chat(
                    "system", "Live Desktop Vision متوقف شد و تحلیل جاری لغو شد."
                )
        vision_trace("desktop_vision_state", enabled=enabled)
        return enabled

    def set_desktop_monitor(self, monitor_id):
        """Persist selected display; empty value follows the foreground window's display."""
        capture = self.context.adapters.game_mode.capture_service
        selected = str(monitor_id or "").strip()
        available = {monitor.id for monitor in capture.list_monitors()}
        if selected and selected not in available:
            self.feature_controller("session").add_chat(
                "system", "مانیتور انتخاب‌شده دیگر در دسترس نیست."
            )
            return False
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        privacy.set_selected_monitor(selected)
        self.context.services.settings["desktop_vision_monitor_id"] = selected
        save_settings(self.context.services.settings)
        for monitor_id_value, action in self.context.views.desktop_vision_monitor_actions.items():
            action.setChecked(monitor_id_value == selected)
        self.context.views.desktop_vision_auto_action.setChecked(not selected)
        self.context.services.vision_application_service.reset()
        self._cancel_vision_worker()
        _FRAME_SOURCE["value"] = None
        _FRAME_WINDOW_INFO["value"] = None
        if privacy.enabled:
            self._capture_desktop_frame()
        return True

    def allow_desktop_window(self, kind, value):
        """Persist an explicit exe/title/path privacy exception."""
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        if not privacy.add_allow_rule(kind, value):
            return False
        save_settings(self.context.services.settings)
        return True

    def _capture_active_vision_frame(self):
        """Dispatch the shared timer to the sole manually enabled source."""
        if self.context.state._game_mode_enabled:
            self._capture_game_frame()
        elif self.context.services.vision_application_service.desktop_capture_application_service.enabled:
            self._capture_desktop_frame()

    def _cancel_vision_worker(self):
        worker = getattr(self.context.session, "_vision_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel_request()

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
            self._cancel_vision_worker()
            self.context.services.vision_application_service.reset()
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
        self.context.views.game_mode_story_action.setChecked(self.context.services.game_mode_application_service.is_story(self.context.state._game_mode_profile))
        self.context.views.game_mode_safe_action.setChecked(self.context.services.game_mode_application_service.is_competitive_safe(self.context.state._game_mode_profile))
        self.set_game_mode(True)

    def handle_game_mode_command(self, action):
        """Execute an explicit chat command against the real Game Mode controller state."""
        action = str(action or "").strip().lower()
        vision_trace("command", action=action)
        if action in ("enable", "disable"):
            enabled = action == "enable"
            self.set_game_mode(enabled, announce=False)
            if not enabled:
                return "Game Mode خاموش شد؛ Capture متوقف شد و من الان تصویر زنده‌ای از بازی دریافت نمی‌کنم."
        return self._game_vision_status_message()

    def _game_vision_status_message(self):
        """Describe Game Mode only when a foreground game window was actually captured."""
        if not self.context.state._game_mode_enabled:
            return "Game Mode خاموش است؛ برای فعال‌کردن دستی کلیک کن."
        service = self.context.services.vision_application_service
        if not service.capture_allowed(
            self.context.state._game_mode_enabled,
            self.context.state._game_mode_profile,
            source="game",
        ):
            return "پروفایل فعلی اجازهٔ Capture بازی را نمی‌دهد."
        self._capture_game_frame()
        game = self.context.adapters.game_mode.last_game
        frame = self.context.state._latest_game_frame
        if not game:
            return "پنجرهٔ بازی پشتیبانی‌شده‌ای در پیش‌زمینه شناسایی نشد؛ هیچ تصویر جایگزینی ارسال نمی‌شود."
        exe = str(game.get("exe") or "بازی")[:80]
        if frame is None or frame.isNull():
            return f"پنجرهٔ {exe} شناسایی شد، اما Capture مجاز یا موفق نبود."
        worker = getattr(self.context.session, "_vision_worker", None)
        if worker is not None and worker.isRunning():
            return f"فریم پنجرهٔ {exe} دریافت شده و تحلیل Vision در حال اجراست."
        return f"فریم پنجرهٔ {exe} دریافت شده؛ هنگام ارسال پیام دربارهٔ بازی می‌توان آن را ضمیمه کرد."

    def _vision_status(self, turn_extra=None):
        """Describe only a frame proven to be attached to this exact provider request."""
        extra = turn_extra if isinstance(turn_extra, dict) else {}
        attached = extra.get("live_vision_frame_attached") is True
        source = str(extra.get("live_vision_frame_source") or "")
        if not attached and extra.get("live_game_frame_attached") is True:
            attached, source = True, "game"
        if attached and source == "desktop":
            return "attached", (
                "LIVE DESKTOP VISION STATUS: A privacy-approved crop of the foreground application "
                "window on the user's selected monitor is attached to THIS request. It is a single "
                "captured frame, not unrestricted access to the desktop. Describe only visible evidence "
                "and do not claim to see windows behind the foreground window."
            )
        if attached and source == "game":
            return "attached", (
                "LIVE GAME VISION STATUS: A foreground game-window frame captured while the user's "
                "Game Mode was manually enabled is attached to THIS request. Describe only visible "
                "evidence; this is not unrestricted desktop access."
            )
        if attached:
            return "attached_unknown_source", (
                "LIVE VISION STATUS: An image is attached, but its live-capture source could not be "
                "verified. Inspect only the image actually attached; do not infer other screen contents."
            )
        desktop = self.context.services.vision_application_service.desktop_capture_application_service
        if desktop.enabled:
            return "desktop_frame_not_attached", (
                "LIVE DESKTOP VISION STATUS: Desktop Vision is enabled, but no privacy-approved "
                "foreground-window frame was attached to this request. You cannot inspect live pixels "
                "in this turn and must not claim to see the desktop. Blocked or unidentified windows "
                "produce no image."
            )
        if not self.context.state._game_mode_enabled:
            return "vision_off", (
                "LIVE VISION STATUS: Both Game Mode and Live Desktop Vision are OFF. No live frame is "
                "available to this request. Do not claim to see the desktop or game. User-supplied image "
                "attachments, if present, are separate and may still be analyzed."
            )
        service = self.context.services.vision_application_service
        if not service.capture_allowed(
            self.context.state._game_mode_enabled,
            self.context.state._game_mode_profile,
            source="game",
        ):
            return "profile_blocks_capture", (
                "LIVE GAME VISION STATUS: Game Mode is on, but the selected profile does not permit "
                "screen capture. No live frame is attached; do not claim to see the game."
            )
        self.context.adapters.game_mode.poll()
        game = self.context.adapters.game_mode.last_game
        frame = self.context.state._latest_game_frame
        if not game:
            self.context.state._latest_game_frame = None
            return "no_game_window", (
                "LIVE GAME VISION STATUS: Game Mode is on, but no supported game window is detected "
                "in the foreground. No fallback whole-screen image is captured or attached."
            )
        exe = str(game.get("exe") or "game")[:80]
        if frame is None or frame.isNull():
            return "capture_failed", (
                f"LIVE GAME VISION STATUS: Foreground process {exe!r} was detected, but no permitted "
                "window frame was captured. No image is attached; do not claim to see its contents."
            )
        return "frame_not_attached", (
            "LIVE GAME VISION STATUS: A local game frame exists, but it was NOT attached to this "
            "provider request. You cannot inspect its pixels in this turn and must not claim to see it."
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
        vision_trace(
            "turn_context",
            status=code,
            game_mode=bool(self.context.state._game_mode_enabled),
            desktop_vision=bool(self.context.services.vision_application_service.desktop_capture_application_service.enabled),
            live_frame_flag=code == "attached",
            frame_source=_FRAME_SOURCE.get("value") if code == "attached" else None,
            images_in_turn=len(images or []),
            image_names=names[:200],
            **_game_fields(game),
        )
        return text

    def set_game_mode(self, enabled, *, announce=True):
        enabled = bool(enabled)
        was_enabled = self.context.state._game_mode_enabled
        self.context.state._game_mode_enabled = enabled
        permissions = self.context.services.game_mode_application_service.permissions(self.context.state._game_mode_profile)
        vision_allowed = bool(permissions["vision_capture"])
        audio_allowed = bool(permissions["game_audio_loopback"])
        vision_trace(
            "game_mode_set", enabled=enabled, profile=str(self.context.state._game_mode_profile),
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
            self.context.views.game_mode_btn.setToolTip("Game Mode خاموش است؛ برای فعال‌کردن دستی کلیک کن")
            if announce:
                self.feature_controller("session").add_chat("system", "🎮 Game Mode خاموش شد؛ تمام Captureها و شنود صدای بازی متوقف شدند.")
        elif self.context.services.game_mode_application_service.is_story(self.context.state._game_mode_profile):
            self.context.views.game_mode_btn.setToolTip("Story Mode فعال است؛ Vision و تحلیل محلی صدای بازی فعال‌اند")
            if announce:
                self.feature_controller("session").add_chat("system", "🎮 Story Mode فعال شد. Vision و تحلیل محلی صدای بازی فعال‌اند. دست‌کاری پردازش، حافظه یا ورودی بازی همچنان ممنوع است.")
        else:
            self.context.views.game_mode_btn.setToolTip("Competitive Safe فعال است؛ Vision فقط‌خواندنی فعال، بدون شنود بازی و کنترل دسکتاپ")
            if announce:
                self.feature_controller("session").add_chat("system", "🛡️ Competitive Safe فعال شد. Kira تصویر بازیِ پنجرهٔ فعال را فقط‌خواندنی تحلیل می‌کند؛ شنود صدای بازی و کنترل ورودی/دسکتاپ غیرفعال‌اند. فقط چت، جست‌وجوی وب و میکروفون/Wake Word مستقل هم فعال‌اند.")
        if enabled and vision_allowed and announce:
            self.feature_controller("session").add_chat("system", "🖥️ فقط فریم پنجرهٔ بازیِ فعال و پس از بررسی حریم خصوصی برای تحلیل استفاده می‌شود؛ اگر پنجرهٔ بازی شناسایی نشود، هیچ تصویر جایگزینی ارسال نمی‌شود.")

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
        """Capture only a supported foreground game window while Game Mode is enabled."""
        service = self.context.services.vision_application_service
        if not service.capture_allowed(
            self.context.state._game_mode_enabled,
            self.context.state._game_mode_profile,
            source="game",
        ):
            self.context.state._latest_game_frame = None
            service.reset()
            _trace_capture_state(None, None)
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            return
        self.context.adapters.game_mode.poll()
        window_info = self.context.adapters.game_mode.last_game
        if not service.capture_allowed(
            self.context.state._game_mode_enabled,
            self.context.state._game_mode_profile,
            source="game",
            window_info=window_info,
        ):
            self.context.state._latest_game_frame = None
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            if window_info:
                _allowed, reason = service.desktop_capture_application_service.evaluate_window(
                    window_info, explicit=True
                )
                vision_trace(
                    "capture_blocked",
                    exe=str(window_info.get("exe") or "")[:80],
                    reason=reason,
                )
            self._cancel_vision_worker()
            service.reset()
            return
        capture = self.context.adapters.game_mode.capture_service
        policy = service.policy
        pixmap = capture.capture_window(
            window_info, max_width=policy.max_width, max_height=policy.max_height
        )
        frame = pixmap.toImage() if pixmap is not None and not pixmap.isNull() else None
        self.context.state._latest_game_frame = frame
        _trace_capture_state(window_info, frame, "game" if frame is not None else None)
        self._submit_vision_frame(frame, "game", window_info)

    def _capture_desktop_frame(self):
        """Capture an approved foreground window only on the selected monitor."""
        service = self.context.services.vision_application_service
        privacy = service.desktop_capture_application_service
        capture = self.context.adapters.game_mode.capture_service
        window_info = capture.foreground_window_info()
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed:
            self.context.state._latest_game_frame = None
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            vision_trace(
                "capture_blocked",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason=reason,
            )
            self._cancel_vision_worker()
            service.reset()
            return
        policy = service.policy
        pixmap = capture.capture_window(
            window_info,
            monitor_id=privacy.selected_monitor_id or None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        frame = pixmap.toImage() if pixmap is not None and not pixmap.isNull() else None
        self.context.state._latest_game_frame = frame
        if frame is None:
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            vision_trace(
                "capture_skipped", source="desktop",
                exe=str(window_info.get("exe") or "")[:80],
                reason="capture_failed_or_window_outside_selected_monitor",
            )
            return
        self._submit_vision_frame(frame, "desktop", window_info)

    def _submit_vision_frame(self, frame, source, window_info):
        """Apply shared FrameGate and Worker path, retaining source/window for validation."""
        service = self.context.services.vision_application_service
        if frame is None or frame.isNull():
            return
        enabled = self.context.state._game_mode_enabled if source == "game" else True
        profile = self.context.state._game_mode_profile if source == "game" else None
        worker = self.context.session._vision_worker
        if not service.should_analyze(
            enabled=enabled,
            profile=profile,
            frame_available=True,
            worker_running=bool(worker is not None and worker.isRunning()),
            chat_busy=self.context.session.busy,
            provider_busy=self.context.session.client.busy,
            speech_active=self.context.services.voice_application_service.is_speaking(),
            source=source,
            window_info=window_info,
        ):
            return
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly) or not frame.save(
                buffer, "JPEG", service.policy.jpeg_quality
            ):
                return
            jpeg = bytes(data)
            thumbnail = frame.scaled(
                32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation
            ).convertToFormat(QImage.Format_Grayscale8)
            visual_sample = bytes(
                thumbnail.pixelColor(x, y).red()
                for y in range(thumbnail.height())
                for x in range(thumbnail.width())
            )
            if not service.accept_frame(jpeg, visual_sample=visual_sample):
                return
            name = "desktop-screen.jpg" if source == "desktop" else "game-screen.jpg"
            image = att.image_attachment(jpeg, name, "image/jpeg")
            session = self.context.state.cur
            self.context.session._vision_session = session
            self.context.session._vision_worker = VisionAnalysisWorker(
                self.context.session.client, image
            )
            _FRAME_SOURCE["value"] = source
            _FRAME_WINDOW_INFO["value"] = dict(window_info or {})
            vision_trace(
                "analysis_started",
                source=source,
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                jpeg_bytes=len(jpeg),
                width=frame.width(),
                height=frame.height(),
            )
            self.context.session._vision_worker.done.connect(session.relay.game_vision_done)
            self.context.session._vision_worker.finished.connect(session.relay.game_vision_finished)
            self.context.session._vision_worker.start()
        except Exception as exc:  # noqa: BLE001 - Vision must never interrupt chat
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            vision_trace("analysis_error", source=source, error=f"{type(exc).__name__}: {exc}")
            self.feature_controller("session").add_chat(
                "system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}"
            )

    def _send_pending_for_session(self, session):
        if self.context.state._closing or session is None or session.cid not in self.context.state.sessions:
            return
        self.feature_controller("runtime")._send_next_pending(session)

    def _on_game_vision_result(self, ok, result, latency_ms):
        service = self.context.services.vision_application_service
        source = _FRAME_SOURCE.get("value") or "game"
        captured = _FRAME_WINDOW_INFO.get("value") or {}
        current = self.context.adapters.game_mode.capture_service.foreground_window_info()
        same_window = (
            current is not None
            and int(current.get("hwnd") or 0) == int(captured.get("hwnd") or -1)
            and int(current.get("pid") or 0) == int(captured.get("pid") or -1)
        )
        service.mark_latency(latency_ms)
        stats = service.snapshot()
        self.context.views.game_mode_btn.setToolTip(
            f"Vision {stats['mode']} · تحلیل: {stats['analysis_count']} · "
            f"فریم تکراری ردشده: {stats['unchanged_skips']} · تأخیر آخرین تحلیل: {latency_ms}ms"
        )
        if not same_window:
            vision_trace(
                "analysis_discarded",
                source=source,
                exe=str(captured.get("exe") or "")[:80] or None,
                reason="foreground_window_changed",
            )
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            return
        message = service.consume_result(
            enabled=self.context.state._game_mode_enabled if source == "game" else True,
            profile=self.context.state._game_mode_profile if source == "game" else None,
            ok=ok,
            result=result,
            source=source,
            window_info=current,
        )
        vision_trace(
            "analysis_result",
            source=source,
            ok=bool(ok),
            latency_ms=int(latency_ms or 0),
            result_chars=len(str(result or "")),
        )
        if message is None:
            return
        if not ok:
            self.feature_controller("session").add_chat("system", "Vision: " + message[:300])
            return
        self.feature_controller("session").add_chat("system", "👁️ " + message[:900])

    def on_game_detected(self, info):
        """Suggest Game Mode once per detected process, unless the user already enabled it."""
        if self.context.state._game_mode_enabled:
            return
        name = info.get("title") or info.get("exe") or "بازی"
        note = (f"🎮 بازی «{name[:90]}» شناسایی شد. برای بازی آنلاین/PvP، Competitive Safe (تحلیل تصویری بدون کنترل بازی) و برای بازی داستانی، Story Mode (به‌همراه تحلیل صدای بازی) را انتخاب کن. انتخاب با خودت است.")
        self.feature_controller("session").add_chat("system", note)
        tray = getattr(self.context.views, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage("Ai1 · Game Mode", "بازی شناسایی شد. برای کمک در حین بازی، Game Mode را خودت فعال کن.",
                             QSystemTrayIcon.Information, 7000)

    def _live_vision_attachment(self):
        """Attach a privacy-approved crop of the foreground window to this chat request."""
        service = self.context.services.vision_application_service
        source = "game" if self.context.state._game_mode_enabled else "desktop"
        if source == "game":
            if not service.capture_allowed(
                self.context.state._game_mode_enabled,
                self.context.state._game_mode_profile,
                source="game",
            ):
                return None
            self.context.adapters.game_mode.poll()
            window_info = self.context.adapters.game_mode.last_game
        else:
            privacy = service.desktop_capture_application_service
            if not privacy.enabled:
                return None
            window_info = self.context.adapters.game_mode.capture_service.foreground_window_info()

        if not service.capture_allowed(
            self.context.state._game_mode_enabled if source == "game" else False,
            self.context.state._game_mode_profile if source == "game" else None,
            source=source,
            window_info=window_info,
        ):
            if window_info:
                _allowed, reason = service.desktop_capture_application_service.evaluate_window(
                    window_info, explicit=(source == "game")
                )
                vision_trace(
                    "capture_blocked",
                    exe=str(window_info.get("exe") or "")[:80],
                    reason=reason,
                )
            else:
                vision_trace(
                    "capture_blocked",
                    exe=None,
                    reason="foreground_window_unidentified",
                )
            return None

        privacy = service.desktop_capture_application_service
        policy = service.policy
        capture = self.context.adapters.game_mode.capture_service
        pixmap = capture.capture_window(
            window_info,
            monitor_id=(privacy.selected_monitor_id or None) if source == "desktop" else None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        frame = pixmap.toImage() if pixmap is not None and not pixmap.isNull() else None
        if frame is None:
            vision_trace(
                "attach_skip",
                source=source,
                exe=str(window_info.get("exe") or "")[:80],
                reason="foreground_window_capture_failed_or_outside_selected_monitor",
            )
            return None
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            quality = min(int(policy.jpeg_quality), int(CAPTURE_JPEG_QUALITY))
            if not buffer.open(QIODevice.WriteOnly) or not frame.save(buffer, "JPEG", quality):
                return None
            jpeg = bytes(data)
            name = "desktop-screen.jpg" if source == "desktop" else "game-screen.jpg"
            vision_trace(
                "attach_ok",
                source=source,
                exe=str(window_info.get("exe") or "")[:80],
                width=frame.width(),
                height=frame.height(),
                jpeg_bytes=len(jpeg),
            )
            return att.image_attachment(jpeg, name, "image/jpeg")
        except Exception as exc:  # noqa: BLE001 - a failed capture must not block ordinary chat
            vision_trace(
                "attach_error",
                source=source,
                exe=str(window_info.get("exe") or "")[:80],
                error=f"{type(exc).__name__}: {exc}",
            )
            self.feature_controller("session").add_chat(
                "system", f"تصویر پنجرهٔ فعال آماده نشد: {str(exc)[:180]}"
            )
            return None

    def _game_vision_attachment(self):
        """Backward-compatible Game Mode attachment facade."""
        if not self.context.state._game_mode_enabled:
            return None
        return self._live_vision_attachment()


# Backward-compatible import name for callers migrating from mixin composition.
AttachmentsVisionMixin = AttachmentsVisionController
