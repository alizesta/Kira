"""Small reusable widgets for the compact companion UI."""
import base64
import math
import os
import random

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPalette, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout, QSizePolicy, QWIDGETSIZE_MAX


class ChatInput(QPlainTextEdit):
    """Compact message box: Enter sends, Shift+Enter adds lines, and EXPAND opens a larger draft area.

    Offers the small QLineEdit-style API the application already uses (text / setText / returnPressed).
    """
    returnPressed = Signal()
    filesDropped = Signal(list)          # local file paths dropped or pasted as files
    imagePasted = Signal(object)         # QImage pasted from the clipboard
    MIN_LINES = 1
    MAX_LINES = 3
    EXPANDED_MAX_LINES = 16
    CHARACTER_PROMPTS = {
        "kira": {"fa": ("خب، امروز قراره چی بسازیم؟", "یه باگ سمج داری که با هم نابودش کنیم؟", "ایده‌تو بگو؛ من آماده‌ام دست‌به‌کد بشیم.", "کجای پروژه گیر کردی؟ بذار بررسیش کنیم.", "یه چیزی بگو که کنجکاوم کنه!"), "en": ("What are we building today?", "Got a stubborn bug to defeat?", "Tell me your idea — let's code.")},
        "mika": {"fa": ("خب خب، امروز چه چیزی رو با هم کشف کنیم؟", "حالت چطوره؟ چیزی هست که بخوای بررسی کنیم؟", "هر سؤالی داری بپرس؛ با حوصله بازش می‌کنیم.", "امروز چه خبر؟ از کجا شروع کنیم؟"), "en": ("What shall we explore today?", "How are you feeling? Anything to look into?", "Ask me anything — we'll unpack it together.")},
        "ren": {"fa": ("چه موضوعی رو می‌خوای دقیق بررسی کنیم؟", "خبر یا ادعایی هست که باید راستی‌آزمایی بشه؟", "داده‌ها رو بده؛ تحلیلش می‌کنم.", "کدوم مسئله ارزش بررسی عمیق داره؟"), "en": ("What should we investigate?", "Any claim or headline to verify?", "Give me the evidence; I'll analyse it.")},
    }

    def set_character_placeholder(self, character_id="kira", language="fa"):
        """Choose a fresh, character-appropriate prompt for the visible chat."""
        profile = self.CHARACTER_PROMPTS.get(str(character_id or "kira").lower(), self.CHARACTER_PROMPTS["kira"])
        lang = "en" if str(language or "fa").lower().startswith("en") else "fa"
        self.setLayoutDirection(Qt.LeftToRight if lang == "en" else Qt.RightToLeft)
        self.setPlaceholderText(random.choice(profile.get(lang) or profile["fa"]))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatInput")
        self.setFrameShape(QFrame.NoFrame)
        self.setContentsMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._expanded = False
        self._last_width = -1
        placeholder_palette = self.palette()
        placeholder_palette.setColor(QPalette.PlaceholderText, QColor("#E2EAF8"))
        self.setPalette(placeholder_palette)
        self.textChanged.connect(self._fit)
        self._fit()

    def set_expanded(self, expanded):
        """Expand to a visibly larger fixed writing area, or return to content height."""
        expanded = bool(expanded)
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._fit()
        self._refresh_parent_layouts()
        self.ensureCursorVisible()
        self.setFocus()

    def _refresh_parent_layouts(self):
        """Reflow the composer and chat viewport after the editor changes height."""
        parent = self.parentWidget()
        while parent is not None:
            parent.updateGeometry()
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            parent = parent.parentWidget()

    def is_expanded(self):
        return self._expanded

    def text(self):
        return self.toPlainText()

    def setText(self, value):
        self.setPlainText(str(value))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()] if source.hasUrls() else []
        if paths:
            self.filesDropped.emit(paths)
        elif source.hasImage() and not source.hasText():
            self.imagePasted.emit(source.imageData())
        else:
            super().insertFromMimeData(source)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.width() != self._last_width:          # only re-measure when the width (wrapping) changed
            self._last_width = self.width()
            self._fit()

    def _fit(self):
        line_spacing = max(1, self.fontMetrics().lineSpacing())
        if self._expanded:
            # Expanded mode must grow even when the draft is empty or only one line.
            lines = self.EXPANDED_MAX_LINES
        else:
            document_height = float(
                self.document().documentLayout().documentSize().height()
            )
            required_height = max(
                float(line_spacing),
                document_height - (2.0 * self.document().documentMargin()),
            )
            required_lines = max(1, math.ceil(required_height / line_spacing))
            lines = min(self.MAX_LINES, max(self.MIN_LINES, required_lines))
        # Derive the editor's constraints from the active font metrics rather than
        # a fixed widget height. Expanded mode can consume the available layout space.
        content_padding = round(self.fontMetrics().height() * 0.7)
        target_height = lines * line_spacing + content_padding + self.contentsMargins().top() + self.contentsMargins().bottom()
        self.setMinimumHeight(target_height)
        if self._expanded:
            self.setMaximumHeight(QWIDGETSIZE_MAX)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.setMaximumHeight(target_height)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class RouteChip(QToolButton):
    """Small pill showing the active provider / model; long names are shortened, the tooltip keeps the full text."""
    MAX_CHARS = 40

    def setText(self, text, display=None):
        """text = the full status (kept for text() and the tooltip); display = optional shorter wording for the button."""
        self._full = full = str(text)
        shown = str(display) if display else full
        short = shown if len(shown) <= self.MAX_CHARS else shown[: self.MAX_CHARS - 1] + "…"
        super().setText(short)
        self.setToolTip(full)

    def text(self):
        return getattr(self, "_full", super().text())


class AttachmentTile(QFrame):
    """One attachment card: square thumbnail (or a file-type badge), file name, optional remove button and a
    progress overlay ("37%" -> "✓") drawn on top of the thumbnail."""
    removeRequested = Signal(object)
    THUMB = 88

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.setObjectName("attTile")
        self.name = str(name)
        self.att = None                       # the loaded attachment dict (set when loading finished)
        self.deleted = False
        self.setFixedSize(self.THUMB + 12, self.THUMB + 34)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 4)
        lay.setSpacing(3)
        self.thumb = QLabel()
        self.thumb.setObjectName("attThumb")
        self.thumb.setFixedSize(self.THUMB, self.THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)
        self.caption = QLabel()
        self.caption.setObjectName("hint")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setToolTip(self.name)
        self.caption.setText(QFontMetrics(self.caption.font()).elidedText(self.name, Qt.ElideMiddle, self.THUMB))
        lay.addWidget(self.caption)
        self.overlay = QLabel(self.thumb)
        self.overlay.setObjectName("attOverlay")
        self.overlay.setGeometry(0, 0, self.THUMB, self.THUMB)
        self.overlay.setAlignment(Qt.AlignCenter)
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.overlay.hide()
        self.close_btn = QToolButton(self)
        self.close_btn.setObjectName("attClose")
        self.close_btn.setText("✕")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.move(self.width() - 24, 3)
        self.close_btn.clicked.connect(lambda: self.removeRequested.emit(self))
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.overlay.hide)
        self.set_badge(os.path.splitext(self.name)[1])

    def set_badge(self, ext):
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText((ext.lstrip(".")[:4].upper() or "FILE"))

    def set_attachment(self, attachment):
        self.att = attachment
        if attachment.get("kind") == "image":
            pm = QPixmap()
            if pm.loadFromData(base64.b64decode(attachment["b64"])):
                size = self.THUMB
                pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                pm = pm.copy((pm.width() - size) // 2, (pm.height() - size) // 2, size, size)      # centre crop to a square
                self.thumb.setText("")
                self.thumb.setPixmap(pm)

    def set_removable(self, on):
        self.close_btn.setEnabled(bool(on))
        self.close_btn.setVisible(bool(on))

    def set_progress(self, percent):
        """None hides the overlay, -1 shows '…' (size unknown), 0-99 shows the percentage, 100 shows ✓ and fades out."""
        self._hide_timer.stop()
        if percent is None:
            self.overlay.hide()
            return
        self.overlay.setText("…" if percent < 0 else ("✓" if percent >= 100 else f"{int(percent)}%"))
        self.overlay.raise_()
        self.overlay.show()
        self.close_btn.raise_()
        if percent >= 100:
            self._hide_timer.start(1200)
