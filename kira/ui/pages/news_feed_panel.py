"""Compact live news feed embedded in each character's chat screen."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout,
)

from ...news_feed import CATEGORY_LABELS, CHARACTER_IDS


_CHARACTER_LABELS = {
    "kira": "کیرا · اخبار بازی و سخت‌افزار",
    "ren": "رن · اقتصاد، بازار و فناوری",
    "mika": "میکا · پزشکی و سلامت عمومی",
}


class NewsFeedPanel(QFrame):
    """Always-visible, collapsible headline panel scoped to the character in front."""

    refresh_requested = Signal(str)
    location_detection_requested = Signal()
    region_confirm_requested = Signal(str)
    location_suggestion_ready = Signal(str, str, str, str)

    def __init__(self, service, settings: dict, parent=None):
        super().__init__(parent)
        self._service = service
        self._settings = settings if isinstance(settings, dict) else {}
        self._character_id = "kira"
        self._expanded = True
        self.setObjectName("newsFeedPanel")
        self.setMaximumHeight(148)
        self.setMaximumWidth(234)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        header = QHBoxLayout()
        self.title_label = QLabel(_CHARACTER_LABELS["kira"])
        self.title_label.setObjectName("newsFeedTitle")
        self.title_label.setMinimumWidth(0)
        header.addWidget(self.title_label, 1)
        self.status_label = QLabel("در حال آماده‌سازی فید خبر…")
        self.status_label.setObjectName("newsFeedStatus")
        self.status_label.setMaximumWidth(72)
        self.status_label.setMinimumWidth(0)
        header.addWidget(self.status_label)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("newsFeedRefresh")
        self.refresh_button.setToolTip("به‌روزرسانی خبرهای این شخصیت")
        self.refresh_button.setFixedWidth(30)
        self.refresh_button.clicked.connect(self._request_refresh)
        header.addWidget(self.refresh_button)
        self.toggle_button = QPushButton("⌃")
        self.toggle_button.setObjectName("newsFeedToggle")
        self.toggle_button.setToolTip("جمع‌کردن فید خبر")
        self.toggle_button.setFixedWidth(30)
        self.toggle_button.clicked.connect(self._toggle)
        header.addWidget(self.toggle_button)
        outer.addLayout(header)

        self.content = QFrame(self)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        self.region_row = QFrame(self.content)
        self.region_row.setObjectName("newsFeedRegionRow")
        region_layout = QVBoxLayout(self.region_row)
        region_layout.setContentsMargins(0, 0, 0, 0)
        region_layout.setSpacing(2)
        self.region_status = QLabel()
        self.region_status.setObjectName("newsFeedRegionStatus")
        self.region_status.setWordWrap(True)
        region_layout.addWidget(self.region_status)
        region_controls = QHBoxLayout()
        region_controls.setContentsMargins(0, 0, 0, 0)
        region_controls.setSpacing(3)
        self.region_edit = QLineEdit()
        self.region_edit.setObjectName("newsFeedRegionEdit")
        self.region_edit.setPlaceholderText("City, Country")
        self.region_edit.setMinimumWidth(0)
        region_controls.addWidget(self.region_edit, 1)
        self.detect_button = QPushButton("GPS/IP")
        self.detect_button.setObjectName("newsFeedDetectLocation")
        self.detect_button.setToolTip("اول GPS دستگاه و در صورت نبود آن موقعیت تقریبی IP")
        self.detect_button.setFixedWidth(46)
        self.detect_button.clicked.connect(self.location_detection_requested.emit)
        region_controls.addWidget(self.detect_button)
        self.confirm_button = QPushButton("✓")
        self.confirm_button.setObjectName("newsFeedConfirmLocation")
        self.confirm_button.setToolTip("ذخیرهٔ شهر و کشور برای هشدارهای محلی میکا")
        self.confirm_button.setFixedWidth(28)
        self.confirm_button.clicked.connect(
            lambda: self.region_confirm_requested.emit(self.region_edit.text())
        )
        region_controls.addWidget(self.confirm_button)
        region_layout.addLayout(region_controls)
        content_layout.addWidget(self.region_row)

        self.feed_browser = QTextBrowser(self.content)
        self.feed_browser.setObjectName("newsFeedHeadlines")
        self.feed_browser.setOpenLinks(False)
        self.feed_browser.setOpenExternalLinks(True)
        self.feed_browser.setReadOnly(True)
        self.feed_browser.setFrameShape(QFrame.NoFrame)
        self.feed_browser.setMinimumHeight(42)
        self.feed_browser.setMaximumHeight(66)
        content_layout.addWidget(self.feed_browser)
        outer.addWidget(self.content)
        tail = QHBoxLayout()
        tail.setContentsMargins(0, -5, 14, 0)
        tail.setSpacing(2)
        tail.addStretch(1)
        small_dot = QLabel("●", self)
        small_dot.setObjectName("newsFeedBubbleTailSmall")
        large_dot = QLabel("●", self)
        large_dot.setObjectName("newsFeedBubbleTailLarge")
        tail.addWidget(small_dot)
        tail.addWidget(large_dot)
        outer.addLayout(tail)

        self.location_suggestion_ready.connect(self.apply_location_suggestion)
        self._load_region()
        self._timer = QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self.refresh_view)
        self._timer.start()
        self.set_character("kira")

    def _load_region(self):
        region = self._settings.get("news_health_region") or {}
        if isinstance(region, dict) and region.get("confirmed") is True:
            city = str(region.get("city") or "").strip()
            country = str(region.get("country") or "").strip()
            self.region_edit.setText(f"{city}, {country}" if city and country else "")
            self.region_status.setText(f"موقعیت تأییدشده: {city}, {country}")
        else:
            self.region_status.setText("موقعیت میکا هنوز تأیید نشده؛ پیشنهاد GPS/IP را بررسی و تأیید کن.")

    def set_character(self, character_id: str):
        cid = str(character_id or "").strip().lower()
        self._character_id = cid
        self.title_label.setText(
            _CHARACTER_LABELS.get(cid, f"{cid or 'شخصیت'} · فید خبری اختصاصی تعریف نشده")
        )
        is_mika = cid == "mika"
        self.region_row.setVisible(is_mika)
        self.refresh_button.setEnabled(cid in CHARACTER_IDS)
        self.refresh_view()

    def _request_refresh(self):
        if self._character_id not in CHARACTER_IDS:
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText("در حال دریافت…")
        self.refresh_requested.emit(self._character_id)

    def show_refreshing(self, character_id: str):
        if str(character_id) == self._character_id:
            self.status_label.setText("در حال دریافت خبرهای همین شخصیت…")
            self.refresh_button.setEnabled(False)

    def apply_location_suggestion(self, city: str, country: str, source: str, error: str):
        self.detect_button.setEnabled(True)
        region = self._settings.get("news_health_region") or {}
        if isinstance(region, dict) and region.get("confirmed") is True:
            return
        if city and country:
            self.region_edit.setText(f"{city}, {country}")
            source_label = "GPS دستگاه" if source == "device_gps" else "IP"
            self.region_status.setText(
                f"پیشنهاد {source_label}: {city}, {country} · هنوز ذخیره نشده؛ برای تأیید دکمه را بزن."
            )
        elif error:
            self.region_status.setText(
                "موقعیت خودکار پیدا نشد؛ شهر و کشور را دستی وارد کن. تا تأیید، هشدار محلی فعال نمی‌شود."
            )

    def set_region_confirmed(self, city: str, country: str):
        region = self._settings.get("news_health_region")
        if not isinstance(region, dict):
            region = {}
        region.update({
            "city": city,
            "country": country,
            "confirmed": True,
            "source": "user_confirmed",
        })
        self._settings["news_health_region"] = region
        self.region_edit.setText(f"{city}, {country}")
        self.region_status.setText(f"موقعیت تأییدشده و ذخیره‌شده: {city}, {country}")

    def refresh_view(self):
        cid = self._character_id
        if cid not in CHARACTER_IDS:
            self.status_label.setText("برای این شخصیت فید خبری تعریف نشده است.")
            self.feed_browser.setHtml("<p>این شخصیت فید خبری اختصاصی ندارد.</p>")
            return

        items = self._service.store.list_items(cid, limit=2)
        state = self._service.store.status(cid)
        refreshing = self._service.is_refreshing(cid)
        if refreshing:
            self.status_label.setText("در حال دریافت خبرهای تازه…")
            self.refresh_button.setEnabled(False)
        else:
            self.refresh_button.setEnabled(True)
            if state.get("refreshed_at"):
                checked = datetime.fromtimestamp(
                    float(state["refreshed_at"]), tz=timezone.utc
                ).astimezone().strftime("%H:%M")
                text = f"{len(items)} خبر · بررسی {checked}"
                if state.get("last_error"):
                    text += " · برخی منابع در دسترس نبودند"
                self.status_label.setText(text)
            elif state.get("last_error"):
                self.status_label.setText("دریافت خبر ناموفق بود · دوباره تلاش کن")
            else:
                self.status_label.setText("فید در حال آماده‌شدن است")

        if not items:
            message = (
                "در حال دریافت نخستین خبرها…" if refreshing
                else "هنوز خبری دریافت نشده؛ دکمهٔ ↻ را بزن تا دوباره جست‌وجو شود."
            )
            self.feed_browser.setHtml(
                "<html><body style='margin:4px'><span>" + html.escape(message) + "</span></body></html>"
            )
            return

        cards = []
        for item in items:
            category = html.escape(CATEGORY_LABELS.get(item.get("category"), item.get("category", "خبر")))
            title = html.escape(str(item.get("title") or "خبر"))
            summary = html.escape(str(item.get("summary") or "برای جزئیات منبع را باز کن."))
            source = html.escape(str(item.get("source") or "منبع"))
            url = html.escape(str(item.get("url") or ""), quote=True)
            published = html.escape(str(item.get("published_at") or ""))
            if not published:
                published = datetime.fromtimestamp(
                    float(item.get("first_seen_at") or 0), tz=timezone.utc
                ).astimezone().strftime("%m-%d %H:%M")
            cards.append(
                "<div style='margin:2px 0;padding:2px 4px;border-left:2px solid #8d65ff;'>"
                f"<small>{category} · {published}</small> "
                f"<a href='{url}' style='font-weight:600;text-decoration:none'>{title}</a>"
                f"<br><span>{summary[:110]}</span>"
                f" <small>({source})</small></div>"
            )
        self.feed_browser.setHtml(
            "<html><body style='margin:3px'>" + "".join(cards) + "</body></html>"
        )

    def _toggle(self):
        self._expanded = not self._expanded
        self.content.setVisible(self._expanded)
        self.toggle_button.setText("⌃" if self._expanded else "⌄")
        self.toggle_button.setToolTip(
            "جمع‌کردن فید خبر" if self._expanded else "نمایش خبرها"
        )

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
