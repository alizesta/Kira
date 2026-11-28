"""Compact, character-separated news and health-region page."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTabBar, QTextBrowser, QVBoxLayout, QWidget,
)

from ...news_feed import CATEGORY_LABELS, is_relevant_character_news


class NewsFeedPage(QWidget):
    refresh_requested = Signal(str)
    region_confirm_requested = Signal(str)
    location_detection_requested = Signal()
    location_suggestion_ready = Signal(str, str, str, str)

    def __init__(self, service, settings: dict, parent=None):
        super().__init__(parent)
        self._service = service
        self._settings = settings if isinstance(settings, dict) else {}
        self._character_id = "kira"
        self.setObjectName("characterNewsFeedPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.character_tabs = QTabBar()
        self.character_tabs.setExpanding(False)
        self.character_tabs.setDrawBase(False)
        self.character_tabs.addTab("کیرا · بازی")
        self.character_tabs.addTab("رن · اقتصاد و فناوری")
        self.character_tabs.addTab("میکا · سلامت")
        self.character_tabs.currentChanged.connect(self._select_character)
        header.addWidget(self.character_tabs, 1)
        self.refresh_button = QPushButton("به‌روزرسانی")
        self.refresh_button.clicked.connect(self._request_refresh)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.status_label = QLabel("خبرهای هر شخصیت جداگانه نگهداری می‌شوند.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        region_box = QGroupBox("موقعیت میکا برای هشدارهای سلامت محلی")
        self.region_box = region_box
        region_layout = QVBoxLayout(region_box)
        region_row = QHBoxLayout()
        self.region_edit = QLineEdit()
        self.region_edit.setPlaceholderText("City, Country")
        region_row.addWidget(self.region_edit, 1)
        self.detect_button = QPushButton("تشخیص تقریبی")
        self.detect_button.clicked.connect(self.location_detection_requested.emit)
        region_row.addWidget(self.detect_button)
        self.confirm_button = QPushButton("تأیید و ذخیره")
        self.confirm_button.clicked.connect(lambda: self.region_confirm_requested.emit(self.region_edit.text()))
        region_row.addWidget(self.confirm_button)
        region_layout.addLayout(region_row)
        self.region_status = QLabel()
        self.region_status.setWordWrap(True)
        region_layout.addWidget(self.region_status)
        root.addWidget(region_box)
        self.region_box.hide()

        self.feed_browser = QTextBrowser()
        self.feed_browser.setOpenExternalLinks(True)
        self.feed_browser.setReadOnly(True)
        self.feed_browser.setFrameShape(QFrame.StyledPanel)
        root.addWidget(self.feed_browser, 1)

        self.location_suggestion_ready.connect(self.apply_location_suggestion)
        self._load_region_from_settings()
        region = self._settings.get("news_health_region") or {}
        if not (isinstance(region, dict) and region.get("confirmed") is True):
            self.character_tabs.setCurrentIndex(2)
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh_view)
        self._timer.start()
        self.refresh_view()

    def _load_region_from_settings(self):
        region = self._settings.get("news_health_region") or {}
        if isinstance(region, dict) and region.get("confirmed") is True:
            city, country = str(region.get("city") or "").strip(), str(region.get("country") or "").strip()
            self.region_edit.setText(f"{city}, {country}" if city and country else "")
            self.region_status.setText(f"موقعیت تأییدشده و ذخیره‌شده: {city}, {country}")
        else:
            self.region_status.setText(
                "ابتدا موقعیت دستگاه با مجوز سیستم بررسی می‌شود؛ اگر در دسترس نباشد، IP فقط پیشنهاد اولیه می‌دهد. تا تأیید تو هشدار محلی فعال نمی‌شود."
            )

    def _select_character(self, index: int):
        ids = ("kira", "ren", "mika")
        if 0 <= index < len(ids):
            self._character_id = ids[index]
            self.region_box.setVisible(self._character_id == "mika")
            self.refresh_view()

    def current_character_id(self) -> str:
        return self._character_id

    def _request_refresh(self):
        self.refresh_requested.emit(self._character_id)
        self.show_refreshing(self._character_id)

    def show_refreshing(self, character_id: str):
        if character_id == self._character_id:
            self.status_label.setText("در حال دریافت و ذخیرهٔ خبرهای همین شخصیت…")

    def apply_location_suggestion(self, city: str, country: str, source: str, error: str):
        self.detect_button.setEnabled(True)
        region = self._settings.get("news_health_region") or {}
        if city and country and not (isinstance(region, dict) and region.get("confirmed") is True):
            self.region_edit.setText(f"{city}, {country}")
            source_label = "موقعیت دستگاه (GPS)" if source == "device_gps" else "موقعیت تقریبی IP"
            self.region_status.setText(
                f"پیشنهاد {source_label}: {city}, {country} — هنوز تأیید نشده؛ برای ذخیره روی «تأیید و ذخیره» بزن."
            )
        elif error and not (isinstance(region, dict) and region.get("confirmed") is True):
            self.region_status.setText(
                "موقعیت دستگاه و IP دریافت نشد. شهر و کشور را دستی وارد کن؛ بدون تأیید، هشدار محلی میکا فعال نمی‌شود."
            )

    def set_region_confirmed(self, city: str, country: str):
        region = self._settings.get("news_health_region")
        if not isinstance(region, dict):
            region = {}
        region.update({"city": city, "country": country, "confirmed": True, "source": "user_confirmed"})
        self._settings["news_health_region"] = region
        self.region_edit.setText(f"{city}, {country}")
        self.region_status.setText(f"موقعیت تأییدشده و ذخیره‌شده: {city}, {country}")

    def refresh_view(self):
        items = [
            item for item in self._service.store.list_items(self._character_id, limit=25)
            if is_relevant_character_news(
                self._character_id, item.get("category"), item.get("title"), item.get("summary")
            )
        ]
        state = self._service.store.status(self._character_id)
        if self._service.is_refreshing(self._character_id):
            self.status_label.setText("در حال بروزرسانی… خبرهای قبلی تا پایان دریافت حفظ می‌شوند.")
        elif state.get("refreshed_at"):
            stamp = datetime.fromtimestamp(float(state["refreshed_at"]), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
            label = f"آخرین بررسی: {stamp} · {len(items)} خبر در پنجرهٔ ۷روزه"
            if state.get("last_error"):
                label += " · بعضی جست‌وجوها ناموفق بودند"
            self.status_label.setText(label)
        else:
            self.status_label.setText("هنوز فیدی ذخیره نشده است؛ برای دریافت خبرها به‌روزرسانی را بزن.")

        if not items:
            self.feed_browser.setHtml("<html><body><p>برای این شخصیت هنوز خبری در حافظهٔ هفت‌روزه ثبت نشده است.</p></body></html>")
            return
        cards = []
        for item in items:
            category = html.escape(CATEGORY_LABELS.get(item.get("category"), item.get("category", "خبر")))
            title = html.escape(str(item.get("title") or "خبر"))
            summary = html.escape(str(item.get("summary") or "خلاصه‌ای در منبع موجود نبود."))
            source = html.escape(str(item.get("source") or "منبع"))
            url = html.escape(str(item.get("url") or ""), quote=True)
            published = str(item.get("published_at") or "").strip()
            if not published:
                published = datetime.fromtimestamp(float(item.get("first_seen_at") or 0), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
                published = "زمان دریافت: " + published
            else:
                published = "انتشار: " + html.escape(published)
            cards.append(
                "<section style='margin:8px 0;padding:10px;border:1px solid #554b88;border-radius:9px;'>"
                f"<small>{category} · {published}</small><h3>{title}</h3><p>{summary}</p>"
                f"<a href='{url}'>{source} · مشاهدهٔ منبع</a></section>"
            )
        self.feed_browser.setHtml("<html><body>" + "".join(cards) + "</body></html>")

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_view()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
