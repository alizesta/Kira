"""Small provider-neutral stream filter for hidden reasoning and protocol blocks."""
from __future__ import annotations


class ThinkFilter:
    """Remove delimited blocks from a stream, including tags split across chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, text):
        self.buf += text or ""
        out = []
        while True:
            if self.inside:
                index = self.buf.find(self.CLOSE)
                if index < 0:
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf = self.buf[index + len(self.CLOSE):]
                self.inside = False
                continue
            index = self.buf.find(self.OPEN)
            if index >= 0:
                out.append(self.buf[:index])
                self.buf = self.buf[index + len(self.OPEN):]
                self.inside = True
                continue
            hold = 0
            for size in range(min(len(self.OPEN) - 1, len(self.buf)), 0, -1):
                if self.OPEN.startswith(self.buf[-size:]):
                    hold = size
                    break
            out.append(self.buf[:len(self.buf) - hold])
            self.buf = self.buf[len(self.buf) - hold:]
            break
        return "".join(out)

    def flush(self):
        remainder = "" if self.inside else self.buf
        self.buf, self.inside = "", False
        return remainder
