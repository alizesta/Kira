"""File System Agent (T5-A): create / copy / rename / write / organise / batch operations on the user's files, with real results.

Safety model (all enforced in code, never by trusting the model):
  * every path goes through PathPolicy (allowed folders only, never secrets, never Kira's own data);
  * nothing is ever overwritten silently: create / copy / rename / move refuse an existing target; replacing content is a separate
    SENSITIVE tool that makes a backup copy first;
  * level 2 tools (create / copy / rename / make folder / append) only run when the user's CURRENT message asks for such a change;
  * delete, replace, batch and organise operations are level 3: the exact plan is shown and needs the user's explicit "تأیید";
  * a new or renamed file can never get an executable / script extension; names are checked for Windows rules;
  * every result is verified on disk before success is reported; reversible operations are journaled (kira_file_ops.json) for undo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .access import PathPolicy, EXECUTABLE_EXT
from .fileops import TEXT_EXT, _fmt_size, _recycle
from .registry import Tool, Param, ToolError, ACTION, SENSITIVE, DENIED

_LOGGER = logging.getLogger(__name__)

JOURNAL_NAME = "kira_file_ops.json"
JOURNAL_KEEP = 30
UNDO_WINDOW = 3600
MAX_TEXT_BYTES = 200_000
MAX_APPEND_TARGET = 2 * 1024 * 1024
COPY_MAX_FILES, COPY_MAX_BYTES = 3000, 500 * 1024 * 1024
BATCH_MAX = 50
ORGANISE_MAX = 500
_BAD_CHARS = set('<>:"/\\|?*')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
# the user's current message must ask for a change (normalised: lower case, Persian letters, ZWNJ -> space)
WRITE_INTENT = re.compile(r"(?:بساز|ایجاد|درست\s*کن|بنویس|نوشتن|ذخیره|اضافه|کپی|رونوشت|نسخه|تغییر\s*(?:نام|اسم)|اسم.{0,40}بذار|عوض|"
                          r"create|make|new\b|write|save|append|add\b|copy|duplicate|rename|name)", re.I)
CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".svg", ".heic"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".rtf", ".odt", ".csv"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi"},
}


def valid_name(name: str, *, allow_exec: bool = False) -> str:
    """The cleaned file / folder name, or ToolError. Windows rules + no executable extension for anything Kira creates."""
    name = str(name or "").strip().strip('"')
    if not name or name in (".", ".."):
        raise ToolError("نام خالی یا نامعتبر است.")
    if len(name) > 150:
        raise ToolError("نام خیلی بلند است (حداکثر ۱۵۰ نویسه).")
    if any(c in _BAD_CHARS or ord(c) < 32 for c in name):
        raise ToolError('نام نباید شامل این نویسه‌ها باشد: < > : " / \\ | ? *')
    if name.endswith((" ", ".")):
        raise ToolError("نام نباید به نقطه یا فاصله ختم شود.")
    if name.split(".")[0].lower() in _RESERVED:
        raise ToolError("این نام در ویندوز رزرو است (مثل CON یا NUL).")
    if not allow_exec and os.path.splitext(name)[1].lower() in EXECUTABLE_EXT:
        raise ToolError("ساخت یا نام‌گذاری فایل اجرایی/اسکریپت (exe, bat, ps1, lnk ...) مجاز نیست.", DENIED)
    return name


class Journal:
    """Thread-safe, atomic persistence for reversible file-operation history."""

    def __init__(self, data_dir):
        self.path = Path(data_dir) / JOURNAL_NAME if data_dir else None
        self.items: list[dict] = []
        self._lock = threading.RLock()
        if self.path is not None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.items = [x for x in data if isinstance(x, dict)][-JOURNAL_KEEP:] if isinstance(data, list) else []
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                _LOGGER.warning("Could not load file-operation journal: %s", self.path, exc_info=True)

    def _save(self) -> bool:
        if self.path is None:
            return False
        with self._lock:
            tmp = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    dir=self.path.parent,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(self.items[-JOURNAL_KEEP:], stream, ensure_ascii=False, default=str)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, self.path)
                tmp = None
                return True
            except OSError:
                # The filesystem operation has already happened when Journal.add()
                # is called. Keep in-memory history and log the persistence failure
                # rather than falsely reporting the file operation itself as failed.
                _LOGGER.warning("Could not persist file-operation journal: %s", self.path, exc_info=True)
                return False
            finally:
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        _LOGGER.debug("Could not remove temporary journal file: %s", tmp, exc_info=True)

    def add(self, op: str, **fields) -> bool:
        with self._lock:
            self.items.append({"journal_id": uuid.uuid4().hex, "op": op, "ts": time.time(), **fields})
            self.items = self.items[-JOURNAL_KEEP:]
            return self._save()

    def last(self):
        with self._lock:
            for item in reversed(self.items):
                if not item.get("undone"):
                    return dict(item)
        return None

    def mark_undone(self, item):
        with self._lock:
            journal_id = str(item.get("journal_id") or "")
            target = next(
                (entry for entry in reversed(self.items)
                 if journal_id and entry.get("journal_id") == journal_id),
                None,
            )
            if target is None and not journal_id:
                target = next(
                    (entry for entry in reversed(self.items)
                     if entry.get("op") == item.get("op")
                     and entry.get("ts") == item.get("ts")
                     and not entry.get("undone")),
                    None,
                )
            if target is None or target.get("undone"):
                return False
            target["undone"] = True
            return self._save()


def _unlink_created_if_same(path: str, expected_stat) -> None:
    """Remove only the inode this operation created; never unlink a raced replacement."""
    try:
        current_stat = os.lstat(path)
    except FileNotFoundError:
        return
    if not os.path.samestat(expected_stat, current_stat):
        raise OSError("destination was replaced by another process; refusing to remove it")
    os.unlink(path)


def _is_link_or_reparse(path: str) -> bool:
    """Treat symlinks and Windows junction/reparse points as links; fail closed on unreadable metadata."""
    isjunction = getattr(os.path, "isjunction", None)
    try:
        if os.path.islink(path) or (callable(isjunction) and isjunction(path)):
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def _count_tree(root: str):
    files = size = skipped = 0

    def onerror(_error):
        nonlocal skipped
        skipped += 1

    for base, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        retained_dirs = []
        for directory in dirs:
            directory_path = os.path.join(base, directory)
            if _is_link_or_reparse(directory_path):
                skipped += 1
            else:
                retained_dirs.append(directory)
        dirs[:] = retained_dirs
        for name in names:
            path = os.path.join(base, name)
            if _is_link_or_reparse(path):
                skipped += 1
                continue
            files += 1
            try:
                size += os.path.getsize(path)
            except OSError:
                skipped += 1
    return files, size, skipped


class FileAgent:
    JOURNAL_WARNING = " هشدار: سابقه‌ی این عملیات روی دیسک ذخیره نشد؛ Undo پس از بسته‌شدن برنامه تضمین‌شده نیست."
    JOURNAL_UNDO_WARNING = " هشدار: عملیات برگردانده شد، اما وضعیت Undo روی دیسک ذخیره نشد؛ پس از راه‌اندازی مجدد ممکن است سابقه آن را انجام‌نشده نشان دهد."

    def __init__(self, policy: PathPolicy, journal: Journal):
        self.policy, self.journal = policy, journal

    @classmethod
    def _journal_note(cls, persisted: bool) -> str:
        return "" if persisted else cls.JOURNAL_WARNING

    @classmethod
    def _journal_undo_note(cls, persisted: bool) -> str:
        return "" if persisted else cls.JOURNAL_UNDO_WARNING

    # ---------------------------------------------------------------- helpers
    def _new_target(self, folder: str, name: str, *, allow_exec=False) -> str:
        """Checked path of an item that must NOT exist yet, inside an allowed existing folder."""
        folder = self.policy.check(folder)
        if not os.path.isdir(folder):
            raise ToolError("پوشه‌ی مقصد وجود ندارد یا پوشه نیست.")
        target = self.policy.check(os.path.join(folder, valid_name(name, allow_exec=allow_exec)), must_exist=False)
        if os.path.lexists(target):
            raise ToolError(f"از قبل مورد هم‌نامی وجود دارد و رونویسی نمی‌شود: {target}")
        return target

    def _parent_and_name(self, path: str):
        text = os.path.expandvars(os.path.expanduser(str(path or "").strip().strip('"')))
        if not os.path.isabs(text):
            raise ToolError("مسیر باید کامل (مثل C:\\Users\\...) باشد.")
        parent, name = os.path.split(text.rstrip("\\/"))
        return parent, name

    # ---------------------------------------------------------------- level 2
    def make_folder(self, a: dict) -> str:
        parent, name = self._parent_and_name(a["path"])
        target = self._new_target(parent, name)
        os.mkdir(target)
        if not os.path.isdir(target):
            raise ToolError("پوشه ساخته نشد.")
        persisted = self.journal.add("mkdir", path=target)
        return f"پوشه ساخته شد: {target}" + self._journal_note(persisted)

    def create_file(self, a: dict) -> str:
        parent, name = self._parent_and_name(a["path"])
        target = self._new_target(parent, name)
        content = str(a.get("content") or "")
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise ToolError("متن خیلی بزرگ است (حداکثر ۲۰۰ کیلوبایت در یک بار).")
        try:
            created = open(target, "xb")                               # "x": fails instead of overwriting, even in a race
        except OSError:
            raise
        created_stat = os.fstat(created.fileno())
        try:
            with created as fh:
                written = fh.write(data)
                if written != len(data):
                    raise OSError("short write while creating file")
            current_stat = os.lstat(target)
            if (not os.path.samestat(created_stat, current_stat)
                    or not os.path.isfile(target) or os.path.getsize(target) != len(data)):
                raise OSError("created file was replaced or its size does not match content")
        except Exception as exc:
            try:
                _unlink_created_if_same(target, created_stat)
            except FileNotFoundError:
                pass
            except OSError:
                _LOGGER.exception("Could not remove partial created file: %s", target)
                raise ToolError(f"نوشتن ناقص ماند و فایل ناقص هم پاک نشد: {target}") from exc
            raise ToolError(f"ساخت فایل ناموفق بود؛ فایل ناقص پاک شد: {type(exc).__name__}: {exc}") from exc
        persisted = self.journal.add("create", path=target)
        return f"فایل ساخته شد: {target} ({_fmt_size(len(data))})" + self._journal_note(persisted)

    def append_text(self, a: dict) -> str:
        path = self.policy.check(a["path"])
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in TEXT_EXT or os.path.splitext(path)[1].lower() in EXECUTABLE_EXT:
            raise ToolError("افزودن متن فقط برای فایل متنی ساده (txt, md, csv, json, log ...) ممکن است. برای Word بعداً ابزار جدا هست.")
        if os.path.getsize(path) > MAX_APPEND_TARGET:
            raise ToolError("فایل خیلی بزرگ است.")
        data = str(a.get("content") or "").encode("utf-8")
        if not data or len(data) > MAX_TEXT_BYTES:
            raise ToolError("متن خالی است یا بیش از ۲۰۰ کیلوبایت است.")
        before_stat = os.stat(path)
        before = before_stat.st_size
        original_digest = hashlib.sha256()
        if before:
            with open(path, "rb") as fh:
                current_stat = os.fstat(fh.fileno())
                if (current_stat.st_dev, current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (
                    before_stat.st_dev, before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns
                ):
                    raise ToolError("فایل هم‌زمان تغییر کرده؛ append انجام نشد.")
                last_byte = None
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    original_digest.update(chunk)
                    last_byte = chunk[-1]
                if last_byte not in (b"\n", b"\r"):
                    data = b"\n" + data                                   # a new paragraph starts on its own line (tool arguments are stripped)
        try:
            with open(path, "ab") as fh:
                current_stat = os.fstat(fh.fileno())
                if (current_stat.st_dev, current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (
                    before_stat.st_dev, before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns
                ):
                    raise OSError("file changed before append")
                written = fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if written != len(data) or os.path.getsize(path) != before + len(data):
                raise OSError("append size does not match requested bytes")
            digest = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
        except Exception as exc:
            try:
                current_stat = os.stat(path)
                if ((current_stat.st_dev, current_stat.st_ino) != (before_stat.st_dev, before_stat.st_ino)
                        or not before <= current_stat.st_size <= before + len(data)):
                    raise OSError("file identity or size changed; safe rollback is not possible")
                with open(path, "r+b") as fh:
                    prefix_digest = hashlib.sha256()
                    remaining = before
                    while remaining:
                        chunk = fh.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise OSError("original file prefix is incomplete")
                        prefix_digest.update(chunk)
                        remaining -= len(chunk)
                    if prefix_digest.digest() != original_digest.digest():
                        raise OSError("original file content changed; safe rollback is not possible")
                    fh.truncate(before)
                    fh.flush()
                    os.fsync(fh.fileno())
            except Exception as rollback_exc:
                raise ToolError(
                    f"افزودن متن شکست خورد و بازگردانی امن هم ممکن نشد؛ فایل را بررسی کن: {path}"
                ) from rollback_exc
            raise ToolError(f"افزودن متن شکست خورد؛ فایل به اندازه‌ی قبلی بازگردانده شد: {type(exc).__name__}") from exc
        persisted = self.journal.add(
            "append",
            path=path,
            size_before=before,
            size_after=os.path.getsize(path),
            sha256_after=digest.hexdigest(),
        )
        return f"{_fmt_size(len(data))} به انتهای فایل اضافه شد: {path}" + self._journal_note(persisted)

    def copy_item(self, a: dict) -> str:
        src, target, note = self._copy(a)
        persisted = self.journal.add("copy", source=src, path=target)
        return f"کپی شد: {src} ← {target}{note}" + self._journal_note(persisted)

    def _copy_file_exclusive(self, src: str, target: str) -> None:
        """Copy one file without overwriting a raced destination or leaving partial output."""
        try:
            destination = open(target, "xb")
        except OSError as exc:
            raise ToolError(f"مقصد کپی ایجاد نشد: {exc}") from exc
        created_stat = os.fstat(destination.fileno())
        try:
            with destination as out, open(src, "rb") as source:
                shutil.copyfileobj(source, out)
            shutil.copystat(src, target)
            current_stat = os.lstat(target)
            if (not os.path.samestat(created_stat, current_stat)
                    or os.path.getsize(target) != os.path.getsize(src)):
                raise OSError("copied file was replaced or its size does not match source")
        except Exception as exc:
            try:
                _unlink_created_if_same(target, created_stat)
            except FileNotFoundError:
                pass
            except OSError:
                _LOGGER.exception("Could not remove partial copied file: %s", target)
                raise ToolError(f"کپی ناقص ماند و پاک‌سازی مقصد هم ناموفق بود: {target}") from exc
            raise ToolError(f"کپی فایل ناموفق بود؛ مقصد ناقص پاک شد: {type(exc).__name__}: {exc}") from exc

    def _copy(self, a: dict):
        src = self.policy.check(a["source"])
        name = a.get("new_name") or os.path.basename(src)
        target = self._new_target(a["destination_folder"], name)
        if os.path.isdir(src):
            if target == src or target.startswith(src + os.sep):
                raise ToolError("پوشه را نمی‌شود داخل خودش کپی کرد.")
            files, size, _ = _count_tree(src)
            if files > COPY_MAX_FILES or size > COPY_MAX_BYTES:
                raise ToolError(f"پوشه بزرگ است ({files} فایل، {_fmt_size(size)}). سقف: {COPY_MAX_FILES} فایل و {_fmt_size(COPY_MAX_BYTES)}.")
            skipped = []

            def ignore(folder, names):
                out = []
                for n in names:
                    p = os.path.join(folder, n)
                    if (_is_link_or_reparse(p) or not self.policy.is_allowed(p)
                            or os.path.splitext(n)[1].lower() in EXECUTABLE_EXT):
                        out.append(n)
                        skipped.append(n)
                return out
            # Claim the destination atomically before copying. If copytree
            # fails halfway, only this operation's own directory is rolled back.
            os.mkdir(target)
            try:
                shutil.copytree(src, target, symlinks=False, ignore=ignore, dirs_exist_ok=True)
            except Exception as exc:
                try:
                    shutil.rmtree(target)
                except OSError:
                    _LOGGER.exception("Could not remove partial folder copy: %s", target)
                    raise ToolError(f"کپی پوشه ناقص ماند و پاک‌سازی مقصد هم ناموفق بود: {target}") from exc
                raise ToolError(f"کپی پوشه ناموفق بود؛ مقصد ناقص پاک شد: {type(exc).__name__}: {exc}") from exc
            note = f" ({len(skipped)} مورد حساس/لینک/اجرایی رد شد)" if skipped else ""
        else:
            if os.path.splitext(src)[1].lower() in EXECUTABLE_EXT:
                raise ToolError("کپی فایل اجرایی یا اسکریپت مجاز نیست.", DENIED)
            self._copy_file_exclusive(src, target)
            note = ""
        if not os.path.exists(target):
            raise ToolError("کپی انجام نشد.")
        return src, target, note

    def rename_item(self, a: dict) -> str:
        src = self.policy.check(a["path"])
        old_ext = os.path.splitext(src)[1].lower()
        new = valid_name(a["new_name"], allow_exec=old_ext == os.path.splitext(str(a["new_name"]).strip())[1].lower())   # the extension may not become executable
        target = self._new_target(os.path.dirname(src), new, allow_exec=True)
        os.rename(src, target)
        if os.path.exists(src) or not os.path.exists(target):
            raise ToolError("تغییر نام انجام نشد.")
        persisted = self.journal.add("rename", source=src, path=target)
        return f"نام تغییر کرد: {os.path.basename(src)} ← {os.path.basename(target)} (در {os.path.dirname(target)})" + self._journal_note(persisted)

    # ---------------------------------------------------------------- level 3: replace / delete folder
    def precheck_write(self, a: dict) -> dict:
        path = self.policy.check(a["path"], must_exist=False)
        ext = os.path.splitext(path)[1].lower()
        if ext in EXECUTABLE_EXT:
            raise ToolError("نوشتن روی فایل اجرایی/اسکریپت مجاز نیست.", DENIED)
        if os.path.isdir(path):
            raise ToolError("این مسیر پوشه است.")
        if len(str(a.get("content") or "").encode("utf-8")) > MAX_TEXT_BYTES:
            raise ToolError("متن خیلی بزرگ است (حداکثر ۲۰۰ کیلوبایت).")
        valid_name(os.path.basename(path))
        return {**a, "path": path}

    def confirm_write(self, a: dict) -> str:
        exists = os.path.exists(a["path"])
        return (f"محتوای فایل «{a['path']}» با متن جدید ({_fmt_size(len(str(a.get('content') or '').encode('utf-8')))}) جایگزین می‌شود؛ از نسخه‌ی قبلی کنارش پشتیبان گرفته می‌شود."
                if exists else f"فایل جدید «{a['path']}» ساخته می‌شود.")

    def write_file(self, a: dict) -> str:
        a = self.precheck_write(a)
        path, data = a["path"], str(a.get("content") or "").encode("utf-8")
        backup = ""
        existed_before = os.path.exists(path)
        if existed_before:
            # Multiple characters can request writes concurrently. A timestamp
            # alone is not unique enough: never let a later write overwrite an
            # earlier recovery copy.
            backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            shutil.copy2(path, backup)
            if not os.path.isfile(backup) or os.path.getsize(backup) != os.path.getsize(path):
                raise ToolError("پشتیبان ساخته نشد یا کامل نیست؛ فایل دست نخورد.")
        elif not os.path.isdir(os.path.dirname(path)):
            raise ToolError("پوشه‌ی فایل وجود ندارد.")

        # A shared '<target>.kira-tmp' collides when two ToolAgent sessions
        # write the same path at once. Use a unique sibling so os.replace
        # remains atomic on the target filesystem.
        fd, tmp = tempfile.mkstemp(
            prefix=f".{Path(path).name}.kira-",
            suffix=".tmp",
            dir=os.path.dirname(path),
        )
        try:
            try:
                with os.fdopen(fd, "wb") as fh:
                    written = fh.write(data)
                    if written != len(data):
                        raise OSError("short write while preparing replacement")
                    fh.flush()
                    os.fsync(fh.fileno())
                    if os.fstat(fh.fileno()).st_size != len(data):
                        raise OSError("temporary replacement size does not match content")
                os.replace(tmp, path)
            except Exception:
                if backup:
                    try:
                        os.unlink(backup)
                    except OSError:
                        _LOGGER.exception("Could not remove unused write backup after failed replacement: %s", backup)
                raise
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        persisted = self.journal.add(
            "write",
            path=path,
            backup=backup,
            created=not existed_before,
            written_size=len(data),
            written_sha256=hashlib.sha256(data).hexdigest(),
        )
        return f"فایل نوشته شد: {path}" + (f" (پشتیبان: {backup})" if backup else "") + self._journal_note(persisted)

    def precheck_delete_folder(self, a: dict) -> dict:
        path = self.policy.check(a["path"])
        if not os.path.isdir(path):
            raise ToolError("این مسیر پوشه نیست. برای فایل از delete_file استفاده کن.")
        if os.path.normcase(path) in {os.path.normcase(r) for r in self.policy.roots()}:
            raise ToolError("خود پوشه‌های اصلی (Desktop, Documents ...) حذف نمی‌شوند.", DENIED)
        return {**a, "path": path}

    def confirm_delete_folder(self, a: dict) -> str:
        files, size, skipped = _count_tree(a["path"])
        warning = (
            f" شمارش {skipped} مورد به‌دلیل لینک یا خطای دسترسی/خواندن ممکن نبود؛ تعداد و حجم واقعی می‌تواند بیشتر باشد."
            if skipped else ""
        )
        return (f"پوشه‌ی «{a['path']}» با {files} فایل ({_fmt_size(size)}) به سطل بازیافت ویندوز منتقل می‌شود "
                f"(قابل برگرداندن است).{warning}")

    def delete_folder(self, a: dict) -> str:
        a = self.precheck_delete_folder(a)
        if sys.platform != "win32":
            raise ToolError("انتقال به سطل بازیافت فقط روی ویندوز ممکن است؛ حذف انجام نشد.")
        _recycle(a["path"])
        if os.path.exists(a["path"]):
            raise ToolError("پوشه هنوز سر جایش است؛ حذف انجام نشد.")
        return f"پوشه به سطل بازیافت منتقل شد: {a['path']}"

    # ---------------------------------------------------------------- level 3: batch
    @staticmethod
    def _paths(value) -> list:
        if isinstance(value, str):
            value = [p for p in re.split(r"[\r\n;|]+", value) if p.strip()]
        if not isinstance(value, list):
            raise ToolError("paths باید فهرستی از مسیرهای کامل باشد.")
        out, seen = [], set()
        for p in value:
            p = str(p).strip().strip('"')
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
        if not out:
            raise ToolError("هیچ مسیری داده نشده است.")
        if len(out) > BATCH_MAX:
            raise ToolError(f"در هر بار حداکثر {BATCH_MAX} مورد مجاز است.")
        return out

    def precheck_batch(self, a: dict) -> dict:
        op = a["operation"]
        paths = [self.policy.check(p) for p in self._paths(a["paths"])]
        dest = ""
        if op in ("copy", "move"):
            if not a.get("destination_folder"):
                raise ToolError("برای copy و move باید destination_folder داده شود.")
            dest = self.policy.check(a["destination_folder"])
            if not os.path.isdir(dest):
                raise ToolError("destination_folder باید پوشه‌ی موجود باشد.")
            for p in paths:
                target = os.path.join(dest, os.path.basename(p))
                if os.path.lexists(target):
                    raise ToolError(f"در مقصد از قبل «{os.path.basename(p)}» هست و رونویسی نمی‌شود؛ چیزی انجام نشد.")
                if os.path.isdir(p):
                    normalized_source = os.path.normcase(os.path.abspath(p))
                    normalized_dest = os.path.normcase(os.path.abspath(dest))
                    try:
                        destination_inside_source = os.path.commonpath(
                            [normalized_source, normalized_dest]
                        ) == normalized_source
                    except ValueError:                              # different drives
                        destination_inside_source = False
                    if destination_inside_source:
                        raise ToolError("پوشه را نمی‌شود داخل خودش برد/کپی کرد.")
                    if op == "move" and os.stat(p).st_dev != os.stat(dest).st_dev:
                        raise ToolError("انتقال پوشه بین فایل‌سیستم‌های متفاوت مجاز نیست؛ برای جلوگیری از دنبال‌کردن لینک‌های داخل پوشه، عملیات متوقف شد.")
        elif op == "delete":
            roots = {os.path.normcase(r) for r in self.policy.roots()}
            if any(os.path.normcase(p) in roots for p in paths):
                raise ToolError("پوشه‌های اصلی حذف نمی‌شوند.", DENIED)
        return {**a, "paths": paths, "destination_folder": dest}

    def confirm_batch(self, a: dict) -> str:
        names = "، ".join(os.path.basename(p) for p in a["paths"][:6]) + (f" و {len(a['paths']) - 6} مورد دیگر" if len(a["paths"]) > 6 else "")
        verb = {"copy": "کپی می‌شوند به", "move": "منتقل می‌شوند به", "delete": "به سطل بازیافت می‌روند"}[a["operation"]]
        return f"{len(a['paths'])} مورد ({names}) {verb}" + (f" «{a['destination_folder']}»" if a["destination_folder"] else "") + "."

    def batch_files(self, a: dict) -> str:
        a = self.precheck_batch(a)
        done, failed, moves, copies = [], [], [], []
        for p in a["paths"]:
            try:
                if a["operation"] == "copy":
                    copies.append(self._copy({"source": p, "destination_folder": a["destination_folder"]})[1])
                elif a["operation"] == "move":
                    target = os.path.join(a["destination_folder"], os.path.basename(p))
                    if os.path.isdir(p):
                        os.rename(p, target)                           # same-device only; never let shutil.move follow nested links
                    else:
                        shutil.move(p, target)
                    if not os.path.exists(target) or os.path.exists(p):
                        raise ToolError("انتقال کامل نشد.")
                    moves.append([p, target])
                else:
                    if sys.platform != "win32":
                        raise ToolError("حذف به سطل بازیافت فقط روی ویندوز ممکن است.")
                    _recycle(p)
                    if os.path.exists(p):
                        raise ToolError("فایل هنوز سر جایش است.")
                done.append(os.path.basename(p))
            except (ToolError, OSError, shutil.Error) as exc:
                failed.append(f"{os.path.basename(p)}: {exc}")
        journal_ok = True
        if moves:
            journal_ok = self.journal.add("move_many", moves=moves) and journal_ok
        if copies:
            journal_ok = self.journal.add("copy_many", paths=copies) and journal_ok
        text = f"{len(done)} مورد انجام شد، {len(failed)} مورد ناموفق." + self._journal_note(journal_ok)
        if failed:
            text += "\nناموفق‌ها:\n- " + "\n- ".join(failed[:10])
        if not done:
            raise ToolError(text)
        return text

    # ---------------------------------------------------------------- level 3: organise a folder
    def _organise_subfolder(self, folder: str, key: str) -> str:
        candidate = os.path.join(folder, key)
        checked = self.policy.check(candidate, must_exist=False)
        if os.path.normcase(checked) != os.path.normcase(candidate):
            raise ToolError("پوشه‌ی مقصد مرتب‌سازی یک لینک/مسیر غیرمستقیم است؛ برای جلوگیری از خروج فایل از مسیر مجاز رد شد.", DENIED)
        if os.path.lexists(candidate) and not os.path.isdir(candidate):
            raise ToolError(f"مقصد مرتب‌سازی پوشه نیست: {candidate}")
        return candidate

    def _plan_organise(self, folder: str, by: str):
        plan: dict[str, list] = {}
        for entry in os.scandir(folder):
            if not entry.is_file(follow_symlinks=False) or not self.policy.is_allowed(entry.path):
                continue
            if by == "date":
                key = time.strftime("%Y-%m", time.localtime(entry.stat().st_mtime))
            else:
                ext = os.path.splitext(entry.name)[1].lower()
                key = next((cat for cat, exts in CATEGORIES.items() if ext in exts), "Other")
            plan.setdefault(key, []).append(entry.name)
            if sum(len(v) for v in plan.values()) > ORGANISE_MAX:
                raise ToolError(f"بیش از {ORGANISE_MAX} فایل در این پوشه است؛ پوشه‌ی کوچک‌تری انتخاب کن.")
        for key in plan:
            self._organise_subfolder(folder, key)
        return plan

    def precheck_organise(self, a: dict) -> dict:
        folder = self.policy.check(a["folder"])
        if not os.path.isdir(folder):
            raise ToolError("این مسیر پوشه نیست.")
        by = a.get("by", "type")
        plan = self._plan_organise(folder, by)
        if not plan:
            raise ToolError("فایلی برای مرتب‌کردن در این پوشه (بدون زیرپوشه‌ها) نیست.")
        return {**a, "folder": folder, "by": by}

    def confirm_organise(self, a: dict) -> str:
        plan = self._plan_organise(a["folder"], a["by"])
        parts = "، ".join(f"{k}: {len(v)}" for k, v in sorted(plan.items()))
        return f"فایل‌های سطح اول «{a['folder']}» داخل زیرپوشه‌ها جابه‌جا می‌شوند ({parts}). هیچ فایلی رونویسی یا حذف نمی‌شود."

    def organise_folder(self, a: dict) -> str:
        a = self.precheck_organise(a)
        moved, skipped, moves = 0, 0, []
        for key, names in self._plan_organise(a["folder"], a["by"]).items():
            sub = self._organise_subfolder(a["folder"], key)
            if not os.path.lexists(sub):
                os.mkdir(sub)
            sub = self._organise_subfolder(a["folder"], key)
            for n in names:
                src, dst = os.path.join(a["folder"], n), os.path.join(sub, n)
                if os.path.lexists(dst):
                    skipped += 1
                    continue
                shutil.move(src, dst)
                if os.path.exists(dst) and not os.path.exists(src):
                    moved += 1
                    moves.append([src, dst])
                else:
                    skipped += 1
        journal_ok = self.journal.add("organise", moves=moves, path=a["folder"]) if moves else True
        if not moved:
            raise ToolError("هیچ فایلی جابه‌جا نشد.")
        return f"{moved} فایل مرتب شد" + (f"؛ {skipped} مورد رد شد (هم‌نام موجود بود)" if skipped else "") + f". پوشه: {a['folder']}" + self._journal_note(journal_ok)

    # ---------------------------------------------------------------- undo
    def _undo_target(self):
        item = self.journal.last()
        if item is None or time.time() - item.get("ts", 0) > UNDO_WINDOW:
            raise ToolError("عملیات اخیری برای برگرداندن (در یک ساعت گذشته) نیست.")
        return item

    def confirm_undo(self, a: dict) -> str:
        item = self._undo_target()
        what = {"mkdir": "پوشه‌ی ساخته‌شده خالی حذف می‌شود", "create": "فایل ساخته‌شده به سطل بازیافت می‌رود", "copy": "نسخه‌ی کپی‌شده به سطل بازیافت می‌رود",
                "rename": "نام به حالت قبل برمی‌گردد", "move": "فایل به جای قبلی برمی‌گردد", "append": "متن اضافه‌شده از انتها برداشته می‌شود",
                "write": "فایل از پشتیبان برمی‌گردد", "organise": "همه‌ی فایل‌های جابه‌جاشده به جای قبلی برمی‌گردند",
                "move_many": "همه‌ی مورد‌های منتقل‌شده به جای قبلی برمی‌گردند", "copy_many": "همه‌ی نسخه‌های کپی‌شده به سطل بازیافت می‌روند"}.get(item["op"], "برگردانده می‌شود")
        if item["op"] == "write" and item.get("created"):
            what = "فایل تازه‌ساخته‌شده به سطل بازیافت می‌رود"
        return f"آخرین عملیات ({item['op']}: {item.get('path')}): {what}."

    def undo_last(self, a: dict) -> str:
        item = self._undo_target()
        op, path = item["op"], item.get("path", "")
        if op in ("create", "copy"):
            real = self.policy.check(path)
            if sys.platform != "win32":
                raise ToolError("انتقال به سطل بازیافت فقط روی ویندوز ممکن است.")
            _recycle(real)
            if os.path.exists(real):
                raise ToolError("برگرداندن انجام نشد.")
        elif op in ("organise", "move_many"):
            back_ok = 0
            for src, dst in item["moves"]:
                try:
                    back = self.policy.check(src, must_exist=False)
                    if os.path.exists(dst) and not os.path.lexists(back):
                        shutil.move(self.policy.check(dst), back)
                        back_ok += 1
                except (ToolError, OSError, shutil.Error):
                    continue
            if not back_ok:
                raise ToolError("هیچ موردی برنگشت (جای قبلی‌ها پر است یا فایل‌ها جابه‌جا شده‌اند).")
            persisted = self.journal.mark_undone(item)
            return f"{back_ok} از {len(item['moves'])} مورد به جای قبلی برگشت." + self._journal_undo_note(persisted)
        elif op == "copy_many":
            if sys.platform != "win32":
                raise ToolError("انتقال به سطل بازیافت فقط روی ویندوز ممکن است.")
            gone = 0
            for p in item["paths"]:
                try:
                    real = self.policy.check(p)
                    _recycle(real)
                    gone += 0 if os.path.exists(real) else 1
                except (ToolError, OSError):
                    continue
            if not gone:
                raise ToolError("هیچ نسخه‌ای برداشته نشد.")
            persisted = self.journal.mark_undone(item)
            return f"{gone} نسخه‌ی کپی‌شده به سطل بازیافت رفت." + self._journal_undo_note(persisted)
        elif op == "mkdir":
            real = self.policy.check(path)
            os.rmdir(real)                                               # only an empty folder can go
        elif op in ("rename", "move"):
            real, src = self.policy.check(path), item["source"]
            back = self.policy.check(src, must_exist=False)
            if os.path.lexists(back):
                raise ToolError("جای قبلی الان پر است؛ برنگرداندم.")
            shutil.move(real, back)
        elif op == "append":
            real = self.policy.check(path)
            size_before = item["size_before"]
            expected_size = item.get("size_after")
            expected_digest = item.get("sha256_after")
            with open(real, "r+b") as fh:
                if expected_size is not None and fh.seek(0, os.SEEK_END) != expected_size:
                    raise ToolError("فایل بعد از عملیات append تغییر کرده؛ برنگرداندم.")
                if expected_digest:
                    fh.seek(0)
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        digest.update(chunk)
                    if digest.hexdigest() != expected_digest:
                        raise ToolError("محتوای فایل بعد از عملیات append تغییر کرده؛ برنگرداندم.")
                elif fh.seek(0, os.SEEK_END) < size_before:
                    raise ToolError("فایل بعد از آن تغییر کرده؛ برنگرداندم.")
                fh.truncate(size_before)
        elif op == "write":
            real = self.policy.check(path, must_exist=False)
            if item.get("created"):
                if not os.path.isfile(real):
                    raise ToolError("فایل ساخته‌شده دیگر وجود ندارد؛ چیزی برای برگرداندن نیست.")
                expected_digest = item.get("written_sha256")
                expected_size = item.get("written_size")
                if expected_digest:
                    if expected_size is not None and os.path.getsize(real) != expected_size:
                        raise ToolError("فایل بعد از write تغییر کرده؛ برای جلوگیری از حذف تغییرات جدید برنگرداندم.")
                    digest = hashlib.sha256()
                    with open(real, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected_digest:
                        raise ToolError("محتوای فایل بعد از write تغییر کرده؛ برنگرداندم.")
                if sys.platform != "win32":
                    raise ToolError("انتقال فایل به سطل بازیافت فقط روی ویندوز ممکن است.")
                _recycle(real)
                if os.path.exists(real):
                    raise ToolError("فایل ساخته‌شده به سطل بازیافت منتقل نشد.")
            else:
                backup_path = item.get("backup")
                if not backup_path:
                    raise ToolError("پشتیبانی برای برگرداندن نیست.")
                # The journal is local data and can be edited or corrupted. Never
                # let an undo record copy an arbitrary file into an allowed target.
                backup = self.policy.check(backup_path)
                expected_name = os.path.basename(real) + ".bak-"
                if (os.path.dirname(os.path.normcase(backup)) != os.path.dirname(os.path.normcase(real))
                        or not os.path.basename(backup).startswith(expected_name)
                        or not os.path.isfile(backup)
                        or (os.path.exists(real) and os.path.samefile(backup, real))):
                    raise ToolError("پشتیبان معتبر و مستقل برای برگرداندن پیدا نشد.")
                expected_digest = item.get("written_sha256")
                expected_size = item.get("written_size")
                if os.path.exists(real) and expected_digest:
                    if expected_size is not None and os.path.getsize(real) != expected_size:
                        raise ToolError("فایل بعد از write تغییر کرده؛ برای جلوگیری از حذف تغییرات جدید برنگرداندم.")
                    digest = hashlib.sha256()
                    with open(real, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected_digest:
                        raise ToolError("محتوای فایل بعد از write تغییر کرده؛ برنگرداندم.")
                shutil.copy2(backup, real)
        else:
            raise ToolError("این نوع عملیات قابل برگرداندن نیست.")
        persisted = self.journal.mark_undone(item)
        return f"برگردانده شد ({op}): {path}" + self._journal_undo_note(persisted)


def register_file_agent(reg, policy: PathPolicy, data_dir=None) -> FileAgent:
    fa = FileAgent(policy, Journal(data_dir or getattr(policy, "data_dir", None)))
    write_intent = WRITE_INTENT
    reg.register(Tool("make_folder", "create ONE new folder (full path of the new folder; never overwrites)", fa.make_folder,
                      (Param("path", "string", "full path of the new folder", True),), ACTION, ("files",), intent_rx=write_intent,
                      memo=lambda a, t: f"make_folder → {a.get('path')}"))
    reg.register(Tool("create_file", "create ONE new text file (txt, md, csv, json ...) with content; refuses an existing name and script/exe extensions", fa.create_file,
                      (Param("path", "string", "full path of the new file", True), Param("content", "string", "text to put in it (max 200 KB)")),
                      ACTION, ("files",), intent_rx=write_intent, memo=lambda a, t: f"create_file → {a.get('path')}"))
    reg.register(Tool("append_text", "add text at the END of an existing plain text file", fa.append_text,
                      (Param("path", "string", "full path of a text file", True), Param("content", "string", "text to add", True)),
                      ACTION, ("files",), intent_rx=write_intent))
    reg.register(Tool("copy_item", "copy a file or a folder into another allowed folder (never overwrites; optional new_name)", fa.copy_item,
                      (Param("source", "string", "full path of the file/folder", True), Param("destination_folder", "string", "existing destination folder", True),
                       Param("new_name", "string", "optional name for the copy")),
                      ACTION, ("files",), intent_rx=write_intent, memo=lambda a, t: f"copy_item → {a.get('source')}"))
    reg.register(Tool("rename_item", "rename ONE file or folder (same folder; never overwrites)", fa.rename_item,
                      (Param("path", "string", "full path", True), Param("new_name", "string", "new name only, not a path", True)),
                      ACTION, ("files",), intent_rx=write_intent))
    reg.register(Tool("write_file", "replace the whole content of a text file (a backup copy is kept) or create it", fa.write_file,
                      (Param("path", "string", "full path", True), Param("content", "string", "the new full text", True)),
                      SENSITIVE, ("files",), confirm_summary=fa.confirm_write, precheck=fa.precheck_write))
    reg.register(Tool("delete_folder", "move ONE folder with its content to the Windows Recycle Bin (recoverable)", fa.delete_folder,
                      (Param("path", "string", "full folder path", True),), SENSITIVE, ("files",),
                      confirm_summary=fa.confirm_delete_folder, precheck=fa.precheck_delete_folder))
    reg.register(Tool("batch_files", "copy / move / delete SEVERAL files at once (paths = list of full paths, max 50)", fa.batch_files,
                      (Param("operation", "string", "copy | move | delete", True, None, ("copy", "move", "delete")),
                       Param("paths", "array", "list of full paths", True), Param("destination_folder", "string", "for copy / move")),
                      SENSITIVE, ("files",), confirm_summary=fa.confirm_batch, precheck=fa.precheck_batch))
    reg.register(Tool("organise_folder", "sort the top-level files of a folder into sub-folders by type (Images, Documents ...) or by month", fa.organise_folder,
                      (Param("folder", "string", "full folder path", True), Param("by", "string", "type (default) | date", False, "type", ("type", "date"))),
                      SENSITIVE, ("files",), confirm_summary=fa.confirm_organise, precheck=fa.precheck_organise))
    reg.register(Tool("undo_file_operation", "undo the latest reversible file operation of the last hour (create / copy / rename / move / append / write)", fa.undo_last,
                      (), SENSITIVE, ("files",), confirm_summary=fa.confirm_undo, precheck=lambda a: (fa._undo_target(), a)[1]))
    return fa
