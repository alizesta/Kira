"""Splits a reply into short sentences for speech, also while the reply is still being written.

  * a sentence ends at . ! ? ؟ ؛ ; … 。！？ (also several in a row, closing quotes / brackets) when whitespace follows, or at a line break;
  * NOT inside decimals (3.5), URLs, abbreviations (Dr. e.g. vs.) - those have no whitespace after the dot or are listed;
  * a piece that is too short (< MIN_CHARS) is joined to the next one, so "OK." never becomes its own request;
  * a very long run without any ending is cut at a comma / space (MAX_CHARS); the FIRST piece may be cut early at a comma
    (SOFT_FIRST) so speech starts sooner;
  * a terminator at the very end of the text so far waits for the next character (the dot of "3.5" may still be coming) until flush().
"""
from __future__ import annotations

import re

TERMS = "。！？.!?؟؛;…"
CLOSERS = "\"'»”’)]}"
SOFT = "،,;:"
MIN_CHARS = 14
MIN_FIRST = 6
MAX_CHARS = 200
SOFT_FIRST = 90
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "st", "no", "fig", "inc", "ltd", "co", "approx", "e.g", "i.e", "u.s", "a.m", "p.m"}
_THINK = re.compile(r"<think>.*?</think>", re.S)


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks (and an unclosed <think> at the end) before splitting."""
    from .leak_guard import strip_blocks, scrub_lines
    text = _THINK.sub("", text or "")
    return scrub_lines(strip_blocks(text.split("<think>", 1)[0]))


class StreamSplitter:
    def __init__(self):
        self.buf = ""
        self.carry = ""            # a too-short piece waiting for the next one
        self.first = True          # nothing emitted yet: the first piece may be short and may be cut early

    def push(self, delta: str) -> list[str]:
        self.buf += delta or ""
        return self._drain(final=False)

    def flush(self) -> list[str]:
        out = self._drain(final=True)
        rest = (self.carry + " " + self.buf).strip()
        self.buf = self.carry = ""
        if rest:
            out.append(rest)
            self.first = False
        return out

    # ---- internals ----
    @staticmethod
    def _is_abbrev(text: str, dot: int) -> bool:
        m = re.search(r"([A-Za-z](?:\.[A-Za-z])*)$", text[:dot])
        return bool(m) and m.group(1).lower() in ABBREVIATIONS

    def _boundary(self, text: str, final: bool) -> int:
        n, i = len(text), 0
        while i < n:
            ch = text[i]
            if ch == "\n":
                return i + 1
            if ch in TERMS:
                j = i + 1
                while j < n and (text[j] in TERMS or text[j] in CLOSERS):
                    j += 1
                if j >= n:
                    return j if final else -1                 # may continue ("3." + "5"): wait
                if text[j].isspace():
                    if ch == "." and j == i + 1 and self._is_abbrev(text, i):
                        i = j
                        continue
                    return j
                i = j                                         # "3.5", "a.b", "word.next": not an ending
                continue
            i += 1
        return -1

    def _soft_cut(self, text: str) -> int | None:
        total = len(self.carry) + len(text)
        if self.first and total >= SOFT_FIRST:
            k = max((text.rfind(c, 0, 140) for c in "،,"), default=-1)
            if k >= 25:
                return k + 1
        if total > MAX_CHARS:
            window = text[:max(MIN_CHARS, MAX_CHARS - len(self.carry))]
            k = max((window.rfind(c) for c in SOFT), default=-1)
            if k < MIN_CHARS // 2:
                k = window.rfind(" ")
            return (k + 1) if k > 0 else len(window)
        return None

    def _drain(self, final: bool) -> list[str]:
        out = []
        while self.buf:
            pos = self._boundary(self.buf, final)
            if pos < 0:
                pos = self._soft_cut(self.buf)
                if pos is None:
                    break
            piece, self.buf = self.buf[:pos].strip(), self.buf[pos:].lstrip(" \t")
            if not piece:
                continue
            piece = (self.carry + " " + piece).strip()
            self.carry = ""
            if len(piece) < (MIN_FIRST if self.first else MIN_CHARS) and not final:
                self.carry = piece                            # too short: join with the next piece
                continue
            out.append(piece)
            self.first = False
        return out


def split_sentences(text: str) -> list[str]:
    sp = StreamSplitter()
    return sp.push(strip_think(text)) + sp.flush()
