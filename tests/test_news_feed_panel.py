"""Qt regression tests for the character-authored news-card carousel."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from kira.ui.pages.news_feed_panel import NewsFeedPanel, _ImageMetaParser, _SwipeScrollArea


_APP = QApplication.instance() or QApplication([])


class _Store:
    def list_posts(self, character_id, limit=12):
        if character_id == "kira":
            return [{
                "category": "gaming_industry",
                "title": "Visible character-written headline for Kira",
                "summary": "این روایت خود کیراست؛ خبر را از چند زاویه بررسی کرده و توضیح داده چرا برای بازیکن‌ها اهمیت دارد.\n\nسطح اطمینان: گزارش‌شده\nمنابع تکمیلی: Example source: https://source.example/report",
                "source": "example.com",
                "url": "https://example.com/kira",
                "image_url": "https://cdn.example.com/kira.jpg",
                "published_at": "2026-11-27T00:00:00Z",
                "first_seen_at": 1_000,
            }]
        if character_id == "ren":
            return [{
                "category": "economy_markets",
                "title": "Visible market analysis written by Ren",
                "summary": "رن توضیح می‌دهد که داده‌های منتشرشده چه معنایی دارند و کدام بخش هنوز قطعی نیست.",
                "source": "example.com",
                "url": "https://example.com/ren",
                "image_url": "https://cdn.example.com/ren.webp",
                "published_at": "2026-11-27T00:00:00Z",
                "first_seen_at": 1_000,
            }]
        return []

    def status(self, _character_id):
        return {"refreshed_at": 1_000, "last_error": ""}


class _Service:
    store = _Store()
    refreshes = []

    @staticmethod
    def is_refreshing(_character_id):
        return False

    @classmethod
    def refresh_character_async(cls, character_id):
        cls.refreshes.append(character_id)
        return True


class NewsFeedPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._image_loader_patch = patch.object(NewsFeedPanel, "_download_cover", autospec=True)
        cls._image_loader_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._image_loader_patch.stop()

    def setUp(self):
        self.panel = NewsFeedPanel(_Service(), {})

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        _APP.processEvents()

    def test_kira_character_authored_post_is_visible_as_a_large_card(self):
        self.panel.set_character("kira")
        _APP.processEvents()
        text = self.panel.rendered_text()
        self.assertIn("Visible character-written headline for Kira", text)
        self.assertIn("این روایت خود کیراست", text)
        self.assertIn("سطح اطمینان: گزارش‌شده", text)
        self.assertNotIn("https://source.example/report", text)
        cards = self.panel.cards_container.findChildren(QFrame, "newsStoryCard")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].width(), 372)
        cover = cards[0].findChild(QLabel, "newsCardCover")
        self.assertIsNotNone(cover)
        self.assertGreaterEqual(cover.height(), 170)

    def test_switching_character_changes_authored_cards_and_keeps_them_isolated(self):
        self.panel.set_character("ren")
        text = self.panel.rendered_text()
        self.assertIn("Visible market analysis written by Ren", text)
        self.assertNotIn("Visible character-written headline for Kira", text)

    def test_feed_uses_a_horizontal_scroll_area_for_mouse_swipe(self):
        class ManyPostsStore(_Store):
            def list_posts(self, character_id, limit=12):
                if character_id != "kira":
                    return []
                return [{
                    "category": "gaming_industry",
                    "title": f"روایت شماره {index}",
                    "summary": "متن روایت‌شده توسط کیرا.",
                    "source": "Example",
                    "url": f"https://example.com/{index}",
                    "published_at": "2026-11-27T00:00:00Z",
                } for index in range(6)]

        service = type("Service", (), {
            "store": ManyPostsStore(),
            "is_refreshing": staticmethod(lambda _character_id: False),
        })()
        panel = NewsFeedPanel(service, {})
        self.addCleanup(panel.close)
        panel.resize(1100, 620)
        panel.show()
        panel.set_character("kira")
        _APP.processEvents()

        self.assertIsInstance(panel.cards_scroll, _SwipeScrollArea)
        panel._refresh_card_widths()
        cards = panel.cards_container.findChildren(QFrame, "newsStoryCard")
        self.assertEqual(len(cards), 6)
        margins = panel.cards_layout.contentsMargins()
        visible_width = panel.cards_scroll.viewport().width()
        used_width = (
            sum(card.width() for card in cards[:3])
            + 2 * panel.cards_layout.spacing()
            + margins.left() + margins.right()
        )
        self.assertLessEqual(used_width, visible_width)
        bar = panel.cards_scroll.horizontalScrollBar()
        self.assertGreater(bar.maximum(), 0)

        target = panel.cards_container
        press = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(220, 100), QPointF(220, 100),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        move = QMouseEvent(
            QEvent.MouseMove, QPointF(110, 100), QPointF(110, 100),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(110, 100), QPointF(110, 100),
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        )
        _APP.sendEvent(target, press)
        _APP.sendEvent(target, move)
        self.assertGreater(bar.value(), 0)
        _APP.sendEvent(target, release)

    def test_publisher_image_metadata_parser_reads_open_graph_lazy_images_and_json_ld(self):
        parser = _ImageMetaParser()
        parser.feed("""
            <html><head>
              <meta property="og:image:secure_url" content="https://cdn.example.com/cover.jpg">
              <script type="application/ld+json">
                {"@type":"NewsArticle","image":{"url":"https://cdn.example.com/story.webp"}}
              </script>
            </head><body>
              <img data-srcset="https://cdn.example.com/lazy.webp 640w, https://cdn.example.com/lazy-large.webp 1280w">
            </body></html>
        """)
        parser.close()
        self.assertEqual(parser.candidates[0], "https://cdn.example.com/cover.jpg")
        self.assertIn("https://cdn.example.com/story.webp", parser.candidates)
        self.assertIn("https://cdn.example.com/lazy.webp", parser.candidates)

    def test_image_decoder_accepts_octet_stream_only_with_a_raster_signature(self):
        jpeg = bytes.fromhex("ffd8ff") + b"jpeg"
        self.assertTrue(NewsFeedPanel._supported_image(jpeg, "application/octet-stream"))
        self.assertTrue(NewsFeedPanel._supported_image(jpeg, "image/jpeg"))
        self.assertFalse(NewsFeedPanel._supported_image(b"<svg/>", "application/octet-stream"))
        self.assertFalse(NewsFeedPanel._supported_image(b"<svg/>", "image/svg+xml"))

    def test_missing_image_preview_is_not_permanently_cached(self):
        self.panel._apply_image("https://example.com/story", b"")
        self.assertNotIn("https://example.com/story", self.panel._image_cache)

    def test_mika_region_controls_are_only_shown_for_mika(self):
        self.panel.set_character("kira")
        self.assertTrue(self.panel.region_row.isHidden())
        self.panel.set_character("mika")
        self.assertFalse(self.panel.region_row.isHidden())

    def test_opening_journal_starts_the_first_refresh_for_the_selected_character(self):
        class EmptyStore:
            @staticmethod
            def list_posts(_character_id, limit=12):
                return []

            @staticmethod
            def status(_character_id):
                return {"refreshed_at": 0, "last_error": ""}

        class EmptyService:
            store = EmptyStore()
            started = []

            @staticmethod
            def is_refreshing(_character_id):
                return False

            @classmethod
            def refresh_character_async(cls, character_id):
                cls.started.append(character_id)
                return True

        panel = NewsFeedPanel(EmptyService(), {})
        self.addCleanup(panel.close)
        panel.open_for_character("ren")
        self.assertEqual(panel._character_id, "ren")
        self.assertEqual(EmptyService.started, ["ren"])
        self.assertIn("در حال بررسی", panel.status_label.text())

    def test_failed_generation_never_displays_raw_source_headlines(self):
        class PendingStore(_Store):
            def list_posts(self, _character_id, limit=12):
                return []

            def status(self, _character_id):
                return {
                    "refreshed_at": 1_000,
                    "last_error": "Post generation: RuntimeError: model offline",
                }

        service = type("Service", (), {
            "store": PendingStore(),
            "is_refreshing": staticmethod(lambda _character_id: False),
        })()
        panel = NewsFeedPanel(service, {})
        self.addCleanup(panel.close)
        panel.set_character("kira")
        content = panel.rendered_text()
        self.assertIn("شخصیت نتوانست خبرها را روایت کند", content)
        self.assertIn("model offline", content)
        self.assertNotIn("Pending GPU launch report", content)
        self.assertNotIn("Example Hardware", content)
        self.assertNotIn("هنوز توسط شخصیت روایت نشده‌اند", content)

    def test_empty_feed_explains_that_raw_news_is_not_published_as_character_posts(self):
        self.panel.set_character("mika")
        content = self.panel.rendered_text()
        self.assertIn("هنوز روایتی آماده نشده", content)
        self.assertIn("خبر خام به‌جای شخصیت نمایش داده نمی‌شود", content)


if __name__ == "__main__":
    unittest.main()
