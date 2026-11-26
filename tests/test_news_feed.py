from __future__ import annotations

import tempfile
import time
import unittest
from datetime import date, datetime, time as day_time, timedelta, timezone
from pathlib import Path

from kira import news_feed


class NewsFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "news.sqlite3"
        self.now = datetime.combine(
            date.today(), day_time(hour=12), tzinfo=timezone.utc
        ).timestamp()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def result(title, url, published, snippet="fresh sourced summary"):
        return {
            "title": title,
            "url": url,
            "date": published,
            "snippet": snippet,
        }

    def test_each_character_has_an_independent_feed(self):
        region = "Abadan, Iran"
        settings = {"health_news_region": region}

        def mika_search(query):
            return {
                "engine": "test",
                "results": [self.result(
                    "Regional health notice",
                    "https://health.example.org/notice",
                    date.today().isoformat(),
                )],
            }

        def ren_search(query):
            return {
                "engine": "test",
                "results": [self.result(
                    "Central bank rate announcement",
                    "https://markets.example.com/rates",
                    date.today().isoformat(),
                )],
            }

        news_feed.refresh_character(
            "mika", settings, now=self.now, db_path=self.db, search_fn=mika_search
        )
        news_feed.refresh_character(
            "ren", settings, now=self.now, db_path=self.db, search_fn=ren_search
        )

        mika_items = news_feed.get_items("mika", region=region, now=self.now, db_path=self.db)
        ren_items = news_feed.get_items("ren", now=self.now, db_path=self.db)
        kira_items = news_feed.get_items("kira", now=self.now, db_path=self.db)

        self.assertTrue(mika_items)
        self.assertTrue(ren_items)
        self.assertEqual(kira_items, [])
        self.assertIn("Regional health notice", " ".join(i["title"] for i in mika_items))
        self.assertNotIn("Central bank", " ".join(i["title"] for i in mika_items))
        self.assertNotIn("Regional health", " ".join(i["title"] for i in ren_items))

    def test_rolling_window_expires_day_one_and_keeps_day_two_on_day_eight(self):
        day_one = (date.today() - timedelta(days=6)).isoformat()
        day_two = (date.today() - timedelta(days=5)).isoformat()

        def search(query):
            if "public health" in query:
                items = [self.result("Day one outbreak report", "https://health.example.org/day-one", day_one)]
            else:
                items = [self.result("Day two medical study", "https://medicine.example.org/day-two", day_two)]
            return {"engine": "test", "results": items}

        news_feed.refresh_character(
            "mika",
            {"health_news_region": "Test City, Testland"},
            now=self.now,
            db_path=self.db,
            search_fn=search,
        )

        day_seven = news_feed.get_items(
            "mika", region="Test City, Testland", now=self.now, db_path=self.db
        )
        self.assertEqual(
            {item["title"] for item in day_seven},
            {"Day one outbreak report", "Day two medical study"},
        )

        day_eight = news_feed.get_items(
            "mika",
            region="Test City, Testland",
            now=self.now + 24 * 60 * 60,
            db_path=self.db,
        )
        titles = {item["title"] for item in day_eight}
        self.assertNotIn("Day one outbreak report", titles)
        self.assertIn("Day two medical study", titles)

    def test_regionless_mika_feed_does_not_claim_local_epidemic_alerts(self):
        queries = news_feed._queries("mika", "")
        self.assertEqual([item[0] for item in queries], ["medical_science"])

    def test_gaming_queries_belong_to_kira_not_ren(self):
        kira_queries = " ".join(item[2] for item in news_feed._queries("kira", ""))
        ren_queries = " ".join(item[2] for item in news_feed._queries("ren", ""))
        self.assertIn("video games", kira_queries)
        self.assertIn("gaming hardware", kira_queries)
        self.assertNotIn("video games", ren_queries)
        self.assertIn("-gaming", ren_queries)

    def test_confirmed_region_is_long_term_context_even_without_news(self):
        block = news_feed.build_context(
            "mika",
            "hello",
            {"health_news_region": "Frankfurt, Germany"},
            now=self.now,
            db_path=self.db,
        )
        self.assertIn("Frankfurt, Germany", block)
        self.assertIn("دوباره برای دانستن منطقه سؤال نکن", block)

    def test_current_prices_are_never_answered_from_week_old_feed(self):
        def search(query):
            return {
                "engine": "test",
                "results": [self.result(
                    "Bitcoin market news",
                    "https://markets.example.com/bitcoin",
                    date.today().isoformat(),
                    "Bitcoin market developments and regulation",
                )],
            }

        news_feed.refresh_character(
            "ren", {}, now=self.now, db_path=self.db, search_fn=search
        )
        self.assertTrue(news_feed.can_answer_from_feed(
            "ren", "latest Bitcoin news", {}, now=self.now, db_path=self.db
        ))
        self.assertFalse(news_feed.can_answer_from_feed(
            "ren", "قیمت فعلی بیت کوین چقدر است؟", {}, now=self.now, db_path=self.db
        ))

    def test_context_contains_sources_and_does_not_mix_characters(self):
        def mika_search(query):
            return {
                "engine": "test",
                "results": [self.result(
                    "Medical research headline",
                    "https://medical.example.org/study",
                    date.today().isoformat(),
                )],
            }

        news_feed.refresh_character(
            "mika",
            {"health_news_region": "Test City, Testland"},
            now=self.now,
            db_path=self.db,
            search_fn=mika_search,
        )
        block = news_feed.build_context(
            "mika", "medical research", {"health_news_region": "Test City, Testland"}, now=self.now, db_path=self.db
        )
        self.assertIn("Medical research headline", block)
        self.assertIn("https://medical.example.org/study", block)
        self.assertNotIn("بنیادی", block)
        self.assertEqual(
            news_feed.build_context("ren", "economy", {}, now=self.now, db_path=self.db),
            "",
        )


if __name__ == "__main__":
    unittest.main()
