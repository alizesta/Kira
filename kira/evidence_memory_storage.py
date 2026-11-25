"""SQLite persistence boundary for evidence facts and independently rebuildable embedding indexes."""
from __future__ import annotations
import contextlib
import logging
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable
from .evidence_memory_models import EmbeddingIndex, EvidenceVector

_log = logging.getLogger(__name__)
DB_NAME = "kira_evidence.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL, text TEXT NOT NULL,
    category TEXT NOT NULL, status TEXT NOT NULL, source_kind TEXT NOT NULL, valid_from REAL, valid_to REAL,
    supersedes TEXT NOT NULL DEFAULT '[]', legacy INTEGER NOT NULL DEFAULT 0, persona_id TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS facts_sp ON facts(subject, predicate, status);
CREATE INDEX IF NOT EXISTS facts_persona ON facts(persona_id);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fact_id TEXT NOT NULL, message_id INTEGER, speaker TEXT NOT NULL, quote TEXT NOT NULL,
    created_at REAL NOT NULL, UNIQUE(fact_id, quote));
CREATE TABLE IF NOT EXISTS vectors (
    fact_id TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, blob BLOB NOT NULL,
    PRIMARY KEY(fact_id, model));
CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, reason TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS embedding_indexes (
    model_tag TEXT PRIMARY KEY, backend TEXT NOT NULL, provider TEXT NOT NULL, model_name TEXT NOT NULL,
    index_version INTEGER NOT NULL, dimensions INTEGER NOT NULL, updated_at REAL NOT NULL);
"""

class SQLiteEvidenceStorage:
    """Owns database lifecycle and vector-index persistence, never embedding computation."""
    schema = SCHEMA

    def __init__(self, database_name: str = DB_NAME):
        self.database_name = database_name
        self.ensure_lock = Lock()

    def path(self, data_dir) -> Path:
        return Path(data_dir) / self.database_name

    @staticmethod
    def quarantine_file(path: Path, why: str) -> Path:
        """Preserve a damaged database under a distinct name; never discard its bytes."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        counter = 1
        while target.exists():
            counter += 1
            target = path.with_name(f"{path.stem}.corrupt-{stamp}-{counter}{path.suffix}")
        try:
            path.replace(target)
            for suffix in ("-journal", "-wal", "-shm"):
                side = Path(str(path) + suffix)
                if side.exists():
                    side.replace(Path(str(target) + suffix))
        except OSError:
            _log.exception("Could not preserve damaged evidence database (%s)", why)
            raise
        _log.error("Preserved damaged evidence database at %s (%s)", target, why)
        return target

    def ensure(self, path: Path, ready_path: Callable[[], str | None], mark_ready: Callable[[str], None]) -> None:
        key = str(path)
        with self.ensure_lock:
            if ready_path() == key:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                try:
                    connection = sqlite3.connect(str(path), timeout=10)
                    try:
                        result = connection.execute("PRAGMA quick_check").fetchone()
                    finally:
                        connection.close()
                    if not result or result[0] != "ok":
                        self.quarantine_file(path, "quick_check failed")
                except sqlite3.DatabaseError:
                    self.quarantine_file(path, "not a database")
            connection = sqlite3.connect(str(path), timeout=10)
            try:
                with connection:
                    connection.executescript(self.schema)
            finally:
                connection.close()
            mark_ready(key)

    @contextlib.contextmanager
    def database(self, path: Path, ensure: Callable[[], None]):
        ensure()
        connection = sqlite3.connect(str(path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def next_vector_batch(db_factory, model_tag: str, limit: int, index_version: int = 1):
        with db_factory() as connection:
            metadata = connection.execute(
                "SELECT index_version FROM embedding_indexes WHERE model_tag=?", (model_tag,)
            ).fetchone()
            if metadata is None or int(metadata["index_version"]) != int(index_version):
                # Unknown/old vector rows are derived data and cannot be trusted without their index contract.
                connection.execute("DELETE FROM vectors WHERE model=?", (model_tag,))
                connection.execute("DELETE FROM embedding_indexes WHERE model_tag=?", (model_tag,))
            return connection.execute(
                "SELECT f.id, f.text, f.value FROM facts f "
                "WHERE f.status IN ('active','uncertain') AND NOT EXISTS "
                "(SELECT 1 FROM vectors v WHERE v.fact_id=f.id AND v.model=?) "
                "ORDER BY f.created_at DESC LIMIT ?",
                (model_tag, int(limit)),
            ).fetchall()

    @staticmethod
    def save_vectors(
        db_factory,
        index: EmbeddingIndex,
        fact_ids: Iterable[str],
        vectors: Iterable[Iterable[float]],
        now: float | None = None,
    ) -> int:
        ids, raw_vectors = list(fact_ids), list(vectors)
        if len(ids) != len(raw_vectors):
            raise ValueError("embedding response count does not match fact count")
        if not ids:
            return 0
        records = [
            EvidenceVector.create(str(fact_id), index.tag, values)
            for fact_id, values in zip(ids, raw_vectors)
        ]
        dimensions = {record.dimension for record in records}
        if len(dimensions) != 1:
            raise ValueError("embedding batch contains incompatible dimensions")
        dimension = next(iter(dimensions))
        timestamp = time.time() if now is None else float(now)
        saved = 0
        with db_factory() as connection:
            existing = connection.execute(
                "SELECT index_version, dimensions FROM embedding_indexes WHERE model_tag=?", (index.tag,)
            ).fetchone()
            if existing and (
                int(existing["index_version"]) != index.index_version
                or int(existing["dimensions"]) != dimension
            ):
                # Only the derived vector index is invalidated. Facts and provenance stay untouched.
                connection.execute("DELETE FROM vectors WHERE model=?", (index.tag,))
            elif existing is None:
                connection.execute("DELETE FROM vectors WHERE model=?", (index.tag,))
            connection.execute(
                "INSERT INTO embedding_indexes(model_tag, backend, provider, model_name, index_version, dimensions, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(model_tag) DO UPDATE SET backend=excluded.backend, provider=excluded.provider, "
                "model_name=excluded.model_name, index_version=excluded.index_version, "
                "dimensions=excluded.dimensions, updated_at=excluded.updated_at",
                (index.tag, index.backend, index.provider, index.model, index.index_version, dimension, timestamp),
            )
            for record in records:
                if not connection.execute("SELECT 1 FROM facts WHERE id=?", (record.fact_id,)).fetchone():
                    continue
                connection.execute(
                    "INSERT OR REPLACE INTO vectors(fact_id, model, dim, blob) VALUES (?, ?, ?, ?)",
                    (record.fact_id, index.tag, record.dimension, record.to_blob()),
                )
                saved += 1
        return saved

    @staticmethod
    def vector_dimension(db_factory, index: EmbeddingIndex) -> int | None:
        """Return dimensions only when the persisted index contract matches this reader."""
        with db_factory() as connection:
            metadata = connection.execute(
                "SELECT index_version, dimensions FROM embedding_indexes WHERE model_tag=?",
                (index.tag,),
            ).fetchone()
        if metadata is None or int(metadata["index_version"]) != index.index_version:
            return None
        return int(metadata["dimensions"])

    @staticmethod
    def invalidate_index(db_factory, model_tag: str) -> None:
        """Discard only incompatible derived vectors; authoritative facts and evidence are untouched."""
        with db_factory() as connection:
            connection.execute("DELETE FROM vectors WHERE model=?", (model_tag,))
            connection.execute("DELETE FROM embedding_indexes WHERE model_tag=?", (model_tag,))

    @staticmethod
    def fetch_vectors(db_factory, index: EmbeddingIndex, fact_ids: Iterable[str]) -> list[EvidenceVector]:
        ids = list(dict.fromkeys(str(item) for item in fact_ids if item))
        if not ids:
            return []
        with db_factory() as connection:
            metadata = connection.execute(
                "SELECT index_version, dimensions FROM embedding_indexes WHERE model_tag=?", (index.tag,)
            ).fetchone()
            if metadata is None or int(metadata["index_version"]) != index.index_version:
                return []
            marks = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"SELECT fact_id, dim, blob FROM vectors WHERE model=? AND fact_id IN ({marks})",
                (index.tag, *ids),
            ).fetchall()
        expected_dimension = int(metadata["dimensions"])
        result = []
        for row in rows:
            try:
                vector = EvidenceVector.from_row(row, index.tag)
                if vector.dimension == expected_dimension:
                    result.append(vector)
            except (TypeError, ValueError, OverflowError):
                # A malformed derived row is skipped; the fact remains available to lexical retrieval.
                continue
        return result
