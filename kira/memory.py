"""Chat history (SQLite). Same public API as always: init_db, add_message, recent_messages, clear_memory, conversation_context.

Task 02 hardening - the goal is that a chat can never silently vanish:
* every connection is closed, with a busy timeout (no 'database is locked' / Windows file locks);
* a database error never reaches the chat: the message is kept in memory, written on the next successful call, and
  add_message() returns False so the window can tell the person;
* a damaged database file is NEVER deleted: it is renamed (kira_memory.corrupt-<time>.sqlite3), readable rows are
  salvaged, merged with the newest valid backup, and written to a fresh database;
* clear_memory() first saves a snapshot (snapshots/cleared-<time>/) and refuses to delete if that fails;
  restore_last_cleared() brings those messages back; import_messages() merges chats from an older database.
"""
from __future__ import annotations

import contextlib
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from .config import DB_PATH

DB_NAME = "kira_memory.sqlite3"
SNAPSHOTS_KEEP = 5


class ChatStoreError(RuntimeError):
    """The chat database could not do what was asked (and nothing was lost)."""


_lock = threading.RLock()
_pending: list[tuple[str, str]] = []        # messages that could not be written yet (database problem)
last_error: str | None = None
startup_notes: list[str] = []


# ---------------- low level ----------------
@contextlib.contextmanager
def _db(path=None):
    con = sqlite3.connect(str(path or DB_PATH), timeout=15)
    try:
        with con:                            # commit on success, rollback on error
            yield con
    finally:
        con.close()


def _create(con):
    con.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")


def _data_dir() -> Path:
    return Path(DB_PATH).parent


def _is_corruption(exc) -> bool:
    if isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, (sqlite3.OperationalError, sqlite3.IntegrityError)):
        return True
    text = str(exc).lower()
    return any(k in text for k in ("malformed", "not a database", "disk image", "corrupt", "file is encrypted"))


def _healthy(path: Path) -> bool:
    """True when the file is a readable SQLite database whose structure passes quick_check (or does not exist yet)."""
    path = Path(path)
    if not path.exists():
        return True
    try:
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                return False
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "messages" in tables:
                con.execute("SELECT COUNT(*) FROM messages").fetchone()
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def read_rows(path) -> list[tuple[str, str, str]]:
    """(role, content, created_at) of every readable message in a database file; partial result for a damaged file."""
    rows: list[tuple[str, str, str]] = []
    path = Path(path)
    if not path.is_file():
        return rows
    try:
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return rows
    try:
        cur = con.execute("SELECT role, content, COALESCE(created_at, '') FROM messages ORDER BY id")
        while True:
            try:
                batch = cur.fetchmany(200)
            except sqlite3.Error:
                break                        # keep what was readable before the damaged page
            if not batch:
                break
            rows.extend((str(r), str(c), str(t)) for r, c, t in batch if r in ("user", "assistant", "system") and str(c).strip())
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return rows


def _merge(*sources):
    """Union of row lists without duplicates, oldest first. Earlier sources win ties inside the same second."""
    seen, out = set(), []
    for order, rows in enumerate(sources):
        for i, (role, content, ts) in enumerate(rows):
            key = (role, content, ts)
            if key in seen:
                continue
            seen.add(key)
            out.append((ts or "", order, i, role, content))
    out.sort(key=lambda x: (x[0], x[1], x[2]))
    return [(r, c, t) for t, _, _, r, c in out]


def _write_all(rows):
    """Replace the table content with `rows` in ONE transaction (rolled back entirely if anything fails)."""
    with _db() as con:
        _create(con)
        con.execute("DELETE FROM messages")
        con.executemany("INSERT INTO messages(role, content, created_at) VALUES (?, ?, NULLIF(?, ''))", rows)


def _backup_dirs():
    root = _data_dir() / "backups"
    try:
        return sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return []


def _latest_backup_rows():
    for folder in _backup_dirs():
        candidate = folder / DB_NAME
        if candidate.is_file() and _healthy(candidate):
            return read_rows(candidate), candidate
    return [], None


def _recover(reason: str) -> str:
    """Quarantine a damaged database (never delete it), then rebuild from salvaged rows + the newest valid backup."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    salvaged = read_rows(DB_PATH)
    quarantine = Path(DB_PATH).with_name(f"kira_memory.corrupt-{stamp}.sqlite3")
    n = 1
    while quarantine.exists():
        n += 1
        quarantine = quarantine.with_name(f"kira_memory.corrupt-{stamp}-{n}.sqlite3")
    try:
        Path(DB_PATH).replace(quarantine)
        for suffix in ("-journal", "-wal", "-shm"):                 # sidecar files belong to the damaged database
            side = Path(str(DB_PATH) + suffix)
            if side.exists():
                side.replace(Path(str(quarantine) + suffix))
    except OSError as exc:
        raise ChatStoreError(f"فایل دیتابیس خراب جابه‌جا نشد: {exc}") from exc
    backup_rows, backup = _latest_backup_rows()
    rows = _merge(backup_rows, salvaged)
    _write_all(rows)
    where = f" و از پشتیبان «{backup.parent.name}» کامل شد" if backup and backup_rows else ""
    return (f"دیتابیس گفتگو خراب بود ({reason}). فایل خراب پاک نشد و با نام «{quarantine.name}» کنار گذاشته شد؛ "
            f"{len(salvaged)} پیام از آن نجات یافت{where}. در مجموع {len(rows)} پیام بازیابی شد.")


def _note_error(exc):
    global last_error
    last_error = f"{type(exc).__name__}: {exc}"


# ---------------- public API (unchanged signatures) ----------------
def init_db() -> list[str]:
    """Create the table, verify the file, auto-recover a damaged one. Never raises; returns notes for the person."""
    notes: list[str] = []
    with _lock:
        try:
            Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            if not _healthy(DB_PATH):
                notes.append(_recover("بررسی سلامت فایل ناموفق بود"))
            with _db() as con:
                _create(con)
        except (sqlite3.Error, OSError, ChatStoreError) as exc:
            _note_error(exc)
            notes.append(f"دیتابیس گفتگو باز نشد ({exc}). گفتگو فعلاً فقط در حافظه نگه داشته می‌شود.")
    startup_notes[:] = notes
    return notes


def _flush_pending_locked():
    if not _pending:
        return
    with _db() as con:
        _create(con)
        con.executemany("INSERT INTO messages(role, content) VALUES (?, ?)", _pending)
    _pending.clear()


def add_message(role, content) -> bool:
    """Save one message. Returns True when it is on disk; False when the database failed (the message is kept in memory
    and written with the next successful call, so nothing is lost while the program stays open)."""
    global last_error
    role, content = str(role), str(content)
    with _lock:
        for attempt in (1, 2):
            try:
                _flush_pending_locked()
                with _db() as con:
                    _create(con)
                    con.execute("INSERT INTO messages(role, content) VALUES (?, ?)", (role, content))
                last_error = None
                return True
            except (sqlite3.Error, OSError) as exc:
                _note_error(exc)
                if attempt == 1 and _is_corruption(exc):
                    try:
                        startup_notes.append(_recover(str(exc)))
                        continue
                    except (sqlite3.Error, OSError, ChatStoreError) as rec:
                        _note_error(rec)
                break
        _pending.append((role, content))
        del _pending[:-500]                         # bounded
        return False


def recent_messages(limit=12):
    with _lock:
        for attempt in (1, 2):
            try:
                _flush_pending_locked()
                with _db() as con:
                    rows = con.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
                return [{"role": role, "content": content} for role, content in reversed(rows)]
            except (sqlite3.Error, OSError) as exc:
                _note_error(exc)
                if attempt == 1 and _is_corruption(exc):
                    try:
                        startup_notes.append(_recover(str(exc)))
                        continue
                    except (sqlite3.Error, OSError, ChatStoreError) as rec:
                        _note_error(rec)
                break
        # database unusable right now: the conversation continues from what is held in memory
        return [{"role": r, "content": c} for r, c in _pending[-int(limit):]]


def rows_with_ids(limit=3000, after_id=0):
    """[(id, role, content, created_at)] oldest first: the newest `limit` messages with id > after_id. Read-only; [] when the store is unusable.
    Used by the evidence memory to point each fact at the exact message it came from."""
    try:
        with _lock, _db() as con:
            rows = con.execute("SELECT id, role, content, created_at FROM messages WHERE id > ? ORDER BY id DESC LIMIT ?",
                               (int(after_id), int(limit))).fetchall()
        return [(int(i), str(r), str(c), str(ts or "")) for i, r, c, ts in reversed(rows)]
    except (sqlite3.Error, OSError):
        return []


def max_message_id() -> int:
    try:
        with _lock, _db() as con:
            return int(con.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0])
    except (sqlite3.Error, OSError):
        return 0


def message_count() -> int:
    try:
        with _db() as con:
            return int(con.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
    except (sqlite3.Error, OSError):
        return 0


def pending_count() -> int:
    return len(_pending)


# ---------------- snapshots: protection against deleting by mistake ----------------
def _snapshot(kind: str) -> Path:
    root = _data_dir() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target, n = root / f"{kind}-{stamp}", 1
    while target.exists():
        n += 1
        target = root / f"{kind}-{stamp}-{n}"
    target.mkdir()
    src = sqlite3.connect(str(DB_PATH), timeout=15)
    try:
        dst = sqlite3.connect(str(target / DB_NAME))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    for old in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(kind + "-")))[:-SNAPSHOTS_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return target


def list_snapshots(kind="cleared"):
    root = _data_dir() / "snapshots"
    try:
        return sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(kind + "-")), reverse=True)
    except OSError:
        return []


def clear_memory():
    """Delete the whole chat history - only after a snapshot was saved. If the snapshot cannot be made nothing is deleted."""
    with _lock:
        try:
            if message_count():
                _snapshot("cleared")
        except (sqlite3.Error, OSError) as exc:
            raise ChatStoreError(f"نسخه‌ی پشتیبان قبل از پاک‌سازی ساخته نشد؛ چیزی پاک نشد. ({exc})") from exc
        try:
            with _db() as con:
                _create(con)
                con.execute("DELETE FROM messages")
        except (sqlite3.Error, OSError) as exc:
            raise ChatStoreError(f"پاک‌سازی ناموفق بود: {exc}") from exc
        _pending.clear()


def import_messages(source) -> int:
    """Merge the messages of another chat database (older version, backup, snapshot) into the current one.
    Nothing is overwritten or removed: duplicates are skipped, order is chronological. Returns how many were added."""
    source = Path(source)
    if not source.is_file():
        raise ChatStoreError("فایل انتخاب‌شده پیدا نشد.")
    incoming = read_rows(source)
    if not incoming:
        return 0
    with _lock:
        try:
            with _db() as con:
                _create(con)
                current = [(str(r), str(c), str(t)) for r, c, t in
                           con.execute("SELECT role, content, COALESCE(created_at, '') FROM messages ORDER BY id")]
        except (sqlite3.Error, OSError) as exc:
            raise ChatStoreError(f"ورود چت ناموفق بود (چیزی تغییر نکرد): {exc}") from exc
        merged = _merge(current, incoming)
        added = len(merged) - len(current)
        if added <= 0:
            return 0                                   # nothing new: no snapshot, no rewrite
        try:
            if current:
                _snapshot("before-import")             # safety copy of the chat as it is now
            _write_all(merged)
        except (sqlite3.Error, OSError) as exc:
            raise ChatStoreError(f"ورود چت ناموفق بود (چیزی تغییر نکرد): {exc}") from exc
        return added


def restore_last_cleared() -> int:
    """Bring back the messages deleted by the most recent clear_memory(). Returns how many were restored."""
    for snap in list_snapshots("cleared"):
        candidate = snap / DB_NAME
        if candidate.is_file():
            return import_messages(candidate)
    raise ChatStoreError("هیچ پاک‌سازی قبلی برای بازگردانی پیدا نشد.")


def conversation_context(limit=12, max_chars=12000):
    """Provider-neutral chat history, newest messages retained within a size budget."""
    messages = recent_messages(max(1, int(limit)))
    kept = []
    used = 0
    for item in reversed(messages):
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        content = content[-4000:]
        cost = len(content)
        if kept and used + cost > max_chars:
            break
        kept.append({"role": role, "content": content})
        used += cost
    return list(reversed(kept))
