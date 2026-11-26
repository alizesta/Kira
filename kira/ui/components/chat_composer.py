"""Chat message composer and its toolbar controls."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .kode_activity import KodeActivityPanel


class ChatComposer(QFrame):
    """Owns the message input, attachment indicators, and chat action toolbar.

    MainWindow remains the controller for application behavior. Widget attributes
    are mirrored onto it as compatibility aliases while the UI is extracted
    incrementally.
    """

    # Only widgets declared in WindowPresentationContext are mirrored to the
    # legacy window-view namespace. Every other child remains available through
    # views.chat_composer.<name> and is deliberately not a window-level alias.
    _OWNER_ALIASES = (
        "send_strip",
        "kode_activity",
        "input",
        "route_badge",
        "route_menu",
        "web_btn",
        "search_btn",
        "screen_capture_btn",
        "img_search_btn",
        "code_chat",
        "mic_btn",
        "wake_btn",
        "voice_btn",
        "game_mode_btn",
        "gen_stop_btn",
        "send_btn",
    )

    def __init__(
        self,
        owner,
        *,
        chat_input_factory,
        route_chip_factory,
        code_chat_factory,
        make_icon,
        story_mode,
        competitive_safe_mode,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("composer")
        self._owner = owner

        co = QVBoxLayout(self)
        co.setContentsMargins(10, 6, 8, 6)
        co.setSpacing(2)

        self.send_strip = owner.make_tile_strip()
        self.attach_strip = owner.make_tile_strip()
        self.attach_err = QLabel()
        self.attach_err.setObjectName("hint")
        self.attach_err.setWordWrap(True)
        self.attach_err_close = QToolButton()
        self.attach_err_close.setObjectName("attClose")
        self.attach_err_close.setText("✕")
        self.attach_err_close.setToolTip("لغو بارگذاری ضمیمه‌ها / بستن پیام")
        self.attach_err_close.setCursor(Qt.PointingHandCursor)
        self.attach_err_close.setFixedSize(20, 20)
        self.attach_err_close.clicked.connect(owner.cancel_attachments)
        self.attach_err_row = QHBoxLayout()
        self.attach_err_row.setContentsMargins(0, 0, 0, 0)
        self.attach_err_row.addWidget(self.attach_err, 1)
        self.attach_err_row.addWidget(self.attach_err_close)
        self.attach_err_widget = QWidget()
        self.attach_err_widget.setLayout(self.attach_err_row)
        self.attach_err_widget.hide()
        self.kode_activity = KodeActivityPanel(self)
        owner.kode_activity = self.kode_activity
        # Progress is drawn inside the chat page (not above the input): see sync_progress.
        self.kode_activity.changed.connect(owner.sync_progress)
        co.addWidget(self.send_strip)
        co.addWidget(self.attach_strip)
        co.addWidget(self.attach_err_widget)

        self.input = chat_input_factory()
        self.input.filesDropped.connect(owner.add_attachment_paths)
        self.input.imagePasted.connect(owner.add_pasted_image)
        self.input.returnPressed.connect(owner.send_message)
        self.input.textChanged.connect(lambda: owner.on_input_changed(self.input.text()))

        input_tools_row = QHBoxLayout()
        input_tools_row.setContentsMargins(0, 0, 0, 0)
        input_tools_row.setSpacing(0)
        input_tools_row.setDirection(QHBoxLayout.LeftToRight)
        input_tools_row.addStretch(1)
        self.expand_btn = QToolButton(self)
        self.expand_btn.setObjectName("expandInputBtn")
        self.expand_btn.setProperty("kiraIconName", "expand")
        self._expand_icon = make_icon("expand")
        self._collapse_icon = make_icon("collapse")
        self.expand_btn.setIcon(self._expand_icon)
        self.expand_btn.setIconSize(QSize(16, 16))
        self.expand_btn.setFixedSize(28, 26)
        self.expand_btn.setCheckable(True)
        self.expand_btn.setAutoRaise(True)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setFocusPolicy(Qt.NoFocus)
        self.expand_btn.setAccessibleName("Expand message editor")
        self.expand_btn.setToolTip("باز کردن فضای بزرگ‌تر برای نوشتن")
        self.expand_btn.toggled.connect(self._set_input_expanded)
        input_tools_row.addWidget(self.expand_btn)
        co.addLayout(input_tools_row)
        co.addWidget(self.input)

        bar = QHBoxLayout()
        bar.setSpacing(2)

        self.route_badge = route_chip_factory()
        self.route_badge.setObjectName("routeChip")
        self.route_badge.setText("● Ready")
        self.route_badge.setProperty("kiraIconName", "chevron_up")
        self.route_badge.setIcon(make_icon("chevron_up", normal="#4FD8FF", hover="#FFFFFF"))
        self.route_badge.setIconSize(QSize(12, 12))
        self.route_badge.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.route_badge.setCursor(Qt.PointingHandCursor)
        self.route_badge.setFocusPolicy(Qt.NoFocus)
        self.route_badge.setPopupMode(QToolButton.InstantPopup)
        self.route_menu = QMenu(owner.widget)
        self.route_menu.setStyleSheet("QMenu { menu-scrollable: 1; }")
        self.route_menu.aboutToShow.connect(owner.build_badge_menu)
        self.route_badge.setMenu(self.route_menu)
        bar.addWidget(self.route_badge)

        self.attach_btn = QToolButton()
        self.attach_btn.setProperty("kiraIconName", "attachment")
        self.attach_btn.setIcon(make_icon("attachment"))
        self.attach_btn.setIconSize(QSize(18, 18))
        self.attach_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.attach_btn.setToolTip("پیوست عکس یا فایل (می‌توانی فایل را روی پنجره بکشی یا عکس را Ctrl+V کنی)")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setFocusPolicy(Qt.NoFocus)
        self.attach_btn.clicked.connect(owner.pick_attachments)
        bar.addWidget(self.attach_btn)

        self.search_btn = QToolButton()
        self.search_btn.setProperty("kiraIconName", "search")
        self.search_btn.setIcon(make_icon("search"))
        self.search_btn.setIconSize(QSize(18, 18))
        self.search_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setFocusPolicy(Qt.NoFocus)
        self.search_menu = QMenu(self.search_btn)
        self.web_btn = QAction("جست‌وجوی وب", self.search_menu)
        self.web_btn.setCheckable(True)
        self.web_btn.setChecked(bool(owner.settings.get("web_search", True)))
        self.web_btn.toggled.connect(owner.toggle_web_search)
        self.search_menu.addAction(self.web_btn)
        self.img_search_btn = QAction("جست‌وجوی تصویری عکس ارسالی", self.search_menu)
        self.img_search_btn.setCheckable(True)
        self.img_search_btn.setChecked(bool(owner.settings.get("image_search", False)))
        self.img_search_btn.toggled.connect(owner.toggle_image_search)
        self.search_menu.addAction(self.img_search_btn)
        self.search_btn.setMenu(self.search_menu)
        self.search_btn.setPopupMode(QToolButton.InstantPopup)
        self.search_btn.setToolTip("جست‌وجو: وب یا جست‌وجوی تصویری عکس ارسالی")
        owner.search_btn = self.search_btn
        owner.web_btn = self.web_btn
        owner.img_search_btn = self.img_search_btn
        owner.update_web_tip()
        owner.update_image_search_tip()
        bar.addWidget(self.search_btn)

        self.code_chat = code_chat_factory(owner.code_chat_host)
        bar.addStretch(1)

        self.mic_btn = owner.icon_button("mic", True)
        self.mic_btn.toggled.connect(owner.toggle_mic)
        # Keep the microphone as a single-action button: no split-button arrow.
        self.mic_btn.setMenu(None)
        self.mic_btn.setPopupMode(QToolButton.DelayedPopup)
        self.mic_btn.setToolTip("روشن/خاموش کردن میکروفون")
        self.wake_btn = QAction("حالت بیدارباش", self.mic_btn)
        self.wake_btn.setCheckable(True)
        self.wake_btn.setChecked(False)
        self.wake_btn.triggered.connect(owner.toggle_wake)
        self.voice_btn = owner.icon_button("speaker", True)
        self.voice_btn.setChecked(bool(owner.settings.get("speak_replies", True)))
        self.voice_btn.setProperty("voiceOnIcon", make_icon("speaker"))
        self.voice_btn.setProperty("voiceOffIcon", make_icon("speaker_muted"))
        self.voice_btn.setIcon(
            self.voice_btn.property("voiceOnIcon")
            if self.voice_btn.isChecked()
            else self.voice_btn.property("voiceOffIcon")
        )
        self.voice_btn.clicked.connect(
            lambda: owner.set_voice_enabled(self.voice_btn.isChecked())
        )

        self.game_mode_btn = QToolButton()
        self.game_mode_btn.setObjectName("gameModeBtn")
        self.game_mode_btn.setProperty("kiraIconName", "eye")
        self.game_mode_btn.setIcon(make_icon("eye"))
        self.game_mode_btn.setIconSize(QSize(19, 19))
        self.game_mode_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.game_mode_btn.setCheckable(True)
        self.game_mode_btn.setChecked(False)
        self.game_mode_btn.setCursor(Qt.PointingHandCursor)
        self.game_mode_btn.setFocusPolicy(Qt.NoFocus)
        self.game_mode_btn.toggled.connect(owner.set_game_mode)
        self.game_mode_btn.setToolTip("Eye Mode خاموش است؛ برای دیدن صفحه کلیک کن")
        self.screen_capture_btn = self.game_mode_btn
        owner.screen_capture_btn = self.game_mode_btn
        bar.addWidget(self.game_mode_btn)

        # The composer runs in RTL: Qt lays out QHBoxLayout items right-to-left.
        # Add mic first so the speaker is physically to its left on screen.
        for button, key in (
            (self.mic_btn, "mic"),
            (self.voice_btn, "voice"),
        ):
            owner.reg(button.setToolTip, key)
            bar.addWidget(button)
        self.voice_btn.setToolTip(
            "پاسخ صوتی روشن است؛ Kira با صدا پاسخ می‌دهد."
            if self.voice_btn.isChecked()
            else "پاسخ صوتی خاموش است؛ Kira فقط متنی پاسخ می‌دهد."
        )

        self.gen_stop_btn = QToolButton()
        self.gen_stop_btn.setObjectName("genStop")
        self.gen_stop_btn.setProperty("kiraIconName", "stop")
        self.gen_stop_btn.setIcon(
            make_icon("stop", normal="#ffffff", hover="#ffffff", disabled="#e0aab3")
        )
        self.gen_stop_btn.setIconSize(QSize(16, 16))
        self.gen_stop_btn.setFixedSize(32, 32)
        self.gen_stop_btn.setCursor(Qt.PointingHandCursor)
        self.gen_stop_btn.setFocusPolicy(Qt.NoFocus)
        self.gen_stop_btn.setToolTip("توقف تولید پاسخ (متن دریافت‌شده تا اینجا حفظ می‌شود)")
        self.gen_stop_btn.clicked.connect(owner.stop_generation)
        self.gen_stop_btn.hide()

        self.send_btn = QToolButton()
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setProperty("kiraIconName", "send")
        self.send_btn.setIcon(
            make_icon("send", normal="#ffffff", hover="#ffffff", disabled="#7d8095")
        )
        self.send_btn.setIconSize(QSize(18, 18))
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFocusPolicy(Qt.NoFocus)
        owner.reg(self.send_btn.setToolTip, "send")
        self.send_btn.clicked.connect(owner.send_message)
        bar.addSpacing(4)
        bar.addWidget(self.gen_stop_btn)
        bar.addWidget(self.send_btn)
        co.addLayout(bar)

        for name in self._OWNER_ALIASES:
            setattr(owner, name, getattr(self, name))

    def _set_input_expanded(self, expanded):
        """Resize the draft editor and switch the control between expand/collapse icons."""
        self.input.set_expanded(expanded)
        icon_name = "collapse" if expanded else "expand"
        self.expand_btn.setProperty("kiraIconName", icon_name)
        self.expand_btn.setIcon(
            self._collapse_icon if expanded else self._expand_icon
        )
        self.expand_btn.setAccessibleName(
            "Collapse message editor" if expanded else "Expand message editor"
        )
        self.expand_btn.setToolTip(
            "جمع کردن کادر نوشتن" if expanded else "باز کردن فضای بزرگ‌تر برای نوشتن"
        )
