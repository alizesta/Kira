"""File tools: search, list, info, read (read-only) and delete / move (sensitive, always confirmed first).

All of them go through PathPolicy: only the allowed folders, never secrets, never Kira's own data.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import datetime, timedelta

from .access import PathPolicy
from .registry import ToolError, DENIED

SEARCH_TIME_LIMIT = 8.0                 # seconds: a search never blocks Kira for long (it says so when it stops early)
SEARCH_SCAN_LIMIT = 40000               # entries looked at
SEARCH_DEPTH = 10
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py", ".java", ".c",
            ".cpp", ".h", ".cs", ".go", ".rs", ".php", ".sql", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml", ".log", ".bat", ".ps1",
            ".srt", ".vtt", ".tex", ".rtf", ".gcode", ".nc", ".tap", ".mpf", ".spf", ".cnc"}
DOC_EXT = {".docx", ".pdf"}
MAX_READ_BYTES = 10 * 1024 * 1024
READ_DEFAULT, READ_MAX = 6000, 12000


def _fa(text: str) -> str:
    """Search-friendly form: Arabic yeh/kaf -> Persian, no ZWNJ, lower case."""
    return (str(text or "").lower().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").replace("\u200f", " ")).strip()


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _day_range(value: str):
    """'today' | 'yesterday' | 'YYYY-MM-DD' -> (start_ts, end_ts) of that local calendar day."""
    v = _fa(value)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if v in ("today", "امروز"):
        day = today
    elif v in ("yesterday", "دیروز"):
        day = today - timedelta(days=1)
    else:
        try:
            day = datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise ToolError("تاریخ باید today، yesterday یا به شکل YYYY-MM-DD باشد.") from exc
    return day.timestamp(), (day + timedelta(days=1)).timestamp()


class FileTools:
    def __init__(self, policy: PathPolicy):
        self.policy = policy

    # ------------------------------------------------------------ search
    def search_files(self, a: dict) -> str:
        query = _fa(a.get("query", ""))
        words = [w for w in query.split() if w]
        ext = str(a.get("extension") or "").strip().lower().lstrip("*").lstrip(".")
        limit = max(1, min(int(a.get("max_results") or 15), 40))
        day = _day_range(a["date"]) if a.get("date") else None
        within = float(a["within_days"]) * 86400 if a.get("within_days") else None
        if not words and not ext and not day and not within:
            raise ToolError("حداقل یکی از query، extension، date یا within_days لازم است.", "bad_args")
        if a.get("folder"):
            roots = [self.policy.check(a["folder"])]
            if not os.path.isdir(roots[0]):
                raise ToolError("folder باید یک پوشه باشد.")
        else:
            roots = [r for r in self.policy.root_labels() if os.path.isdir(r)]
        if not roots:
            raise ToolError("هیچ پوشه‌ی مجازی برای جست‌وجو پیدا نشد.")
        started, scanned, hidden, scan_errors, stopped_early = time.monotonic(), 0, 0, 0, None
        now, hits, seen_dirs = time.time(), [], set()

        def match(entry_name: str, st) -> bool:
            low = _fa(entry_name)
            if ext and not low.endswith("." + ext):
                return False
            if words and not all(w in low for w in words):
                return False
            if day and not (day[0] <= st.st_mtime < day[1] or day[0] <= getattr(st, "st_ctime", 0) < day[1]):
                return False
            if within and now - max(st.st_mtime, getattr(st, "st_ctime", 0)) > within:
                return False
            return True

        stack = [(r, 0) for r in reversed(roots)]
        while stack and stopped_early is None:
            folder, depth = stack.pop()
            real = os.path.normcase(os.path.realpath(folder))
            if real in seen_dirs:
                continue
            seen_dirs.add(real)
            try:
                it = os.scandir(folder)
            except OSError:
                scan_errors += 1
                continue
            try:
                with it:
                    for entry in it:
                        scanned += 1
                        if scanned > SEARCH_SCAN_LIMIT:
                            stopped_early = "تعداد موارد بررسی‌شده به سقف رسید"
                            break
                        if time.monotonic() - started > SEARCH_TIME_LIMIT:
                            stopped_early = "زمان جست‌وجو تمام شد"
                            break
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            if not self.policy.is_allowed(entry.path):
                                if self.policy.sensitive_name(entry.path):
                                    hidden += 1
                                continue
                            if is_dir:
                                if depth < SEARCH_DEPTH:
                                    stack.append((entry.path, depth + 1))
                                continue
                            st = entry.stat(follow_symlinks=False)
                        except OSError:
                            scan_errors += 1
                            continue
                        if match(entry.name, st):
                            hits.append((st.st_mtime, entry.path, st.st_size))
            except OSError:
                # scandir can fail while advancing the iterator, not only at open.
                scan_errors += 1
        hits.sort(reverse=True)
        lines = [f"{len(hits)} فایل پیدا شد" + (f" (بیشتر از {limit} مورد؛ {limit} تای جدیدتر نشان داده می‌شود)" if len(hits) > limit else "")
                 + f" · {scanned} مورد بررسی شد."]
        for i, (mt, path, size) in enumerate(hits[:limit], 1):
            lines.append(f"{i}. {path} — {_fmt_size(size)} — تغییر: {_fmt_time(mt)}")
        if not hits:
            lines[0] = f"فایلی با این مشخصات پیدا نشد ({scanned} مورد در پوشه‌های مجاز بررسی شد)."
        if stopped_early:
            lines.append(f"توجه: جست‌وجو ناقص ماند ({stopped_early}). ممکن است فایل‌های بیشتری وجود داشته باشند؛ با folder مشخص‌تر دوباره بگرد.")
        if scan_errors:
            lines.append(
                f"توجه: دسترسی یا خواندن {scan_errors} پوشه/مورد ناموفق بود؛ نتایج ممکن است ناقص باشند."
            )
        if hidden:
            lines.append(f"{hidden} مورد با نام شبیه اطلاعات محرمانه عمداً نشان داده نشد.")
        lines.append("پوشه‌های جست‌وجوشده: " + "؛ ".join(roots))
        return "\n".join(lines)

    # ------------------------------------------------------------ list / info
    def list_folder(self, a: dict) -> str:
        path = self.policy.check(a["path"])
        if not os.path.isdir(path):
            raise ToolError("این مسیر پوشه نیست.")
        limit = max(1, min(int(a.get("max_items") or 40), 100))
        dirs, files, hidden, scan_errors = [], [], 0, 0
        try:
            for entry in os.scandir(path):
                try:
                    allowed = self.policy.is_allowed(entry.path)
                except OSError:
                    scan_errors += 1
                    continue
                if not allowed:
                    hidden += 1
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    scan_errors += 1
                    continue
                (dirs if is_dir else files).append((entry.name, st))
        except OSError:
            # scandir may fail to open the directory or while advancing its iterator.
            scan_errors += 1
        dirs.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[1].st_mtime, reverse=True)
        lines = [f"{path} — {len(dirs)} پوشه و {len(files)} فایل"]
        shown = 0
        for name, st in dirs:
            if shown >= limit:
                break
            lines.append(f"[پوشه] {name}")
            shown += 1
        for name, st in files:
            if shown >= limit:
                break
            lines.append(f"{name} — {_fmt_size(st.st_size)} — {_fmt_time(st.st_mtime)}")
            shown += 1
        if len(dirs) + len(files) > shown:
            lines.append(f"... {len(dirs) + len(files) - shown} مورد دیگر نشان داده نشد.")
        if hidden:
            lines.append(f"{hidden} مورد حساس/غیرمجاز پنهان شد.")
        if scan_errors:
            lines.append(
                f"توجه: خواندن اطلاعات {scan_errors} مورد ناموفق بود؛ فهرست ممکن است ناقص باشد."
            )
        return "\n".join(lines)

    def file_info(self, a: dict) -> str:
        path = self.policy.check(a["path"])
        st = os.stat(path)
        if os.path.isdir(path):
            try:
                count = sum(1 for _ in os.scandir(path))
            except OSError:
                count = None
            return "\n".join([f"پوشه: {path}", f"تعداد موارد مستقیم داخلش: {count if count is not None else 'نامشخص'}",
                              f"آخرین تغییر: {_fmt_time(st.st_mtime)}", f"ساخت: {_fmt_time(st.st_ctime)}"])
        ext = os.path.splitext(path)[1].lower()
        readable = ext in TEXT_EXT or ext in DOC_EXT or ext == ""
        return "\n".join([f"فایل: {path}", f"حجم: {_fmt_size(st.st_size)} ({st.st_size} بایت)", f"پسوند: {ext or 'ندارد'}",
                          f"آخرین تغییر: {_fmt_time(st.st_mtime)}", f"ساخت: {_fmt_time(st.st_ctime)}",
                          "قابل خواندن با read_file: " + ("بله" if readable and st.st_size <= MAX_READ_BYTES else "خیر (نوع پشتیبانی‌نشده یا بزرگ)")])

    # ------------------------------------------------------------ read
    def read_file(self, a: dict) -> str:
        from .. import attachments as att
        path = self.policy.check(a["path"])
        if os.path.isdir(path):
            raise ToolError("این یک پوشه است؛ برای دیدن محتویاتش list_folder را بزن.")
        size = os.path.getsize(path)
        if size > MAX_READ_BYTES:
            raise ToolError(f"فایل بزرگ است ({_fmt_size(size)}؛ سقف {MAX_READ_BYTES // (1024 * 1024)} MB).")
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".docx":
                text = att._docx_text(path)
            elif ext == ".pdf":
                text = att._pdf_text(path)
            elif ext in TEXT_EXT or ext == "":
                with open(path, "rb") as fh:
                    text = att._decode_text(fh.read())
            else:
                raise ToolError(f"خواندن فایل‌های «{ext}» پشتیبانی نمی‌شود. پشتیبانی‌شده: متن/کد/CSV/JSON و… ، DOCX، PDF.")
        except att.AttachmentError as exc:
            raise ToolError(str(exc)) from exc
        text = text.replace("\r\n", "\n").strip()
        if not text:
            raise ToolError("در این فایل متنی پیدا نشد (شاید PDF اسکن‌شده/تصویری است).")
        start = max(0, int(a.get("start") or 0))
        limit = max(500, min(int(a.get("max_chars") or READ_DEFAULT), READ_MAX))
        chunk = text[start:start + limit]
        head = f"فایل: {path} — {len(text)} نویسه" + (f" — نمایش از نویسه‌ی {start}" if start else "")
        tail = f"\n[ادامه دارد: برای بخش بعد start={start + limit} را بده]" if start + limit < len(text) else "\n[پایان فایل]"
        return head + "\n---\n" + chunk + tail

    # ------------------------------------------------------------ sensitive: delete / move
    def precheck_delete(self, a: dict) -> dict:
        path = self.policy.check(a["path"])
        if os.path.isdir(path):
            raise ToolError("در این نسخه فقط حذف فایل ممکن است، نه پوشه.", DENIED)
        return {**a, "path": path}

    def confirm_delete(self, a: dict) -> str:
        return f"فایل «{a['path']}» به سطل بازیافت ویندوز منتقل می‌شود (قابل برگرداندن است)."

    def delete_file(self, a: dict) -> str:
        path = self.policy.check(a["path"])
        if os.path.isdir(path):
            raise ToolError("در این نسخه فقط حذف فایل ممکن است، نه پوشه.", DENIED)
        if sys.platform != "win32":
            raise ToolError("انتقال به سطل بازیافت فقط روی ویندوز ممکن است؛ حذف انجام نشد.")
        _recycle(path)
        if os.path.exists(path):
            raise ToolError("ویندوز فایل را به سطل بازیافت نبرد؛ فایل هنوز سر جایش است.")
        return f"فایل به سطل بازیافت منتقل شد: {path}"

    def precheck_move(self, a: dict) -> dict:
        src = self.policy.check(a["source"])
        dest = self.policy.check(a["destination_folder"])
        if not os.path.isdir(dest):
            raise ToolError("destination_folder باید یک پوشه‌ی موجود باشد.")
        target = os.path.join(dest, os.path.basename(src))
        if os.path.exists(target):
            raise ToolError(f"در مقصد از قبل مورد هم‌نامی وجود دارد و رونویسی نمی‌شود: {target}")
        return {**a, "source": src, "destination_folder": dest}

    def confirm_move(self, a: dict) -> str:
        return f"«{a['source']}» به پوشه‌ی «{a['destination_folder']}» منتقل می‌شود."

    def move_file(self, a: dict) -> str:
        a = self.precheck_move(a)
        target = os.path.join(a["destination_folder"], os.path.basename(a["source"]))
        shutil.move(a["source"], target)
        if not os.path.exists(target):
            raise ToolError("انتقال انجام نشد (فایل در مقصد دیده نشد).")
        return f"منتقل شد: {a['source']} ← {target}"


def _recycle(path: str):
    """Send one file to the Windows Recycle Bin (never a permanent delete)."""
    import ctypes
    from ctypes import wintypes

    fields = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
              ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
              ("lpszProgressTitle", wintypes.LPCWSTR)]
    attrs = {"_fields_": fields}
    if ctypes.sizeof(ctypes.c_void_p) == 4:                   # the structure is packed only in 32-bit processes
        attrs["_pack_"] = 1
    SHFILEOPSTRUCTW = type("SHFILEOPSTRUCTW", (ctypes.Structure,), attrs)

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"                   # the API wants a double-null-terminated list
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        raise ToolError(f"انتقال به سطل بازیافت ناموفق بود (کد {code}).")
