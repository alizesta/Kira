"""Attachment and vision feature controller for the desktop window."""
from PySide6.QtCore import Slot
from ..request_trace import vision_trace
from ..perception import PerceptionEngine
from ..perception.events import PerceptionEvent
from ..live_video_selector import LiveFrameSelector, SAMPLE_HEIGHT, SAMPLE_WIDTH, SelectorPolicy
from ..vision_orchestrator import FrameJob
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


def _live_gray_sample(image):
    """Small smoothed grayscale grid used only to decide whether the screen changed."""
    small = image.scaled(
        SAMPLE_WIDTH, SAMPLE_HEIGHT, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    ).convertToFormat(QImage.Format_Grayscale8)
    stride = small.bytesPerLine()
    raw = bytes(small.constBits())
    return b"".join(
        raw[row * stride:row * stride + SAMPLE_WIDTH] for row in range(SAMPLE_HEIGHT)
    )


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

    def _live_budget_values(self):
        """Frame budget from settings, clamped; bad or missing values fall back to the defaults."""
        settings = self.context.services.settings
        defaults = SelectorPolicy()
        try:
            interval = float(settings.get("eye_live_min_interval_seconds", defaults.min_interval_seconds))
        except (TypeError, ValueError):
            interval = defaults.min_interval_seconds
        try:
            per_minute = int(settings.get("eye_live_max_frames_per_minute", defaults.max_frames_per_minute))
        except (TypeError, ValueError):
            per_minute = defaults.max_frames_per_minute
        return max(1.0, min(interval, 60.0)), max(1, min(per_minute, 60))

    def live_video_budget(self):
        """Return the effective minimum interval and rolling per-minute frame cap."""
        return self._live_budget_values()

    def _live_policy(self):
        interval, per_minute = self._live_budget_values()
        return SelectorPolicy(
            mean_threshold=LIVE_VIDEO_CHANGE_THRESHOLD,
            min_interval_seconds=interval,
            max_frames_per_minute=per_minute,
        )

    def _live_selector(self):
        selector = getattr(self, "_live_frame_selector", None)
        if selector is None:
            selector = LiveFrameSelector(self._live_policy())
            self._live_frame_selector = selector
        return selector

    def set_live_frame_budget(self, interval_seconds, frames_per_minute):
        """Persist the Gemini Live frame budget and apply it to the running selector."""
        settings = self.context.services.settings
        settings["eye_live_min_interval_seconds"] = float(interval_seconds)
        settings["eye_live_max_frames_per_minute"] = int(frames_per_minute)
        save_settings(settings)
        self._live_selector().policy = self._live_policy()

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
        capture = self.context.adapters.game_mode.capture_service
        return [
            (monitor.id, monitor.name + (" · اصلی" if monitor.primary else ""))
            for monitor in capture.list_monitors()
        ]

    def build_eye_vision_page(self):
        """Settings page for Eye Mode; widgets live in the page, behaviour stays in this controller."""
        from .pages.eye_vision_page import EyeVisionPage

        session = self.feature_controller("session")
        privacy = self.context.services.vision_application_service.desktop_capture_application_service
        page = EyeVisionPage(session.t)
        page.set_monitors(self._eye_monitor_choices(), privacy.selected_monitor_id or "")
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
                page.select_monitor(privacy.selected_monitor_id or "")

        def refresh():
            page.set_monitors(self._eye_monitor_choices(), privacy.selected_monitor_id or "")
            page.set_profile(self.context.state._game_mode_profile)
            page.set_eye_enabled(bool(self.context.state._game_mode_enabled))

        page.monitor_selected.connect(select_monitor)
        page.refresh_requested.connect(refresh)
        page.bind_translations(session.reg)
        self._eye_vision_page = page
        return page

    def _clear_live_video_state(self):
        self._live_selector().reset()
        self._live_video_identity = None
        self.feature_controller("runtime").clear_gemini_video_frames()

    def set_live_video_active(self, enabled):
        """Use a 1 Hz timer only while Live and a manual screen source are both active."""
        self._live_video_active = bool(enabled)
        if enabled:
            # A new Live session has seen no frame yet, even if the screen has not changed.
            self._live_selector().reset()
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

    def _maybe_stream_gemini_live_frame(self, _frame, source, window_info, *, frame_context=None):
        """Send a full-monitor JPEG after rechecking Live readiness and foreground privacy."""
        runtime = self.feature_controller("runtime")
        if not runtime.is_gemini_live_ready():
            return False
        # Imported here: Live is already running at this point and startup stays deferred.
        from ..gemini_live import MAX_VIDEO_FRAME_BYTES
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
        allow_partial_identity = source == "desktop"
        current = capture.foreground_window_info(
            allow_partial_identity=allow_partial_identity
        )
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
        if source == "game" and (not all(foreground_identity) or foreground_identity != expected):
            self._clear_live_video_state()
            vision_trace("live_video_blocked", source=source, reason="foreground_changed")
            return False
        if identity != getattr(self, "_live_video_identity", None):
            runtime.clear_gemini_video_frames()
            self._live_selector().reset()
            self._live_video_identity = identity

        monitor_id = privacy.selected_monitor_id if source == "desktop" else None
        if frame_context is not None and not self.context.services.vision_application_service.frame_orchestrator.is_current(frame_context):
            return False
        if _frame is not None and not _frame.isNull():
            frame_image = _frame
        else:
            pixmap = capture.capture_monitor_for_window(
                current, monitor_id=monitor_id or None,
                max_width=LIVE_VIDEO_MAX_WIDTH, max_height=LIVE_VIDEO_MAX_HEIGHT,
            )
            frame_image = pixmap.toImage() if pixmap is not None and not pixmap.isNull() else None
        if frame_image is None or frame_image.isNull():
            self._clear_live_video_state()
            vision_trace("live_video_capture_skipped", source=source, reason="full_monitor_capture_failed")
            return False
        latest = capture.foreground_window_info(
            allow_partial_identity=allow_partial_identity
        )
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

        image = _quantize_live_video_image(frame_image)
        selector = self._live_selector()
        sample = _live_gray_sample(image)
        decision = selector.evaluate(sample)
        if not decision.send:
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
        selector.commit(sample)
        vision_trace(
            "live_video_frame_queued", source=source,
            frame_id=frame_context.frame_id if frame_context is not None else None,
            session_id=frame_context.session_id if frame_context is not None else None,
            reason=decision.reason, mean_change=round(decision.mean_change, 4),
            changed_cells=decision.changed_cells,
            skipped_unchanged=selector.skipped_unchanged,
            skipped_rate_limited=selector.skipped_rate_limited,
            format="JPEG", width=encoded_image.width(), height=encoded_image.height(),
            jpeg_quality=quality, jpeg_bytes=len(jpeg),
            jpeg_kib=round(len(jpeg) / 1024.0, 2),
            max_bytes=MAX_VIDEO_FRAME_BYTES, gate_max_fps=1,
            min_interval_seconds=selector.policy.min_interval_seconds,
            max_frames_per_minute=selector.policy.max_frames_per_minute,
            approx_kib_per_frame=round(len(jpeg) / 1024.0, 2),
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
        current = capture.foreground_window_info(
            allow_partial_identity=(source == "desktop")
        )
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
        session = self.context.session
        session_id = (
            getattr(session, "session_id", None)
            or getattr(session, "cid", None)
            or "default"
        )
        service = getattr(self.context.services, "vision_application_service", None)
        if service is not None:
            service.frame_orchestrator.cancel_session(session_id)
        session._vision_frame_context = None
        worker = getattr(session, "_vision_worker", None)
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
        window_info = self.context.adapters.game_mode.capture_service.foreground_window_info(
            allow_partial_identity=True
        )
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
        """Capture one frame and let the orchestrator choose its sole cloud consumer."""
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
                vision_trace("capture_blocked", exe=str(window_info.get("exe") or "")[:80], reason=reason)
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
        if frame is None:
            return
        frame_context, decision = self._submit_vision_frame(frame, "game", window_info)
        if decision is not None and decision.route == "live":
            # The game source still streams the complete monitor; route ownership is
            # decided against the same immutable capture context as local analysis.
            self._maybe_stream_gemini_live_frame(
                None, "game", window_info, frame_context=frame_context
            )

    def _capture_desktop_frame(self):
        """Capture the selected monitor once and share that frame across eligible routes."""
        service = self.context.services.vision_application_service
        privacy = service.desktop_capture_application_service
        capture = self.context.adapters.game_mode.capture_service
        window_info = capture.foreground_window_info(allow_partial_identity=True)
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
        frame_context, decision = self._submit_vision_frame(frame, "desktop", window_info)
        if decision is not None and decision.route == "live":
            self._maybe_stream_gemini_live_frame(
                frame, "desktop", window_info, frame_context=frame_context
            )

    def _submit_vision_frame(self, frame, source, window_info):
        """Create one immutable frame context and select exactly one cloud route."""
        service = self.context.services.vision_application_service
        if frame is None or frame.isNull():
            return None, None
        # Local OCR/perception is a separate on-device capability, not a cloud route.
        self._queue_perception_ocr(frame, source, window_info)
        enabled = self.context.state._game_mode_enabled if source == "game" else True
        profile = self.context.state._game_mode_profile if source == "game" else None
        worker = self.context.session._vision_worker
        analysis_allowed = service.should_analyze(
            enabled=enabled,
            profile=profile,
            frame_available=True,
            worker_running=False,
            chat_busy=self.context.session.busy,
            provider_busy=self.context.session.client.busy,
            speech_active=self.context.services.voice_application_service.is_speaking(),
            source=source,
            window_info=window_info,
        )
        runtime = self.feature_controller("runtime")
        live_ready = bool(runtime.is_gemini_live_ready())
        session_id = (
            getattr(self.context.session, "session_id", None)
            or getattr(self.context.session, "cid", None)
            or "default"
        )
        orchestrator = service.frame_orchestrator
        frame_context = orchestrator.create_context(session_id, source, window_info)
        decision = orchestrator.decide(
            frame_context, live_ready=live_ready, analysis_allowed=analysis_allowed
        )
        vision_trace(
            "frame_route_decided",
            frame_id=frame_context.frame_id,
            session_id=frame_context.session_id,
            source=source,
            route=decision.route,
            reason=decision.reason,
            generation=frame_context.generation,
        )
        if decision.route != orchestrator.ANALYSIS:
            return frame_context, decision
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly) or not frame.save(
                buffer, "JPEG", service.policy.jpeg_quality
            ):
                return frame_context, decision
            jpeg = bytes(data)
            thumbnail = frame.scaled(
                32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation
            ).convertToFormat(QImage.Format_Grayscale8)
            visual_sample = bytes(
                thumbnail.pixelColor(x, y).red()
                for y in range(thumbnail.height())
                for x in range(thumbnail.width())
            )
            if not service.enqueue_frame(FrameJob(frame_context, jpeg, visual_sample)):
                return frame_context, decision
            self._dispatch_next_vision_job()
        except Exception as exc:  # noqa: BLE001 - Vision must never interrupt chat
            _FRAME_SOURCE["value"] = None
            _FRAME_WINDOW_INFO["value"] = None
            vision_trace("analysis_error", source=source, error=f"{type(exc).__name__}: {exc}")
            self.feature_controller("session").add_chat(
                "system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}"
            )
        return frame_context, decision

    def _dispatch_next_vision_job(self):
        """Dispatch the newest queued frame only when its owning session is ready."""
        service = self.context.services.vision_application_service
        session = self.context.session
        if self.context.state._closing or session is None:
            service.frame_orchestrator.cancel_all()
            return
        active = getattr(session, "_vision_worker", None)
        if active is not None and active.isRunning():
            return
        job = service.take_next_frame()
        if job is None:
            return
        frame_context = job.context
        session_id = str(
            getattr(session, "session_id", None)
            or getattr(session, "cid", None)
            or "default"
        )
        if session_id != frame_context.session_id or not service.frame_context_is_current(frame_context):
            vision_trace(
                "analysis_discarded", frame_id=frame_context.frame_id,
                session_id=frame_context.session_id, source=frame_context.source,
                reason="stale_session_context",
            )
            return
        source = frame_context.source
        enabled = self.context.state._game_mode_enabled if source == "game" else True
        profile = self.context.state._game_mode_profile if source == "game" else None
        window_info = {
            "hwnd": frame_context.window_identity[0],
            "pid": frame_context.window_identity[1],
            "exe": frame_context.window_identity[2],
            "title": frame_context.window_identity[3],
            "path": frame_context.window_identity[4],
        }
        if not service.should_analyze(
            enabled=enabled, profile=profile, frame_available=True,
            worker_running=False, chat_busy=session.busy, provider_busy=session.client.busy,
            speech_active=self.context.services.voice_application_service.is_speaking(),
            source=source, window_info=window_info,
        ):
            return
        if not service.accept_frame(job.payload, visual_sample=job.visual_sample):
            return
        image_name = "desktop-screen.jpg" if source == "desktop" else "game-screen.jpg"
        image = att.image_attachment(job.payload, image_name, "image/jpeg")
        try:
            router = getattr(self.context.services, "vision_router", None)
            if router is None:
                raise RuntimeError("isolated Vision router is unavailable")
            worker = VisionAnalysisWorker(
                router, image,
                ocr_enabled=(
                    bool(self.context.services.settings.get("vision_ocr_in_game_mode", False))
                    if source == "game" else False
                ),
            )
            session._vision_session = session
            session._vision_frame_context = frame_context
            session._vision_worker = worker
            _FRAME_SOURCE["value"] = source
            _FRAME_WINDOW_INFO["value"] = window_info
            vision_trace(
                "analysis_started", frame_id=frame_context.frame_id,
                session_id=frame_context.session_id, source=source,
                jpeg_bytes=len(job.payload),
            )
            worker.done.connect(session.relay.game_vision_done)
            worker.finished.connect(session.relay.game_vision_finished)
            worker.start()
        except Exception as exc:
            vision_trace(
                "analysis_error", frame_id=frame_context.frame_id,
                session_id=frame_context.session_id, source=source,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.feature_controller("session").add_chat(
                "system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}"
            )

    def _send_pending_for_session(self, session):
        if self.context.state._closing or session is None or session.cid not in self.context.state.sessions:
            return
        self.feature_controller("runtime")._send_next_pending(session)

    def _on_game_vision_result(self, ok, result, latency_ms):
        service = self.context.services.vision_application_service
        frame_context = getattr(self.context.session, "_vision_frame_context", None)
        if frame_context is not None and not service.frame_orchestrator.is_current(frame_context):
            vision_trace(
                "analysis_discarded",
                frame_id=frame_context.frame_id,
                session_id=frame_context.session_id,
                source=frame_context.source,
                reason="stale_session_generation",
            )
            self.context.session._vision_frame_context = None
            return
        self.context.session._vision_frame_context = None
        source = frame_context.source if frame_context is not None else (_FRAME_SOURCE.get("value") or "game")
        captured = (
            {
                "hwnd": frame_context.window_identity[0],
                "pid": frame_context.window_identity[1],
                "exe": frame_context.window_identity[2],
                "title": frame_context.window_identity[3],
                "path": frame_context.window_identity[4],
            }
            if frame_context is not None else (_FRAME_WINDOW_INFO.get("value") or {})
        )
        current = self.context.adapters.game_mode.capture_service.foreground_window_info(
            allow_partial_identity=(source == "desktop")
        )
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
            # Failed background observations stay in diagnostics; they are not
            # presented as if Kira were replying to the user.
            vision_trace("visual_observation_not_presented", source=source, reason="analysis_failed")
            return
        # Successful observations are stored in the rolling desktop context and
        # consumed by the next conversational reply. Do not dump the model's raw
        # analysis into chat as a fake assistant/system utterance.
        vision_trace(
            "visual_observation_ready_for_chat",
            source=source,
            observation_chars=len(message),
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

    def _live_vision_attachment(self):
        """Attach a privacy-approved frame from Eye Mode's selected monitor."""
        if not self.context.state._game_mode_enabled:
            return None
        service = self.context.services.vision_application_service
        privacy = service.desktop_capture_application_service
        if not privacy.enabled:
            return None
        capture = self.context.adapters.game_mode.capture_service
        window_info = capture.foreground_window_info(allow_partial_identity=True)
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
