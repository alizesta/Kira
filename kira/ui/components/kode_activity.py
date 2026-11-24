"""Inline progress for Kira's visible work stages.

`KodeActivityPanel` is a headless tracker (no widget of its own): it records the
real stages of the current request (thinking, tool start/finish, plan steps) and
announces changes through `changed`. The chat page renders those stages as a few
small lines at the end of the conversation (see `apply_progress_to_view`), so the
person sees what Kira is doing inside the chat, not above the input field.
"""
from __future__ import annotations

import html as _html

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor

PENDING, ACTIVE, DONE, FAILED, STOPPED = "pending", "active", "done", "failed", "stopped"

_MAX_ROWS = 8          # stages kept in memory
_SHOWN_ROWS = 3        # stages drawn in the chat (the latest ones)
PROGRESS_BLOCK_STATE = 7731

_GLYPHS = {
    ACTIVE: ("◌", "#52e5ff", "#e4e0fa", "normal"),
    DONE: ("✓", "#5ef2b0", "#8c90a8", "normal"),
    FAILED: ("✗", "#ff6b8a", "#ff9fb3", "normal"),
    STOPPED: ("!", "#ffc14d", "#ffd78a", "normal"),
    PENDING: ("○", "#8c90a8", "#8c90a8", "normal"),
}


class KodeActivityPanel(QObject):
    """Tracks the live stages of one request; owns no UI."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._active = False
        self._shown = False
        self.status_text = ""

    # ------------------------------------------------------------------ state
    @property
    def active(self) -> bool:
        return self._active

    def items(self) -> list[tuple[str, str]]:
        """(text, state) of every stage, oldest first."""
        return [(r["text"], r["state"]) for r in self._rows]

    def visible_rows(self) -> list[tuple[str, str]]:
        """What the chat should draw right now (empty once the request is over)."""
        if not (self._active and self._shown):
            return []
        return self.items()[-_SHOWN_ROWS:]

    def _add(self, text: str, state: str, key: str | None) -> dict:
        row = {"text": text, "state": state, "key": key}
        self._rows.append(row)
        del self._rows[:-_MAX_ROWS]
        return row

    def _settle(self, state: str = DONE) -> None:
        for row in self._rows:
            if row["state"] == ACTIVE:
                row["state"] = state

    def _emit(self) -> None:
        self.changed.emit()

    # ------------------------------------------------------------------ API
    def start(self, status: str) -> None:
        status = str(status or "").strip() or "در حال فکر کردن…"
        self._rows.clear()
        self._active = True
        self._shown = True
        self._add(status, ACTIVE, None)
        self.status_text = status
        self._emit()

    def ensure_running(self, status: str) -> None:
        if not self._active:
            self.start(status)

    def begin(self, text: str, key: str | None = None) -> None:
        """The previous stage is finished; this one is running now."""
        text = str(text or "").strip()
        if not text:
            return
        if not self._active:
            self.start(text)
            self._rows[-1]["key"] = key
            return
        last = self._rows[-1] if self._rows else None
        if last is not None and last["state"] == ACTIVE and last["text"] == text:
            return
        self._settle(DONE)
        self._add(text, ACTIVE, key)
        self.status_text = text
        self._emit()

    def finish(self, key: str, text: str | None = None, state: str = DONE) -> None:
        """Resolve the running stage identified by `key` (adds it if it was never shown)."""
        if not self._active:
            return
        target = next((r for r in reversed(self._rows) if r["key"] == key and r["state"] == ACTIVE), None)
        if target is None:
            if not text:
                return
            self._add(text, state, key)
        else:
            target["state"] = state
            if text:
                target["text"] = text
        if text:
            self.status_text = text
        self._emit()

    def add_done(self, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        if not self._active:
            self.start(text)
        self._add(text, DONE, None)
        self.status_text = text
        self._emit()

    def step(self, description: str) -> None:
        self.begin(description)

    def update(self, status: str) -> None:
        self.begin(status)

    def suspend(self) -> None:
        """The answer itself is appearing in the chat: take the progress lines away."""
        if self._shown:
            self._shown = False
            self._emit()

    def complete(self, status: str = "انجام شد") -> None:
        if not self._active:
            return
        self._settle(DONE)
        self.status_text = status
        self._active = False
        self._emit()

    def cancel(self, status: str = "درخواست متوقف شد") -> None:
        if not self._active:
            return
        self._settle(STOPPED)
        self.status_text = status
        self._active = False
        self._emit()

    def fail(self, status: str = "با خطا متوقف شد") -> None:
        if not self._active:
            self._add(status, FAILED, None)
        self._settle(FAILED)
        self.status_text = status
        self._active = False
        self._emit()

    def reset(self) -> None:
        self._rows.clear()
        self._active = False
        self._shown = False
        self.status_text = ""
        self._emit()


# ---------------------------------------------------------------------- chat rendering
def progress_html(rows: list[tuple[str, str]], rtl: bool = True) -> list[str]:
    """One small paragraph per stage (✓ finished, ◌ running)."""
    align = "right" if rtl else "left"
    out = []
    for text, state in rows:
        glyph, glyph_color, text_color, style = _GLYPHS.get(state, _GLYPHS[PENDING])
        out.append(
            f'<p align="{align}" style="margin:1px 14px 1px 14px; font-size:9pt; '
            f'font-style:{style}; color:{text_color};">'
            f'<span style="color:{glyph_color};">{glyph}</span> {_html.escape(text)}</p>'
        )
    return out


def clear_progress(view) -> None:
    """Remove the progress lines (wherever they are) from a chat view."""
    doc = view.document()
    last = doc.lastBlock()
    scanned = 0
    while last.isValid() and last.userState() != PROGRESS_BLOCK_STATE and scanned < 400:
        last = last.previous()
        scanned += 1
    if not last.isValid() or last.userState() != PROGRESS_BLOCK_STATE:
        return
    first = last
    while first.previous().isValid() and first.previous().userState() == PROGRESS_BLOCK_STATE:
        first = first.previous()
    cursor = QTextCursor(doc)
    cursor.setPosition(max(0, first.position() - 1))     # also takes the separator block we inserted
    cursor.setPosition(last.position() + max(last.length() - 1, 0), QTextCursor.KeepAnchor)
    cursor.removeSelectedText()
    cursor.block().setUserState(-1)                       # Qt keeps the removed block's marker on the merged one


def apply_progress_to_view(view, rows: list[tuple[str, str]], rtl: bool = True) -> None:
    """Replace the progress lines at the end of `view` with `rows` (no rows -> just remove them)."""
    bar = view.verticalScrollBar()
    at_bottom = bar.value() >= bar.maximum() - 48
    clear_progress(view)
    if rows:
        doc = view.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.End)
        cursor.insertBlock()
        first_pos = cursor.position()
        for index, fragment in enumerate(progress_html(rows, rtl)):
            if index:
                cursor.insertBlock()
            cursor.insertHtml(fragment)
        block = doc.findBlock(first_pos)
        while block.isValid():
            block.setUserState(PROGRESS_BLOCK_STATE)
            block = block.next()
    if at_bottom:
        bar.setValue(bar.maximum())
