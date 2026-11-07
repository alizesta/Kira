"""Chat message rendering with correct Persian (right-to-left) layout.

Every message becomes its own bubble; every *line* of a message gets its own direction decided from its
letters, so Persian text is right-aligned and ordered right-to-left, English stays left-to-right, and mixed
lines (a Persian sentence containing English words) follow whichever script dominates.
"""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import unquote, urlparse

RTL, LTR = "rtl", "ltr"

# kind -> (bubble colour, name colour, text colour, physical side of the bubble)
STYLES = {
    "user":      ("#35306a", "#cfc4ff", "#f1f2f8", "right"),
    "assistant": ("#252839", "#b9a7ff", "#eceef6", "left"),
    "system":    ("#1e2030", "#8d93ab", "#a2a8c0", "left"),
    "error":     ("#47232f", "#ff9aa8", "#ffe3e7", "left"),
}


def detect_direction(text: str, default: str = RTL) -> str:
    """'rtl' when right-to-left letters (Persian/Arabic/Hebrew) are at least as many as left-to-right ones."""
    rtl = ltr = 0
    for ch in str(text or ""):
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            rtl += 1
        elif kind == "L":
            ltr += 1
    if rtl == 0 and ltr == 0:
        return default
    return RTL if rtl >= ltr else LTR


def _lines(text: str):
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or [""]


_URL = re.compile(r"https?://[^\s<>\"')\]،؛]+")
LINK_COLOUR = "#8fb8ff"


def short_url(url: str, limit: int = 56) -> str:
    """Readable label for a link: host + decoded path, shortened ("youtube.com/watch?v=abc…")."""
    parts = urlparse(url)
    label = (parts.netloc.removeprefix("www.") + unquote(parts.path or "") + (("?" + parts.query) if parts.query else "")).rstrip("/")
    return label if len(label) <= limit else label[:limit - 1] + "…"


def _linkify(escaped: str) -> str:
    """Turn bare URLs of an already HTML-escaped line into short clickable links."""
    def repl(m):
        url = m.group(0)
        trail = ""
        while url and url[-1] in ".,;:!?":
            trail, url = url[-1] + trail, url[:-1]
        return f'<a href="{url}" style="color:{LINK_COLOUR};">{html.escape(short_url(html.unescape(url)), quote=False)}</a>{trail}'
    return _URL.sub(repl, escaped)


def sources_html(results, title: str = "منابع") -> str:
    """Compact list of sources: the page title is the link, the site name follows it."""
    rows = []
    for i, r in enumerate(results or [], 1):
        url = str(r.get("url") or "")
        if not url.startswith("http"):
            continue
        name = html.escape(str(r.get("title") or short_url(url)), quote=False)
        site = html.escape(urlparse(url).netloc.removeprefix("www."), quote=False)
        rows.append(f'<p dir="ltr" align="left" style="margin:2px 0;color:#a2a8c0;">{i}. '
                    f'<a href="{html.escape(url)}" style="color:{LINK_COLOUR};">{name}</a> <span style="color:#6f7590;">· {site}</span></p>')
    if not rows:
        return ""
    return f'<p dir="rtl" align="right" style="margin:1px 0 3px 0;color:#8d93ab;font-weight:600;">🌐 {html.escape(title)}</p>' + "".join(rows)


def _paragraph(line: str, colour: str, ui_dir: str, size: str = "", italic: bool = False, force_dir: str = "") -> str:
    d = force_dir or detect_direction(line, ui_dir)
    align = "right" if d == RTL else "left"
    style = f"color:{colour};margin:1px 0;{size}" + ("font-style:italic;" if italic else "")
    return f'<p dir="{d}" align="{align}" style="{style}">{_linkify(html.escape(line, quote=False)) or "&nbsp;"}</p>'


def message_html(kind: str, name: str, text: str, ui_dir: str = RTL, extra_html: str = "") -> str:
    bubble, name_colour, text_colour, side = STYLES.get(kind, STYLES["assistant"])
    lines = _lines(text)
    body = "" if (extra_html and not str(text or "").strip()) else "".join(
        _paragraph(line, text_colour, ui_dir, italic=(kind == "system")) for line in lines)
    head = ""
    if name:
        # the sender name sits on the same side as the first line of the message, whatever script the name is in
        head = _paragraph(name, name_colour, ui_dir, size="font-size:9pt;font-weight:600;",
                          force_dir=detect_direction(lines[0], ui_dir))
    table_side = "right" if side == "right" else "left"
    return (f'<table align="{table_side}" width="86%" cellspacing="0" cellpadding="10" style="margin:7px 4px;">'
            f'<tr><td bgcolor="{bubble}">{head}{extra_html}{body}</td></tr></table><p style="margin:0;font-size:3pt;">&nbsp;</p>')
