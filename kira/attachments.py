"""Chat attachments: images (sent to vision models) and text-like files (their text is added to the message).

Pure helpers - no UI. Images are downscaled with Qt when it is available (falls back to the raw bytes), documents are read
with the standard library (.docx) or pypdf when installed (.pdf). Nothing here touches the network.
"""
from __future__ import annotations

import base64
import os
import zipfile
from xml.etree import ElementTree

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".bmp": "image/bmp"}
MAX_FILES = 5
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 200
MAX_ARCHIVE_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_UNPACKED_BYTES = 40 * 1024 * 1024
MAX_IMAGE_SIDE = 1568                  # larger images are shrunk: vision models downscale anyway and big payloads get rejected
MAX_TEXT_CHARS = 30000                 # text sent to the model for one file
HISTORY_EXCERPT = 3000                 # part of a file kept in the saved chat so Kira can still refer to it later


class AttachmentError(ValueError):
    """Message is Persian and safe to show to the user."""


def _decode_text(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:4096]:
        raise AttachmentError("این نوع فایل متنی نیست و پشتیبانی نمی‌شود.")
    for enc in ("utf-8-sig", "cp1256"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _read_file(path: str, progress=None, cancelled=None) -> bytes:
    """Read a whole file in blocks and report 0-100 while doing it."""
    total = max(1, os.path.getsize(path))
    chunks, done = [], 0
    with open(path, "rb") as fh:
        while True:
            if cancelled and cancelled():
                raise AttachmentError("بارگذاری فایل لغو شد.")
            block = fh.read(256 * 1024)
            if not block:
                break
            chunks.append(block)
            done += len(block)
            if progress:
                progress(min(99, int(done * 100 / total)))
    return b"".join(chunks)



_ARCHIVE_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".json", ".jsonl", ".csv", ".tsv", ".log", ".py", ".pyi",
    ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".scss", ".xml", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".bat", ".cmd", ".ps1", ".sh", ".sql",
    ".java", ".kt", ".kts", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".php",
    ".rb", ".swift", ".dart", ".vue", ".svelte", ".gradle", ".properties",
}


def _zip_text(path: str, progress=None, cancelled=None) -> str:
    """Read a ZIP without extracting it; reject zip bombs and include only bounded text files."""
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise AttachmentError("فایل ZIP خراب است یا باز نمی‌شود.") from exc
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        visible = infos[:MAX_ARCHIVE_ENTRIES]
        omitted = max(0, len(infos) - len(visible))
        unpacked = sum(max(0, info.file_size) for info in infos)
        if unpacked > MAX_ARCHIVE_UNPACKED_BYTES:
            raise AttachmentError("حجم بازشده‌ی فایل ZIP بیش از سقف امن ۴۰ مگابایت است.")
        lines = ["فهرست فایل ZIP:"]
        total_chars = MAX_TEXT_CHARS
        remaining_unpacked = MAX_ARCHIVE_UNPACKED_BYTES
        for index, info in enumerate(visible):
            if cancelled and cancelled():
                raise AttachmentError("بارگذاری فایل لغو شد.")
            name = info.filename.replace("\\", "/")
            if info.flag_bits & 0x1:
                lines.append(f"[رمزگذاری‌شده، خوانده نشد] {name}")
                continue
            if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                lines.append(f"[بزرگ‌تر از ۲ مگابایت، محتوا خوانده نشد] {name}")
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in _ARCHIVE_TEXT_EXTENSIONS:
                lines.append(f"[فایل غیرمتنی، فقط نام ثبت شد] {name}")
                continue
            read_limit = min(MAX_ARCHIVE_MEMBER_BYTES, remaining_unpacked)
            if info.file_size > read_limit:
                lines.append(f"[از سقف امن محتوای ZIP بیشتر بود] {name}")
                continue
            try:
                with archive.open(info, "r") as member:
                    data = member.read(read_limit + 1)
                if len(data) > read_limit:
                    raise AttachmentError("محتوای ZIP از سقف امن بیشتر است.")
                remaining_unpacked -= len(data)
                body = _decode_text(data).strip()
            except (AttachmentError, OSError, RuntimeError, zipfile.BadZipFile):
                lines.append(f"[محتوا خوانده نشد] {name}")
                continue
            if not body:
                lines.append(f"[فایل خالی] {name}")
                continue
            if total_chars <= 0:
                lines.append("[بقیه‌ی محتوا به‌دلیل محدودیت حجم ارسال نشد.]")
                break
            body = body[:total_chars]
            lines.extend([f"--- {name} ---", body])
            total_chars -= len(body)
            if progress:
                progress(min(99, int((index + 1) * 100 / max(1, len(visible)))))
        if omitted:
            lines.append(f"[{omitted} فایل دیگر در فهرست کوتاه شد.]")
        if progress:
            progress(100)
        return "\n".join(lines)

def _docx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise AttachmentError("فایل Word خوانده نشد.") from exc
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for p in root.iter(ns + "p"):
        paragraphs.append("".join(t.text or "" for t in p.iter(ns + "t")))
    return "\n".join(paragraphs)


def _pdf_text(path: str, progress=None, cancelled=None) -> str:
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
    except ImportError as exc:
        raise AttachmentError("برای خواندن PDF باید بسته‌ی pypdf نصب شود (pip install pypdf).") from exc
    try:
        reader = PdfReader(path)
        pages, out = list(reader.pages), []
        for i, page in enumerate(pages, 1):
            if cancelled and cancelled():
                raise AttachmentError("بارگذاری فایل لغو شد.")
            out.append(page.extract_text() or "")
            if progress:
                progress(min(99, int(i * 100 / max(1, len(pages)))))
        return "\n\n".join(out)
    except Exception as exc:                                  # noqa: BLE001 - corrupt / encrypted file
        raise AttachmentError("فایل PDF خوانده نشد (خراب یا قفل‌دار).") from exc


def _prepare_image(data: bytes, mime: str):
    """(bytes, mime) shrunk to MAX_IMAGE_SIDE when Qt is available; GIF/anything unreadable is returned unchanged."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage
    except ImportError:
        return data, mime
    image = QImage.fromData(data)
    if image.isNull():
        return data, mime
    if max(image.width(), image.height()) <= MAX_IMAGE_SIDE and len(data) < 4 * 1024 * 1024 and mime != "image/bmp":
        return data, mime
    if max(image.width(), image.height()) > MAX_IMAGE_SIDE:
        image = image.scaled(MAX_IMAGE_SIDE, MAX_IMAGE_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    fmt, out_mime = ("PNG", "image/png") if image.hasAlphaChannel() else ("JPEG", "image/jpeg")
    buf = QByteArray()
    stream = QBuffer(buf)
    stream.open(QIODevice.WriteOnly)
    image.save(stream, fmt, 90)
    return bytes(buf), out_mime


def image_attachment(data: bytes, name: str, mime: str = "image/png") -> dict:
    if len(data) > MAX_IMAGE_BYTES:
        raise AttachmentError(f"تصویر «{name}» بزرگ‌تر از {MAX_IMAGE_BYTES // (1024 * 1024)} مگابایت است.")
    data, mime = _prepare_image(data, mime)
    return {"name": name, "kind": "image", "mime": mime, "b64": base64.b64encode(data).decode("ascii"), "size": len(data)}


def load_attachment(path: str, progress=None, cancelled=None) -> dict:
    """Read one file -> {'name','kind':'image'|'text', ...}. Raises AttachmentError with a Persian message.
    progress(percent) is called while the file is being read / parsed."""
    progress = progress or (lambda pct: None)
    path = str(path)
    name = os.path.basename(path) or path
    ext = os.path.splitext(name)[1].lower()
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise AttachmentError(f"فایل «{name}» خوانده نشد.") from exc
    if ext in IMAGE_TYPES:
        if size > MAX_IMAGE_BYTES:
            raise AttachmentError(f"تصویر «{name}» بزرگ‌تر از {MAX_IMAGE_BYTES // (1024 * 1024)} مگابایت است.")
        if cancelled and cancelled():
            raise AttachmentError("بارگذاری فایل لغو شد.")
        result = image_attachment(_read_file(path, progress, cancelled), name, IMAGE_TYPES[ext])
        progress(100)
        return result
    if size > MAX_FILE_BYTES:
        raise AttachmentError(f"فایل «{name}» بزرگ‌تر از {MAX_FILE_BYTES // (1024 * 1024)} مگابایت است.")
    if ext == ".zip":
        text = _zip_text(path, progress, cancelled)
    elif ext == ".docx":
        progress(30)
        text = _docx_text(path)
    elif ext == ".pdf":
        text = _pdf_text(path, progress, cancelled)
    else:
        text = _decode_text(_read_file(path, progress, cancelled))
    text = text.replace("\r\n", "\n").strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS + 1]          # compose() adds the visible truncation marker
    if not text:
        raise AttachmentError(f"در فایل «{name}» متنی پیدا نشد.")
    progress(100)
    return {"name": name, "kind": "text", "text": text, "size": size}


def compose(text: str, attachments: list, search: bool = False) -> dict:
    """Combine the typed text and attachments.

    display - what the chat bubble shows;  stored - what is saved in the chat history (short);
    model - the full text for this request;  images - [{'mime','b64','name'}] for vision models."""
    text = str(text or "").strip()
    files = [a for a in (attachments or []) if a.get("kind") == "text"]
    images = [a for a in (attachments or []) if a.get("kind") == "image"]
    lead = text or ("این تصویر چیست؟ با کمک نتایج جست‌وجوی وب بگو." if images and not files and search else
                    "این تصویر را ببین و نظرت را بگو." if images and not files else
                    "این فایل را بخوان و درباره‌اش نظر بده." if files and not images else "این ضمیمه‌ها را ببین و نظرت را بگو.")
    notes = [f"🖼 {a['name']}" for a in images] + [f"📎 {a['name']}" for a in files]
    display = (text + "\n" if text else "") + "\n".join(notes)
    model, stored = lead, lead
    for a in files:
        body = a["text"]
        cut = len(body) > MAX_TEXT_CHARS
        model += f"\n\n--- فایل ضمیمه: {a['name']} ---\n{body[:MAX_TEXT_CHARS]}" + ("\n[... بقیه‌ی فایل بریده شد ...]" if cut else "") + "\n--- پایان فایل ---"
        excerpt = body[:HISTORY_EXCERPT]
        stored += f"\n\n[فایل ضمیمه: {a['name']}]\n{excerpt}" + ("\n[...]" if len(body) > HISTORY_EXCERPT else "")
    if images:
        tag = "\n\n" + "\n".join(f"[تصویر ضمیمه: {a['name']}]" for a in images)
        model += tag
        stored += tag
    return {"display": display or lead, "stored": stored, "model": model,
            "images": [{"mime": a["mime"], "b64": a["b64"], "name": a["name"]} for a in images]}


def summary(attachments: list) -> str:
    return "، ".join(("🖼 " if a.get("kind") == "image" else "📎 ") + a["name"] for a in attachments)
