"""Curated RSS/Atom sources for character news; all downloads use the SSRF-safe web fetcher."""
from __future__ import annotations

import concurrent.futures
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import NamedTuple


class FeedSource(NamedTuple):
    character: str
    category: str
    label: str
    url: str
    health_filter: bool = False


# Kira deliberately mixes publishers, community discussion, and X accounts.
# FxEmbed exposes RSS for public X profiles; it is a best-effort bridge, not an X API.
FEED_SOURCES = (
    FeedSource("kira", "gaming_news", "IGN", "https://www.ign.com/rss/v2/articles/feed"),
    FeedSource("kira", "gaming_news", "PC Gamer", "https://www.pcgamer.com/rss/"),
    FeedSource("kira", "gaming_news", "GameSpot", "https://www.gamespot.com/feeds/news/"),
    FeedSource("kira", "gaming_news", "Eurogamer", "https://www.eurogamer.net/feed"),
    FeedSource("kira", "gaming_news", "Kotaku", "https://kotaku.com/feed"),
    FeedSource("kira", "gaming_news", "Polygon", "https://www.polygon.com/rss/index.xml"),
    FeedSource("kira", "gaming_news", "Rock Paper Shotgun", "https://www.rockpapershotgun.com/feed"),
    FeedSource("kira", "gaming_rumor", "Reddit GamingLeaksAndRumours", "https://www.reddit.com/r/GamingLeaksAndRumours/.rss"),
    FeedSource("kira", "gaming_community", "Reddit Games", "https://www.reddit.com/r/Games/.rss"),
    FeedSource("kira", "gaming_community", "Reddit PCGaming", "https://www.reddit.com/r/pcgaming/.rss"),
    FeedSource("kira", "gaming_social", "X @Wario64", "https://fxtwitter.com/Wario64/feed.xml?count=6"),
    FeedSource("kira", "gaming_rumor", "X @billbil_kun", "https://fxtwitter.com/billbil_kun/feed.xml?count=6"),
    FeedSource("kira", "gaming_report", "X @PlaystationSize", "https://fxtwitter.com/PlaystationSize/feed.xml?count=6"),
    FeedSource("kira", "gaming_report", "X @tomwarren", "https://fxtwitter.com/tomwarren/feed.xml?count=6"),
    FeedSource("kira", "gaming_report", "X @jasonschreier", "https://fxtwitter.com/jasonschreier/feed.xml?count=6"),
    FeedSource("kira", "gaming_rumor", "X @Shpeshal_Nick", "https://fxtwitter.com/Shpeshal_Nick/feed.xml?count=6"),
    FeedSource("kira", "gaming_rumor", "X @AestheticGamer1", "https://fxtwitter.com/AestheticGamer1/feed.xml?count=6"),

    # Iranian publishers. Their general feeds are filtered locally so Mika only
    # receives health, medicine, nutrition, public-health and wellness stories.
    FeedSource("mika", "iran_health", "سلامت نیوز", "https://www.salamatnews.com/rss.xml", True),
    FeedSource("mika", "iran_health", "بهداشت نیوز", "https://behdasht.news/rss-fa.xml", True),
    FeedSource("mika", "iran_health", "ایسنا", "https://www.isna.ir/rss", True),
    FeedSource("mika", "iran_health", "مهر", "https://www.mehrnews.com/rss", True),
    FeedSource("mika", "iran_health", "تسنیم", "https://www.tasnimnews.com/fa/rss/feed/0/0/8/1/TopStories", True),
    FeedSource("mika", "iran_health", "باشگاه خبرنگاران جوان", "https://www.yjc.ir/fa/rss/allnews", True),
    FeedSource("mika", "iran_health", "خبرآنلاین", "https://www.khabaronline.ir/rss", True),
    FeedSource("mika", "iran_health", "ایرنا", "https://www.irna.ir/rss", True),
    FeedSource("mika", "iran_health", "تابناک", "https://www.tabnak.ir/fa/rss/allnews", True),
    FeedSource("mika", "iran_health", "عصر ایران", "https://www.asriran.com/fa/rss/allnews", True),
)

_HEALTH_TERMS = re.compile(
    r"سلامت|بهداشت|پزشک|پزشکی|درمان|بیمار|بیماری|دارو|دارویی|"
    r"تغذیه|غذا|ویتامین|مکمل|واکسن|واکسیناسیون|آنفلوآنزا|کرونا|"
    r"سرطان|قلب|دیابت|فشار خون|روان.?شناسی|سلامت روان|"
    r"وزارت بهداشت|دانشگاه علوم پزشکی|سازمان غذا و دارو|"
    r"health|medical|medicine|nutrition|vitamin|vaccine|disease|hospital",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data and data.strip():
            self.parts.append(data.strip())


def _plain_text(value: str, limit: int) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value or "")
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]*>", " ", value or "")
    return " ".join(text.split())[:limit].strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def _child_text(element, names) -> str:
    wanted = set(names)
    for child in element.iter():
        if child is element or _local(child.tag) not in wanted:
            continue
        value = "".join(child.itertext()).strip()
        if value:
            return value
    return ""


def _entry_link(entry) -> str:
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        rel = child.attrib.get("rel", "alternate").lower()
        if href and rel in ("alternate", ""):
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def parse_feed(xml_data: bytes | str, source: FeedSource, *, limit: int = 20) -> list[dict]:
    """Parse RSS 2.0 or Atom safely; reject DTD/entity declarations and malformed XML."""
    raw = xml_data.encode("utf-8") if isinstance(xml_data, str) else bytes(xml_data or b"")
    if not raw or len(raw) > 1_000_000:
        return []
    # Scan the entire bounded document and ignore UTF-16/32 NUL bytes so a
    # padded prolog or alternate XML encoding cannot hide a DTD declaration.
    upper = raw.replace(b"\\x00", b"").upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return []
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, TypeError):
        return []
    entries = [node for node in root.iter() if _local(node.tag) in ("item", "entry")]
    results = []
    for entry in entries[:max(1, min(int(limit), 30))]:
        title = _plain_text(_child_text(entry, ("title",)), 240)
        link = _entry_link(entry) or _child_text(entry, ("link", "guid", "id"))
        summary = _plain_text(
            _child_text(entry, ("encoded", "description", "summary", "content", "subtitle")), 900
        )
        published = _child_text(entry, ("pubdate", "published", "updated", "date", "created"))
        if not title or not link.startswith(("http://", "https://")):
            continue
        if source.health_filter and not _HEALTH_TERMS.search(title + " " + summary):
            continue
        results.append({
            "title": title,
            "summary": summary,
            "url": link,
            "published_at": published,
            "category": source.category,
            "source_label": source.label,
        })
    return results


def collect_character_feeds(character: str) -> tuple[list[dict], list[str]]:
    """Fetch a character's curated feeds concurrently, without allowing one dead feed to block others."""
    sources = [item for item in FEED_SOURCES if item.character == character]
    if not sources:
        return [], []
    from .webintel.netguard import fetch

    def load(source: FeedSource):
        response = fetch(
            source.url, timeout=7, max_bytes=1_000_000, max_redirects=2, total_timeout=12
        )
        if response.status < 200 or response.status >= 300:
            raise ValueError(f"HTTP {response.status}")
        return source, parse_feed(response.body, source, limit=6)

    items, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="kira-rss") as pool:
        futures = {pool.submit(load, source): source for source in sources}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                _source, found = future.result()
                items.extend(found)
            except Exception as exc:  # noqa: BLE001 - individual feeds are optional
                errors.append(f"{source.label}: {type(exc).__name__}")
    return items, errors
