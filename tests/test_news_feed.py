"""Regression tests for character news retention and isolation."""
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from kira.news_feed import (
    CHARACTER_QUERIES, NewsFeedService, NewsFeedStore, build_prompt_context,
    is_official_health_source, is_official_weather_source, is_gaming_news,
)


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

    def test_published_news_expires_seven_days_after_publication(self):
        now = time.time()
        published = now - 2 * 86_400
        published_at = datetime.fromtimestamp(published, timezone.utc).isoformat()
        self.store.upsert_items("kira", [{
            "title": "Dated story", "url": "https://example.com/dated",
            "published_at": published_at,
        }], now=now)
        self.assertEqual(len(self.store.list_items("kira", now=published + 6 * 86_400)), 1)
        self.assertEqual(len(self.store.list_items("kira", now=published + 8 * 86_400)), 0)

    def test_known_stale_news_is_rejected(self):
        now = time.time()
        stale = datetime.fromtimestamp(now - 8 * 86_400, timezone.utc).isoformat()
        count = self.store.upsert_items("kira", [{
            "title": "Old story", "url": "https://example.com/old",
            "published_at": stale,
        }], now=now)
        self.assertEqual(count, 0)
        self.assertEqual(self.store.list_items("kira", now=now), [])

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

    def test_confirmed_region_is_injected_only_into_mika_context(self):
        region_settings = {
            "news_health_region": {
                "city": "Abadan", "country": "Iran", "confirmed": True,
                "source": "user_confirmed", "confirmed_at": "2026-11-27T00:00:00+00:00",
            }
        }
        mika = build_prompt_context("mika", self.temp.name, settings=region_settings)
        kira = build_prompt_context("kira", self.temp.name, settings=region_settings)
        ren = build_prompt_context("ren", self.temp.name, settings=region_settings)
        self.assertIn("Abadan, Iran", mika)
        self.assertNotIn("Abadan", kira)
        self.assertNotIn("Abadan", ren)

    def test_default_refresh_interval_is_four_hours(self):
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {}, temp)
            self.assertEqual(service._interval_seconds(), 4 * 3600)

    def test_mika_has_weather_and_nutrition_queries(self):
        categories = {category for category, _query in CHARACTER_QUERIES["mika"]}
        self.assertTrue({"weather", "nutrition", "medical_science"} <= categories)
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {
                "news_health_region": {"city": "Frankfurt", "country": "Germany", "confirmed": True}
            }, temp)
            local = {category for category, _query in service._queries("mika", service._settings())}
            self.assertIn("local_weather", local)
            self.assertIn("local_outbreak", local)

    def test_local_health_alerts_require_official_sources(self):
        self.assertTrue(is_official_health_source("https://www.who.int/news"))
        self.assertTrue(is_official_health_source("https://www.cdc.gov/flu/"))
        self.assertTrue(is_official_health_source("https://www.gov.uk/health"))
        self.assertFalse(is_official_health_source("https://health-blog.example.com/outbreak"))

    def test_local_weather_requires_a_recognized_meteorological_source(self):
        self.assertTrue(is_official_weather_source("https://www.dwd.de/weather"))
        self.assertTrue(is_official_weather_source("https://weather.gov/alerts"))
        self.assertFalse(is_official_weather_source("https://random-weather-blog.example.com/forecast"))

    def test_ren_feed_rejects_game_industry_stories(self):
        self.assertTrue(is_gaming_news("New PlayStation console announced", "Gaming industry report"))
        self.assertFalse(is_gaming_news("Central bank holds interest rates", "Currency market update"))

    def test_rss_collector_failure_keeps_web_search_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {}, temp)
            with patch("kira.news_sources.collect_character_feeds", side_effect=RuntimeError("feed parser failed")), \
                 patch("kira.webintel.engine.search", return_value={"results": []}) as search:
                service._refresh_character("kira")
            self.assertEqual(search.call_count, len(CHARACTER_QUERIES["kira"]))
            self.assertIn("RSS collector: RuntimeError", service.store.status("kira")["last_error"])

    def test_unknown_character_scope_is_rejected(self):
        item = {"title": "Story", "url": "https://example.com/story"}
        self.assertEqual(self.store.upsert_items("custom", [item], now=100), 0)
        self.assertEqual(self.store.list_items("custom"), [])


if __name__ == "__main__":
    unittest.main()
