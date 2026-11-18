"""Attachment and vision feature controller for the desktop window."""
from .main_window_attachments_vision_support import (
    AttachmentTile,
    CAPTURE_JPEG_QUALITY,
    GameAudioListener,
    QApplication,
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


class AttachmentsVisionController(WindowFeatureController):
    def capture_screen_attachment(self):
        """Capture the primary desktop only after an explicit user click; attach it for a normal Vision request."""
        try:
            screen = QApplication.primaryScreen()
            if screen is None:
                raise RuntimeError("نمایشگری برای ثبت تصویر پیدا نشد.")
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("ثبت تصویر صفحه ناموفق بود.")
            self.add_pasted_image(pixmap.toImage())
            self.feature_controller("session").add_chat("system", "🖥️ تصویر صفحه به پیوست‌ها اضافه شد؛ تا وقتی خودت پیام را نفرستی، برای مدل ارسال نمی‌شود.")
        except Exception as exc:
            self.feature_controller("session").add_chat("system", "ثبت تصویر صفحه ناموفق بود: " + str(exc)[:180])

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
        """Change analysis cadence without changing the manual Game Mode safety gate."""
        policy = self.context.services.vision_application_service.set_mode(mode)
        self.context.services.settings["vision_mode"] = policy.name
        save_settings(self.context.services.settings)
        if hasattr(self, "vision_rate_actions"):
            for key, action in self.context.views.vision_rate_actions.items():
                action.setChecked(key == policy.name)
        self.context.state._game_capture_timer.setInterval(max(250, int(policy.interval_seconds * 1000)))
        if self.context.services.vision_application_service.capture_allowed(self.context.state._game_mode_enabled, self.context.state._game_mode_profile):
            self._capture_game_frame()
            if not self.context.state._game_capture_timer.isActive():
                self.context.state._game_capture_timer.start()
        self.context.views.game_mode_btn.setToolTip(f"Game Mode · Vision {policy.name} · هر {policy.interval_seconds:g} ثانیه")

    def _set_game_vision_capture(self, allowed):
        """Synchronize capture permission and cancel in-flight analysis whenever Vision is disallowed."""
        allowed = bool(allowed)
        self.context.adapters.game_mode.set_enabled(allowed)
        if allowed:
            self._capture_game_frame()
            self.context.state._game_capture_timer.start()
        else:
            self.context.state._game_capture_timer.stop()
            self.context.state._latest_game_frame = None
            self.context.services.vision_application_service.reset()
            self._cancel_vision_worker()

    def _cancel_vision_worker(self):
        worker = getattr(self, "_vision_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel_request()

    def _stop_local_code_jobs(self):
        code_chat = getattr(self, "code_chat", None)
        session = getattr(code_chat, "session", None) if code_chat is not None else None
        if session is not None:
            with self.feature_controller("session")._as(session):
                self.context.services.coding_agent_application_service.stop_session(code_chat, session)

    def set_game_mode_profile(self, profile):
        """Apply a manually selected gameplay profile; never infer or enable it automatically."""
        self.context.state._game_mode_profile = self.context.services.game_mode_application_service.normalize_profile(profile)
        self.context.views.game_mode_story_action.setChecked(self.context.services.game_mode_application_service.is_story(self.context.state._game_mode_profile))
        self.context.views.game_mode_safe_action.setChecked(self.context.services.game_mode_application_service.is_competitive_safe(self.context.state._game_mode_profile))
        self.set_game_mode(True)

    def set_game_mode(self, enabled):
        enabled = bool(enabled)
        was_enabled = self.context.state._game_mode_enabled
        self.context.state._game_mode_enabled = enabled
        permissions = self.context.services.game_mode_application_service.permissions(self.context.state._game_mode_profile)
        vision_allowed = bool(permissions["vision_capture"])
        audio_allowed = bool(permissions["game_audio_loopback"])

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
            self.feature_controller("session").add_chat("system", "🎮 Game Mode خاموش شد؛ تمام Captureها و شنود صدای بازی متوقف شدند.")
        elif self.context.services.game_mode_application_service.is_story(self.context.state._game_mode_profile):
            self.context.views.game_mode_btn.setToolTip("Story Mode فعال است؛ Vision و تحلیل محلی صدای بازی فعال‌اند")
            self.feature_controller("session").add_chat("system", "🎮 Story Mode فعال شد. Vision و تحلیل محلی صدای بازی فعال‌اند. دست‌کاری پردازش، حافظه یا ورودی بازی همچنان ممنوع است.")
        else:
            self.context.views.game_mode_btn.setToolTip("Competitive Safe فعال است؛ بدون Vision، Capture، شنود بازی یا کنترل دسکتاپ")
            self.feature_controller("session").add_chat("system", "🛡️ Competitive Safe فعال شد. Vision، Capture، شنود صدای بازی و ابزارهای کنترل دسکتاپ/MCP مسدودند. فقط چت، جست‌وجوی وب و میکروفون/Wake Word مستقل فعال‌اند.")

    def _start_game_audio_listener(self):
        self._stop_game_audio_listener()
        self.context.adapters.game_audio_listener = GameAudioListener(self.context.services.settings, self.window)
        self.context.adapters.game_audio_listener.transcript.connect(self.on_game_audio_transcript)
        self.context.adapters.game_audio_listener.error.connect(self.on_game_audio_error)
        self.context.adapters.game_audio_listener.start()

    def _stop_game_audio_listener(self):
        listener = self.context.adapters.game_audio_listener
        self.context.adapters.game_audio_listener = None
        if listener is not None:
            listener.stop()
            if listener.isRunning():
                self._stopping_game_audio_listener = listener
                listener.finished.connect(lambda: setattr(self, "_stopping_game_audio_listener", None))

    def on_game_audio_error(self, message):
        if (self.context.state._game_mode_enabled
                and self.context.services.game_mode_application_service.permissions(self.context.state._game_mode_profile)["game_audio_loopback"]):
            self.feature_controller("session").add_chat("system", "🎧 " + message)

    def on_game_audio_transcript(self, text):
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
        """Capture a bounded frame and analyze only changed frames at the selected low-cost rate."""
        if not self.context.services.vision_application_service.capture_allowed(self.context.state._game_mode_enabled, self.context.state._game_mode_profile):
            self.context.state._latest_game_frame = None
            self.context.services.vision_application_service.reset()
            return
        # Re-check the foreground immediately before every capture; the slower
        # suggestion timer alone could leave a background game capturable for seconds.
        self.context.adapters.game_mode.poll()
        pixmap = self.context.adapters.game_mode.capture_last_game(
            self.context.services.vision_application_service.policy.max_width, self.context.services.vision_application_service.policy.max_height
        )
        self.context.state._latest_game_frame = pixmap.toImage() if pixmap is not None else None
        if not self.context.services.vision_application_service.should_analyze(
            enabled=self.context.state._game_mode_enabled,
            profile=self.context.state._game_mode_profile,
            frame_available=self.context.state._latest_game_frame is not None,
            worker_running=bool(self.context.session._vision_worker is not None and self.context.session._vision_worker.isRunning()),
            chat_busy=self.context.session.busy,
            provider_busy=self.context.session.client.busy,
            speech_active=self.context.services.voice_application_service.is_speaking(),
        ):
            return
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly):
                return
            if not self.context.state._latest_game_frame.save(buffer, "JPEG", self.context.services.vision_application_service.policy.jpeg_quality):
                return
            jpeg = bytes(data)
            # Compare a tiny grayscale thumbnail, not compressed JPEG bytes, to detect real scene changes.
            thumb = self.context.state._latest_game_frame.scaled(32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_Grayscale8)
            visual_sample = bytes(thumb.pixelColor(x, y).red() for y in range(thumb.height()) for x in range(thumb.width()))
            if not self.context.services.vision_application_service.accept_frame(jpeg, visual_sample=visual_sample):
                return
            image = att.image_attachment(jpeg, "game-screen.jpg", "image/jpeg")
            session = self.context.state.cur
            self.context.session._vision_session = session
            self.context.session._vision_worker = VisionAnalysisWorker(self.context.session.client, image)
            self.context.session._vision_worker.done.connect(session.relay.game_vision_done)
            self.context.session._vision_worker.finished.connect(session.relay.game_vision_finished)
            self.context.session._vision_worker.start()
        except Exception as exc:  # noqa: BLE001 - vision must never interrupt the game/chat
            self.feature_controller("session").add_chat("system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}")

    def _send_pending_for_session(self, session):
        if self.context.state._closing or session is None or session.cid not in self.context.state.sessions:
            return
        self.feature_controller("runtime")._send_next_pending(session)

    def _on_game_vision_result(self, ok, result, latency_ms):
        self.context.services.vision_application_service.mark_latency(latency_ms)
        stats = self.context.services.vision_application_service.snapshot()
        self.context.views.game_mode_btn.setToolTip(
            f"Vision {stats['mode']} · تحلیل: {stats['analysis_count']} · "
            f"فریم تکراری ردشده: {stats['unchanged_skips']} · تأخیر آخرین تحلیل: {latency_ms}ms"
        )
        message = self.context.services.vision_application_service.consume_result(
            enabled=self.context.state._game_mode_enabled,
            profile=self.context.state._game_mode_profile,
            ok=ok,
            result=result,
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
        note = (f"🎮 بازی «{name[:90]}» شناسایی شد. اگر آفلاین/داستانی است Story Mode و اگر آنلاین/PvP یا نامشخص است Competitive Safe را انتخاب کن. انتخاب با خودت است.")
        self.feature_controller("session").add_chat("system", note)
        tray = getattr(self, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage("Ai1 · Game Mode", "بازی شناسایی شد. برای کمک در حین بازی، Game Mode را خودت فعال کن.",
                             QSystemTrayIcon.Information, 7000)

    def _game_vision_attachment(self):
        """Attach only the newest 480p JPEG frame captured while Game Mode is manually enabled."""
        if (not self.context.services.vision_application_service.capture_allowed(self.context.state._game_mode_enabled, self.context.state._game_mode_profile)
                or self.context.state._latest_game_frame is None):
            return None
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly) or not self.context.state._latest_game_frame.save(buffer, "JPEG", CAPTURE_JPEG_QUALITY):
                return None
            return att.image_attachment(bytes(data), "game-screen.jpg", "image/jpeg")
        except Exception as exc:  # noqa: BLE001 - a failed capture must not block ordinary chat
            self.feature_controller("session").add_chat("system", f"تصویر بازی آماده نشد: {exc}")
            return None


# Backward-compatible import name for callers migrating from mixin composition.
AttachmentsVisionMixin = AttachmentsVisionController
