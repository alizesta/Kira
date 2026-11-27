"""Regression tests for RSS source coverage and untrusted feed parsing."""
import unittest

from kira.news_sources import FEED_SOURCES, FeedSource, collect_character_feeds, parse_feed


class NewsSourceTests(unittest.TestCase):
    def test_kira_has_publishers_community_and_x_sources(self):
        kira = [item for item in FEED_SOURCES if item.character == "kira"]
        self.assertGreaterEqual(len(kira), 12)
        self.assertTrue(any(item.category == "gaming_news" for item in kira))
        self.assertTrue(any(item.category == "gaming_community" for item in kira))
        x_sources = [item for item in kira if item.url.startswith("https://fxtwitter.com/")]
        self.assertGreaterEqual(len(x_sources), 5)
        self.assertGreaterEqual(sum(item.category == "gaming_rumor" for item in x_sources), 3)
        self.assertGreaterEqual(sum(item.category == "gaming_report" for item in x_sources), 2)
        self.assertTrue(any(item.category == "gaming_social" for item in x_sources))
        self.assertTrue(any(item.category == "gaming_rumor" and "GamingLeaksAndRumours" in item.label for item in kira))

    def test_mika_has_multiple_iranian_health_sources(self):
        mika = [item for item in FEED_SOURCES if item.character == "mika"]
        iranian = [item for item in mika if item.health_filter]
        self.assertGreaterEqual(len(iranian), 6)
        self.assertTrue(all(item.category == "iran_health" for item in iranian))
        self.assertTrue(any("salamatnews" in item.url for item in iranian))
        self.assertTrue(any("isna.ir" in item.url for item in iranian))

    def test_rss_items_are_parsed_and_health_filtered(self):
        source = FeedSource("mika", "iran_health", "سلامت نیوز", "https://example.ir/rss", True)
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><title>خبر تازه درباره سلامت قلب</title>
            <link>https://example.ir/health/1</link>
            <description><![CDATA[پژوهش پزشکی جدید درباره سلامت قلب.]]></description>
            <pubDate>Fri, 27 Nov 2026 10:00:00 GMT</pubDate>
          </item>
          <item><title>نتیجه مسابقه فوتبال</title>
            <link>https://example.ir/sport/2</link>
            <description>نتیجه مسابقه امروز</description>
          </item>
        </channel></rss>""".encode("utf-8")
        items = parse_feed(xml, source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"], "iran_health")
        self.assertEqual(items[0]["source_label"], "سلامت نیوز")
        self.assertIn("27 Nov 2026", items[0]["published_at"])

    def test_atom_links_and_html_summaries_are_supported(self):
        source = FeedSource("kira", "gaming_rumor", "X @example", "https://example.com/feed")
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Unconfirmed game leak</title>
            <link rel="alternate" href="https://example.com/post/1"/>
            <summary type="html">&lt;p&gt;A possible release date&lt;/p&gt;</summary>
            <updated>2026-11-27T10:00:00Z</updated>
          </entry>
        </feed>"""
        items = parse_feed(xml, source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/post/1")
        self.assertEqual(items[0]["summary"], "A possible release date")

    def test_dtd_and_entity_declarations_are_rejected(self):
        source = FeedSource("kira", "gaming_rumor", "bad", "https://example.com/feed")
        xml = b"""<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <rss><channel><item><title>&xxe;</title></item></channel></rss>"""
        self.assertEqual(parse_feed(xml, source), [])
        self.assertEqual(parse_feed(b" " * 5000 + xml, source), [])
        utf16 = b"\\xff\\xfe" + xml.decode("utf-8").encode("utf-16-le")
        self.assertEqual(parse_feed(utf16, source), [])

    def test_unknown_character_returns_no_feeds_without_network(self):
        self.assertEqual(collect_character_feeds("unknown"), ([], []))


if __name__ == "__main__":
    unittest.main()
