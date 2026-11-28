"""Qt smoke tests for the embedded character news panel."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from kira.ui.pages.news_feed_panel import NewsFeedPanel


_APP = QApplication.instance() or QApplication([])


class _Store:
    def list_posts(self, character_id, limit=4):
        if character_id == "kira":
            return [{
                "category": "gaming_industry",
                "title": "Visible headline for Kira",
                "summary": "Game industry story",
                "source": "example.com",
                "url": "https://example.com/kira",
                "published_at": "2026-11-27T00:00:00Z",
                "first_seen_at": 1_000,
            }]
        if character_id == "ren":
            return [{
                "category": "economy_markets",
                "title": "Visible market headline for Ren",
                "summary": "Central bank story",
                "source": "example.com",
                "url": "https://example.com/ren",
                "published_at": "2026-11-27T00:00:00Z",
                "first_seen_at": 1_000,
            }]
        return []

    def list_unprocessed_items(self, _character_id, limit=12):
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
    def setUp(self):
        self.panel = NewsFeedPanel(_Service(), {})

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        _APP.processEvents()

    def test_kira_headline_is_visible_in_the_chat_panel(self):
        self.panel.set_character("kira")
        self.panel.refresh_view()
        _APP.processEvents()
        self.assertIn("Visible headline for Kira", self.panel.feed_browser.toPlainText())

    def test_switching_character_changes_the_visible_feed(self):
        self.panel.set_character("ren")
        self.panel.refresh_view()
        _APP.processEvents()
        content = self.panel.feed_browser.toPlainText()
        self.assertIn("Visible market headline for Ren", content)
        self.assertNotIn("Visible headline for Kira", content)

    def test_mika_region_controls_are_only_shown_for_mika(self):
        self.panel.set_character("kira")
        self.assertTrue(self.panel.region_row.isHidden())
        self.panel.set_character("mika")
        self.assertFalse(self.panel.region_row.isHidden())

    def test_opening_journal_starts_the_first_refresh_for_the_selected_character(self):
        class EmptyStore:
            @staticmethod
            def list_posts(_character_id, limit=4):
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

    def test_pending_source_headlines_are_visible_when_model_generation_fails(self):
        class PendingStore(_Store):
            def list_posts(self, _character_id, limit=4):
                return []

            def list_unprocessed_items(self, _character_id, limit=12):
                return [{
                    "category": "gaming_hardware",
                    "title": "Pending GPU launch report",
                    "summary": "Publisher reports a new graphics card announcement.",
                    "source": "Example Hardware",
                    "url": "https://example.com/gpu-launch",
                    "published_at": "2026-11-28T08:00:00Z",
                    "first_seen_at": 1_000,
                }]

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
        panel.refresh_view()
        content = panel.feed_browser.toPlainText()
        self.assertIn("خبرهای دریافت‌شده", content)
        self.assertIn("هنوز توسط شخصیت روایت نشده‌اند", content)
        self.assertIn("Pending GPU launch report", content)
        self.assertIn("model offline", content)
        self.assertIn("Example Hardware", content)
        self.assertIn("خبر دریافتی", panel.status_label.text())

    def test_empty_feed_still_displays_refresh_guidance(self):
        self.panel.set_character("mika")
        self.panel.refresh_view()
        self.assertIn("هنوز خبری دریافت نشده", self.panel.feed_browser.toPlainText())


if __name__ == "__main__":
    unittest.main()
