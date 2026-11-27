"""Registers the Web Intelligence tools in the unified tool registry (category "web"). All logic lives in kira/webintel; this file only
defines the tool contracts, so every Provider (even without function calling) reaches them through the same text protocol.

  web_search          multi-kind search (web / news / docs / images): de-duplicated, ranked by relevance + credibility + freshness
  web_read            open ONE page safely, return title / publisher / date + the relevant passages, optionally follow related links
  web_research        Deep Research: plan sub-topics, search and read several sources, fill gaps, compare, structured cited report
  web_research_status status / stop / continue-info / clear the temporary research memory

They are READ-level tools (they never change the PC, never download or run files). The user's own request must be about the web, the
address must come from the user or from this research, and nothing secret can leave in a query or a link (see webintel/netguard.py).
"""
from __future__ import annotations

import re

from .. import websearch
from ..webintel import engine
from ..webintel.session import CANCEL, ResearchStore, SessionScopedResearchStore
from .registry import Tool, Param, ToolError, READ, DENIED

# the user's CURRENT message must be about the web / research (a page can not make Kira search by itself)
_WEB_INTENT = re.compile(
    r"(?:سرچ|جست\s?و\s?جو|جستجو|گوگل|\bgoogle\b|\bsearch\b|look\s*up|اینترنت|آنلاین|\bonline\b|\bوب\b|\bweb\b|تحقیق|پژوهش|research|investigate|بررسی|منبع|منابع|source|"
    r"استناد|مستند|لینک|آدرس|سایت|صفحه|\burl\b|https?://|www\.|خبر|اخبار|news|آخرین|جدیدترین|latest|امروز|الان|اکنون|today|current|قیمت|نرخ|price|مقاله|paper|pdf|"
    r"fact\s*-?check|صحت|درست\s+است|راست\s+است|تأیید\s+کن|مقایسه|compare|گزارش|report|ادامه|resume|continue|توقف|بس\s*کن|stop|عکس|تصویر|image|photo|"
    r"بخون|بخوان|read|باز\s*کن|open|چک\s*کن|check)", re.I)
_NORM = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": " ", "\u200f": " "})


def _followup(ctx: engine.Context, text: str) -> bool:
    """Second way to pass the central explicit-request gate (sysaccess intent_alt): `text` is the normalised user message."""
    cur = ctx.store.current()                                   # a short follow-up while a research is paused ("بزن بریم", "باشه") continues it
    return cur is not None and cur.status in ("paused", "running") and len(text.split()) <= 6


def _gate(ctx: engine.Context):
    # Re-check the user's current message at execution time. The keyword intent
    # regex also matches negated phrases such as "سرچ نکن"; those must never
    # authorize a network request.
    if websearch.explicit_no_web(ctx.user_text()):
        raise ToolError("طبق درخواستت جست‌وجوی وب انجام نمی‌دهم.", DENIED)
    if not ctx.enabled():
        raise ToolError("تحقیق وب در تنظیمات خاموش است (web_research = false).", DENIED)


def _clip_int(value, lo, hi, default):
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def web_tools(settings_fn, data_dir, user_text_fn, session_id_fn=None) -> tuple[engine.Context, list[Tool]]:
    store = (
        SessionScopedResearchStore(data_dir, session_id_fn)
        if session_id_fn is not None else ResearchStore(data_dir)
    )
    ctx = engine.Context(settings_fn, store, user_text_fn)

    def _ensure_session():
        sess = ctx.store.current()
        if sess is None:
            from ..webintel.session import budget_from
            sess = ctx.store.start("(جست‌وجوی آزاد)", budget_from(ctx.settings))
            sess.status = "done"
        return sess

    def _search(a: dict) -> str:
        _gate(ctx)
        res = engine.search(ctx, a["query"], a.get("kind", "web"), _clip_int(a.get("max_results"), 1, 10, 6), _ensure_session())
        ctx.store.save()
        return engine.format_search(res)

    def _read(a: dict) -> str:
        _gate(ctx)
        sess = _ensure_session()
        query = a.get("query", "")
        start = _clip_int(a.get("start"), 0, 5_000_000, 0)
        max_chars = _clip_int(a.get("max_chars"), 500, 8000, 3500)
        rec = engine.read_page(ctx, a["url"], query, sess, 4 if query else 3, use_cache=start == 0)
        followed = []
        want = _clip_int(a.get("follow_links"), 0, 3, 0)
        if want and rec.get("status") == "ok":
            for l in engine.related_links(rec, query, want):
                if len(followed) >= want:
                    break
                try:
                    f = engine.read_page(ctx, l["url"], query or rec.get("title", ""), sess, 2, check_allowed=False)
                except Exception:                                      # noqa: BLE001 - a broken link must not spoil the main page
                    continue
                followed.append(f)
        ctx.store.save()
        return engine.format_page(rec, query, max_chars, followed, start)

    def _research(a: dict) -> str:
        _gate(ctx)
        raw_subs = a.get("subtopics") or ""
        raw_subs = raw_subs if isinstance(raw_subs, list) else re.split(r"[|\n؛;]", str(raw_subs))
        subs = [str(s).strip() for s in raw_subs if str(s).strip()]
        over = {"max_searches": a.get("max_searches"), "max_pages": a.get("max_pages"), "max_seconds": a.get("max_seconds"), "max_chars": a.get("max_chars")}
        resume = bool(a.get("resume", False))
        if not resume and not a.get("topic"):
            raise ToolError("آرگومان لازم ارسال نشده: topic (یا resume=true برای ادامه‌ی تحقیق متوقف‌شده).", "bad_args")
        _sess, report = engine.deep_research(ctx, a.get("topic", ""), subs, over, resume)
        return report

    def _status(a: dict) -> str:
        action = a.get("action", "status")
        sess = ctx.store.current()
        if action == "clear":
            ctx.store.clear()
            return "حافظه‌ی موقت تحقیق پاک شد (حافظه‌ی بلندمدت Kira دست‌نخورده است)."
        if action == "stop":
            CANCEL.set()
            if sess is not None and sess.status == "running":
                sess.status = "paused"
                sess.stop_reason = "کاربر متوقف کرد"
                ctx.store.save()
            return "تحقیق متوقف شد و وضعیتش نگه داشته شد؛ با «ادامه‌ی تحقیق» ادامه پیدا می‌کند."
        return engine.format_status(sess, as_json=(action == "json"))

    tools = [
        Tool("web_search", "search the WEB (kind: web | news | docs=PDF/documents | images). Results are ranked and de-duplicated, with date, freshness and source type. Search results alone are NOT proof",
             _search,
             (Param("query", "string", "short, specific search words (no secrets, no file paths)", True),
              Param("kind", "string", "web (default) | news | docs | images", False, "web", ("web", "news", "docs", "images")),
              Param("max_results", "integer", "default 6, max 10", False, 6)),
             READ, ("web",), max_chars=7000),
        Tool("web_read", "open ONE web page or online PDF (address from the user or from a web_search result) and get its title, publisher, date and the passages about `query`; follow_links=1-3 also reads related links",
             _read,
             (Param("url", "string", "full http(s) address", True),
              Param("query", "string", "what to look for in the page (returns only the relevant passages)"),
              Param("follow_links", "integer", "also read up to N related links of the page (0-3)", False, 0),
              Param("start", "integer", "character offset to continue a long page (only without query)", False, 0),
              Param("max_chars", "integer", "default 3500, max 8000", False, 3500)),
             READ, ("web",), max_chars=12000),
        Tool("web_research", "DEEP RESEARCH on a topic: plans sub-topics, searches and reads several independent sources, compares them, and returns a cited report (confirmed / single-source / analysis / uncertain, contradictions, stale data, unreachable pages). resume=true continues a stopped research",
             _research,
             (Param("topic", "string", "the research topic or question"),
              Param("subtopics", "array", "optional: list of sub-topics (or text separated by |); otherwise they are planned automatically"),
              Param("max_searches", "integer", "limit on searches (default 8, max 20)"),
              Param("max_pages", "integer", "limit on pages read (default 10, max 25)"),
              Param("max_seconds", "integer", "time limit (default 90, max 300)"),
              Param("max_chars", "integer", "size of the report (default 9000, max 14000)"),
              Param("resume", "boolean", "continue the paused / stopped research instead of starting a new one", False, False)),
             READ, ("web",), max_chars=14500),
        Tool("web_research_status", "status of the current temporary research (action: status | json | stop | clear)",
             _status,
             (Param("action", "string", "status (default) | json | stop | clear", False, "status", ("status", "json", "stop", "clear")),),
             READ, ("web",)),
    ]
    for t in tools:
        if t.name in ("web_search", "web_read", "web_research"):      # the explicit-request gate is enforced centrally (sysaccess), not inside the handlers
            t.intent_rx = _WEB_INTENT
            t.intent_alt = lambda text, c=ctx: _followup(c, text)
    return ctx, tools


def register_web_tools(reg, settings_fn, data_dir):
    ctx, tools = web_tools(
        settings_fn,
        data_dir,
        lambda: reg.user_text,
        session_id_fn=lambda: reg.access.session_id,
    )
    for t in tools:
        reg.register(t)
    reg.web_context = ctx
    return ctx
