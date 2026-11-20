import base64

from PySide6.QtCore import Qt, Signal, QThread, QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QPixmap, QFontMetrics
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, QFrame, QToolButton, QLabel,
                               QFileDialog)
from . import attachments as att
from .vrm_avatar import KiraAvatar
from .chat_render import message_html
from .ui_widgets import ChatInput
from .pet import PetController

RATIO = 1536 / 1024 * 1.02


class CompanionWindow(QWidget):
    """Floating Kira. Drag = move, wheel = resize, right-click = hide."""
    visibility = Signal(bool)
    geometry_changed = Signal()

    def __init__(self, animator):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.NoDropShadowWindowHint)
        self.setWindowTitle("Kira Companion")
        self.setAttribute(Qt.WA_TranslucentBackground, True)   # no background at all
        self.ratio = RATIO
        self.view = KiraAvatar(animator, draggable=True)
        animator.art_changed.connect(self.apply_art)
        self.clicked = self.view.clicked
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.pet = PetController(self, animator)
        self.set_height(620)

    def wheelEvent(self, event):
        step = 1.08 if event.angleDelta().y() > 0 else 1 / 1.08
        self.set_height(self.height() * step)
        event.accept()

    def set_on_top(self, on):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        if on:
            flags |= Qt.WindowStaysOnTopHint
        was = self.isVisible()
        self.setWindowFlags(flags)
        if was:
            self.show()

    def apply_art(self):
        """The active character changed: keep the window height, adopt the proportions of the new picture."""
        ratio = self.view.anim.window_ratio
        self.ratio = ratio if ratio else RATIO
        self.set_height(self.height())

    def set_height(self, h):
        h = int(max(300, min(1100, h)))
        self.resize(int(h / self.ratio), h)

    def showEvent(self, e):
        self.visibility.emit(True)

    def hideEvent(self, e):
        self.visibility.emit(False)

    def moveEvent(self, e):
        super().moveEvent(e)
        self.geometry_changed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.geometry_changed.emit()


class _BubbleLoader(QThread):
    """Reads the chosen files off the GUI thread: loaded(index, attachment) / failed(index, message)."""
    loaded = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(self, paths):
        super().__init__()
        self.paths = list(paths)

    def run(self):
        for i, path in enumerate(self.paths):
            try:
                self.loaded.emit(i, att.load_attachment(path))
            except (att.AttachmentError, OSError) as exc:
                self.failed.emit(i, str(exc))


class _Chip(QFrame):
    """Small attachment chip above the input of the tray chat: thumbnail (or 📎), shortened name, remove button."""
    removeRequested = Signal(object)
    THUMB = 26

    def __init__(self, name):
        super().__init__()
        self.setObjectName("attChip")
        self.name, self.att, self.deleted = str(name), None, False
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 2, 2)
        row.setSpacing(4)
        self.thumb = QLabel("⏳")
        self.thumb.setFixedSize(self.THUMB, self.THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.label = QLabel(QFontMetrics(self.font()).elidedText(self.name, Qt.ElideMiddle, 90))
        self.label.setToolTip(self.name)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("attClose")
        self.close_btn.setText("✕")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(lambda: self.removeRequested.emit(self))
        for w in (self.thumb, self.label, self.close_btn):
            row.addWidget(w)

    def set_attachment(self, attachment):
        self.att = attachment
        pm = QPixmap()
        if attachment.get("kind") == "image" and pm.loadFromData(base64.b64decode(attachment["b64"])):
            self.thumb.setText("")
            self.thumb.setPixmap(pm.scaled(self.THUMB, self.THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setText("📎")


class CompanionBubble(QWidget):
    """Small chat panel that sits beside the floating Kira while the main window is in the system tray.
    It mirrors the conversation (last few messages, live while she types) and has its own input line.
    Like the main window it takes pictures and files (📎 button, drag & drop, Ctrl+V) and has the 🔎 image-search switch."""
    submitted = Signal(str, list)              # text, [attachment dicts] (empty list when nothing is attached)
    imageSearchToggled = Signal(bool)
    KEEP = 6

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setWindowTitle("Kira Chat")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.items = []                    # [(kind, name, text)]
        self.live = None                   # (name, text) while a reply streams
        self.ui_dir = "rtl"
        self._chips = []                   # attachment chips waiting for the next message
        self._seq = 0
        self._loader = None
        self._load_chips = []
        panel = QFrame(self)
        panel.setObjectName("bubblePanel")
        panel.setStyleSheet("#bubblePanel{background:rgba(24,26,40,230);border:1px solid rgba(160,140,255,90);border-radius:16px;}"
                            "QTextBrowser{background:transparent;border:none;color:#eceef6;}"
                            "QPlainTextEdit{background:rgba(255,255,255,18);border:1px solid rgba(255,255,255,40);border-radius:10px;"
                            "padding:4px 8px;color:#f1f2f8;}"
                            "QPushButton{background:#6c5ce7;color:white;border:none;border-radius:10px;padding:6px 12px;}"
                            "QToolButton{background:rgba(255,255,255,18);color:#f1f2f8;border:none;border-radius:10px;padding:5px 8px;}"
                            "QToolButton:checked{background:#6c5ce7;}"
                            "#attChip{background:rgba(255,255,255,22);border-radius:8px;}"
                            "#attChip QLabel{color:#eceef6;}"
                            "#attClose{background:transparent;color:#cfd2e6;padding:2px 4px;}"
                            "#bubbleErr{color:#ffb86b;}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setAcceptDrops(False)                      # a file dropped on the history goes to the panel, not into the text
        self.view.viewport().setAcceptDrops(False)
        lay.addWidget(self.view, 1)
        self.strip = QFrame()                                # chips of the files chosen for the next message
        self.strip_row = QHBoxLayout(self.strip)
        self.strip_row.setContentsMargins(0, 0, 0, 0)
        self.strip_row.setSpacing(4)
        self.strip_row.addStretch(1)
        self.strip.hide()
        lay.addWidget(self.strip)
        self.err = QLabel()
        self.err.setObjectName("bubbleErr")
        self.err.setWordWrap(True)
        self.err.hide()
        lay.addWidget(self.err)
        row = QHBoxLayout()
        self.attach_btn = QToolButton()
        self.attach_btn.setText("📎")
        self.attach_btn.setToolTip("پیوست عکس یا فایل (فایل را روی این پنجره بکش یا عکس را Ctrl+V کن)")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setFocusPolicy(Qt.NoFocus)
        self.attach_btn.clicked.connect(self.pick_files)
        self.img_btn = QToolButton()
        self.img_btn.setText("🔎")
        self.img_btn.setCheckable(True)
        self.img_btn.setCursor(Qt.PointingHandCursor)
        self.img_btn.setFocusPolicy(Qt.NoFocus)
        self.img_btn.toggled.connect(self._image_toggled)
        self._update_img_tip()
        self.edit = ChatInput()
        self.edit.setPlaceholderText("با کیرا حرف بزن…")
        self.send = QPushButton("ارسال")
        row.addWidget(self.attach_btn)
        row.addWidget(self.img_btn)
        row.addWidget(self.edit, 1)
        row.addWidget(self.send)
        lay.addLayout(row)
        self.edit.returnPressed.connect(self._submit)
        self.edit.filesDropped.connect(self.add_paths)
        self.edit.imagePasted.connect(self.add_pasted_image)
        self.send.clicked.connect(self._submit)
        self.resize(360, 300)

    # ---- image-search switch (shared with the main window) ----
    def _update_img_tip(self):
        on = self.img_btn.isChecked()
        self.img_btn.setToolTip("جست‌وجوی تصویری: " + ("روشن — عکسی که می‌فرستی در وب (Gemini / Tavily / DuckDuckGo) جست‌وجو می‌شود تا معلوم شود چیست."
                                                       if on else "خاموش — عکس فقط به مدل داده می‌شود (می‌توانی یک پیام را با /img شروع کنی)."))

    def _image_toggled(self, on):
        self._update_img_tip()
        self.imageSearchToggled.emit(bool(on))

    def set_image_search(self, on):
        """Follow the setting changed elsewhere without emitting the signal again."""
        self.img_btn.blockSignals(True)
        self.img_btn.setChecked(bool(on))
        self.img_btn.blockSignals(False)
        self._update_img_tip()

    # ---- attachments ----
    def show_error(self, message):
        self.err.setText(("✕ " + message) if message else "")
        self.err.setVisible(bool(message))

    def loading(self):
        return self._loader is not None and self._loader.isRunning()

    def pending_attachments(self):
        return [c.att for c in self._chips if c.att]

    def _add_chip(self, chip):
        chip.removeRequested.connect(self.remove_chip)
        self._chips.append(chip)
        self.strip_row.insertWidget(self.strip_row.count() - 1, chip)
        self.strip.show()

    def remove_chip(self, chip):
        chip.deleted = True
        if chip in self._chips:
            self._chips.remove(chip)
        self.strip_row.removeWidget(chip)
        chip.setParent(None)
        chip.deleteLater()
        self.strip.setVisible(bool(self._chips))

    def clear_attachments(self):
        for chip in list(self._chips):
            self.remove_chip(chip)
        self.show_error("")

    def pick_files(self):
        exts = " ".join("*" + e for e in sorted(att.IMAGE_TYPES))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "انتخاب عکس یا فایل", "",
            f"عکس و فایل‌های پشتیبانی‌شده ({exts} *.txt *.md *.json *.csv *.log *.py *.js *.html *.xml *.yaml *.yml *.ini *.docx *.pdf);;همه‌ی فایل‌ها (*)")
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        if self.loading():
            self.show_error("صبر کن؛ ضمیمه‌های قبلی هنوز در حال بارگذاری‌اند.")
            return
        paths = list(paths)
        room = att.MAX_FILES - len(self._chips)
        self.show_error(f"حداکثر {att.MAX_FILES} ضمیمه برای هر پیام." if len(paths) > room else "")
        paths = paths[:max(0, room)]
        if not paths:
            return
        import os
        self._load_chips = []
        for path in paths:
            chip = _Chip(os.path.basename(path) or path)
            self._load_chips.append(chip)
            self._add_chip(chip)
        self._loader = _BubbleLoader(paths)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._loader.start()

    def _on_loaded(self, index, attachment):
        chip = self._load_chips[index] if index < len(self._load_chips) else None
        if chip is not None and not chip.deleted:
            chip.set_attachment(attachment)

    def _on_failed(self, index, message):
        chip = self._load_chips[index] if index < len(self._load_chips) else None
        if chip is not None and not chip.deleted:
            self.remove_chip(chip)
        self.show_error(message)

    def add_pasted_image(self, image):
        try:
            if len(self._chips) >= att.MAX_FILES:
                raise att.AttachmentError(f"حداکثر {att.MAX_FILES} ضمیمه برای هر پیام.")
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            image.save(buf, "PNG")
            self._seq += 1
            attachment = att.image_attachment(bytes(buf.data()), f"tray-clipboard-{self._seq}.png")
        except (att.AttachmentError, AttributeError) as exc:
            self.show_error(str(exc))
            return
        chip = _Chip(attachment["name"])
        chip.set_attachment(attachment)
        self._add_chip(chip)
        self.show_error("")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def _submit(self):
        if self.loading():
            self.show_error("ضمیمه‌ها هنوز در حال بارگذاری‌اند؛ چند لحظه صبر کن.")
            return
        text = self.edit.text().strip()
        files = self.pending_attachments()
        if text or files:
            self.edit.clear()
            self.clear_attachments()
            self.submitted.emit(text, files)

    def _render(self):
        html = "".join(message_html(k, n, t, self.ui_dir) for k, n, t in self.items)
        if self.live and self.live[1].strip():
            html += message_html("assistant", self.live[0], self.live[1], self.ui_dir)
        self.view.setHtml(html)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def push(self, kind, name, text, ui_dir="rtl"):
        if kind not in ("user", "assistant", "error") or not str(text).strip():
            return
        self.ui_dir = ui_dir
        self.items = (self.items + [(kind, name, str(text))])[-self.KEEP:]
        self.live = None
        self._render()

    def set_live(self, name, text, ui_dir="rtl"):
        self.ui_dir = ui_dir
        self.live = (name, text)
        self._render()

    def commit_live(self):
        if self.live and self.live[1].strip():
            self.items = (self.items + [("assistant", self.live[0], self.live[1])])[-self.KEEP:]
        self.live = None
        self._render()

    def place_beside(self, companion):
        """Left of Kira when there is room on screen, otherwise right; bottom-aligned with her."""
        g = companion.frameGeometry()
        screen = (QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()).availableGeometry()
        h = min(max(260, g.height() // 2), screen.height() - 20)
        self.resize(360, h)
        x = g.left() - self.width() - 6
        if x < screen.left():
            x = g.right() + 6
        y = min(max(screen.top(), g.bottom() - h), screen.bottom() - h)
        self.move(x, y)
