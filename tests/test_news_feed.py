import tempfile
import unittest
from pathlib import Path

from kira.news_feed import NewsFeedStore, RETENTION_SECONDS


class NewsFeedStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = NewsFeedStore(Path(self.temp.name) / "feed.sqlite3")

    def add(self, character, category, url, now):
        return self.store.add_item(
            character,
            category=category,
            title=f"{character} headline",
            summary="Verified source summary",
            source_name="Example Source",
            source_url=url,
            published_at=now,
            fetched_at=now,
        )

    def test_seven_day_window_moves_forward_and_drops_oldest_day(self):
        day = 86400
        start = 2_000_000_000
        for offset in range(7):
            self.add("ren", "economy", f"https://example.com/{offset}", start + offset * day)

        day_eight = start + 7 * day
        self.add("ren", "economy", "https://example.com/7", day_eight)
        current = self.store.list_items("ren", now=day_eight)
        self.assertEqual(len(current), 7)
        self.assertEqual(
            {row["source_url"] for row in current},
            {f"https://example.com/{i}" for i in range(1, 8)},
        )

        day_nine = start + 8 * day
        self.add("ren", "economy", "https://example.com/8", day_nine)
        current = self.store.list_items("ren", now=day_nine)
        self.assertEqual(len(current), 7)
        self.assertEqual(
            {row["source_url"] for row in current},
            {f"https://example.com/{i}" for i in range(2, 9)},
        )

    def test_news_is_isolated_by_character(self):
        self.add("mika", "medical", "https://health.example/a", 2_000_000_000)
        self.add("ren", "crypto", "https://finance.example/b", 2_000_000_000)
        self.add("kira", "gaming", "https://games.example/c", 2_000_000_000)

        self.assertEqual([x["category"] for x in self.store.list_items("mika", now=2_000_000_001)], ["medical"])
        self.assertEqual([x["category"] for x in self.store.list_items("ren", now=2_000_000_001)], ["crypto"])
        self.assertEqual([x["category"] for x in self.store.list_items("kira", now=2_000_000_001)], ["gaming"])

    def test_cross_character_category_is_rejected(self):
        with self.assertRaises(ValueError):
            self.add("ren", "gaming", "https://games.example/a", 2_000_000_000)
        with self.assertRaises(ValueError):
            self.add("mika", "crypto", "https://finance.example/a", 2_000_000_000)

    def test_expired_item_is_removed_and_old_publication_is_not_refreshed(self):
        now = 2_000_000_000
        self.add("mika", "medical", "https://health.example/old", now - RETENTION_SECONDS - 1)
        self.assertEqual(self.store.list_items("mika", now=now), [])

    def test_context_contains_source_and_separates_analysis(self):
        self.store.add_item(
            "ren",
            category="markets",
            title="Market headline",
            summary="Reported fact",
            analysis="Independent interpretation",
            source_name="Market Desk",
            source_url="https://markets.example/story",
            published_at=2_000_000_000,
            fetched_at=2_000_000_000,
        )
        context = self.store.build_context("ren")
        self.assertIn("Market Desk", context)
        self.assertIn("https://markets.example/story", context)
        self.assertIn("Reported summary: Reported fact", context)
        self.assertIn("Separate analysis: Independent interpretation", context)
        self.assertNotIn("Market headline", self.store.build_context("mika"))


if __name__ == "__main__":
    unittest.main()
