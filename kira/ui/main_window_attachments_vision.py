"""Attachment and vision feature controller for the desktop window."""
from PySide6.QtCore import Slot
from ..request_trace import vision_trace
from ..perception import PerceptionEngine
from ..perception.events import PerceptionEvent
from ..vision_ocr import OcrResult, TesseractOcrEngine
from ..chat.attachment_content import format_desktop_context
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
    TaskWorker,
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
LIVE_VIDEO_MAX_WIDTH = 480
LIVE_VIDEO_MAX_HEIGHT = 270
LIVE_VIDEO_JPEG_QUALITY = 35
LIVE_VIDEO_CHANGE_THRESHOLD = 0.015
# 16 levels per RGB channel produce at most 4,096 distinct colors.
LIVE_VIDEO_CHANNEL_LEVELS = 16
LIVE_VIDEO_PALETTE_COLORS = LIVE_VIDEO_CHANNEL_LEVELS ** 3
_LIVE_VIDEO_CHANNEL_LUT = bytes(
    (((value * (LIVE_VIDEO_CHANNEL_LEVELS - 1) + 127) // 255) * 255
     + (LIVE_VIDEO_CHANNEL_LEVELS - 1) // 2)
    // (LIVE_VIDEO_CHANNEL_LEVELS - 1)
    for value in range(256)
)


def _quantize_live_video_image(image):
    """Reduce RGB channel precision while keeping a true-color JPEG stream."""
    if image is None or image.isNull():
        return image
    rgb = image.convertToFormat(QImage.Format_RGB888)
    quantized = bytes(rgb.constBits()).translate(_LIVE_VIDEO_CHANNEL_LUT)
    return QImage(
        quantized, rgb.width(), rgb.height(), rgb.bytesPerLine(),
        QImage.Format_RGB888,
    ).copy()


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
    def _perception_engine(self):
        engine = getattr(self, "_desktop_perception_engine", None)
        if engine is None:
            engine = PerceptionEngine(
                self.context.services.desktop_context_application_service,
                TesseractOcrEngine(),
            )
            self._desktop_perception_engine = engine
        return engine

    @staticmethod
    def _perception_sample(frame):
        thumbnail = frame.scaled(
            32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation
        ).convertToFormat(QImage.Format_Grayscale8)
        return bytes(
            thumbnail.pixelColor(x, y).red()
            for y in range(thumbnail.height())
            for x in range(thumbnail.width())
        )

    def _cancel_perception_worker(self):
        worker = self.context.state._perception_worker
        if worker is not None and worker.isRunning():
            worker.cancel()

    def _vision_interval_ms(self):
        base = max(
            250, int(self.context.services.vision_application_service.policy.interval_seconds * 1000)
        )
        return 1000 if getattr(self, "_live_video_active", False) else base

    def _clear_live_video_state(self):
        self._live_video_sample = b""
        self._live_video_identity = None
        self.feature_controller("runtime").clear_gemini_video_frames()

    def set_live_video_active(self, enabled):
        """Use a 1 Hz timer only while Live and a manual screen source are both active."""
        self._live_video_active = bool(enabled)
        source_active = bool(self.context.state._game_mode_enabled)
        timer = self.context.state._game_capture_timer
        timer.setInterval(self._vision_interval_ms())
        if not enabled:
            self._clear_live_video_state()
        if source_active and not self.context.state._closing:
            if not timer.isActive():
                timer.start()
            if enabled:
                self._capture_active_vision_frame()

    def _maybe_stream_gemini_live_frame(self, _frame, source, window_info):
        """Send a full-monitor JPEG after rechecking Live readiness and foreground privacy."""
        runtime = self.feature_controller("runtime")
        if not runtime.is_gemini_live_ready():
            return False
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        if source == "desktop":
            source_enabled = bool(privacy.enabled)
        elif source == "game":
            permissions = self.context.services.game_mode_application_service.permissions(
                self.context.state._game_mode_profile
            )
            source_enabled = bool(self.context.state._game_mode_enabled and permissions["vision_capture"])
        else:
            source_enabled = False
        if not source_enabled:
            self._clear_live_video_state()
            return False

        capture = self.context.adapters.game_mode.capture_service
        current = capture.foreground_window_info()
        service = self.context.services.vision_application_service
        permitted = service.capture_allowed(
            self.context.state._game_mode_enabled if source == "game" else False,
            self.context.state._game_mode_profile if source == "game" else None,
            source=source, window_info=current,
        )
        if not permitted:
            self._clear_live_video_state()
            vision_trace("live_video_blocked", source=source, reason="privacy_or_source_disabled")
            return False
        foreground_identity = (
            int(current.get("hwnd") or 0), int(current.get("pid") or 0),
            str(current.get("exe") or "").casefold(), str(current.get("title") or "").strip(),
            str(current.get("path") or "").casefold(),
        )
        expected = (
            int((window_info or {}).get("hwnd") or 0), int((window_info or {}).get("pid") or 0),
            str((window_info or {}).get("exe") or "").casefold(),
            str((window_info or {}).get("title") or "").strip(),
            str((window_info or {}).get("path") or "").casefold(),
        )
        # Desktop Eye Mode captures the selected monitor, not the foreground window.
        # Keep its Live stream stable while focus moves between applications.
        identity = (
            ("desktop-monitor", str(privacy.selected_monitor_id or "auto"))
            if source == "desktop" else foreground_identity
        )
        if not all(foreground_identity) or (source == "game" and foreground_identity != expected):
            self._clear_live_video_state()
            vision_trace("live_video_blocked", source=source, reason="foreground_changed")
            return False
        if identity != getattr(self, "_live_video_identity", None):
            runtime.clear_gemini_video_frames()
            self._live_video_sample = b""
            self._live_video_identity = identity

        monitor_id = privacy.selected_monitor_id if source == "desktop" else None
        pixmap = capture.capture_monitor_for_window(
            current, monitor_id=monitor_id or None,
            max_width=LIVE_VIDEO_MAX_WIDTH, max_height=LIVE_VIDEO_MAX_HEIGHT,
        )
        if pixmap is None or pixmap.isNull():
            self._clear_live_video_state()
            vision_trace("live_video_capture_skipped", source=source, reason="full_monitor_capture_failed")
            return False
        latest = capture.foreground_window_info()
        latest_identity = (
            int((latest or {}).get("hwnd") or 0), int((latest or {}).get("pid") or 0),
            str((latest or {}).get("exe") or "").casefold(),
            str((latest or {}).get("title") or "").strip(),
            str((latest or {}).get("path") or "").casefold(),
        )
        if (source == "game" and latest_identity != foreground_identity) or not service.capture_allowed(
            self.context.state._game_mode_enabled if source == "game" else False,
            self.context.state._game_mode_profile if source == "game" else None,
            source=source, window_info=latest,
        ):
            self._clear_live_video_state()
            vision_trace("live_video_blocked", source=source, reason="foreground_changed_during_capture")
            return False

        image = _quantize_live_video_image(pixmap.toImage())
        sample = self._perception_sample(image)
        previous = getattr(self, "_live_video_sample", b"")
        if previous and len(previous) == len(sample):
            delta = sum(abs(a - b) for a, b in zip(previous, sample))
            if delta / (255.0 * len(sample)) < LIVE_VIDEO_CHANGE_THRESHOLD:
                return False
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice

            def encode_jpeg(frame, quality):
                data = QByteArray()
                buffer = QBuffer(data)
                if not buffer.open(QIODevice.WriteOnly) or not frame.save(buffer, "JPEG", quality):
                    return b""
                return bytes(data)

            # Keep the normal frame small first; only step down further when necessary.
            encoded_image = image
            quality = LIVE_VIDEO_JPEG_QUALITY
            jpeg = encode_jpeg(encoded_image, quality)
            if len(jpeg) > MAX_VIDEO_FRAME_BYTES:
                for quality in (30, 25, 20):
                    jpeg = encode_jpeg(encoded_image, quality)
                    if jpeg and len(jpeg) <= MAX_VIDEO_FRAME_BYTES:
                        break
            if len(jpeg) > MAX_VIDEO_FRAME_BYTES:
                for width, height, quality in ((384, 216, 22), (320, 180, 20)):
                    encoded_image = image.scaled(
                        width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    jpeg = encode_jpeg(encoded_image, quality)
                    if jpeg and len(jpeg) <= MAX_VIDEO_FRAME_BYTES:
                        break
            if not jpeg or len(jpeg) > MAX_VIDEO_FRAME_BYTES:
                vision_trace(
                    "live_video_frame_dropped", source=source,
                    reason="frame_exceeds_size_limit", jpeg_bytes=len(jpeg),
                    max_bytes=MAX_VIDEO_FRAME_BYTES,
                    width=encoded_image.width(), height=encoded_image.height(),
                )
                return False
        except Exception as exc:  # a video path error must not interrupt audio
            vision_trace("live_video_encode_failed", source=source, error=type(exc).__name__)
            return False
        if not runtime.send_gemini_video_frame(jpeg):
            return False
        self._live_video_sample = sample
        vision_trace(
            "live_video_frame_queued", source=source,
            format="JPEG", width=encoded_image.width(), height=encoded_image.height(),
            jpeg_quality=quality, jpeg_bytes=len(jpeg),
            jpeg_kib=round(len(jpeg) / 1024.0, 2),
            max_bytes=MAX_VIDEO_FRAME_BYTES, fps=1,
            approx_kib_per_second=round(len(jpeg) / 1024.0, 2),
            color_levels=LIVE_VIDEO_CHANNEL_LEVELS,
            palette_colors=LIVE_VIDEO_PALETTE_COLORS,
        )
        return True

    def _queue_perception_ocr(self, frame, source, window_info):
        """Update safe app context immediately; OCR only follows a changed screen."""
        context = self.context.services.desktop_context_application_service
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        allowed, reason = privacy.evaluate_window(
            window_info, explicit=(source == "game")
        )
        if not allowed:
            context.clear_sensitive(
                exe=str((window_info or {}).get("exe") or ""),
                reason=reason,
            )
            self._cancel_perception_worker()
            vision_trace(
                "perception_blocked", source=source,
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason=reason,
            )
            return

        engine = self._perception_engine()
        previous_window = context.snapshot().get("active_window")
        normalized = engine.observe_window(window_info, source=source)
        if normalized is None:
            context.clear_sensitive(reason="foreground_window_unidentified")
            self._cancel_perception_worker()
            return

        current_identity = (
            int(normalized.get("hwnd") or 0),
            int(normalized.get("pid") or 0),
            str(normalized.get("exe") or "").casefold(),
            str(normalized.get("title") or "").strip(),
            str(normalized.get("path") or "").casefold(),
        )
        previous_identity = None
        if isinstance(previous_window, dict):
            previous_identity = (
                int(previous_window.get("hwnd") or 0),
                int(previous_window.get("pid") or 0),
                str(previous_window.get("exe") or "").casefold(),
                str(previous_window.get("title") or "").strip(),
                str(previous_window.get("path") or "").casefold(),
            )
        if previous_identity != current_identity:
            vision_trace(
                "perception_event",
                event_type="active_window_changed",
                source=source,
                exe=str(normalized.get("exe") or "")[:80] or None,
            )

        worker = self.context.state._perception_worker
        if worker is not None and worker.isRunning():
            # Do not advance the change detector while OCR is busy; the next timer
            # tick will compare the newest frame with the last processed sample.
            return
        sample = self._perception_sample(frame)
        if not engine.screen_changed(sample):
            return

        sample_key = PerceptionEvent.fingerprint(sample.hex())
        context.record_event(
            "screen_changed",
            "Visible foreground content changed",
            source=source,
            dedupe_key=f"screen:{source}:{sample_key}",
        )
        vision_trace(
            "perception_event",
            event_type="screen_changed",
            source=source,
            sample_id=sample_key,
        )
        settings = self.context.services.settings
        ocr_enabled = (
            bool(settings.get("desktop_vision_ocr_enabled", True))
            if source == "desktop"
            else bool(settings.get("vision_ocr_in_game_mode", False))
        )
        if not ocr_enabled:
            vision_trace("perception_change", source=source, ocr_enabled=False)
            return

        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly) or not frame.save(buffer, "JPEG", 65):
                vision_trace("perception_ocr_skipped", source=source, reason="jpeg_encode_failed")
                return
            jpeg = bytes(data)
        except Exception as exc:  # OCR must never interrupt live capture.
            vision_trace("perception_ocr_skipped", source=source, reason=type(exc).__name__)
            return

        started = time.monotonic()
        worker = TaskWorker(
            lambda cancelled, payload=jpeg, engine=engine: engine.recognize(payload, cancelled),
            cancellable=True,
        )
        self.context.state._perception_window_info = dict(normalized)
        self.context.state._perception_source = source
        self.context.state._perception_result = None
        self.context.state._perception_worker = worker
        self._perception_started_at = started
        worker.done.connect(self._on_perception_worker_done)
        worker.finished.connect(self._on_perception_worker_finished)
        worker.start()
        vision_trace(
            "perception_ocr_started", source=source,
            exe=str(normalized.get("exe") or "")[:80] or None,
            image_bytes=len(jpeg),
        )

    @Slot(object)
    def _on_perception_worker_done(self, result):
        self.context.state._perception_result = result

    @Slot()
    def _on_perception_worker_finished(self):
        worker = self.sender()
        source = self.context.state._perception_source or "desktop"
        captured = self.context.state._perception_window_info or {}
        outcome = self.context.state._perception_result
        self.context.state._perception_worker = None
        self.context.state._perception_window_info = None
        self.context.state._perception_source = None
        self.context.state._perception_result = None
        if worker is not None:
            worker.deleteLater()

        latency_ms = int(max(0.0, time.monotonic() - getattr(self, "_perception_started_at", time.monotonic())) * 1000)
        if not isinstance(outcome, tuple) or len(outcome) != 2 or not outcome[0]:
            vision_trace("perception_ocr_failed", source=source, latency_ms=latency_ms)
            return
        result = outcome[1]
        if not isinstance(result, OcrResult):
            return

        capture = self.context.adapters.game_mode.capture_service
        current = capture.foreground_window_info()
        same_window = (
            current is not None
            and int(current.get("hwnd") or 0) == int(captured.get("hwnd") or -1)
            and int(current.get("pid") or 0) == int(captured.get("pid") or -1)
            and str(current.get("exe") or "").casefold() == str(captured.get("exe") or "").casefold()
            and str(current.get("title") or "").strip() == str(captured.get("title") or "").strip()
            and str(current.get("path") or "").casefold() == str(captured.get("path") or "").casefold()
        )
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        source_enabled = (
            not bool(self.context.state._closing)
            and (
                bool(self.context.state._game_mode_enabled)
                if source == "game" else bool(privacy.enabled)
            )
        )
        allowed, reason = privacy.evaluate_window(
            current, explicit=(source == "game")
        )
        if not source_enabled:
            self.context.services.desktop_context_application_service.clear()
        elif not allowed:
            self.context.services.desktop_context_application_service.clear_sensitive(
                exe=str((current or {}).get("exe") or ""),
                reason=reason,
            )
        elif not same_window:
            # A title/PID/HWND change can occur before the next capture tick.
            # Update the current identity now so a chat turn cannot reuse old OCR.
            if current is None:
                self.context.services.desktop_context_application_service.clear_sensitive(
                    reason="foreground_window_unidentified"
                )
            else:
                self._perception_engine().observe_window(current, source=source)
        if not source_enabled or not same_window or not allowed:
            vision_trace(
                "perception_ocr_discarded", source=source,
                reason=("capture_source_disabled" if not source_enabled else
                        "foreground_changed" if not same_window else reason),
            )
            return

        applied = self._perception_engine().apply_ocr(result, current, source=source)
        if result.error_code:
            self.context.services.desktop_context_application_service.record_event(
                "ocr_unavailable",
                "Local OCR unavailable; application and window metadata remain available",
                source=source,
                dedupe_key=f"ocr-unavailable:{result.error_code}",
            )
        vision_trace(
            "perception_ocr_result", source=source, applied=applied,
            text_chars=len(result.text), language=result.language or None,
            confidence=round(result.confidence, 3), error=result.error_code or None,
            latency_ms=latency_ms,
        )

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
            self._vision_interval_ms()
        )
        if self.context.state._game_mode_enabled:
            self._capture_desktop_frame()
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
        """Eye Mode owns the only live capture source: the selected desktop monitor."""
        allowed = bool(allowed)
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        privacy.set_enabled(allowed)
        self.context.adapters.game_mode.set_enabled(allowed)
        if not allowed:
            self._cancel_vision_worker()
            self._cancel_perception_worker()
            self._clear_live_video_state()
            self.context.services.desktop_context_application_service.clear()
            self.context.state._game_capture_timer.stop()
            self.context.state._latest_game_frame = None
            self.context.services.vision_application_service.reset()
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            return
        # Drop any in-flight game-window result before switching the shared pipeline
        # to the selected-monitor source.
        self._cancel_vision_worker()
        self._cancel_perception_worker()
        self._clear_live_video_state()
        self.context.services.desktop_context_application_service.clear()
        self.context.services.vision_application_service.reset()
        _FRAME_SOURCE["value"] = None
        _FRAME_WINDOW_INFO["value"] = None
        self.context.state._game_capture_timer.setInterval(self._vision_interval_ms())
        self._capture_desktop_frame()
        self.context.state._game_capture_timer.start()

    def set_desktop_vision(self, enabled, *, announce=True):
        """Compatibility shim: legacy Desktop Vision requests now toggle Eye Mode."""
        return self.set_game_mode(bool(enabled), announce=announce)

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
        self._clear_live_video_state()
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
        """Eye Mode always captures the selected desktop monitor."""
        if self.context.state._game_mode_enabled:
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
            self._clear_live_video_state()
            self.context.services.vision_application_service.reset()
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
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
        window_info = self.context.adapters.game_mode.capture_service.foreground_window_info()
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
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
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        window_info = self.context.adapters.game_mode.capture_service.foreground_window_info()
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed:
            return "eye_mode_blocked", (
                f"EYE MODE STATUS: Capture is blocked by the privacy policy ({reason}). No current "
                "screen observation is available; do not claim to see the screen."
            )
        context_service = self.context.services.desktop_context_application_service
        if context_service.summary():
            return "eye_mode_monitoring", (
                "EYE MODE STATUS: Eye Mode is monitoring the selected monitor. The DESKTOP CONTEXT "
                "below contains recent timestamped visual observations and window facts accumulated "
                "over time. Use that timeline to understand what happened before the user's question. "
                "No new screenshot is captured just because the user sent a chat message. If the "
                "timeline has no recent observation, state that limitation instead of inventing details."
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
        else:
            context_service.clear()
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
        """Capture only a supported foreground game window while Game Mode is enabled."""
        service = self.context.services.vision_application_service
        if not service.capture_allowed(
            self.context.state._game_mode_enabled,
            self.context.state._game_mode_profile,
            source="game",
        ):
            self._clear_live_video_state()
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
            self._clear_live_video_state()
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
        # Live Gemini receives the complete monitor independently of the foreground-window crop.
        self._maybe_stream_gemini_live_frame(None, "game", window_info)
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
        """Capture the complete privacy-approved selected monitor."""
        service = self.context.services.vision_application_service
        privacy = service.desktop_capture_application_service
        capture = self.context.adapters.game_mode.capture_service
        window_info = capture.foreground_window_info()
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed:
            self._clear_live_video_state()
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
        # The same complete selected-monitor frame feeds live Gemini and local analysis.
        self._maybe_stream_gemini_live_frame(None, "desktop", window_info)
        policy = service.policy
        pixmap = capture.capture_monitor_for_window(
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
                reason="selected_monitor_capture_failed",
            )
            return
        self._submit_vision_frame(frame, "desktop", window_info)

    def _submit_vision_frame(self, frame, source, window_info):
        """Apply shared FrameGate and Worker path, retaining source/window for validation."""
        service = self.context.services.vision_application_service
        if frame is None or frame.isNull():
            return
        # The local Perception path is independent of cloud/model analysis busy state.
        self._queue_perception_ocr(frame, source, window_info)
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
            vision_router = getattr(self.context.services, "vision_router", None)
            if vision_router is None:
                raise RuntimeError("isolated Vision router is unavailable")
            self.context.session._vision_worker = VisionAnalysisWorker(
                vision_router,
                image,
                ocr_enabled=(
                    bool(self.context.services.settings.get("vision_ocr_in_game_mode", False))
                    if source == "game" else False
                ),
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
        privacy = service.desktop_capture_application_service
        desktop_source_active = (
            source == "desktop"
            and not bool(self.context.state._closing)
            and bool(self.context.state._game_mode_enabled)
            and bool(privacy.enabled)
        )
        desktop_allowed, desktop_block_reason = (
            privacy.evaluate_window(current) if desktop_source_active else (False, "source_disabled")
        )
        # A desktop frame represents the entire selected monitor. A foreground
        # switch after capture must not invalidate the visual analysis result.
        result_is_current = (
            (desktop_source_active and current is not None and desktop_allowed)
            if source == "desktop"
            else (same_window and bool(self.context.state._game_mode_enabled))
        )
        service.mark_latency(latency_ms)
        stats = service.snapshot()
        self.context.views.game_mode_btn.setToolTip(
            f"Vision {stats['mode']} · تحلیل: {stats['analysis_count']} · "
            f"فریم تکراری ردشده: {stats['unchanged_skips']} · تأخیر آخرین تحلیل: {latency_ms}ms"
        )
        if not result_is_current:
            vision_trace(
                "analysis_discarded",
                source=source,
                exe=str(captured.get("exe") or "")[:80] or None,
                reason=(
                    "capture_source_disabled" if source == "desktop" and not desktop_source_active
                    else desktop_block_reason if source == "desktop" and not desktop_allowed
                    else "foreground_window_changed"
                ),
            )
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            return
        if source == "desktop" and not same_window:
            vision_trace(
                "analysis_foreground_changed_accepted",
                source=source,
                captured_exe=str(captured.get("exe") or "")[:80] or None,
                current_exe=str((current or {}).get("exe") or "")[:80] or None,
                reason="selected_monitor_frame_is_independent_of_foreground_window",
            )
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
        if ok and self.context.state._game_mode_enabled:
            # Preserve each distinct model observation in the bounded desktop timeline.
            # Chat turns consume this history instead of triggering another screenshot.
            context_service = self.context.services.desktop_context_application_service
            context_service.record_event(
                "visual_observation",
                message[:240],
                source=source,
                dedupe_key=f"visual:{PerceptionEvent.fingerprint(message)}",
            )
            vision_trace(
                "visual_observation_recorded",
                source=source,
                observation_chars=len(message),
                history_events=len(context_service.snapshot().get("recent_events", ())),
            )
        if not ok:
            self.feature_controller("session").add_chat("system", "Vision: " + message[:300])
            return
        self.feature_controller("session").add_chat("system", "👁️ " + message[:900])

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

    def _live_vision_attachment(self):
        """Attach a privacy-approved frame from Eye Mode's selected monitor."""
        if not self.context.state._game_mode_enabled:
            return None
        service = self.context.services.vision_application_service
        privacy = service.desktop_capture_application_service
        if not privacy.enabled:
            return None
        capture = self.context.adapters.game_mode.capture_service
        window_info = capture.foreground_window_info()
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed or not service.capture_allowed(
            False, None, source="desktop", window_info=window_info
        ):
            vision_trace(
                "attach_blocked",
                source="desktop",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason=reason if not allowed else "eye_mode_source_disabled",
            )
            return None
        policy = service.policy
        pixmap = capture.capture_monitor_for_window(
            window_info,
            monitor_id=privacy.selected_monitor_id or None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        frame = pixmap.toImage() if pixmap is not None and not pixmap.isNull() else None
        if frame is None:
            vision_trace(
                "attach_skip",
                source="desktop",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason="selected_monitor_capture_failed",
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
            vision_trace(
                "attach_ok",
                source="desktop",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                width=frame.width(),
                height=frame.height(),
                jpeg_bytes=len(jpeg),
            )
            return att.image_attachment(jpeg, "eye-screen.jpg", "image/jpeg")
        except Exception as exc:  # noqa: BLE001 - a failed capture must not block ordinary chat
            vision_trace(
                "attach_error",
                source="desktop",
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.feature_controller("session").add_chat(
                "system", f"تصویر مانیتور انتخاب‌شده آماده نشد: {str(exc)[:180]}"
            )
            return None

    def _game_vision_attachment(self):
        """Backward-compatible Game Mode attachment facade."""
        if not self.context.state._game_mode_enabled:
            return None
        return self._live_vision_attachment()


# Backward-compatible import name for callers migrating from mixin composition.
AttachmentsVisionMixin = AttachmentsVisionController
