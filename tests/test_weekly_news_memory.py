from __future__ import annotations

from datetime import datetime, timezone

from kira import websearch
from kira.app.web_search import WebSearchApplicationService
from kira.weekly_news_memory import DAY, WeeklyNewsMemoryService


def _published_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _story(url="https://www.who.int/news/item", title="New medical research", **overrides):
    item = {
        "url": url,
        "title": title,
        "snippet": "Researchers reported new findings in a recently published study.",
        "date": _published_today(),
    }
    item.update(overrides)
    return item


def test_refresh_filters_old_undated_and_weak_sources_and_keeps_character_scope(tmp_path):
    calls = []

    def search(settings, query):
        calls.append(query)
        return {"results": [
            _story(),
            _story("https://www.reddit.com/r/science/example", "Social discussion", date=_published_today()),
            _story("https://www.nih.gov/old-study", "Old study", date="2020-01-01"),
            _story("https://www.nih.gov/undated", "Undated study", date=""),
        ]}

    service = WeeklyNewsMemoryService(lambda: {}, tmp_path, search_fn=search)
    now = datetime.now(timezone.utc).timestamp()
    assert service.refresh_character("mika", force=True, now=now)
    assert len(calls) == 2
    assert len(service.active_items("mika", now=now)) == 1
    assert service.active_items("ren", now=now) == []


def test_seven_day_expiry_and_persistent_reload(tmp_path):
    service = WeeklyNewsMemoryService(
        lambda: {},
        tmp_path,
        search_fn=lambda settings, query: {"results": [_story()]},
    )
    now = datetime.now(timezone.utc).timestamp()
    assert service.refresh_character("mika", force=True, now=now)
    assert len(service.active_items("mika", now=now + 6 * DAY)) == 1
    reloaded = WeeklyNewsMemoryService(lambda: {}, tmp_path, search_fn=lambda *_: {})
    assert len(reloaded.active_items("mika", now=now + 6 * DAY)) == 1
    assert reloaded.active_items("mika", now=now + 7 * DAY + 1) == []


def test_prompt_and_cache_are_character_scoped_and_respect_live_lookup_requests(tmp_path):
    service = WeeklyNewsMemoryService(
        lambda: {},
        tmp_path,
        search_fn=lambda settings, query: {"results": [
            _story(title="Clinical trial reports progress on cancer treatment")
        ]},
    )
    now = datetime.now(timezone.utc).timestamp()
    service.refresh_character("mika", force=True, now=now)

    block = service.prompt_block("mika", "آخرین خبرهای پزشکی", now=now)
    assert "Clinical trial reports progress" in block
    assert "https://www.who.int/news/item" in block
    assert service.prompt_block("ren", "آخرین خبرهای پزشکی", now=now) == ""
    assert service.covers_query("mika", "درمان سرطان", now=now)
    assert not service.covers_query("mika", "سرچ کن آخرین درمان سرطان", now=now)
    assert not service.covers_query("mika", "قیمت لحظه‌ای دارو", now=now)
    assert not service.covers_query("mika", "قیمت دارو چنده؟", now=now)
    assert not service.covers_query("mika", "latest cryptocurrency news", now=now)


def test_failed_refresh_preserves_still_valid_memory(tmp_path):
    working = {"fail": False}

    def search(settings, query):
        if working["fail"]:
            raise RuntimeError("network unavailable")
        return {"results": [_story()]}

    service = WeeklyNewsMemoryService(lambda: {}, tmp_path, search_fn=search)
    now = datetime.now(timezone.utc).timestamp()
    assert service.refresh_character("mika", force=True, now=now)
    before = service.active_items("mika", now=now)
    working["fail"] = True
    assert not service.refresh_character("mika", force=True, now=now + 60)
    after = service.active_items("mika", now=now + 60)
    assert [item["id"] for item in after] == [item["id"] for item in before]




def test_ren_collects_its_own_finance_and_digital_news(tmp_path):
    calls = []

    def search(settings, query):
        calls.append(query)
        return {"results": [
            _story("https://www.reuters.com/markets/example", "Global stock markets react to central bank decision"),
            _story("https://www.reuters.com/technology/example", "Digital technology industry reports new AI investment"),
            _story("https://www.reuters.com/business/example", "Inflation and currency markets move after policy update"),
            _story("https://www.reuters.com/technology/crypto-example", "Bitcoin and Ethereum regulation news"),
        ]}

    service = WeeklyNewsMemoryService(lambda: {}, tmp_path, search_fn=search)
    now = datetime.now(timezone.utc).timestamp()
    assert service.refresh_character("ren", force=True, now=now)
    assert len(calls) == 4
    assert len(service.active_items("ren", now=now)) == 4
    assert service.covers_query("ren", "آخرین اخبار اقتصاد و فناوری", now=now)
    assert service.prompt_block("mika", "آخرین اخبار پزشکی", now=now) == ""
    assert "Bitcoin and Ethereum regulation" in service.prompt_block(
        "ren", "آخرین اخبار رمزارز", now=now
    )




def test_news_domains_do_not_cross_between_mika_and_ren(tmp_path):
    def search(settings, query):
        if "medical" in query or "biomedical" in query:
            return {"results": [_story(title="Medical clinical trial reports a new treatment result")]}
        return {"results": [
            _story("https://www.reuters.com/technology/bitcoin", "Bitcoin technology and cryptocurrency market update")
        ]}

    service = WeeklyNewsMemoryService(lambda: {}, tmp_path, search_fn=search)
    now = datetime.now(timezone.utc).timestamp()
    assert service.refresh_character("mika", force=True, now=now)
    assert service.refresh_character("ren", force=True, now=now)

    assert service.covers_query("mika", "آخرین اخبار پزشکی", now=now)
    assert not service.covers_query("mika", "latest cryptocurrency news", now=now)
    assert service.covers_query("ren", "latest cryptocurrency news", now=now)
    assert not service.covers_query("ren", "آخرین اخبار پزشکی", now=now)
    assert not service.covers_query("ren", "قیمت بیت کوین چنده؟", now=now)
    assert not service.covers_query("ren", "نرخ دلار چنده؟", now=now)


def test_automatic_search_uses_cached_news_but_explicit_web_still_wins(monkeypatch):
    service = WebSearchApplicationService()
    monkeypatch.setattr(websearch, "plan", lambda text: ("latest medical science", False))
    assert service.plan_request(
        "latest medical science", {"web_search": True}, cached_news=True
    ) == (None, False)

    monkeypatch.setattr(websearch, "plan", lambda text: ("latest medical science", True))
    assert service.plan_request(
        "latest medical science", {"web_search": True}, cached_news=True
    ) == ("latest medical science", True)
    assert service.plan_request(
        "medical science", {"web_search": True}, force_web=True, cached_news=True
    ) == ("medical science", True)
