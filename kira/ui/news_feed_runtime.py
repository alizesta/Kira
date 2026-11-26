"""Qt runtime for first-run region confirmation and periodic news refresh."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot


class NewsFeedRuntime(QObject):
    """Keep news refreshes off the GUI thread and keep the confirmed region stable."""

    _windows_permission_result = Signal(bool)

    def __init__(self, parent, settings: dict, state, chat_client=None):
        super().__init__(parent)
        self.window = parent
        self.settings = settings
        self.state = state
        self.chat_client = chat_client
        self._worker = None
        self._location_operation = None
        self._busy = False
        self._pending_refresh = None
        self._shutting_down = False
        if not hasattr(self.state, "_news_feed_workers"):
            self.state._news_feed_workers = []
        self._windows_permission_result.connect(self._on_windows_permission_result)
        self.timer = QTimer(self)
        interval_hours = max(2, min(24, int(settings.get("news_feed_interval_hours", 6) or 6)))
        self.timer.setInterval(interval_hours * 60 * 60 * 1000)
        self.timer.timeout.connect(self.refresh_due)

    def shutdown(self) -> None:
        """Stop scheduling work; the app close protocol waits for any active worker."""
        self._shutting_down = True
        self.timer.stop()

    def start(self) -> None:
        if self._shutting_down or not self.settings.get("news_feed_enabled", True):
            return
        self.timer.start()
        if not self.settings.get("health_news_region_prompted", False):
            QTimer.singleShot(900, self._begin_region_setup)
        else:
            QTimer.singleShot(1800, self.refresh_due)

    def _begin_region_setup(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from ..location import request_windows_location_permission

        choice = QMessageBox.question(
            self.window,
            "تنظیم منطقهٔ میکا",
            "برای نمایش هشدارهای محلی سلامت، Kira باید شهر شما را یک‌بار تشخیص دهد و از شما تأیید بگیرد.\n\n"
            "ابتدا مجوز موقعیت مکانی Windows درخواست می‌شود. در صورت در دسترس نبودن آن، "
            "می‌توان شهر را از روی IP عمومی تخمین زد؛ VPN یا Proxy ممکن است نتیجه را اشتباه کند. "
            "در حالت IP، نشانی IP برای سرویس ipapi.co فرستاده می‌شود. فقط شهر/منطقهٔ تأییدشده "
            "در تنظیمات Kira ذخیره می‌شود؛ IP و مختصات ذخیره نمی‌شوند.\n\n"
            "ادامه می‌دهی؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if choice != QMessageBox.Yes:
            self._ask_for_region("", "manual")
            return

        operation = request_windows_location_permission(self._windows_permission_result.emit)
        if operation is not None:
            self._location_operation = operation
            return
        self._detect_ip_region()

    @Slot(bool)
    def _on_windows_permission_result(self, allowed: bool) -> None:
        self._location_operation = None
        if allowed:
            self._start_location_worker(prefer_windows=True)
        else:
            self._detect_ip_region()

    def _start_location_worker(self, *, prefer_windows: bool) -> None:
        from ..location import detect_ip_region, detect_windows_region
        from .workers import TaskWorker

        def detect():
            if prefer_windows:
                result = detect_windows_region()
                if result:
                    return result
            return detect_ip_region()

        self._start_worker(TaskWorker(detect), self._on_region_detected)

    def _detect_ip_region(self) -> None:
        from ..location import detect_ip_region
        from .workers import TaskWorker

        self._start_worker(TaskWorker(detect_ip_region), self._on_region_detected)

    def _on_region_detected(self, outcome) -> None:
        detected = None
        if isinstance(outcome, tuple) and outcome and outcome[0] is True:
            detected = outcome[1] if isinstance(outcome[1], dict) else None
        suggestion = str((detected or {}).get("region") or "").strip()
        source = str((detected or {}).get("source") or "manual")
        self._ask_for_region(suggestion, source)

    def _ask_for_region(self, suggestion: str, source: str) -> None:
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        from ..config import save_settings

        prompt = (
            "شهر و کشور را بررسی کن یا اصلاحش کن. این منطقه فقط برای خبرها و هشدارهای محلی میکا استفاده می‌شود."
        )
        if source == "ip_estimate":
            prompt += "\nاین فقط تخمین بر اساس IP است؛ اگر VPN روشن باشد ممکن است مکان سرور VPN باشد."
        elif source == "windows_location":
            prompt += "\nاین پیشنهاد از موقعیت مکانی Windows آمده است."
        region, accepted = QInputDialog.getText(
            self.window,
            "تأیید منطقهٔ سلامت",
            prompt,
            QLineEdit.Normal,
            suggestion,
        )
        confirmed = str(region or "").strip() if accepted else ""
        if confirmed:
            self.settings["health_news_region"] = confirmed[:160]
            self.settings["health_news_region_source"] = (
                source if confirmed.casefold() == suggestion.casefold() and suggestion else "manual"
            )
        else:
            self.settings["health_news_region"] = ""
            self.settings["health_news_region_source"] = ""
        self.settings["health_news_region_prompted"] = True
        try:
            save_settings(self.settings)
        except Exception:
            # Do not block Kira if settings storage is temporarily unavailable.
            self.settings["health_news_region_prompted"] = False
            return
        if confirmed:
            # First-run setup must prime every character, not only Mika.
            self.refresh_due(force=True)
        else:
            self.refresh_due(force=True)

    def region_changed(self) -> None:
        """Force Mika's local alert search after the user edits the saved region."""
        self.refresh_due(force=True, characters=("mika",))

    def _start_worker(self, worker, callback) -> None:
        worker.setParent(self.window)
        self._worker = worker
        self.state._news_feed_worker = worker
        registry = self.state._news_feed_workers
        if worker not in registry:
            registry.append(worker)
        worker.done.connect(callback)
        worker.finished.connect(lambda current=worker: self._on_worker_finished(current))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_worker_finished(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
        if getattr(self.state, "_news_feed_worker", None) is worker:
            self.state._news_feed_worker = None
        registry = getattr(self.state, "_news_feed_workers", [])
        if worker in registry:
            registry.remove(worker)

    def refresh_due(self, *, force: bool = False, characters=None) -> None:
        if self._shutting_down or not self.settings.get("news_feed_enabled", True):
            return
        if self._busy:
            if force:
                self._pending_refresh = (True, tuple(characters) if characters else None)
            return
        from .. import news_feed
        from .workers import TaskWorker

        selected = tuple(characters or ("mika", "ren", "kira"))
        settings_snapshot = dict(self.settings)
        interval = max(2, min(24, int(settings_snapshot.get("news_feed_interval_hours", 6) or 6)))
        cutoff = time.time() - interval * 3600

        def refresh():
            output = {}
            for character_id in selected:
                previous = news_feed.get_refresh_state(character_id)
                if (
                    not force
                    and previous
                    and previous.get("status") == "ok"
                    and float(previous.get("refreshed_at") or 0) > cutoff
                ):
                    continue
                chat_client = self.chat_client() if callable(self.chat_client) else self.chat_client
                output[character_id] = news_feed.refresh_character(
                    character_id,
                    settings_snapshot,
                    chat_client=chat_client,
                )
            return output

        self._busy = True
        worker = TaskWorker(refresh)
        self._start_worker(worker, self._on_refresh_complete)

    def _on_refresh_complete(self, _outcome) -> None:
        self._busy = False
        pending = self._pending_refresh
        self._pending_refresh = None
        if pending is not None:
            force, characters = pending
            QTimer.singleShot(
                0,
                lambda f=force, c=characters: self.refresh_due(force=f, characters=c),
            )
