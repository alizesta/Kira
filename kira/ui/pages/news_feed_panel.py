"""Large, character-authored news cards with image previews and mouse-swipe navigation."""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from threading import Thread
from urllib.parse import urljoin, urlsplit

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from ...news_feed import CATEGORY_LABELS, CHARACTER_IDS


_CHARACTER_LABELS = {
    "kira": "کیرا · اخبار بازی و سخت‌افزار",
    "ren": "رن · اقتصاد، بازار و فناوری",
    "mika": "میکا · پزشکی و سلامت عمومی",
}

_CARD_STYLE = """
QFrame#newsStoryCard {
    background: rgba(17, 11, 39, 238);
    border: 1px solid rgba(125, 88, 216, 150);
    border-radius: 18px;
}
QLabel#newsCardCategory { color: #bda9f7; font-size: 11px; font-weight: 600; }
QLabel#newsCardTitle { color: #f5f1ff; font-size: 17px; font-weight: 700; }
QLabel#newsCardBody { color: #d8d0ed; font-size: 13px; line-height: 1.5; }
QLabel#newsCardSource { color: #a995dc; font-size: 11px; }
QLabel#newsCardCover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #382365, stop:1 #140f2e);
    border: 1px solid rgba(139, 92, 246, 100);
    border-radius: 12px;
    color: #cbbcff;
    font-size: 14px;
}
QPushButton#newsCardOpen {
    background: rgba(87, 53, 160, 110);
    border: 1px solid rgba(139, 92, 246, 150);
    border-radius: 9px;
    color: #f5f1ff;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#newsCardOpen:hover { background: rgba(112, 73, 196, 170); }
QLabel#newsFeedEmptyTitle { color: #eee7ff; font-size: 20px; font-weight: 700; }
QLabel#newsFeedEmptyBody { color: #b8a9d9; font-size: 13px; }
QScrollBar:horizontal {
    background: rgba(18, 12, 42, 150); height: 9px; border-radius: 4px; margin: 3px 10px;
}
QScrollBar::handle:horizontal {
    background: #7950c7; min-width: 38px; border-radius: 4px;
}
QScrollBar::handle:horizontal:hover { background: #9c74ec; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


class _ImageMetaParser(HTMLParser):
    """Read only standard preview metadata from an already safely fetched article page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        values = {str(key).lower(): str(value or "").strip() for key, value in attrs}
        tag = tag.lower()
        if tag == "meta":
            marker = (values.get("property") or values.get("name") or "").lower()
            if marker in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
                value = values.get("content", "")
                if value:
                    self.candidates.append(value)
        elif tag == "link" and "image_src" in values.get("rel", "").lower().split():
            value = values.get("href", "")
            if value:
                self.candidates.append(value)
        elif tag == "img" and not self.candidates:
            value = values.get("src") or values.get("data-src") or ""
            if value:
                self.candidates.append(value)


class _CoverImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__("در حال دریافت تصویر…", parent)
        self._original = QPixmap()
        self.setObjectName("newsCardCover")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(170)
        self.setFixedHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_cover(self, data: bytes):
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self._original = pixmap
            self.setText("")
            self._rescale()
        else:
            self._original = QPixmap()
            self.setPixmap(QPixmap())
            self.setText("تصویر برای این خبر پیدا نشد")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._original.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        scaled = self._original.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)


class _SwipeScrollArea(QScrollArea):
    """Horizontal carousel that can be dragged with the left mouse button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_origin: QPoint | None = None
        self._scroll_origin = 0
        self._dragging = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.viewport().setCursor(Qt.OpenHandCursor)

    def install_drag_targets(self, root: QWidget):
        for widget in (root, *root.findChildren(QWidget)):
            widget.installEventFilter(self)
            widget.setMouseTracking(True)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._scroll_origin = self.horizontalScrollBar().value()
            self._dragging = False
            return False
        if event_type == QEvent.MouseMove and self._drag_origin is not None:
            if not (event.buttons() & Qt.LeftButton):
                return False
            delta = event.globalPosition().toPoint() - self._drag_origin
            if not self._dragging and abs(delta.x()) >= 7:
                self._dragging = True
                self.viewport().setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self.horizontalScrollBar().setValue(self._scroll_origin - delta.x())
                return True
        if event_type == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            was_dragging = self._dragging
            self._drag_origin = None
            self._dragging = False
            self.viewport().setCursor(Qt.OpenHandCursor)
            return was_dragging
        return super().eventFilter(watched, event)


class _NewsCard(QFrame):
    def __init__(self, item: dict, panel: "NewsFeedPanel", parent=None):
        super().__init__(parent)
        self.setObjectName("newsStoryCard")
        self.setStyleSheet(_CARD_STYLE)
        self.setFixedWidth(372)
        self.setMinimumHeight(440)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(9)

        self.cover = _CoverImageLabel(self)
        layout.addWidget(self.cover)

        category = CATEGORY_LABELS.get(item.get("category"), item.get("category") or "خبر")
        when = _published_label(item)
        source = str(item.get("source") or "").strip()
        meta_parts = [str(category)]
        if when:
            meta_parts.append(when)
        if source:
            meta_parts.append(source)
        meta = QLabel("  ·  ".join(meta_parts), self)
        meta.setObjectName("newsCardCategory")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        title = QLabel(str(item.get("title") or "خبر"), self)
        title.setObjectName("newsCardTitle")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)

        body = QLabel(str(item.get("summary") or "برای این خبر توضیح بیشتری در دسترس نیست."), self)
        body.setObjectName("newsCardBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setMaximumHeight(116)
        layout.addWidget(body)

        layout.addStretch(1)
        open_button = QPushButton("مشاهدهٔ گزارش اصلی  ↗", self)
        open_button.setObjectName("newsCardOpen")
        open_button.setCursor(Qt.PointingHandCursor)
        article_url = str(item.get("url") or "").strip()
        open_button.clicked.connect(lambda _checked=False, url=article_url: _open_source(url))
        layout.addWidget(open_button)

        panel._register_image(article_url, str(item.get("image_url") or ""), self.cover)


def _published_label(item: dict) -> str:
    value = str(item.get("published_at") or "").strip()
    if not value:
        try:
            stamp = float(item.get("first_seen_at") or 0)
            return datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone().strftime("%Y/%m/%d")
        except (TypeError, ValueError, OverflowError, OSError):
            return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%Y/%m/%d")
    except (TypeError, ValueError, OverflowError):
        return value[:30]


def _open_source(url: str):
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            QDesktopServices.openUrl(QUrl(url))
    except (TypeError, ValueError):
        return


class NewsFeedPanel(QFrame):
    """Full-size, character-scoped editorial feed with a mouse-draggable card carousel."""

    refresh_requested = Signal(str)
    location_detection_requested = Signal()
    region_confirm_requested = Signal(str)
    location_suggestion_ready = Signal(str, str, str, str)
    image_ready = Signal(str, bytes)

    def __init__(self, service, settings: dict, parent=None):
        super().__init__(parent)
        self._service = service
        self._settings = settings if isinstance(settings, dict) else {}
        self._character_id = "kira"
        self._expanded = True
        self._render_signature = None
        self._image_cache: dict[str, bytes] = {}
        self._image_loading: set[str] = set()
        self._image_labels: dict[str, list[_CoverImageLabel]] = {}

        self.setObjectName("newsFeedPanel")
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(self.styleSheet() + _CARD_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = QLabel(_CHARACTER_LABELS["kira"], self)
        self.title_label.setObjectName("newsFeedTitle")
        self.title_label.setStyleSheet("color:#f0eaff;font-size:19px;font-weight:700;")
        header.addWidget(self.title_label, 1)

        self.status_label = QLabel("در حال آماده‌سازی فید خبر…", self)
        self.status_label.setObjectName("newsFeedStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#ac9acc;font-size:11px;")
        header.addWidget(self.status_label, 2)

        self.refresh_button = QPushButton("↻  به‌روزرسانی", self)
        self.refresh_button.setObjectName("newsFeedRefresh")
        self.refresh_button.setToolTip("دریافت خبر و روایت دوباره با صدای همین شخصیت")
        self.refresh_button.clicked.connect(self._request_refresh)
        header.addWidget(self.refresh_button)

        self.toggle_button = QPushButton("جمع‌کردن", self)
        self.toggle_button.setObjectName("newsFeedToggle")
        self.toggle_button.clicked.connect(self._toggle)
        header.addWidget(self.toggle_button)
        outer.addLayout(header)

        self.region_row = QFrame(self)
        self.region_row.setObjectName("newsFeedRegionRow")
        self.region_row.setStyleSheet(
            "QFrame#newsFeedRegionRow { background:rgba(32,21,66,150); border:1px solid #493575; border-radius:10px; }"
        )
        region_layout = QHBoxLayout(self.region_row)
        region_layout.setContentsMargins(10, 6, 10, 6)
        self.region_status = QLabel(self.region_row)
        self.region_status.setWordWrap(True)
        self.region_status.setStyleSheet("color:#c6b6e8;font-size:11px;")
        region_layout.addWidget(self.region_status, 1)
        self.region_edit = QLineEdit(self.region_row)
        self.region_edit.setPlaceholderText("City, Country")
        self.region_edit.setMinimumWidth(150)
        region_layout.addWidget(self.region_edit)
        self.detect_button = QPushButton("GPS/IP", self.region_row)
        self.detect_button.setToolTip("اول GPS دستگاه و در صورت نبود آن موقعیت تقریبی IP")
        self.detect_button.clicked.connect(self.location_detection_requested.emit)
        region_layout.addWidget(self.detect_button)
        self.confirm_button = QPushButton("تأیید", self.region_row)
        self.confirm_button.clicked.connect(
            lambda: self.region_confirm_requested.emit(self.region_edit.text())
        )
        region_layout.addWidget(self.confirm_button)
        outer.addWidget(self.region_row)

        self.feed_stack = QStackedWidget(self)
        self.cards_scroll = _SwipeScrollArea(self.feed_stack)
        self.cards_container = QWidget()
        self.cards_container.setObjectName("newsCardsContainer")
        self.cards_container.setLayoutDirection(Qt.LeftToRight)
        self.cards_layout = QHBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(7, 5, 7, 12)
        self.cards_layout.setSpacing(15)
        self.cards_scroll.setWidget(self.cards_container)
        self.feed_stack.addWidget(self.cards_scroll)

        self.empty_state = QFrame(self.feed_stack)
        self.empty_state.setObjectName("newsFeedEmpty")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(28, 30, 28, 30)
        empty_layout.addStretch(1)
        self.empty_title = QLabel("هنوز روایتی آماده نشده", self.empty_state)
        self.empty_title.setObjectName("newsFeedEmptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_body = QLabel(
            "وقتی شخصیت خبرها را بررسی و با زبان خودش تعریف کند، کارت‌های خبری اینجا نمایش داده می‌شوند.",
            self.empty_state,
        )
        self.empty_body.setObjectName("newsFeedEmptyBody")
        self.empty_body.setWordWrap(True)
        self.empty_body.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_body)
        empty_layout.addStretch(1)
        self.feed_stack.addWidget(self.empty_state)
        outer.addWidget(self.feed_stack, 1)

        self.location_suggestion_ready.connect(self.apply_location_suggestion)
        self.image_ready.connect(self._apply_image)
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
        self.region_row.setVisible(cid == "mika")
        self.refresh_button.setEnabled(cid in CHARACTER_IDS)
        self._render_signature = None
        self.refresh_view()

    def open_for_character(self, character_id: str):
        """Show this character's authored feed and start its first collection pass."""
        self.set_character(character_id)
        cid = self._character_id
        if cid not in CHARACTER_IDS:
            return
        state = self._service.store.status(cid)
        refreshing = self._service.is_refreshing(cid)
        if not state.get("refreshed_at") and not refreshing:
            started = self._service.refresh_character_async(cid)
            if started:
                self.show_refreshing(cid)
        else:
            self.refresh_view()

    def _request_refresh(self):
        if self._character_id not in CHARACTER_IDS:
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText("در حال دریافت خبرها و روایت با صدای شخصیت…")
        self.refresh_requested.emit(self._character_id)

    def show_refreshing(self, character_id: str):
        if str(character_id) == self._character_id:
            self.status_label.setText("در حال بررسی منبع‌ها و نوشتن روایت اختصاصی…")
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
                f"پیشنهاد {source_label}: {city}, {country} — برای فعال‌شدن هشدار محلی تأییدش کن."
            )
        elif error:
            self.region_status.setText("موقعیت خودکار پیدا نشد؛ شهر و کشور را دستی وارد کن.")

    def set_region_confirmed(self, city: str, country: str):
        region = self._settings.get("news_health_region")
        if not isinstance(region, dict):
            region = {}
        region.update({
            "city": city, "country": country, "confirmed": True,
            "source": "user_confirmed",
        })
        self._settings["news_health_region"] = region
        self.region_edit.setText(f"{city}, {country}")
        self.region_status.setText(f"موقعیت تأییدشده: {city}, {country}")

    def _toggle(self):
        self._expanded = not self._expanded
        self.feed_stack.setVisible(self._expanded)
        self.region_row.setVisible(self._expanded and self._character_id == "mika")
        self.toggle_button.setText("جمع‌کردن" if self._expanded else "بازکردن")

    def _model_error(self, state: dict) -> str:
        error = str(state.get("last_error") or "").strip()
        if not error:
            return ""
        for part in error.split(";"):
            part = part.strip()
            if part.startswith("Post generation:"):
                return part.partition(":")[2].strip() or part
        return ""

    def refresh_view(self):
        cid = self._character_id
        if cid not in CHARACTER_IDS:
            self._set_cards([])
            self.status_label.setText("برای این شخصیت هنوز فید خبری تعریف نشده است.")
            return

        items = self._service.store.list_posts(cid, limit=12)
        state = self._service.store.status(cid)
        refreshing = self._service.is_refreshing(cid)
        error = self._model_error(state)
        if refreshing:
            self.status_label.setText("در حال بررسی خبرها و نوشتن روایت…")
        else:
            count_text = f"{len(items)} روایت آماده"
            if state.get("refreshed_at"):
                try:
                    stamp = datetime.fromtimestamp(
                        float(state["refreshed_at"]), tz=timezone.utc
                    ).astimezone().strftime("%Y/%m/%d %H:%M")
                    count_text += f"  ·  آخرین بررسی: {stamp}"
                except (TypeError, ValueError, OverflowError, OSError):
                    pass
            if error:
                count_text += f"  ·  خطای روایت: {error}"
            elif state.get("last_error"):
                count_text += "  ·  بعضی منابع در دسترس نبودند"
            self.status_label.setText(count_text)

        self.refresh_button.setEnabled(not refreshing)
        signature = (
            cid,
            error,
            bool(refreshing),
            tuple(
                (
                    str(item.get("url") or ""),
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("image_url") or ""),
                )
                for item in items
            ),
        )
        if signature == self._render_signature:
            return
        self._render_signature = signature
        self._set_cards(items)

        if not items:
            if error:
                self.empty_title.setText("شخصیت نتوانست خبرها را روایت کند")
                self.empty_body.setText(
                    f"خطای تولید روایت: {error}\nخبرهای دریافت‌شده محفوظ مانده‌اند؛ برای تلاش دوباره «به‌روزرسانی» را بزن."
                )
            elif refreshing:
                self.empty_title.setText("در حال آماده‌کردن روایت‌ها…")
                self.empty_body.setText("خبر خام نمایش داده نمی‌شود؛ به‌محض آماده‌شدن، روایت‌های خود شخصیت اینجا می‌آیند.")
            elif state.get("last_error"):
                self.empty_title.setText("دریافت خبر به مشکل خورد")
                self.empty_body.setText(
                    f"خطای دریافت: {str(state.get('last_error'))[:260]}\nبرای تلاش دوباره «به‌روزرسانی» را بزن."
                )
            else:
                self.empty_title.setText("هنوز روایتی آماده نشده")
                self.empty_body.setText(
                    "خبر خام به‌جای شخصیت نمایش داده نمی‌شود. برای دریافت و روایت خبرها، «به‌روزرسانی» را بزن."
                )

    def _set_cards(self, items: list[dict]):
        while self.cards_layout.count():
            child = self.cards_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._image_labels = {}
        if not items:
            self.feed_stack.setCurrentWidget(self.empty_state)
            return
        for item in items:
            card = _NewsCard(item, self, self.cards_container)
            self.cards_layout.addWidget(card)
        self.cards_scroll.install_drag_targets(self.cards_container)
        self.feed_stack.setCurrentWidget(self.cards_scroll)
        self.cards_container.updateGeometry()

    def _register_image(self, article_url: str, image_url: str, label: _CoverImageLabel):
        if not article_url:
            label.set_cover(b"")
            return
        self._image_labels.setdefault(article_url, []).append(label)
        if article_url in self._image_cache:
            label.set_cover(self._image_cache[article_url])
            return
        if article_url in self._image_loading:
            label.setText("در حال دریافت تصویر…")
            return
        self._image_loading.add(article_url)
        Thread(
            target=self._download_cover,
            args=(article_url, image_url),
            name="kira-news-image",
            daemon=True,
        ).start()

    @staticmethod
    def _supported_image(data: bytes, content_type: str) -> bool:
        if content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            return False
        return (
            data.startswith(b"\xff\xd8\xff")
            or data.startswith(b"\x89PNG\r\n\x1a\n")
            or data.startswith((b"GIF87a", b"GIF89a"))
            or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        )

    def _download_cover(self, article_url: str, image_url: str):
        data = b""
        try:
            from ...webintel.netguard import fetch, safe_url

            target = image_url.strip()
            if not target:
                article = fetch(
                    safe_url(article_url), timeout=7, max_bytes=350_000,
                    max_redirects=2, total_timeout=10,
                )
                parser = _ImageMetaParser()
                parser.feed(article.body.decode("utf-8", errors="replace"))
                parser.close()
                candidate = next(
                    (
                        value for value in parser.candidates
                        if value and len(value) <= 1500
                    ),
                    "",
                )
                if candidate:
                    target = urljoin(article.final_url or article_url, candidate)
            if target:
                response = fetch(
                    safe_url(urljoin(article_url, target)),
                    timeout=8, max_bytes=1_500_000, max_redirects=2,
                    total_timeout=12, allow_images=True,
                )
                if self._supported_image(response.body, response.ctype):
                    data = response.body
        except Exception:
            data = b""
        try:
            self.image_ready.emit(article_url, data)
        except RuntimeError:
            pass

    def _apply_image(self, article_url: str, data: bytes):
        self._image_loading.discard(article_url)
        self._image_cache[article_url] = bytes(data or b"")
        for label in self._image_labels.get(article_url, []):
            if label is not None:
                label.set_cover(self._image_cache[article_url])

    def rendered_text(self) -> str:
        """Plain-text view for accessibility and tests; contains only authored posts."""
        values = []
        for card in self.cards_container.findChildren(_NewsCard):
            values.extend(label.text() for label in card.findChildren(QLabel) if label.text())
        if self.feed_stack.currentWidget() == self.empty_state:
            values.extend((self.empty_title.text(), self.empty_body.text()))
        return "\n".join(values)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_view()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
