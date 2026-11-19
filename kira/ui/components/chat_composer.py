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
        "input",
        "route_badge",
        "route_menu",
        "web_btn",
        "img_search_btn",
        "code_chat",
        "mic_btn",
        "wake_btn",
        "voice_btn",
        "game_mode_btn",
        "game_mode_story_action",
        "game_mode_safe_action",
        "vision_rate_actions",
        "stop_btn",
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
        co.addWidget(self.send_strip)
        co.addWidget(self.attach_strip)
        co.addWidget(self.attach_err_widget)

        self.input = chat_input_factory()
        self.input.filesDropped.connect(owner.add_attachment_paths)
        self.input.imagePasted.connect(owner.add_pasted_image)
        self.input.returnPressed.connect(owner.send_message)
        self.input.textChanged.connect(lambda: owner.on_input_changed(self.input.text()))
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

        self.screen_capture_btn = QToolButton()
        self.screen_capture_btn.setProperty("kiraIconName", "monitor")
        self.screen_capture_btn.setIcon(make_icon("monitor"))
        self.screen_capture_btn.setIconSize(QSize(18, 18))
        self.screen_capture_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.screen_capture_btn.setToolTip("گرفتن تصویر از صفحه و پیوست برای تحلیل Vision")
        self.screen_capture_btn.setCursor(Qt.PointingHandCursor)
        self.screen_capture_btn.setFocusPolicy(Qt.NoFocus)
        self.screen_capture_btn.clicked.connect(owner.capture_screen_attachment)
        bar.addWidget(self.screen_capture_btn)

        self.web_btn = QToolButton()
        self.web_btn.setProperty("kiraIconName", "globe")
        self.web_btn.setIcon(make_icon("globe"))
        self.web_btn.setIconSize(QSize(18, 18))
        self.web_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.web_btn.setCheckable(True)
        self.web_btn.setChecked(bool(owner.settings.get("web_search", True)))
        self.web_btn.setCursor(Qt.PointingHandCursor)
        self.web_btn.setFocusPolicy(Qt.NoFocus)
        self.web_btn.toggled.connect(owner.toggle_web_search)
        owner.web_btn = self.web_btn
        owner.update_web_tip()
        bar.addWidget(self.web_btn)

        self.img_search_btn = QToolButton()
        self.img_search_btn.setProperty("kiraIconName", "search")
        self.img_search_btn.setIcon(make_icon("search"))
        self.img_search_btn.setIconSize(QSize(18, 18))
        self.img_search_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.img_search_btn.setCheckable(True)
        self.img_search_btn.setChecked(bool(owner.settings.get("image_search", False)))
        self.img_search_btn.setCursor(Qt.PointingHandCursor)
        self.img_search_btn.setFocusPolicy(Qt.NoFocus)
        self.img_search_btn.toggled.connect(owner.toggle_image_search)
        owner.img_search_btn = self.img_search_btn
        owner.update_image_search_tip()
        bar.addWidget(self.img_search_btn)

        self.code_chat = code_chat_factory(owner.code_chat_host)
        bar.addStretch(1)

        self.mic_btn = owner.icon_button("mic", True)
        self.mic_btn.clicked.connect(owner.toggle_mic)
        self.wake_btn = owner.icon_button("moon", True)
        self.wake_btn.clicked.connect(owner.toggle_wake)
        self.voice_btn = owner.icon_button("speaker", True)
        self.voice_btn.setChecked(bool(owner.settings.get("speak_replies", True)))
        self.voice_btn.clicked.connect(
            lambda: owner.set_voice_enabled(self.voice_btn.isChecked())
        )

        self.game_mode_btn = QToolButton()
        self.game_mode_btn.setObjectName("gameModeBtn")
        self.game_mode_btn.setProperty("kiraIconName", "gamepad")
        self.game_mode_btn.setIcon(make_icon("gamepad"))
        self.game_mode_btn.setIconSize(QSize(19, 19))
        self.game_mode_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.game_mode_btn.setCheckable(False)
        self.game_mode_btn.setCursor(Qt.PointingHandCursor)
        self.game_mode_btn.setFocusPolicy(Qt.NoFocus)
        self.game_mode_menu = QMenu(self.game_mode_btn)
        self.game_mode_story_action = QAction(
            "Story Mode · آفلاین و داستانی", self.game_mode_menu
        )
        self.game_mode_story_action.setCheckable(True)
        self.game_mode_story_action.triggered.connect(
            lambda checked=False: owner.set_game_mode_profile(story_mode)
        )
        self.game_mode_safe_action = QAction(
            "Competitive Safe · آنلاین و PvP", self.game_mode_menu
        )
        self.game_mode_safe_action.setCheckable(True)
        self.game_mode_safe_action.setChecked(True)
        self.game_mode_safe_action.triggered.connect(
            lambda checked=False: owner.set_game_mode_profile(competitive_safe_mode)
        )
        self.game_mode_off_action = QAction(
            "خاموش‌کردن Game Mode", self.game_mode_menu
        )
        self.game_mode_off_action.triggered.connect(
            lambda checked=False: owner.set_game_mode(False)
        )
        self.vision_rate_menu = self.game_mode_menu.addMenu("سرعت Vision")
        self.vision_rate_actions = {}
        for mode, label in (
            ("economic", "اقتصادی · هر ۵ ثانیه"),
            ("smart", "هوشمند · هر ۱ ثانیه"),
            ("fast", "سریع · هر نیم‌ثانیه"),
        ):
            action = QAction(label, self.vision_rate_menu)
            action.setCheckable(True)
            action.setChecked(mode == owner._vision_gate.policy.name)
            action.triggered.connect(
                lambda checked=False, selected=mode: owner.set_vision_mode(selected)
            )
            self.vision_rate_menu.addAction(action)
            self.vision_rate_actions[mode] = action
        self.game_mode_menu.addAction(self.game_mode_story_action)
        self.game_mode_menu.addAction(self.game_mode_safe_action)
        self.game_mode_menu.addSeparator()
        self.game_mode_menu.addAction(self.game_mode_off_action)
        self.game_mode_btn.setMenu(self.game_mode_menu)
        self.game_mode_btn.setPopupMode(QToolButton.InstantPopup)
        self.game_mode_btn.setToolTip("انتخاب حالت بازی: Story یا Competitive Safe")
        bar.addWidget(self.game_mode_btn)

        self.stop_btn = owner.icon_button("stop")
        self.stop_btn.clicked.connect(lambda: owner.on_stop_clicked())
        for button, key in (
            (self.mic_btn, "mic"),
            (self.wake_btn, "wake"),
            (self.voice_btn, "voice"),
            (self.stop_btn, "stop"),
        ):
            owner.reg(button.setToolTip, key)
            bar.addWidget(button)

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
