"""Regression tests for character news retention and isolation."""
import tempfile
import time
import unittest
from pathlib import Path

from kira.news_feed import NewsFeedStore, build_prompt_context, is_official_health_source, is_gaming_news


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
        stamp = time.time()
        item = {"title": "Shared URL", "summary": "Kira copy", "url": "https://example.com/a"}
        self.store.upsert_items("kira", [item], now=stamp)
        self.store.upsert_items("ren", [{**item, "summary": "Ren copy"}], now=stamp)
        self.assertEqual(self.store.list_items("kira", now=stamp)[0]["summary"], "Kira copy")
        self.assertEqual(self.store.list_items("ren", now=stamp)[0]["summary"], "Ren copy")
        self.assertEqual(self.store.list_items("mika"), [])

    def test_refreshing_an_item_does_not_extend_its_original_expiry(self):
        day = 86_400
        item = {"title": "Story", "summary": "Initial", "url": "https://example.com/story"}
        self.store.upsert_items("mika", [item], now=1_000)
        self.store.upsert_items("mika", [{**item, "summary": "Updated"}], now=1_000 + 3 * day)
        self.assertEqual(self.store.list_items("mika", now=1_000 + 7 * day - 1)[0]["summary"], "Updated")
        self.assertEqual(self.store.list_items("mika", now=1_000 + 7 * day), [])

    def test_prompt_context_reads_only_the_requested_character_feed(self):
        stamp = time.time()
        self.store.upsert_items("kira", [
            {"title": "Kira-only game update", "summary": "A release", "url": "https://example.com/kira"}
        ], now=stamp)
        self.store.upsert_items("ren", [
            {"title": "Ren-only market update", "summary": "A rate change", "url": "https://example.com/ren"}
        ], now=stamp)
        kira = build_prompt_context("kira", self.temp.name)
        ren = build_prompt_context("ren", self.temp.name)
        self.assertIn("Kira-only game update", kira)
        self.assertNotIn("Ren-only market update", kira)
        self.assertIn("Ren-only market update", ren)
        self.assertNotIn("Kira-only game update", ren)

    def test_local_health_alerts_require_official_sources(self):
        self.assertTrue(is_official_health_source("https://www.who.int/news"))
        self.assertTrue(is_official_health_source("https://www.cdc.gov/flu/"))
        self.assertTrue(is_official_health_source("https://www.gov.uk/health"))
        self.assertFalse(is_official_health_source("https://health-blog.example.com/outbreak"))

    def test_ren_feed_rejects_game_industry_stories(self):
        self.assertTrue(is_gaming_news("New PlayStation console announced", "Gaming industry report"))
        self.assertFalse(is_gaming_news("Central bank holds interest rates", "Currency market update"))

    def test_unknown_character_scope_is_rejected(self):
        item = {"title": "Story", "url": "https://example.com/story"}
        self.assertEqual(self.store.upsert_items("custom", [item], now=100), 0)
        self.assertEqual(self.store.list_items("custom"), [])


if __name__ == "__main__":
    unittest.main()
