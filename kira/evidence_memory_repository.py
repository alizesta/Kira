"""Transactional repository operations for evidence facts and their provenance."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable


class EvidenceFactRepository:
    """Own fact/evidence/quarantine writes; storage connections remain application-owned."""

    def __init__(
        self,
        *,
        fact_id: Callable,
        normalize: Callable,
        quote_in: Callable,
        word_regex: Any,
        stop_words: Iterable[str],
        categories: Iterable[str],
        single_valued: Iterable[str],
        cache: dict,
    ) -> None:
        self._fact_id = fact_id
        self._normalize = normalize
        self._quote_in = quote_in
        self._word_regex = word_regex
        self._stop_words = frozenset(stop_words)
        self._categories = frozenset(categories)
        self._single_valued = frozenset(single_valued)
        self._cache = cache

def quarantine(self, con, reason, payload) -> None:
    con.execute("INSERT INTO quarantine(created_at, reason, payload) VALUES (?, ?, ?)",
                (time.time(), str(reason)[:300], json.dumps(payload, ensure_ascii=False, default=str)[:800]))


def same_thing(self, a, b) -> bool:
    na, nb = self._normalize(a), self._normalize(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    wa, wb = set(self._word_regex.findall(na)) - self._stop_words, set(self._word_regex.findall(nb)) - self._stop_words
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def ingest(self, con, *, subject, predicate, value, text, category, quote, speaker, message_id, source_kind, now,
            uncertain=False, explicit=False, persona_id=None, valid_to=None, source_text=None, legacy=0) -> str | None:
    """Store one fact with its evidence. Returns the fact id, or None when it was rejected (and quarantined)."""
    value, text, quote = " ".join(str(value or "").split()), " ".join(str(text or "").split()), " ".join(str(quote or "").split())
    if not value or not text or not quote:
        self.quarantine(con, "empty value / text / quote", {"predicate": predicate, "text": text})
        return None
    if category not in self._categories:
        category = "unverified"
    if source_text is not None and not self._quote_in(quote, source_text):
        self.quarantine(con, "quote is not a literal substring of its source message", {"predicate": predicate, "quote": quote})
        return None
    if speaker == "assistant" and subject == "user" and category != "unverified":
        category = "unverified"                                             # her own words are evidence that she said it, never proof about him
    status = "uncertain" if (uncertain and not explicit) else "active"
    fid = self._fact_id(subject, predicate, value)
    existing = con.execute("SELECT * FROM facts WHERE subject=? AND predicate=? AND status IN ('active','uncertain')", (subject, predicate)).fetchall()
    row = con.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
    if row is not None and row["status"] in ("active", "uncertain"):      # the same fact again: one more piece of evidence
        con.execute("INSERT OR IGNORE INTO evidence(fact_id, message_id, speaker, quote, created_at) VALUES (?, ?, ?, ?, ?)",
                    (fid, message_id, speaker, quote, now))
        new_status = "active" if (row["status"] == "uncertain" and status == "active") else row["status"]
        con.execute("UPDATE facts SET updated_at=?, status=?, persona_id=COALESCE(persona_id, ?) WHERE id=?", (now, new_status, persona_id, fid))
        self._cache.pop(fid, None)
        return fid
    superseded: list[str] = []
    if status == "active":
        if predicate in self._single_valued:
            superseded = [r["id"] for r in existing if r["id"] != fid]
        elif predicate in ("like", "dislike"):
            opposite = "dislike" if predicate == "like" else "like"
            rows = con.execute("SELECT * FROM facts WHERE subject=? AND predicate=? AND status IN ('active','uncertain')", (subject, opposite)).fetchall()
            superseded = [r["id"] for r in rows if self.same_thing(r["value"], value)]
    for old in superseded:
        con.execute("UPDATE facts SET status='superseded', updated_at=? WHERE id=?", (now, old))
    if row is not None:                                                    # an old value that was superseded and is now stated again
        con.execute("UPDATE facts SET status=?, category=?, text=?, valid_from=?, valid_to=?, supersedes=?, created_at=?, updated_at=?,"
                    " persona_id=COALESCE(?, persona_id) WHERE id=?",
                    (status, category, text, now, valid_to, json.dumps(superseded), now, now, persona_id, fid))
    else:
        con.execute("INSERT INTO facts(id, subject, predicate, value, text, category, status, source_kind, valid_from, valid_to, supersedes, legacy,"
                    " persona_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fid, subject, predicate, value, text, category, status, source_kind, now, valid_to, json.dumps(superseded), int(legacy), persona_id, now, now))
    con.execute("INSERT OR IGNORE INTO evidence(fact_id, message_id, speaker, quote, created_at) VALUES (?, ?, ?, ?, ?)",
                (fid, message_id, speaker, quote, now))
    self._cache.pop(fid, None)
    return fid


def prune(self, con) -> None:
    total = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    if total <= MAX_ROWS:
        return
    ids = [r[0] for r in con.execute("SELECT id FROM facts WHERE status IN ('superseded','retracted') ORDER BY updated_at LIMIT ?", (total - MAX_ROWS,))]
    for fid in ids:
        self.delete_rows(con, [fid])


def delete_rows(self, con, ids) -> None:
    for fid in ids:
        con.execute("DELETE FROM vectors WHERE fact_id=?", (fid,))
        con.execute("DELETE FROM evidence WHERE fact_id=?", (fid,))
        con.execute("DELETE FROM facts WHERE id=?", (fid,))
        self._cache.pop(fid, None)


}
