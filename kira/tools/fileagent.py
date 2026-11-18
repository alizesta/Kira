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

import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .access import PathPolicy, EXECUTABLE_EXT
from .fileops import TEXT_EXT, _fmt_size, _recycle
from .registry import Tool, Param, ToolError, ACTION, SENSITIVE, DENIED

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
    def __init__(self, data_dir):
        self.path = Path(data_dir) / JOURNAL_NAME if data_dir else None
        self.items: list[dict] = []
        if self.path is not None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.items = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
            except (OSError, ValueError):
                pass

    def _save(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items[-JOURNAL_KEEP:], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def add(self, op: str, **fields):
        self.items.append({"op": op, "ts": time.time(), **fields})
        self.items = self.items[-JOURNAL_KEEP:]
        self._save()

    def last(self):
        for item in reversed(self.items):
            if not item.get("undone"):
                return item
        return None

    def mark_undone(self, item):
        item["undone"] = True
        self._save()


def _count_tree(root: str):
    files = size = skipped = 0
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(base, d))]
        for n in names:
            p = os.path.join(base, n)
            if os.path.islink(p):
                skipped += 1
                continue
            files += 1
            try:
                size += os.path.getsize(p)
            except OSError:
                skipped += 1
    return files, size, skipped


class FileAgent:
    def __init__(self, policy: PathPolicy, journal: Journal):
        self.policy, self.journal = policy, journal

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
        self.journal.add("mkdir", path=target)
        return f"پوشه ساخته شد: {target}"

    def create_file(self, a: dict) -> str:
        parent, name = self._parent_and_name(a["path"])
        target = self._new_target(parent, name)
        content = str(a.get("content") or "")
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise ToolError("متن خیلی بزرگ است (حداکثر ۲۰۰ کیلوبایت در یک بار).")
        with open(target, "xb") as fh:                                   # "x": fails instead of overwriting, even in a race
            fh.write(data)
        if not os.path.isfile(target) or os.path.getsize(target) != len(data):
            raise ToolError("فایل ساخته نشد یا اندازه‌اش درست نیست.")
        self.journal.add("create", path=target)
        return f"فایل ساخته شد: {target} ({_fmt_size(len(data))})"

    def append_text(self, a: dict) -> str:
        path = self.policy.check(a["path"])
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in TEXT_EXT or os.path.splitext(path)[1].lower() in EXECUTABLE_EXT:
            raise ToolError("افزودن متن فقط برای فایل متنی ساده (txt, md, csv, json, log ...) ممکن است. برای Word بعداً ابزار جدا هست.")
        if os.path.getsize(path) > MAX_APPEND_TARGET:
            raise ToolError("فایل خیلی بزرگ است.")
        data = str(a.get("content") or "").encode("utf-8")
        if not data or len(data) > MAX_TEXT_BYTES:
            raise ToolError("متن خالی است یا بیش از ۲۰۰ کیلوبایت است.")
        before = os.path.getsize(path)
        if before:
            with open(path, "rb") as fh:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) not in (b"\n", b"\r"):
                    data = b"\n" + data                                   # a new paragraph starts on its own line (tool arguments are stripped)
        with open(path, "ab") as fh:
            fh.write(data)
        if os.path.getsize(path) != before + len(data):
            raise ToolError("اندازه‌ی فایل بعد از نوشتن درست نیست.")
        self.journal.add("append", path=path, size_before=before)
        return f"{_fmt_size(len(data))} به انتهای فایل اضافه شد: {path}"

    def copy_item(self, a: dict) -> str:
        src, target, note = self._copy(a)
        self.journal.add("copy", source=src, path=target)
        return f"کپی شد: {src} ← {target}{note}"

    def _copy(self, a: dict):
        src = self.policy.check(a["source"])
        name = a.get("new_name") or os.path.basename(src)
        target = self._new_target(a["destination_folder"], name, allow_exec=not a.get("new_name"))
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
                    if os.path.islink(p) or self.policy.sensitive_name(p):
                        out.append(n)
                        skipped.append(n)
                return out
            shutil.copytree(src, target, symlinks=False, ignore=ignore)
            note = f" ({len(skipped)} مورد حساس/لینک رد شد)" if skipped else ""
        else:
            shutil.copy2(src, target)
            note = ""
            if os.path.getsize(target) != os.path.getsize(src):
                raise ToolError("اندازه‌ی نسخه‌ی کپی‌شده با اصل برابر نیست.")
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
        self.journal.add("rename", source=src, path=target)
        return f"نام تغییر کرد: {os.path.basename(src)} ← {os.path.basename(target)} (در {os.path.dirname(target)})"

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
        if os.path.exists(path):
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
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        if not os.path.isfile(path) or os.path.getsize(path) != len(data):
            raise ToolError("اندازه‌ی فایل بعد از نوشتن درست نیست.")
        self.journal.add("write", path=path, backup=backup)
        return f"فایل نوشته شد: {path}" + (f" (پشتیبان: {backup})" if backup else "")

    def precheck_delete_folder(self, a: dict) -> dict:
        path = self.policy.check(a["path"])
        if not os.path.isdir(path):
            raise ToolError("این مسیر پوشه نیست. برای فایل از delete_file استفاده کن.")
        if os.path.normcase(path) in {os.path.normcase(r) for r in self.policy.roots()}:
            raise ToolError("خود پوشه‌های اصلی (Desktop, Documents ...) حذف نمی‌شوند.", DENIED)
        return {**a, "path": path}

    def confirm_delete_folder(self, a: dict) -> str:
        files, size, _ = _count_tree(a["path"])
        return f"پوشه‌ی «{a['path']}» با {files} فایل ({_fmt_size(size)}) به سطل بازیافت ویندوز منتقل می‌شود (قابل برگرداندن است)."

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
                if os.path.isdir(p) and (dest == p or dest.startswith(p + os.sep)):
                    raise ToolError("پوشه را نمی‌شود داخل خودش برد/کپی کرد.")
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
        if moves:
            self.journal.add("move_many", moves=moves)
        if copies:
            self.journal.add("copy_many", paths=copies)
        text = f"{len(done)} مورد انجام شد، {len(failed)} مورد ناموفق."
        if failed:
            text += "\nناموفق‌ها:\n- " + "\n- ".join(failed[:10])
        if not done:
            raise ToolError(text)
        return text

    # ---------------------------------------------------------------- level 3: organise a folder
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
            sub = os.path.join(a["folder"], key)
            if os.path.exists(sub) and not os.path.isdir(sub):
                skipped += len(names)
                continue
            os.makedirs(sub, exist_ok=True)
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
        if moves:
            self.journal.add("organise", moves=moves, path=a["folder"])
        if not moved:
            raise ToolError("هیچ فایلی جابه‌جا نشد.")
        return f"{moved} فایل مرتب شد" + (f"؛ {skipped} مورد رد شد (هم‌نام موجود بود)" if skipped else "") + f". پوشه: {a['folder']}"

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
            self.journal.mark_undone(item)
            return f"{back_ok} از {len(item['moves'])} مورد به جای قبلی برگشت."
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
            self.journal.mark_undone(item)
            return f"{gone} نسخه‌ی کپی‌شده به سطل بازیافت رفت."
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
            if os.path.getsize(real) < item["size_before"]:
                raise ToolError("فایل بعد از آن تغییر کرده؛ برنگرداندم.")
            with open(real, "r+b") as fh:
                fh.truncate(item["size_before"])
        elif op == "write":
            real = self.policy.check(path, must_exist=False)
            if not item.get("backup") or not os.path.exists(item["backup"]):
                raise ToolError("پشتیبانی برای برگرداندن نیست.")
            shutil.copy2(item["backup"], real)
        else:
            raise ToolError("این نوع عملیات قابل برگرداندن نیست.")
        self.journal.mark_undone(item)
        return f"برگردانده شد ({op}): {path}"


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
