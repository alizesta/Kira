"""Ranking, de-duplication, freshness and credibility of search results. Pure local code: no model, no network, no tokens.

Credibility here is an honest HEURISTIC of the kind of site (official / academic / news agency / reference / forum), never a verdict on
the truth of a claim. The final answer must still say which claims are only reported by one source.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .extract import date_from_url, host_name, parse_date

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# ------------------------------------------------------------------ source kinds
_PRIMARY_SUFFIX = (".gov", ".gov.uk", ".gov.au", ".gov.ir", ".mil", ".int", ".edu", ".ac.uk", ".ac.ir", ".edu.au", ".europa.eu")
_PRIMARY_HOSTS = {"who.int", "un.org", "worldbank.org", "imf.org", "oecd.org", "nih.gov", "cdc.gov", "nasa.gov", "arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov",
                  "ncbi.nlm.nih.gov", "nature.com", "science.org", "sciencedirect.com", "springer.com", "ieee.org", "acm.org", "w3.org", "ietf.org",
                  "rfc-editor.org", "iso.org", "sec.gov", "cbi.ir", "tse.ir", "majlis.ir", "president.ir", "iana.org", "python.org", "kernel.org"}
_AGENCY_HOSTS = {"reuters.com", "apnews.com", "afp.com", "bbc.com", "bbc.co.uk", "dw.com", "aljazeera.com", "theguardian.com", "nytimes.com", "washingtonpost.com",
                 "wsj.com", "ft.com", "bloomberg.com", "economist.com", "npr.org", "france24.com", "cnn.com", "irna.ir", "isna.ir", "ilna.ir", "mehrnews.com",
                 "tasnimnews.com", "farsnews.ir", "euronews.com", "techcrunch.com", "theverge.com", "arstechnica.com", "wired.com", "zoomit.ir", "digiato.com"}
_REFERENCE_HOSTS = {"wikipedia.org", "britannica.com", "wikidata.org", "fa.wikipedia.org", "en.wikipedia.org", "stackoverflow.com", "stackexchange.com",
                    "developer.mozilla.org", "github.com", "docs.python.org", "learn.microsoft.com"}
_WEAK_HOSTS = {"reddit.com", "quora.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "tiktok.com", "pinterest.com", "telegram.me", "t.me",
               "medium.com", "blogspot.com", "wordpress.com", "tumblr.com", "blogfa.com", "blogsky.com", "persianblog.ir", "mihanblog.com", "rozblog.com",
               "linkedin.com", "youtube.com", "youtu.be", "aparat.com", "answers.com", "ask.com", "yahoo.com", "scribd.com", "slideshare.net", "pastebin.com"}
_OPINION_RX = re.compile(r"/(?:opinion|opinions|analysis|editorial|blog|blogs|column|columns|comment|views?|یادداشت|تحلیل|نظر|سرمقاله)(?:/|-|$)", re.I)
_TIME_RX = re.compile(r"(?:اخبار|خبر|امروز|الان|اکنون|اخیراً?|آخرین|جدیدترین|لحظه|فوری|دیشب|هفته\s+(?:گذشته|جاری)|ماه\s+(?:گذشته|جاری)|قیمت|نرخ|دلار|یورو|سکه|طلا|"
                      r"بیت\s?کوین|هوا|وضعیت\s+فعلی|نتیجه|رتبه|فعلی|امسال|\b(?:news|latest|today|now|current(?:ly)?|recent(?:ly)?|breaking|price|prices|rate|weather|"
                      r"score|results?|update[sd]?|this\s+(?:week|month|year)|20(?:2[5-9]|3\d))\b)", re.I)


def is_time_sensitive(text: str) -> bool:
    return bool(_TIME_RX.search(str(text or "")))


def registrable(host: str) -> str:
    """example.co.uk / news.example.com -> a stable key for 'same publisher' (not a full public-suffix list, but good enough here)."""
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if parts[-2] in ("co", "com", "org", "net", "gov", "edu", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def source_kind(url: str, query_tokens: set[str] | None = None) -> tuple[str, float]:
    """-> (kind, credibility 0..1). kind: primary | agency | reference | weak | other. 'primary' also covers the official site of the thing asked about."""
    host = host_name(url)
    reg = registrable(host)
    path = urlsplit(url).path
    if host.endswith(_PRIMARY_SUFFIX) or host in _PRIMARY_HOSTS or reg in _PRIMARY_HOSTS:
        return "primary", 1.0
    if reg in _WEAK_HOSTS or host in _WEAK_HOSTS or any(host.endswith("." + w) for w in _WEAK_HOSTS):
        return "weak", 0.3
    if reg in _AGENCY_HOSTS or host in _AGENCY_HOSTS:
        return ("agency", 0.55) if _OPINION_RX.search(path) else ("agency", 0.85)
    if reg in _REFERENCE_HOSTS or host in _REFERENCE_HOSTS:
        return "reference", 0.65
    name = reg.split(".")[0]
    if query_tokens and len(name) >= 4 and any(name == t or (len(t) >= 5 and name.startswith(t)) or (len(name) >= 6 and t.startswith(name)) for t in query_tokens):
        return "primary", 0.9                                    # the site is named after what was asked about (official page)
    if host.split(".")[0] in ("docs", "developer", "developers", "support", "help", "press", "newsroom", "investor", "ir"):
        return "primary", 0.85
    return "other", 0.5


# ------------------------------------------------------------------ URLs / duplicates
_TRACK_PARAMS = re.compile(r"^(?:utm_\w+|fbclid|gclid|yclid|mc_cid|mc_eid|ref|ref_src|source|spm|igshid|_ga|cmpid|ocid|amp|output)$", re.I)


def canonical_url(url: str) -> str:
    """Same page, different spelling -> same key (no tracking params, no #fragment, no www, no trailing slash, no /amp)."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("amp.")
    path = re.sub(r"/amp/?$", "", p.path or "/").rstrip("/") or "/"
    path = re.sub(r"/index\.(?:html?|php|aspx?)$", "", path) or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not _TRACK_PARAMS.match(k)))
    return urlunsplit(("https", host + (f":{p.port}" if p.port and p.port not in (80, 443) else ""), path, query, ""))


_STOP = set("""و در به از که این آن با برای را است هست بود شد می یک تا هم یا اما اگر هر چه چی کی کجا چرا چطور چگونه درباره بارها
the a an of to in on for and or is are was were be by with at as from that this it its about what who how why when where""".split())


def tokens(text: str) -> list[str]:
    t = str(text or "").lower().translate(_FA_DIGITS).replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    return [w for w in re.findall(r"[\w]+", t) if w not in _STOP and (len(w) > 1 or w.isdigit())]


def token_set(text: str) -> set[str]:
    return set(tokens(text))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def result_date(r: dict) -> date | None:
    return parse_date(r.get("date") or "") or parse_date(r.get("snippet") or "") or date_from_url(r.get("url", ""))


def age_days(d: date | None) -> int | None:
    return (date.today() - d).days if d else None


def freshness_label(days: int | None) -> str:
    if days is None:
        return "تاریخ نامشخص"
    if days <= 2:
        return "بسیار تازه"
    if days <= 30:
        return "تازه"
    if days <= 180:
        return "چند ماه پیش"
    if days <= 730:
        return "قدیمی (بیش از ۶ ماه)"
    return "خیلی قدیمی (بیش از ۲ سال)"


def is_stale(days: int | None, time_sensitive: bool) -> bool:
    if days is None:
        return False
    return days > (60 if time_sensitive else 1100)


# ------------------------------------------------------------------ the main entry points
def dedupe(results: list[dict]) -> list[dict]:
    """Removes repeated addresses and syndicated copies (same headline on several sites). The copy from the more credible site wins;
    ``also`` counts how many copies were folded in (they are NOT independent confirmations)."""
    by_url: dict[str, dict] = {}
    for r in results:
        key = canonical_url(r.get("url", ""))
        if not key:
            continue
        if key in by_url:
            old = by_url[key]
            if len(r.get("snippet", "")) > len(old.get("snippet", "")):
                old["snippet"] = r["snippet"]
            if len(r.get("text", "")) > len(old.get("text", "")):
                old["text"] = r["text"]
            continue
        r = dict(r)
        r["key"] = key
        r.setdefault("also", 0)
        by_url[key] = r
    kept: list[dict] = []
    for r in by_url.values():
        tset = token_set(r.get("title", ""))
        twin = next((k for k in kept if len(tset) >= 4 and jaccard(tset, token_set(k.get("title", ""))) >= 0.85 and registrable(host_name(k["url"])) != registrable(host_name(r["url"]))), None)
        if twin is not None:
            twin["also"] = twin.get("also", 0) + 1
            if source_kind(r["url"])[1] > source_kind(twin["url"])[1]:
                twin_also = twin["also"]
                twin.clear()
                twin.update(r)
                twin["also"] = twin_also
            continue
        kept.append(r)
    return kept


def score_results(results: list[dict], query: str, time_sensitive: bool | None = None, per_domain: int = 2) -> list[dict]:
    """Adds kind / credibility / date / age / relevance / score to every result and returns them best first.
    relevance = share of the query words found in title + snippet; credibility = kind of site; freshness only matters for time-sensitive queries.
    No more than ``per_domain`` results of one site stay on top (variety of sources)."""
    qtokens = token_set(query)
    ts = is_time_sensitive(query) if time_sensitive is None else time_sensitive
    scored = []
    for pos, r in enumerate(results):
        r = dict(r)
        kind, cred = source_kind(r.get("url", ""), qtokens)
        blob = token_set(" ".join([r.get("title", ""), r.get("snippet", ""), r.get("text", "")[:600]]))
        relevance = (len(qtokens & blob) / len(qtokens)) if qtokens else 0.5
        d = result_date(r)
        days = age_days(d)
        fresh = 0.5 if days is None else max(0.0, 1.0 - days / (90 if ts else 1500))
        prior = 1.0 / (1 + pos * 0.15)                           # the engine's own order still counts a little
        score = 0.45 * relevance + 0.25 * cred + 0.1 * prior + (0.2 * fresh if ts else 0.05 * fresh)
        if is_stale(days, ts):
            score -= 0.15
        if relevance < 0.2 and len(qtokens) >= 3:
            score -= 0.25                                        # barely related to the question
        r.update({"kind": kind, "credibility": round(cred, 2), "date": d.isoformat() if d else "", "age_days": days,
                  "freshness": freshness_label(days), "stale": is_stale(days, ts), "relevance": round(relevance, 2), "score": round(score, 3),
                  "domain": registrable(host_name(r.get("url", "")))})
        scored.append(r)
    scored.sort(key=lambda x: x["score"], reverse=True)
    out, counts = [], {}
    overflow = []
    for r in scored:
        n = counts.get(r["domain"], 0)
        if n >= per_domain:
            overflow.append(r)
            continue
        counts[r["domain"]] = n + 1
        out.append(r)
    return out + overflow
