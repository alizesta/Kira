"""Regression tests for character news retention and isolation."""
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from kira.news_feed import (
    CHARACTER_QUERIES, NewsFeedService, NewsFeedStore, build_prompt_context,
    is_official_health_source, is_official_weather_source, is_gaming_news,
    is_relevant_character_news, _prepare_character_posts, _commons_thumbnail,
)
from kira.webintel import engine as webintel_engine
from kira.webintel import netguard as webintel_netguard


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

    def test_image_metadata_survives_refreshes_without_being_erased(self):
        now = time.time()
        url = "https://example.com/image-story"
        self.store.upsert_items("kira", [{
            "title": "Image story", "summary": "Details", "url": url,
            "image_url": "https://cdn.example.com/story.jpg",
        }], now=now)
        self.store.upsert_items("kira", [{
            "title": "Image story", "summary": "Details updated", "url": url,
        }], now=now + 60)
        item = self.store.list_items("kira", now=now + 60)[0]
        self.assertEqual(item["image_url"], "https://cdn.example.com/story.jpg")

    def test_rss_source_classification_survives_duplicate_search_results(self):
        stamp = time.time()
        url = "https://example.com/leak"
        self.store.upsert_items("kira", [{
            "title": "Unconfirmed console leak", "url": url,
            "category": "gaming_rumor", "source_label": "X @insider",
        }], now=stamp)
        self.store.upsert_items("kira", [{
            "title": "Unconfirmed console leak", "url": url,
            "category": "game_releases", "source_label": "example.com",
        }], now=stamp)
        item = self.store.list_items("kira", now=stamp)[0]
        self.assertEqual(item["category"], "gaming_rumor")
        self.assertEqual(item["source"], "X @insider")

    def test_prompt_context_reads_only_the_requested_character_feed(self):
        stamp = time.time()
        self.store.upsert_items("kira", [
            {"title": "Kira-only game update", "summary": "A release", "url": "https://example.com/kira", "category": "gaming_news", "is_post": True}
        ], now=stamp)
        self.store.upsert_items("ren", [
            {"title": "Ren-only market update", "summary": "A rate change", "url": "https://example.com/ren", "category": "economy_markets", "is_post": True}
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

    def test_character_news_domains_reject_cross_character_and_mika_war_politics(self):
        self.assertTrue(is_relevant_character_news(
            "mika", "medical_science", "واکسن جدید برای پیشگیری از آنفلوآنزا",
            "پژوهش پزشکی درباره اثربخشی واکسن منتشر شد.",
        ))
        self.assertTrue(is_relevant_character_news(
            "mika", "weather", "پیش‌بینی بارش باران در روزهای آینده",
            "سازمان هواشناسی دما و بارندگی را اعلام کرد.",
        ))
        self.assertFalse(is_relevant_character_news(
            "mika", "medical_science", "تشدید جنگ و حملات موشکی در منطقه",
            "گزارش تازه از درگیری نظامی و تحولات جبهه.",
        ))
        self.assertFalse(is_relevant_character_news(
            "mika", "public_health", "انتخابات و رقابت احزاب سیاسی",
            "گزارش سیاسی درباره پارلمان و دیپلماسی.",
        ))
        self.assertFalse(is_relevant_character_news(
            "mika", "economy_markets", "افزایش نرخ بهره در بازارها",
            "گزارش اقتصادی.",
        ))
        self.assertTrue(is_relevant_character_news(
            "ren", "economy_markets", "افزایش نرخ بهره توسط بانک مرکزی",
            "تغییر تورم و شاخص بازار سهام.",
        ))
        self.assertFalse(is_relevant_character_news(
            "ren", "digital_technology", "New PlayStation console announced",
            "Gaming hardware update.",
        ))
        self.assertFalse(is_relevant_character_news(
            "kira", "crypto", "Bitcoin price update", "Cryptocurrency market.",
        ))

    def test_mika_refresh_rejects_war_news_before_persistence(self):
        sources = [
            {
                "title": "گزارش جنگ و حملات موشکی در منطقه",
                "summary": "درگیری نظامی و تحولات جبهه ادامه دارد.",
                "url": "https://example.com/war",
                "category": "iran_health",
                "source_label": "General News",
            },
            {
                "title": "واکسن تازه برای پیشگیری از آنفلوآنزا",
                "summary": "پژوهش پزشکی تازه درباره سلامت عمومی منتشر شد.",
                "url": "https://example.com/vaccine",
                "category": "iran_health",
                "source_label": "Health News",
            },
        ]
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {}, temp)
            service._queries = lambda *_args: []
            with (
                patch("kira.news_sources.collect_character_feeds", return_value=(sources, [])),
                patch("kira.news_feed._commons_thumbnail", return_value=""),
            ):
                service._refresh_character("mika")

            items = service.store.list_items("mika")
            self.assertEqual([item["url"] for item in items], ["https://example.com/vaccine"])
            self.assertEqual(service.store.list_posts("mika"), [])

    def test_mika_off_domain_legacy_posts_are_hidden_from_the_feed(self):
        self.store.upsert_items("mika", [{
            "title": "جنگ و انتخابات در منطقه",
            "summary": "سطح اطمینان: گزارش‌شده",
            "url": "https://example.com/old-war",
            "category": "iran_health",
            "is_post": True,
        }])
        self.assertEqual(self.store.list_posts("mika"), [])

    def test_off_domain_legacy_posts_do_not_starve_relevant_posts_below_limit(self):
        now = time.time()
        self.store.upsert_items("mika", [{
            "title": "واکسیناسیون و پیشگیری از آنفلوآنزا",
            "summary": "پژوهش پزشکی تازه دربارهٔ واکسن منتشر شد.\n\nسطح اطمینان: گزارش‌شده",
            "url": "https://example.com/medical",
            "category": "medical_science",
            "is_post": True,
        }], now=now - 60)
        self.store.upsert_items("mika", [{
            "title": "جنگ و انتخابات در منطقه",
            "summary": "گزارش سیاسی و نظامی.\n\nسطح اطمینان: گزارش‌شده",
            "url": "https://example.com/war-newer",
            "category": "iran_health",
            "is_post": True,
        }], now=now)

        posts = self.store.list_posts("mika", limit=1)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["url"], "https://example.com/medical")

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

    def test_commons_thumbnail_uses_only_wikimedia_raster_assets(self):
        payload = (
            b'{"query":{"pages":{"1":{"imageinfo":[{"thumburl":'
            b'"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/game.jpg/640px-game.jpg"}]}}}}'
        )
        response = type("Fetched", (), {"body": payload})()
        with patch.object(webintel_netguard, "fetch", return_value=response) as fetch:
            image = _commons_thumbnail("Grand Theft Auto VI")
        self.assertEqual(
            image,
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/game.jpg/640px-game.jpg",
        )
        self.assertIn("generator=search", fetch.call_args.args[0])

        unsafe_payload = (
            b'{"query":{"pages":{"1":{"imageinfo":[{"thumburl":'
            b'"https://evil.example.com/game.jpg"}]}}}}'
        )
        with patch(
            "kira.webintel.netguard.fetch",
            return_value=type("Fetched", (), {"body": unsafe_payload})(),
        ):
            self.assertEqual(_commons_thumbnail("Grand Theft Auto VI"), "")

    def test_missing_images_use_the_keyless_commons_fallback(self):
        source = {
            "title": "Central bank publishes new rate outlook",
            "summary": "The central bank published its new outlook.",
            "url": "https://example.com/rates",
            "category": "economy_markets",
            "source_label": "Example Finance",
        }
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {}, temp)

            def fake_search(_context, _query, kind="web", max_results=8):
                if kind == "news":
                    return {"results": [{
                        "title": source["title"],
                        "url": source["url"],
                        "snippet": source["summary"],
                        "date": "2026-11-28",
                    }]}
                return {"results": []}

            with (
                patch.object(webintel_engine, "search", side_effect=fake_search),
                patch("kira.news_feed._commons_thumbnail", return_value="https://upload.wikimedia.org/wikipedia/commons/rate.png") as commons,
            ):
                service._queries = lambda *_args: [("economy_markets", "central bank rates")]
                service._refresh_character("ren")

            stored = service.store.list_items("ren")
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["image_url"], "https://upload.wikimedia.org/wikipedia/commons/rate.png")
            commons.assert_called_once_with("Central bank publishes new rate outlook")

    def test_missing_story_images_are_backfilled_from_configured_tavily_image_search(self):
        sources = [{
            "title": "Grand Theft Auto VI new trailer",
            "summary": "A new trailer is reported.",
            "url": "https://example.com/gta6",
            "category": "gaming_news",
            "source_label": "Example Games",
        }]
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {"tavily_api_key": "test-key"}, temp)

            def fake_search(_context, _query, kind="web", max_results=8):
                if kind == "images":
                    return {"results": [{
                        "title": "Grand Theft Auto VI official artwork",
                        "url": "https://cdn.example.com/gta6-artwork.jpg",
                    }]}
                return {"results": []}

            with (
                patch("kira.news_sources.collect_character_feeds", return_value=(sources, [])),
                patch.object(webintel_engine, "search", side_effect=fake_search) as search,
            ):
                service._refresh_character("kira")

            stored = service.store.list_items("kira")
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["image_url"], "https://cdn.example.com/gta6-artwork.jpg")
            self.assertEqual(
                sum(call.kwargs.get("kind") == "images" for call in search.call_args_list),
                1,
            )

    def test_rss_collector_failure_keeps_web_search_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            service = NewsFeedService(lambda: {}, temp)
            with patch("kira.news_sources.collect_character_feeds", side_effect=RuntimeError("feed parser failed")), \
                 patch.object(webintel_engine, "search", return_value={"results": []}) as search:
                service._refresh_character("kira")
            self.assertEqual(search.call_count, len(CHARACTER_QUERIES["kira"]))
            self.assertIn("RSS collector: RuntimeError", service.store.status("kira")["last_error"])

    def test_existing_news_database_is_migrated_without_publishing_old_raw_items(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "news_feed"
            root.mkdir()
            path = root / "news.sqlite3"
            stamp = time.time()
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """CREATE TABLE news_items (
                        id INTEGER PRIMARY KEY, character_id TEXT NOT NULL,
                        category TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
                        source TEXT NOT NULL, url TEXT NOT NULL, url_key TEXT NOT NULL,
                        published_at TEXT NOT NULL DEFAULT '', first_seen_at REAL NOT NULL,
                        expires_at REAL NOT NULL, region TEXT NOT NULL DEFAULT ''
                    )"""
                )
                connection.execute(
                    """INSERT INTO news_items(
                        character_id, category, title, summary, source, url, url_key,
                        published_at, first_seen_at, expires_at, region
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("kira", "gaming_news", "Old raw headline", "Old snippet", "example.com",
                     "https://example.com/old", "https://example.com/old", "", stamp,
                     stamp + 7 * 86400, ""),
                )
                connection.commit()
            finally:
                connection.close()
            migrated = NewsFeedStore(Path(temp))
            with migrated._connection() as db:
                columns = {
                    row["name"] for row in db.execute("PRAGMA table_info(news_items)")
                }
            self.assertTrue({"image_url", "is_post", "processed"} <= columns)
            self.assertEqual(migrated.list_posts("kira"), [])
            self.assertEqual(len(migrated.list_unprocessed_items("kira")), 1)

    def test_changed_source_content_is_queued_for_a_new_editorial_pass(self):
        stamp = time.time()
        item = {
            "title": "First report", "summary": "Initial details",
            "url": "https://example.com/update",
        }
        self.store.upsert_items("ren", [item], now=stamp)
        self.store.mark_sources_processed("ren", [item["url"]])
        self.assertEqual(self.store.list_unprocessed_items("ren"), [])
        self.store.upsert_items("ren", [{
            **item, "title": "Updated report", "summary": "Materially updated details",
        }], now=stamp + 60)
        pending = self.store.list_unprocessed_items("ren")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["summary"], "Materially updated details")

    def test_raw_sources_are_hidden_from_the_character_feed(self):
        stamp = time.time()
        self.store.upsert_items("kira", [
            {"title": "Raw headline", "summary": "Publisher snippet", "url": "https://example.com/raw"}
        ], now=stamp)
        self.assertEqual(self.store.list_posts("kira"), [])
        self.assertEqual(len(self.store.list_unprocessed_items("kira")), 1)

    def test_generated_character_post_is_published_and_sources_are_consumed(self):
        with tempfile.TemporaryDirectory() as temp:
            sources = [
                {"title": "Raw leak headline", "summary": "Possible release window", "url": "https://example.com/leak", "image_url": "https://cdn.example.com/leak.jpg", "category": "gaming_rumor", "source_label": "X @insider"},
                {"title": "Raw reporter headline", "summary": "Independent corroboration", "url": "https://example.net/report", "category": "gaming_report", "source_label": "Reporter"},
            ]
            generator = lambda character, items, previous: [{
                "source_ids": [0, 1], "title": "کیرا: این شایعه جدی‌تر شد؟",
                "body": "دو منبع به یک بازه اشاره کرده‌اند، اما هنوز تأیید رسمی نداریم. من فعلاً با احتیاط نگاهش می‌کنم.",
                "confidence": "reported",
            }]
            service = NewsFeedService(lambda: {}, temp, post_generator=generator)
            with patch("kira.news_sources.collect_character_feeds", return_value=(sources, [])), \
                 patch.object(webintel_engine, "search", return_value={"results": []}):
                service._refresh_character("kira")
            posts = service.store.list_posts("kira")
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]["title"], "کیرا: این شایعه جدی‌تر شد؟")
            self.assertEqual(posts[0]["image_url"], "https://cdn.example.com/leak.jpg")
            self.assertIn("سطح اطمینان: گزارش‌شده", posts[0]["summary"])
            self.assertIn("منابع تکمیلی:", posts[0]["summary"])
            self.assertEqual(service.store.list_unprocessed_items("kira"), [])
            self.assertEqual(service.store.status("kira")["item_count"], 1)

    def test_personalized_caption_opening_is_preserved_without_greeting_cleanup(self):
        sources = [{
            "title": "Game update", "summary": "A new patch is announced.",
            "url": "https://example.com/game-update", "category": "gaming_news",
        }]
        posts = _prepare_character_posts(sources, [{
            "source_ids": [0], "title": "خبر تازهٔ بازی",
            "body": "علیرضا، این آپدیت تازه چند قابلیت مهم به بازی اضافه می‌کند.",
            "confidence": "reported",
        }])
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0]["summary"].startswith("علیرضا،"))

    def test_rumor_only_sources_cannot_be_promoted_to_confirmed(self):
        sources = [{
            "title": "Possible console leak", "url": "https://x.example/post",
            "source": "X @insider", "category": "gaming_rumor",
        }]
        posts = _prepare_character_posts(sources, [{
            "source_ids": [0], "title": "A possible leak",
            "body": "این ادعا هنوز تأیید مستقلی ندارد.", "confidence": "confirmed",
        }])
        self.assertEqual(len(posts), 1)
        self.assertIn("سطح اطمینان: تأییدنشده", posts[0]["summary"])

    def test_failed_post_generation_never_exposes_raw_source_as_a_post(self):
        with tempfile.TemporaryDirectory() as temp:
            sources = [{
                "title": "Raw source title", "summary": "Unprocessed source text",
                "url": "https://example.com/source", "source_label": "Publisher",
            }]
            service = NewsFeedService(
                lambda: {}, temp,
                post_generator=lambda *_args: (_ for _ in ()).throw(RuntimeError("model offline")),
            )
            with patch("kira.news_sources.collect_character_feeds", return_value=(sources, [])), \
                 patch.object(webintel_engine, "search", return_value={"results": []}):
                service._refresh_character("kira")
            self.assertEqual(service.store.list_posts("kira"), [])
            self.assertEqual(len(service.store.list_unprocessed_items("kira")), 1)
            self.assertIn("Post generation: RuntimeError", service.store.status("kira")["last_error"])
            self.assertIn("model offline", service.store.status("kira")["last_error"])

    def test_unknown_character_scope_is_rejected(self):
        item = {"title": "Story", "url": "https://example.com/story"}
        self.assertEqual(self.store.upsert_items("custom", [item], now=100), 0)
        self.assertEqual(self.store.list_items("custom"), [])


if __name__ == "__main__":
    unittest.main()
