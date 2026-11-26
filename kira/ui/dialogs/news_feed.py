"""Visible news feed for the active character."""
from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ... import news_feed
from ..workers import TaskWorker


class NewsFeedDialog(QDialog):
    """Show only the active character's rolling seven-day feed."""

    def __init__(self, character_id: str, settings: dict, parent=None, chat_client=None):
        super().__init__(parent)
        self.character_id = str(character_id or "kira")
        self.settings = dict(settings or {})
        self.chat_client = chat_client
        self._worker = None
        self.setWindowTitle("فید خبرها")
        self.resize(780, 650)
        self.setMinimumSize(560, 420)

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("newsFeedTitle")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #b9a6ff;")
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.refresh_button = QPushButton("به‌روزرسانی")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.status_label)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(
            "QTextBrowser { background: rgba(12, 13, 35, 220); color: #e9e8ff; "
            "border: 1px solid rgba(133, 110, 255, 90); border-radius: 12px; padding: 10px; }"
        )
        root.addWidget(self.browser, 1)
        self._render()

    def _character_title(self) -> str:
        return {
            "mika": "فید میکا · پزشکی و سلامت",
            "ren": "فید رن · اقتصاد و فناوری",
            "kira": "فید کیرا · صنعت گیم",
        }.get(self.character_id, "فید خبرها")

    def _render(self) -> None:
        self.title_label.setText(self._character_title())
        items = news_feed.get_items(
            self.character_id,
            region=str(self.settings.get("health_news_region") or ""),
        )
        state = news_feed.get_refresh_state(self.character_id)
        if state:
            try:
                stamp = datetime.fromtimestamp(float(state["refreshed_at"])).astimezone()
                status_prefix = "به‌روزرسانی ناقص" if state.get("status") == "partial" else "آخرین به‌روزرسانی"
                self.status_label.setText(status_prefix + ": " + stamp.strftime("%Y-%m-%d %H:%M"))
            except (TypeError, ValueError, OSError):
                self.status_label.setText("")
        else:
            self.status_label.setText("هنوز دریافت نشده")

        blocks = [
            "<html><body style='font-family:Segoe UI,sans-serif;'>",
            "<p style='color:#bcb8e8'>فقط خبرهای هفت روز اخیر نمایش داده می‌شوند. "
            "خبرها با گذشت زمان از ابتدای بازه حذف می‌شوند.</p>",
        ]
        if self.character_id == "mika":
            region = str(self.settings.get("health_news_region") or "").strip()
            blocks.append(
                "<p style='color:#f5c987'>منطقهٔ هشدارها: "
                + (html.escape(region) if region else "هنوز تأیید نشده")
                + " · خبر رسانه‌ای با اطلاعیهٔ رسمی یکی نیست.</p>"
            )
        if self.character_id == "ren" and state and state.get("analysis"):
            try:
                analyzed_at = datetime.fromtimestamp(
                    float(state.get("analysis_at") or 0)
                ).astimezone().strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError, OSError):
                analyzed_at = "زمان نامشخص"
            blocks.append(
                "<section style='margin:12px 0;padding:14px;background:#13243a;"
                "border:1px solid #41638e;border-radius:12px;'>"
                "<h3 style='color:#9bc7ff;margin:0 0 8px'>تحلیل بنیادی رن</h3>"
                f"<div style='color:#9bc7ff;font-size:12px'>تحلیل مدل · {html.escape(analyzed_at)} · "
                "برداشت تحلیلی، نه واقعیت خبر</div>"
                f"<p style='color:#e1eafa;line-height:1.65;white-space:pre-wrap'>{html.escape(str(state['analysis']))}</p>"
                "</section>"
            )
        if not items:
            blocks.append(
                "<p style='color:#c5c2df'>هنوز خبری در حافظهٔ هفت‌روزه نیست. "
                "دکمهٔ «به‌روزرسانی» را بزن یا اتصال وب را بررسی کن.</p>"
            )
        for item in items:
            title = html.escape(str(item.get("title") or "بدون عنوان"))
            summary = html.escape(str(item.get("summary") or "خلاصه‌ای ارائه نشده است."))
            source = html.escape(str(item.get("source") or "منبع نامشخص"))
            category = html.escape(str(item.get("category_label") or "خبر"))
            published = html.escape(str(item.get("published_at") or "تاریخ انتشار نامشخص"))
            url = html.escape(str(item.get("url") or ""), quote=True)
            if self.character_id == "mika" and item.get("source_official"):
                source = "مرجع سلامت/دامنهٔ دولتی · نوع نهاد بررسی شود · " + source
            extra = ""
            if self.character_id == "mika" and item.get("category") == "epidemic":
                if item.get("source_official"):
                    recommendations = news_feed.extract_source_recommendations(summary)
                    if recommendations:
                        extra = (
                            "<p style='color:#a8e3bd'><b>توصیهٔ صریحِ متن منبع:</b> "
                            + html.escape(" ؛ ".join(recommendations))
                            + "</p>"
                        )
                    else:
                        extra = "<p style='color:#d9c69e'>در خلاصهٔ منبع توصیهٔ مشخصی نیامده؛ از روی تیتر توصیهٔ پزشکی نمی‌سازیم.</p>"
                else:
                    extra = "<p style='color:#d9c69e'>این خبر منبع رسمی سلامت نیست؛ برای توصیهٔ منطقه‌ای باید اطلاعیهٔ مرجع سلامت بررسی شود.</p>"
            elif self.character_id == "ren":
                lens = news_feed.fundamental_lens(item.get("category"))
                if lens:
                    extra = "<p style='color:#a8d5ff'><b>زاویهٔ تحلیل بنیادی:</b> " + html.escape(lens) + "</p>"
            if not url.startswith(("https://", "http://")):
                link = ""
            else:
                link = f"<a style='color:#9bc7ff' href='{url}'>مشاهدهٔ منبع</a>"
            blocks.append(
                "<section style='margin:12px 0;padding:12px;"
                "background:#171832;border:1px solid #38305e;border-radius:10px;'>"
                f"<div style='color:#b7a5ff;font-size:12px'>{category} · {published}</div>"
                f"<h3 style='color:#f4f0ff;margin:7px 0'>{title}</h3>"
                f"<p style='color:#d5d1ec;line-height:1.55'>{summary}</p>"
                f"{extra}"
                f"<div style='color:#a9a5c7;font-size:12px'>{source}　{link}</div>"
                "</section>"
            )
        blocks.append("</body></html>")
        self.browser.setHtml("".join(blocks))

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText("در حال دریافت خبرها…")
        settings = dict(self.settings)
        self._worker = TaskWorker(
            lambda: news_feed.refresh_character(
                self.character_id,
                settings,
                chat_client=self.chat_client,
            )
        )
        self._worker.setParent(self.parent() or self)
        self._worker.done.connect(self._on_refresh_done)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        self._worker = None
        self.refresh_button.setEnabled(True)

    def _on_refresh_done(self, outcome) -> None:
        if isinstance(outcome, tuple) and outcome and outcome[0] is True:
            result = outcome[1] if len(outcome) > 1 and isinstance(outcome[1], dict) else {}
            errors = result.get("errors") or []
            self._render()
            if errors:
                self.status_label.setText("به‌روزرسانی ناقص بود؛ اتصال یا منبع را بررسی کن.")
        else:
            detail = outcome[1] if isinstance(outcome, tuple) and len(outcome) > 1 else "خطای نامشخص"
            self.status_label.setText("دریافت خبرها ناموفق بود: " + str(detail)[:120])
