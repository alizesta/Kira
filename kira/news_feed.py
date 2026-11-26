"""Persistent, character-isolated news feed with a rolling seven-day window.

News is deliberately stored separately from persona/evidence memory: articles are
external observations, not facts about the user. Each row keeps its source and
publication timestamp so prompts and UI can preserve provenance.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import DATA_DIR

RETENTION_SECONDS = 7 * 24 * 60 * 60
CHARACTER_CATEGORIES = {
    "mika": frozenset({"medical", "public_health", "epidemic"}),
    "ren": frozenset({"economy", "markets", "stocks", "currency", "crypto", "technology"}),
    "kira": frozenset({"gaming", "game_technology", "game_hardware"}),
}


def _character_id(value: str) -> str:
    key = str(value or "").strip().lower()
    if key not in CHARACTER_CATEGORIES:
        raise ValueError(f"Unsupported news-feed character: {value!r}")
    return key


def _timestamp(value: Any, fallback: float) -> float:
    try:
        number = float(value)
        if number > 0 and number < float("inf"):
            return number
    except (TypeError, ValueError, OverflowError):
        pass
    return fallback


def _canonical_url(value: str) -> str:
    raw = str(value or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("News items require an absolute HTTP(S) source URL")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


class NewsFeedStore:
    """SQLite-backed seven-day news feed, isolated by character and category."""

    def __init__(self, path: str | Path | None = None, *, retention_seconds: int = RETENTION_SECONDS):
        self.path = Path(path) if path is not None else Path(DATA_DIR) / "kira_news_feed.sqlite3"
        self.retention_seconds = max(60, int(retention_seconds))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS news_items (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    analysis TEXT NOT NULL DEFAULT '',
                    source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    published_at REAL NOT NULL,
                    fetched_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    region TEXT NOT NULL DEFAULT '',
                    UNIQUE(character_id, source_url)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_character_expiry "
                "ON news_items(character_id, expires_at DESC)"
            )

    def purge_expired(self, *, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        with self._connect() as db:
            cursor = db.execute("DELETE FROM news_items WHERE expires_at <= ?", (current,))
            return max(0, cursor.rowcount)

    def add_item(
        self,
        character_id: str,
        *,
        category: str,
        title: str,
        summary: str,
        source_name: str,
        source_url: str,
        published_at: float | None = None,
        analysis: str = "",
        region: str = "",
        fetched_at: float | None = None,
    ) -> str:
        character = _character_id(character_id)
        kind = str(category or "").strip().lower()
        if kind not in CHARACTER_CATEGORIES[character]:
            raise ValueError(f"Category {kind!r} is not allowed for {character}")
        clean_title = str(title or "").strip()[:500]
        clean_summary = str(summary or "").strip()[:12000]
        clean_source = str(source_name or "").strip()[:200]
        url = _canonical_url(source_url)
        if not clean_title or not clean_summary or not clean_source:
            raise ValueError("News title, summary and source name are required")
        fetched = _timestamp(fetched_at, time.time())
        published = _timestamp(published_at, fetched)
        # Old material is not made fresh merely because it was fetched again.
        expires = min(fetched, published) + self.retention_seconds
        item_id = hashlib.sha256(f"{character}|{url}".encode("utf-8")).hexdigest()[:24]
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO news_items (
                    id, character_id, category, title, summary, analysis,
                    source_name, source_url, published_at, fetched_at, expires_at, region
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id, source_url) DO UPDATE SET
                    category=excluded.category,
                    title=excluded.title,
                    summary=excluded.summary,
                    analysis=excluded.analysis,
                    source_name=excluded.source_name,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at,
                    region=excluded.region
                """,
                (item_id, character, kind, clean_title, clean_summary, str(analysis or "")[:12000],
                 clean_source, url, published, fetched, expires, str(region or "")[:200]),
            )
        return item_id

    def list_items(
        self,
        character_id: str,
        *,
        categories: list[str] | tuple[str, ...] | None = None,
        limit: int = 50,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        character = _character_id(character_id)
        current = time.time() if now is None else float(now)
        self.purge_expired(now=current)
        allowed = CHARACTER_CATEGORIES[character]
        selected = sorted(set(categories or allowed))
        if not selected or any(item not in allowed for item in selected):
            raise ValueError(f"Invalid news categories for {character}")
        placeholders = ",".join("?" for _ in selected)
        cap = max(1, min(int(limit), 200))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM news_items WHERE character_id=? AND category IN ({placeholders}) "
                "AND expires_at>? ORDER BY published_at DESC, fetched_at DESC LIMIT ?",
                (character, *selected, current, cap),
            ).fetchall()
        return [dict(row) for row in rows]

    def build_context(self, character_id: str, *, query: str = "", limit: int = 12) -> str:
        """Return sourced recent context for the selected character only."""
        items = self.list_items(character_id, limit=limit)
        if not items:
            return ""
        lines = [
            f"Recent {character_id.title()} news feed (rolling seven-day window).",
            "Treat sourced article summaries as reported information; treat analysis as interpretation.",
        ]
        for item in items:
            lines.append(
                f"- [{item['category']}] {item['title']} "
                f"(published {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(item['published_at']))}; "
                f"source: {item['source_name']}; URL: {item['source_url']})"
            )
            lines.append(f"  Reported summary: {item['summary']}")
            if item["analysis"]:
                lines.append(f"  Separate analysis: {item['analysis']}")
        return "\n".join(lines)
