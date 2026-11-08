"""Turn a downloaded page into readable text + metadata (title, publisher, date, author, language, links). Standard library only.

The page text is DATA. ``scrub_injection`` removes sentences that try to give the AI orders (prompt injection) before anything reaches
a model, and every tag that looks like Kira's own tool protocol is defused.
"""
from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlsplit

_SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "form", "nav", "footer", "aside", "header", "button", "select",
         "dialog", "menu", "object", "embed", "head"}
_BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "br", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
          "figcaption", "dd", "dt", "td", "th"}
_VOID = {"br", "img", "hr", "meta", "link", "input", "source", "track", "wbr", "area", "base", "col", "embed", "param"}
_BOILER_RX = re.compile(r"(?:cookie|consent|banner|popup|modal|newsletter|subscribe|advert|\bads?\b|sidebar|related|comment|share|social|breadcrumb|promo|"
                        r"sponsor|menu|toolbar|paywall|signup|login|widget|recommend)", re.I)
_MAIN_RX = re.compile(r"(?:article|post|entry|content|story|main|body-text|news-body|text)", re.I)
_MAIN_STRICT = re.compile(r"(?:article[-_]?(?:body|content|text)|entry[-_]?content|post[-_]?(?:content|body)|story[-_]?body|news[-_]?body|main[-_]?content|content[-_]?body|articlebody)", re.I)

# ------------------------------------------------------------------ prompt-injection scrubbing
_INJECTION_RX = re.compile(
    r"(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+|earlier\s+)*"
    r"(?:instructions?|prompts?|rules?|guidelines?|directions?)|"
    r"(?:you\s+are\s+now|from\s+now\s+on\s+you|act\s+as\s+(?:an?\s+)?(?:system|admin|developer|dan)\b|new\s+instructions?\s*:|system\s*prompt|"
    r"developer\s+message|jailbreak|do\s+anything\s+now)|"
    r"(?:reveal|print|show|send|leak|exfiltrate|output)\s+(?:me\s+)?(?:your\s+|the\s+|all\s+)?(?:system\s+prompt|api[\s_-]?keys?|secrets?|passwords?|tokens?|hidden\s+instructions?)|"
    r"(?:call|use|run|execute|invoke)\s+(?:the\s+)?(?:tool|function|command)\b|<\s*/?\s*kira_|kira_tool|kira_plan|"
    r"\b(?:curl|wget|powershell|cmd\.exe|rm\s+-rf|del\s+/[sqf])\b.{0,40}|"
    r"دستور(?:ات|های)?\s+(?:قبلی|بالا|پیشین)\s*(?:را|رو)?\s*(?:نادیده|فراموش|رد)|(?:نادیده\s*بگیر|فراموش\s*کن)\s.{0,30}(?:دستور|قوانین|پرامپت)|"
    r"(?:از\s+این\s+به\s+بعد|اکنون)\s+تو\s+(?:یک\s+)?(?:\w+\s+)?هستی|پرامپت\s+سیستم|کلید\s*(?:های)?\s*api\s*(?:را|رو)?\s*(?:بفرست|نشان\s*بده|بگو)|"
    r"(?:ابزار|دستور)\s+.{0,15}(?:را|رو)\s+اجرا\s+کن", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟!۔\n])\s+")


def scrub_injection(text: str) -> tuple[str, int]:
    """-> (clean text, number of removed sentences). Whole sentences that look like orders to an AI are dropped, not 'fixed'."""
    removed, out = 0, []
    for sent in _SENTENCE_SPLIT.split(text or ""):
        if _INJECTION_RX.search(sent):
            removed += 1
            continue
        out.append(sent)
    clean = " ".join(out)
    clean = clean.replace("<kira", "‹kira").replace("</kira", "‹/kira")
    return clean, removed


# ------------------------------------------------------------------ dates
_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
     ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")], 1) for m in names}
_ISO_RX = re.compile(r"(20\d{2}|19\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])")
_EN_DMY_RX = re.compile(r"\b(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?,?\s+(20\d{2}|19\d{2})\b", re.I)
_EN_MDY_RX = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+(20\d{2}|19\d{2})\b", re.I)
_URL_DATE_RX = re.compile(r"/(20\d{2})[/-](0?[1-9]|1[0-2])(?:[/-](0?[1-9]|[12]\d|3[01]))?(?:/|-|$)")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_JALALI_RX = re.compile(r"(13\d{2}|14\d{2})[/-](0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])")
_JALALI_MONTHS = {"فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4, "مرداد": 5, "شهریور": 6, "مهر": 7, "آبان": 8, "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12}
_JALALI_TEXT_RX = re.compile(r"(0?[1-9]|[12]\d|3[01])\s+(فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)\s+(13\d{2}|14\d{2})")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date | None:
    try:                                                       # standard arithmetic conversion (no library needed)
        jy -= 979
        jm -= 1
        jd -= 1
        j_days = 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4
        j_days += sum([31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29][:jm]) + jd
        g_days = j_days + 79
        gy = 1600 + 400 * (g_days // 146097)
        g_days %= 146097
        leap = True
        if g_days >= 36525:
            g_days -= 1
            gy += 100 * (g_days // 36524)
            g_days %= 36524
            if g_days >= 365:
                g_days += 1
            else:
                leap = False
        gy += 4 * (g_days // 1461)
        g_days %= 1461
        if g_days >= 366:
            leap = False
            g_days -= 1
            gy += g_days // 365
            g_days %= 365
        months = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        gm = 0
        while gm < 12 and g_days >= months[gm]:
            g_days -= months[gm]
            gm += 1
        return date(gy, gm + 1, g_days + 1)
    except (ValueError, IndexError):
        return None


def parse_date(text: str) -> date | None:
    """First plausible publication date inside a string (ISO, English month names, Persian/Jalali). Future dates are rejected."""
    t = str(text or "").translate(_FA_DIGITS)
    found = None
    m = _ISO_RX.search(t)
    if m:
        found = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if not found:
        m = _EN_DMY_RX.search(t)
        if m:
            found = _mk(int(m.group(3)), _MONTHS.get(m.group(2).lower()[:3], 1), int(m.group(1)))
    if not found:
        m = _EN_MDY_RX.search(t)
        if m:
            found = _mk(int(m.group(3)), _MONTHS.get(m.group(1).lower()[:3], 1), int(m.group(2)))
    if not found:
        m = _JALALI_TEXT_RX.search(t)
        if m:
            found = jalali_to_gregorian(int(m.group(3)), _JALALI_MONTHS[m.group(2)], int(m.group(1)))
    if not found:
        m = _JALALI_RX.search(t)
        if m:
            found = jalali_to_gregorian(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if found and found > date.today():
        return None
    return found


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def date_from_url(url: str) -> date | None:
    m = _URL_DATE_RX.search(urlsplit(url or "").path + "/")
    if not m:
        return None
    d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    return d if d and d <= date.today() else None


# ------------------------------------------------------------------ HTML parsing
class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.h1 = ""
        self.lang = ""
        self.canonical = ""
        self.jsonld: list[str] = []
        self.time_attrs: list[str] = []
        self.links: list[tuple[str, str, bool]] = []            # (href, anchor text, inside main area)
        self._stack: list[tuple[str, bool, bool]] = []          # (tag, skipped, is_main)
        self._skip = 0
        self._main_depth = 0
        self._in_title = False
        self._in_h1 = False
        self._in_jsonld = False
        self._a_href = None
        self._a_text: list[str] = []
        self._a_main = False
        self.main_parts: list[str] = []
        self.all_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")[:12]
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
            return
        if tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "")
            return
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_jsonld = True
            self.jsonld.append("")
        if tag == "title":
            self._in_title = True
        if tag == "time" and a.get("datetime"):
            self.time_attrs.append(a["datetime"])
        if tag in _VOID:
            if tag == "br":
                self._add("\n")
            return
        ident = f"{a.get('class', '')} {a.get('id', '')} {a.get('role', '')} {a.get('itemprop', '')}"
        hidden = a.get("hidden") is not None or a.get("aria-hidden") == "true" or "display:none" in a.get("style", "").replace(" ", "").lower()
        boiler = (bool(_BOILER_RX.search(ident)) and tag not in ("article", "main", "body", "html") and not _MAIN_RX.search(a.get("itemprop", ""))
                  and not _MAIN_STRICT.search(ident))
        skipped = tag in _SKIP or hidden or boiler
        is_main = tag in ("article", "main") or "articlebody" in a.get("itemprop", "").lower() or a.get("role", "") == "main"
        self._stack.append((tag, skipped, is_main))
        if skipped:
            self._skip += 1
        if is_main and not self._skip:
            self._main_depth += 1
        if tag == "h1" and not self._skip:
            self._in_h1 = True
        if tag == "a" and a.get("href") and not self._skip:
            self._a_href, self._a_text, self._a_main = a["href"], [], self._main_depth > 0
        if tag in _BLOCK:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._in_jsonld = False
        if tag == "a" and self._a_href is not None:
            self.links.append((self._a_href, " ".join("".join(self._a_text).split())[:140], self._a_main))
            self._a_href = None
        if tag == "h1":
            self._in_h1 = False
        if tag in _VOID:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for t, skipped, is_main in self._stack[i:][::-1]:
                    if skipped:
                        self._skip = max(0, self._skip - 1)
                    if is_main and not skipped:
                        self._main_depth = max(0, self._main_depth - 1)
                del self._stack[i:]
                break
        if tag in _BLOCK:
            self._add("\n")

    def handle_data(self, data):
        if self._in_jsonld and self.jsonld:
            self.jsonld[-1] += data
            return
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if self._in_h1:
            self.h1 += data
        if self._a_href is not None:
            self._a_text.append(data)
        self._add(data)

    def _add(self, text: str):
        self.all_parts.append(text)
        if self._main_depth:
            self.main_parts.append(text)


def _lines(parts: list[str]) -> list[str]:
    text = "".join(parts)
    out = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if line:
            out.append(line)
    return out


def _keep_lines(lines: list[str], min_len: int = 40) -> str:
    """Drop menu / label lines: a content line is either long enough or ends like a sentence. Exact duplicates are removed."""
    seen, out = set(), []
    for ln in lines:
        key = ln.lower()
        if key in seen:
            continue
        if len(ln) >= min_len or (len(ln) >= 20 and re.search(r"[.!?؟:۔]$", ln)):
            seen.add(key)
            out.append(ln)
    return "\n".join(out)


def _jsonld_meta(blobs: list[str]) -> dict:
    found: dict = {}
    for raw in blobs:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            stack.extend(v for v in obj.values() if isinstance(v, (dict, list)))
            if obj.get("datePublished") and "date" not in found:
                found["date"] = str(obj["datePublished"])
            if obj.get("dateModified") and "modified" not in found:
                found["modified"] = str(obj["dateModified"])
            if obj.get("headline") and "title" not in found:
                found["title"] = str(obj["headline"])
            author = obj.get("author")
            if author and "author" not in found:
                a0 = author[0] if isinstance(author, list) and author else author
                found["author"] = str(a0.get("name") if isinstance(a0, dict) else a0)[:80]
            pub = obj.get("publisher")
            if pub and "publisher" not in found:
                found["publisher"] = str(pub.get("name") if isinstance(pub, dict) else pub)[:80]
    return found


def _decode(body: bytes, header_encoding: str | None) -> str:
    head = body[:4096].decode("ascii", "ignore")
    m = re.search(r"charset\s*=\s*[\"']?([\w-]+)", head, re.I)
    for enc in (m.group(1) if m else None, header_encoding if header_encoding and header_encoding.lower() != "iso-8859-1" else None, "utf-8", "cp1256", "latin-1"):
        if not enc:
            continue
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def host_name(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def extract_html(html: str, url: str) -> dict:
    """-> {'title','publisher','date','modified','author','lang','canonical','text','links':[{'url','text','main'}], 'injection_removed'}"""
    page = _Page()
    try:
        page.feed(html)
        page.close()
    except Exception:                                           # noqa: BLE001 - broken HTML must never crash a research run
        pass
    ld = _jsonld_meta(page.jsonld)
    meta = page.meta
    main_text = _keep_lines(_lines(page.main_parts))
    text = main_text if len(main_text) >= 400 else _keep_lines(_lines(page.all_parts))
    if len(text) < 200:                                         # badly broken HTML (unclosed tags hid everything): crude tag stripping
        crude = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer)\b.*?</\1>", " ", html)
        crude = re.sub(r"(?s)<[^>]+>", "\n", crude)
        crude_text = _keep_lines(_lines([crude]))
        if len(crude_text) > len(text):
            text = crude_text
    text, removed = scrub_injection(unescape(text))
    title = (meta.get("og:title") or meta.get("twitter:title") or ld.get("title") or page.h1 or page.title or "").strip()
    title = " ".join(unescape(title).split())[:200]
    raw_date = (meta.get("article:published_time") or meta.get("og:article:published_time") or meta.get("datepublished") or meta.get("date")
                or meta.get("pubdate") or meta.get("publishdate") or meta.get("dc.date") or meta.get("dc.date.issued") or ld.get("date")
                or (page.time_attrs[0] if page.time_attrs else ""))
    published = parse_date(raw_date) or date_from_url(url)
    modified = parse_date(meta.get("article:modified_time") or meta.get("og:updated_time") or ld.get("modified") or "")
    links, seen = [], set()
    for href, label, in_main in page.links:
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        absolute = urljoin(url, href).split("#")[0]
        if not absolute.startswith(("http://", "https://")) or absolute in seen or len(label) < 3:
            continue
        seen.add(absolute)
        links.append({"url": absolute, "text": label, "main": in_main})
        if len(links) >= 80:
            break
    return {"title": title, "publisher": (meta.get("og:site_name") or meta.get("application-name") or ld.get("publisher") or "").strip()[:80],
            "date": published.isoformat() if published else "", "modified": modified.isoformat() if modified else "",
            "author": (meta.get("author") or meta.get("article:author") or ld.get("author") or "").strip()[:80], "lang": page.lang or meta.get("og:locale", "")[:5],
            "canonical": page.canonical, "text": text, "links": links, "injection_removed": removed}


def extract_pdf(body: bytes, max_pages: int = 12) -> dict:
    """Online PDF -> text (needs the optional pypdf package that Kira already uses for attachments)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"error": "برای خواندن PDF بسته‌ی pypdf لازم است (pip install pypdf)."}
    try:
        reader = PdfReader(BytesIO(body))
        if getattr(reader, "is_encrypted", False):
            return {"error": "این PDF رمزگذاری شده است."}
        parts = []
        for i, pg in enumerate(reader.pages):
            if i >= max_pages:
                break
            parts.append(pg.extract_text() or "")
        meta = reader.metadata or {}
        title = str(getattr(meta, "title", "") or "").strip()
        raw_created = str(meta.get("/CreationDate", "") if hasattr(meta, "get") else "")
        mc = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw_created)
        created = _mk(int(mc.group(1)), int(mc.group(2)), int(mc.group(3))) if mc else None
    except Exception as exc:                                    # noqa: BLE001
        return {"error": f"PDF قابل خواندن نبود ({type(exc).__name__})."}
    text = "\n".join(" ".join(p.split()) for p in "\n".join(parts).split("\n") if p.strip())
    if not text.strip():
        return {"error": "متنی در PDF پیدا نشد (شاید اسکن‌شده است و OCR لازم دارد)."}
    text, removed = scrub_injection(text)
    return {"title": title[:200], "publisher": "", "date": created.isoformat() if created else "", "modified": "", "author": "", "lang": "",
            "canonical": "", "text": text, "links": [], "injection_removed": removed, "pdf_pages": min(len(reader.pages), max_pages)}


def extract(fetched, url: str) -> dict:
    """Fetched (netguard) -> the dict of extract_html / extract_pdf, with 'error' when nothing usable was found."""
    ctype = fetched.ctype or ""
    if ctype.startswith("application/pdf") or fetched.body[:5] == b"%PDF-":
        return extract_pdf(fetched.body)
    raw = _decode(fetched.body, fetched.encoding)
    if ctype.startswith(("text/plain", "text/markdown", "application/json")):
        text, removed = scrub_injection(" ".join(raw.split()) if ctype.startswith("application/json") else raw)
        return {"title": "", "publisher": "", "date": date_from_url(url).isoformat() if date_from_url(url) else "", "modified": "", "author": "",
                "lang": "", "canonical": "", "text": text, "links": [], "injection_removed": removed}
    out = extract_html(raw, url)
    if len(out["text"]) < 120:
        out["error"] = "متن قابل‌خواندنی در صفحه پیدا نشد (شاید با جاوااسکریپت ساخته می‌شود یا پشت ورود/پرداخت است)."
    return out
