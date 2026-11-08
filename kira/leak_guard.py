"""Keeps the model's INTERNAL text away from the chat, the voice and the history.

Some models (DeepSeek / Qwen / Gemini thinking / gpt-oss ...) put their analysis in the normal answer text: inside <think>-like
tags, in Harmony channels (<|channel|>analysis<|message|>), or as an untagged English preamble ("Thinking Process: ...",
"The user is asking ... I should reply ...") before the real reply. Only the FINAL reply may reach the person.

LeakGuard is a streaming filter used by the router for every provider (so chat, voice and the tool loop all see clean text):
  1. block tags (think / thinking / thought / reasoning / analysis / scratchpad / router ...) and Harmony analysis channels are removed;
  2. an untagged reasoning preamble is swallowed until the real answer starts (a "Final answer:" line, an emotion tag line, a tool /
     plan block, or - when the reasoning was English - the first Persian line);
  3. if the model produced nothing but analysis, nothing is shown and the router treats the route's answer as empty, so the next
     route is asked for a proper reply.
Tool calling is untouched: <kira_tool> / <kira_plan> blocks always pass through (they end a swallowed preamble).
"""
from __future__ import annotations

import re

_BLOCK = r"think|thinking|thought|thoughts|reasoning|reflection|analysis|scratchpad|inner[_ -]?monologue|internal|internal[_ -]?notes?|router|notes?_to_self|reason"
_TAG_OPEN = re.compile(rf"<(?:{_BLOCK})(?:\s[^>]*)?>", re.I)
_TAG_CLOSE = re.compile(rf"</(?:{_BLOCK})\s*>", re.I)
_HARM_OPEN = re.compile(r"<\|channel\|>\s*(?:analysis|commentary)\s*<\|message\|>", re.I)
_HARM_CLOSE = re.compile(r"<\|(?:end|start|return|call)\|>", re.I)
_SPECIAL = re.compile(r"<\|[a-z_]{2,20}\|>(?:\s*(?:assistant|final)\s*<\|message\|>)?", re.I)

_TAG_LINE = re.compile(r"^\s*\[[A-Za-z_+&/:|=, 0-9%.-]{1,50}\]\s*$")             # the emotion tag line, e.g. [smug:70]
_LEAD_TAG = re.compile(r"^\s*\[[A-Za-z_+&/:|=, 0-9%.-]{1,50}\]\s*")
_CALL_BLOCK = re.compile(r"<kira_(?:tool|plan)>", re.I)

# U+FF1A below is the fullwidth colon (some models write "Thinking" followed by it); it is matched as well as the ASCII colon.
_LEAK_START = re.compile(r"""^\s*[*_#>\-\s]*(?:
    (?:thinking|thoughts?|reasoning|analysis|analy[sz]ing|internal|scratchpad|chain[ -]of[ -]thought|my\ (?:thoughts|reasoning|plan)|plan|draft|
       notes?|router|system(?:\ note|\ prompt)?|instructions?|self[ -]check|reflection)\b[^\n]{0,40}?(?:[:\uff1a]|\*\*|\n)
  | (?:okay|ok|alright|so|hmm+|wait|let\ me|let's|first|now|right)[,.…!]?\s+(?:so\s+)?
        (?:the\s+user|i\s+(?:need|should|must|have\ to|will|am\ going|'ll)|let(?:'s|\ me|\ us)|we\s+(?:need|should|must)|looking\ at|going)\b
  | the\s+user(?:'s)?\s+(?:is\s+(?:asking|saying|greeting|requesting|wants)|asked|wants|said|wrote|message|input|request|greeted|seems|has)\b
  | (?:i|we)\s+(?:need\ to|should|must|have\ to|will)\s+(?:respond|reply|answer|figure|determine|consider|analy[sz]e|check|think|keep|follow|make\ sure|craft|write)\b
  | user\s+(?:is\s+)?(?:asking|says|wants|said|asked)\b
  | (?:تحلیل|استدلال|فکر\s*کردن|یادداشت(?:\s*داخلی)?|فرایند\s*فکری|پیش[‌ ]?نویس|مسیریاب|روتر)\s*[:\uff1a]
  | کاربر\s+(?:می[‌ ]?خواهد|می[‌ ]?خواد|پرسیده|پرسید|گفته|گفت|درخواست|سلام\s+کرده|از\s+من)\b
  | (?:باید|لازم\s+است)\s+(?:پاسخ|جواب)\s+(?:بدهم|بدم)\b
)""", re.I | re.X)

_FINAL_MARK = re.compile(r"^\s*[*_#>\s-]*(?:final(?:\s+(?:answer|response|reply|output))?|answer|response|reply|output|kira|"
                         r"پاسخ(?:\s+نهایی)?|جواب(?:\s+نهایی)?|خروجی(?:\s+نهایی)?)\s*[*_]*\s*[:\uff1a]\s*[*_]*\s*(.*)$", re.I | re.S)

# lines that are app / model internals and never belong in a reply
_NOTE_LINE = re.compile(r"(?im)^[ \t]*(?:\[(?:system(?:\s+note)?|router|route|internal|kira\s+internal|debug|tool\s+note|note\s+to\s+self)[^\]\n]*\]"
                        r"|\((?:internal|router|note\s+to\s+self|system\s+note)[^)\n]*\))[^\n]*\n?")
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")


def _persian_dominant(text: str) -> bool:
    a, l = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
    return a >= 8 and a / max(1, a + l) >= 0.7


def _latin_dominant(text: str) -> bool:
    a, l = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
    return l >= 12 and l > a


class _TagStripper:
    """Removes <open> ... </close> regions from a stream, also when a tag is split between two chunks."""

    def __init__(self, open_rx, close_rx, hold=40):
        self.open_rx, self.close_rx, self.hold = open_rx, close_rx, hold
        self.buf, self.inside = "", False

    def feed(self, text: str) -> str:
        self.buf += text or ""
        out = []
        while True:
            if self.inside:
                m = self.close_rx.search(self.buf)
                if not m:
                    self.buf = self.buf[-self.hold:]
                    break
                self.buf = self.buf[m.end():]
                self.inside = False
                continue
            m = self.open_rx.search(self.buf)
            if m:
                out.append(self.buf[:m.start()])
                self.buf = self.buf[m.end():]
                self.inside = True
                continue
            cut = self.buf.rfind("<")
            if cut >= 0 and len(self.buf) - cut <= self.hold and ">" not in self.buf[cut:]:
                out.append(self.buf[:cut])
                self.buf = self.buf[cut:]
            else:
                out.append(self.buf)
                self.buf = ""
            break
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self.inside else self.buf
        self.buf, self.inside = "", False
        return rest


class LeakGuard:
    def __init__(self):
        self._harm = _TagStripper(_HARM_OPEN, _HARM_CLOSE)
        self._tags = _TagStripper(_TAG_OPEN, _TAG_CLOSE)
        self.mode = "undecided"            # undecided | pass | swallow
        self.buf = ""
        self.swallowed = ""
        self.latin_lead = False
        self.leaked = False                # internal text was held back at some point

    # ---- public ----
    def feed(self, piece: str) -> str:
        text = self._tags.feed(self._harm.feed(piece or ""))
        return self._stage(text, final=False)

    def finish(self) -> str:
        tail = self._tags.feed(self._harm.flush()) + self._tags.flush()
        return self._stage(tail, final=True)

    # ---- preamble stage ----
    def _stage(self, text: str, final: bool) -> str:
        text = _SPECIAL.sub("", text)
        if self.mode == "pass":
            return text
        self.buf += text
        if self.mode == "undecided":
            head = _LEAD_TAG.sub("", self.buf, count=1) if self.buf.lstrip().startswith("[") else self.buf
            if not final and len(head.strip()) < 48 and "\n" not in head.strip():
                return ""                                          # too little text to judge yet (a few characters at most)
            if _LEAK_START.match(head):
                self.mode, self.leaked = "swallow", True
                self.latin_lead = _latin_dominant(head)
            else:
                self.mode, out, self.buf = "pass", self.buf, ""
                return out
        return self._drain(final)

    def _resume(self, line: str):
        m = _FINAL_MARK.match(line)
        if m:
            return m.group(1)
        if _TAG_LINE.match(line):
            return line
        if self.latin_lead and _persian_dominant(line):
            return line
        return None

    def _drain(self, final: bool) -> str:
        m = _CALL_BLOCK.search(self.buf)
        if m:                                                      # a tool / plan block ends the preamble
            out, self.buf, self.mode = self.buf[m.start():], "", "pass"
            return out
        while True:
            nl = self.buf.find("\n")
            if nl < 0:
                break
            line, self.buf = self.buf[:nl + 1], self.buf[nl + 1:]
            res = self._resume(line)
            if res is not None:
                out, self.buf, self.mode = res + self.buf, "", "pass"
                return out
            self.swallowed += line
        if final:
            if self.buf.strip():
                res = self._resume(self.buf)
                if res is not None:
                    self.buf, self.mode = "", "pass"
                    return res
                self.swallowed += self.buf
            self.buf = ""
            return self._fallback()
        return ""

    def _fallback(self) -> str:
        """Analysis with no marker: keep only a final short paragraph that is clearly not analysis; otherwise nothing."""
        paras = [p.strip() for p in re.split(r"\n\s*\n", self.swallowed) if p.strip()]
        if len(paras) >= 2:
            last = paras[-1]
            if len(last) <= 700 and not _LEAK_START.match(last) and not _CALL_BLOCK.search(last):
                self.mode = "pass"
                return last
        return ""


# ---------------------------------------------------------------- non-streaming helpers
def strip_blocks(text: str) -> str:
    """Remove internal blocks from finished text (also an unclosed one at the end)."""
    text = re.sub(r"<\|channel\|>\s*(?:analysis|commentary)\s*<\|message\|>.*?(?:<\|(?:end|start|return|call)\|>|$)", "", text or "", flags=re.S | re.I)
    text = re.sub(rf"<({_BLOCK})(?:\s[^>]*)?>.*?(?:</\1\s*>|$)", "", text, flags=re.S | re.I)
    return _SPECIAL.sub("", text)


def scrub_lines(text: str) -> str:
    """Drop router / system note lines that a model echoed into its reply."""
    return _NOTE_LINE.sub("", text or "")


def clean_final(text: str) -> str:
    """Finished model text -> only the final reply (blocks, analysis preamble and echoed notes removed)."""
    g = LeakGuard()
    out = g.feed(text or "") + g.finish()
    return scrub_lines(out).strip() if out.strip() else ""
