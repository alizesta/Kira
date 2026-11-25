"""Transactional repository operations for evidence facts and their provenance."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable


class EvidenceFactRepository:
    """Own fact/evidence/quarantine writes; connection and transaction ownership stay outside."""

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
        max_rows: int,
        cache: dict,
    ) -> None:
        self._fact_id = fact_id
        self._normalize = normalize
        self._quote_in = quote_in
        self._word_regex = word_regex
        self._stop_words = frozenset(stop_words)
        self._categories = frozenset(categories)
        self._single_valued = frozenset(single_valued)
        self._max_rows = max(1, int(max_rows))
        self._cache = cache

    def quarantine(self, connection, reason, payload) -> None:
        connection.execute(
            "INSERT INTO quarantine(created_at, reason, payload) VALUES (?, ?, ?)",
            (time.time(), str(reason)[:300], json.dumps(payload, ensure_ascii=False, default=str)[:800]),
        )

    def same_thing(self, left, right) -> bool:
        normalized_left = self._normalize(left)
        normalized_right = self._normalize(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left in normalized_right or normalized_right in normalized_left:
            return True
        left_words = set(self._word_regex.findall(normalized_left)) - self._stop_words
        right_words = set(self._word_regex.findall(normalized_right)) - self._stop_words
        return bool(left_words and right_words) and (
            len(left_words & right_words) / len(left_words | right_words) >= 0.5
        )

    def ingest(
        self,
        connection,
        *,
        subject,
        predicate,
        value,
        text,
        category,
        quote,
        speaker,
        message_id,
        source_kind,
        now,
        uncertain=False,
        explicit=False,
        persona_id=None,
        valid_to=None,
        source_text=None,
        legacy=0,
    ) -> str | None:
        """Store a fact and its provenance in the caller's transaction."""
        value, text, quote = (
            " ".join(str(value or "").split()),
            " ".join(str(text or "").split()),
            " ".join(str(quote or "").split()),
        )
        if not value or not text or not quote:
            self.quarantine(connection, "empty value / text / quote", {"predicate": predicate, "text": text})
            return None
        if category not in self._categories:
            category = "unverified"
        if source_text is not None and not self._quote_in(quote, source_text):
            self.quarantine(
                connection,
                "quote is not a literal substring of its source message",
                {"predicate": predicate, "quote": quote},
            )
            return None
        if speaker == "assistant" and subject == "user" and category != "unverified":
            category = "unverified"
        status = "uncertain" if (uncertain and not explicit) else "active"
        fact_id = self._fact_id(subject, predicate, value)
        existing = connection.execute(
            "SELECT * FROM facts WHERE subject=? AND predicate=? AND status IN ('active','uncertain')",
            (subject, predicate),
        ).fetchall()
        existing_row = connection.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
        if existing_row is not None and existing_row["status"] in ("active", "uncertain"):
            connection.execute(
                "INSERT OR IGNORE INTO evidence(fact_id, message_id, speaker, quote, created_at) VALUES (?, ?, ?, ?, ?)",
                (fact_id, message_id, speaker, quote, now),
            )
            new_status = (
                "active"
                if existing_row["status"] == "uncertain" and status == "active"
                else existing_row["status"]
            )
            connection.execute(
                "UPDATE facts SET updated_at=?, status=?, persona_id=COALESCE(persona_id, ?) WHERE id=?",
                (now, new_status, persona_id, fact_id),
            )
            self._cache.pop(fact_id, None)
            return fact_id

        superseded = []
        if status == "active":
            if predicate in self._single_valued:
                superseded = [row["id"] for row in existing_row if row["id"] != fact_id]
            elif predicate in ("like", "dislike"):
                opposite = "dislike" if predicate == "like" else "like"
                opposite_rows = connection.execute(
                    "SELECT * FROM facts WHERE subject=? AND predicate=? AND status IN ('active','uncertain')",
                    (subject, opposite),
                ).fetchall()
                superseded = [
                    row["id"] for row in opposite_rows
                    if self.same_thing(row["value"], value)
                ]
        for old_id in superseded:
            connection.execute(
                "UPDATE facts SET status='superseded', updated_at=? WHERE id=?",
                (now, old_id),
            )

        if existing_row is not None:
            connection.execute(
                "UPDATE facts SET status=?, category=?, text=?, valid_from=?, valid_to=?, supersedes=?, created_at=?, updated_at=?, "
                "persona_id=COALESCE(?, persona_id) WHERE id=?",
                (
                    status, category, text, now, valid_to, json.dumps(superseded),
                    now, now, persona_id, fact_id,
                ),
            )
        else:
            connection.execute(
                "INSERT INTO facts(id, subject, predicate, value, text, category, status, source_kind, valid_from, valid_to, "
                "supersedes, legacy, persona_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fact_id, subject, predicate, value, text, category, status, source_kind,
                    now, valid_to, json.dumps(superseded), int(legacy), persona_id, now, now,
                ),
            )
        connection.execute(
            "INSERT OR IGNORE INTO evidence(fact_id, message_id, speaker, quote, created_at) VALUES (?, ?, ?, ?, ?)",
            (fact_id, message_id, speaker, quote, now),
        )
        self._cache.pop(fact_id, None)
        return fact_id

    def delete_rows(self, connection, ids) -> None:
        for fact_id in ids:
            connection.execute("DELETE FROM vectors WHERE fact_id=?", (fact_id,))
            connection.execute("DELETE FROM evidence WHERE fact_id=?", (fact_id,))
            connection.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            self._cache.pop(fact_id, None)

    def prune(self, connection) -> None:
        total = connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        if total <= self._max_rows:
            return
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM facts WHERE status IN ('superseded','retracted') ORDER BY updated_at LIMIT ?",
                (total - self._max_rows,),
            )
        ]
        self.delete_rows(connection, ids)

    def delete_persona_item(self, connection, persona_id) -> int:
        rows = connection.execute(
            "SELECT id, subject, predicate FROM facts WHERE persona_id=?",
            (persona_id,),
        ).fetchall()
        ids = []
        for row in rows:
            if row["predicate"] in self._single_valued:
                ids.extend(
                    found[0]
                    for found in connection.execute(
                        "SELECT id FROM facts WHERE subject=? AND predicate=?",
                        (row["subject"], row["predicate"]),
                    )
                )
            else:
                ids.append(row["id"])
        unique_ids = set(ids)
        self.delete_rows(connection, unique_ids)
        return len(unique_ids)

    def update_persona_item(
        self,
        connection,
        old_persona_id,
        new_persona_id,
        text,
        *,
        now,
    ) -> None:
        row = connection.execute(
            "SELECT subject, predicate FROM facts WHERE persona_id=? LIMIT 1",
            (old_persona_id,),
        ).fetchone()
        predicate = row["predicate"] if row else "note"
        subject = row["subject"] if row else "user"
        rows = connection.execute(
            "SELECT id, subject, predicate FROM facts WHERE persona_id=?",
            (old_persona_id,),
        ).fetchall()
        ids = []
        for item in rows:
            if item["predicate"] in self._single_valued:
                ids.extend(
                    found[0]
                    for found in connection.execute(
                        "SELECT id FROM facts WHERE subject=? AND predicate=?",
                        (item["subject"], item["predicate"]),
                    )
                )
            else:
                ids.append(item["id"])
        self.delete_rows(connection, set(ids))
        stored_id = self.ingest(
            connection,
            subject=subject,
            predicate=predicate,
            value=text,
            text=text,
            category="permanent",
            quote=text,
            speaker="user",
            message_id=None,
            source_kind="manual",
            now=now,
            persona_id=new_persona_id,
        )
        if stored_id is None:
            raise RuntimeError(
                "Updated persona-memory item could not be synchronized to evidence memory"
            )

    def clear_all(self, connection, *, history_watermark: int, meta_set: Callable) -> None:
        for table in ("vectors", "embedding_indexes", "evidence", "facts", "quarantine"):
            connection.execute(f"DELETE FROM {table}")
        meta_set(connection, "backfilled", "1")
        meta_set(connection, "seen_upto", history_watermark)
        meta_set(connection, "writer_upto", history_watermark)
