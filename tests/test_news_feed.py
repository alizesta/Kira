"""Regression tests for character news retention and isolation."""
import tempfile
import unittest
from pathlib import Path

from kira.news_feed import NewsFeedStore


class NewsFeedStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NewsFeedStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_items_expire_after_a_rolling_seven_day_window(self):
        day = 86_400
        self.store.upsert_items("kira", [
            {"title": "Launch", "summary": "Game update", "url": "https://example.com/news/1"}
        ], now=1_000_000)
        self.assertEqual(len(self.store.list_items("kira", now=1_000_000 + 7 * day - 1)), 1)
        self.assertEqual(len(self.store.list_items("kira", now=1_000_000 + 7 * day)), 0)

    def test_same_url_is_isolated_between_characters(self):
        item = {"title": "Shared URL", "summary": "Kira copy", "url": "https://example.com/a"}
        self.store.upsert_items("kira", [item], now=10_000)
        self.store.upsert_items("ren", [{**item, "summary": "Ren copy"}], now=20_000)
        self.assertEqual(self.store.list_items("kira")[0]["summary"], "Kira copy")
        self.assertEqual(self.store.list_items("ren")[0]["summary"], "Ren copy")
        self.assertEqual(self.store.list_items("mika"), [])

    def test_refreshing_an_item_does_not_extend_its_original_expiry(self):
        day = 86_400
        item = {"title": "Story", "summary": "Initial", "url": "https://example.com/story"}
        self.store.upsert_items("mika", [item], now=1_000)
        self.store.upsert_items("mika", [{**item, "summary": "Updated"}], now=1_000 + 3 * day)
        self.assertEqual(self.store.list_items("mika", now=1_000 + 7 * day - 1)[0]["summary"], "Updated")
        self.assertEqual(self.store.list_items("mika", now=1_000 + 7 * day), [])

    def test_unknown_character_scope_is_rejected(self):
        item = {"title": "Story", "url": "https://example.com/story"}
        self.assertEqual(self.store.upsert_items("custom", [item], now=100), 0)
        self.assertEqual(self.store.list_items("custom"), [])


if __name__ == "__main__":
    unittest.main()
