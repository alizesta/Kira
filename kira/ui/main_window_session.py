"""Session and presentation feature controller."""
import logging

from ..config import ROOT

from .shortcuts import delete_key
from .companion_session import session_marker
from .components.kode_activity import apply_progress_to_view, clear_progress
from .main_window_session_support import (
    KIRA_PROFILE,
    QApplication,
    QColor,
    QComboBox,
    QDesktopServices,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QImage,
    QLabel,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QInputDialog,
    QMenu,
    QPushButton,
    QScrollArea,
    QSize,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextBrowser,
    QTextCursor,
    QTextDocument,
    QTimer,
    QToolButton,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
    STR,
    SessionRelay,
    VERSION,
    base64,
    bubble_accent,
    contextlib,
    detect_direction,
    front_only,
    make_icon,
    message_html,
    save_settings,
    theme_mod,
    textwrap,
    time,
)


from .window_feature_controller import WindowFeatureController


_log = logging.getLogger(__name__)


class SessionController(WindowFeatureController):
    @property
    def _attach_worker(self):
        controller = getattr(self.context.adapters, "chat_attachment_controller", None)
        return controller.worker if controller is not None else None

    def t(self, key, **kw):
        s = STR.get(self.context.services.settings.get("ui_lang", "en"), STR["en"]).get(key, key)
        return s.format(**kw) if kw else s

    def reg(self, setter, key):
        self.context.state._tr.append((setter, key))

    def retranslate(self):
        lang = self.context.services.settings.get("ui_lang", "en")
        QApplication.setLayoutDirection(Qt.RightToLeft if lang == "fa" else Qt.LeftToRight)
        new_chat_button = getattr(self.context.views, "new_chat_btn", None)
        if new_chat_button is not None:
            new_chat_button.setText("چت جدید" if lang == "fa" else "New chat")
            new_chat_button.setToolTip(
                "شروع یک گفتگوی مستقل؛ تاریخچهٔ قبلی حفظ می‌شود."
                if lang == "fa" else "Start a separate conversation; previous history is preserved."
            )
        conversation_title = getattr(self.context.views, "conversation_list_title", None)
        if conversation_title is not None:
            conversation_title.setText("مکالمه‌ها" if lang == "fa" else "Conversations")
        for setter, key in self.context.state._tr:
            setter(self.t(key))
        input_widget = self.context.views.input
        set_character_placeholder = getattr(input_widget, "set_character_placeholder", None)
        if callable(set_character_placeholder):
            set_character_placeholder(getattr(getattr(self.context.state, "front", None), "cid", "kira"),
                                      self.context.services.settings.get("ui_lang", "en"))
        else:
            input_widget.setPlaceholderText(self.t("input_ph"))
        if hasattr(self.context.state, "_menu_actions"):
            for action, key in zip(self.context.state._menu_actions, self.context.views.tab_keys):
                action.setText(self.t(key))
        self.window.setWindowTitle(f"Project {self.context.services.settings['assistant_name']}  {VERSION}")
        self.context.views.title.setText(f"Project {self.context.services.settings['assistant_name']}")
        self.set_status(*self.context.state._status[:1], **self.context.state._status[1])
        self.feature_controller("runtime").update_companion_btn()
        self.feature_controller("runtime").update_engine_label()
        self.refresh_tab_buttons()
        if hasattr(self.context.views, "help_page"):
            self.context.views.help_page.retranslate()
        if hasattr(self.context.views, "assistant_page"):
            self.context.views.assistant_page.retranslate()
        if hasattr(self.context.views, "preferences_page"):
            self.context.views.preferences_page.retranslate()
        if hasattr(self.context.views, "voice_page"):
            self.context.views.voice_page.retranslate()
        if hasattr(self.context.views, "appearance_page"):
            self.context.views.appearance_page.retranslate()
        if hasattr(self.context.views, "character_page"):
            self.context.views.character_page.retranslate()
        if hasattr(self.context.state, "_menu_actions"):
            for action, key in zip(self.context.state._menu_actions, self.context.views.tab_keys):
                action.setText(self.t(key))

    def on_voice_error(self, message):
        """Local voice failures are rate-limited so a broken model does not flood the chat."""
        now = time.monotonic()
        if now - getattr(self, "_voice_err_at", -1e9) < 600:
            return
        self._voice_err_at = now
        self.add_chat("error", message + "\n" + self.t("voice_err_hint"))

    # ---------- chat sessions (one independent conversation per character) ----------

    @contextlib.contextmanager
    def _as(self, session):
        """Run code as `session` (its history, router, stream state and character). Used by every worker / timer callback,
        so a reply for a background tab is handled exactly like one for the visible tab - just without voice / face / status."""
        prev, prev_cid = self.context.state.cur, self.context.services.settings.get("active_character_id", "kira")
        self.context.state.cur = session
        self.context.services.settings["active_character_id"] = session.cid
        try:
            profile = self.context.services.character_service.all_profiles(self.context.services.settings).get(session.cid) or {}
            with self.context.services.mood_service.character_scope(
                session.cid, self.character_traits(session.cid, profile)
            ):
                yield session
        finally:
            self.context.state.cur = prev if self.context.state.sessions.get(prev.cid) is prev else self.context.state.front
            self.context.services.settings["active_character_id"] = prev_cid

    def theme_for_character(self, character_id, profile=None):
        """Resolve a character palette with the saved user-selected accent colour."""
        cid = str(character_id or "kira")
        selected = dict(profile or self.context.services.character_service.all_profiles(self.context.services.settings).get(cid, {}))
        custom = (self.context.services.settings.get("character_theme_colors") or {}).get(cid)
        if custom:
            selected["theme_color"] = custom
        return theme_mod.character_theme(cid, selected)

    def accent(self):
        theme = getattr(self.context.state.cur, "theme", None)
        return theme_mod.chat_accent(theme) if theme else None

    def _new_router(self):
        """Router of one chat. Cooldowns / health are shared with the other chats (a failing key is failing for everyone)."""
        return self.context.services.provider_application_service.create_router(self.context.services.settings)

    def make_session_view(self):
        view = QTextBrowser()                              # read-only chat whose links open in the default browser
        view.setObjectName("chatView")
        view.setOpenLinks(False)                           # links are handled in on_chat_link (web pages + Kode approval links)
        view.setOpenExternalLinks(False)
        view.anchorClicked.connect(self.on_chat_link)
        view.setReadOnly(True)
        view.setFrameShape(QFrame.NoFrame)
        # Give the message viewport usable vertical space; its scrollbar keeps the
        # entire conversation reachable without compressing the history region.
        view.setMinimumHeight(180)
        view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        delete_key(view, lambda: self.feature_controller("runtime").clear_chat())     # Delete in the chat = clear it (asks first)
        return view

    def on_chat_link(self, url):
        """Web/mail links open externally; kode:// handles Kode actions (legacy kira-code:// links remain supported)."""
        if url.scheme() == "kira-action":
            self.handle_chat_link(url)
            return
        if url.scheme() in ("kode", "kira-code"):
            code_chat = getattr(self.context.views, "code_chat", None)
            if code_chat is not None:
                code_chat.on_link(url)
            return
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def active_character(self):
        """Full profile of the character in front. Kira keeps her canonical identity (the profiles list only carries UI data)."""
        cid = getattr(getattr(self.context.state, "cur", None), "cid", "") or self.context.services.character_service.active_id(self.context.services.settings)
        if cid == "kira":
            profile = dict(KIRA_PROFILE)
        else:
            profile = dict(self.context.services.character_service.all_profiles(self.context.services.settings).get(cid) or self.context.services.character_service.active(self.context.services.settings))
        traits = (self.context.services.settings.get("character_traits") or {}).get(cid)
        if isinstance(traits, dict):
            profile["traits"] = {**profile.get("traits", {}), **traits}
        return profile

    def character_traits(self, cid, profile=None):
        """Baseline traits of one character (settings overrides win over the built-in defaults)."""
        profile = profile if isinstance(profile, dict) else (self.context.services.character_service.all_profiles(self.context.services.settings).get(cid) or {})
        traits = dict(profile.get("traits") or {})
        override = (self.context.services.settings.get("character_traits") or {}).get(cid)
        if isinstance(override, dict):
            traits.update(override)
        return traits

    def _sync_mood_character(self):
        """Refresh one character's baseline traits without changing the visible/default Mood context."""
        cid = getattr(getattr(self.context.state, "cur", None), "cid", "") or self.context.services.character_service.active_id(self.context.services.settings)
        profile = self.context.services.character_service.all_profiles(self.context.services.settings).get(cid) or {}
        try:
            self.context.services.mood_service.set_character_traits(cid, self.character_traits(cid, profile))
        except Exception:                                   # noqa: BLE001 - mood is a bonus, never block the UI
            _log.debug("Could not synchronize character mood traits", exc_info=True)

    @staticmethod
    def _schedule_chat_callback(callback):
        QTimer.singleShot(0, callback)

    def new_chat(self):
        """Create a separate durable conversation; older conversations remain selectable."""
        session = self.context.state.cur
        service = self.context.services.chat_application_service
        if session.busy or service.pending_count(session.session_id):
            self.context.views.status.setText(
                "بعد از پایان پاسخ فعلی می‌توانی گفتگوی جدید بسازی."
                if self.context.services.settings.get("ui_lang", "en") == "fa"
                else "Start a new conversation after the current response finishes."
            )
            return False
        try:
            record = service.create_conversation(session.cid)
            conversation_id = (
                record.get("id") or record.get("conversation_id")
                if isinstance(record, dict) else None
            )
            if not conversation_id:
                raise RuntimeError("ذخیره‌ساز شناسهٔ گفتگوی جدید را برنگرداند.")

            previous_id = str(session.conversation_id or "")
            if previous_id:
                session._conversation_drafts[previous_id] = self.context.views.input.text()
            session.conversation_id = str(conversation_id)
            session.draft = ""
            session.loaded = True
            self.context.views.input.clear()
            if session.view is not None:
                session.view.clear()
            with self._as(session):
                self.add_chat("assistant", self.greeting_text())
            self.refresh_conversation_list()
            self.context.views.status.setText(
                "گفتگوی جدید ساخته شد؛ گفتگوهای قبلی در فهرست کنار چت باقی مانده‌اند."
                if self.context.services.settings.get("ui_lang", "en") == "fa"
                else "New conversation created. Previous chats remain in the sidebar."
            )
            return True
        except Exception as exc:
            _log.exception("Could not create a new chat conversation")
            self.context.views.status.setText(
                "ساخت گفتگوی جدید ناموفق بود: " + str(exc)[:180]
            )
            return False

    def refresh_conversation_list(self):
        """Render title-only, unboxed conversation rows with hover timestamps and action menus."""
        widget = getattr(self.context.views, "conversation_list", None)
        session = getattr(self.context.state, "front", None) or getattr(self.context.state, "cur", None)
        if widget is None or session is None:
            return False

        service = self.context.services.chat_application_service
        lang = self.context.services.settings.get("ui_lang", "en")
        try:
            records = service.list_conversations(
                session.cid, statuses=("active", "closed")
            )
        except Exception:
            _log.exception("Could not load the durable conversation sidebar")
            return False

        items = []
        current_id = str(session.conversation_id or "")
        for record in records:
            if not isinstance(record, dict):
                continue
            conversation_id = str(record.get("id") or record.get("conversation_id") or "")
            status = str(record.get("status") or "active")
            if not conversation_id or status not in ("active", "closed"):
                continue

            title = " ".join(str(record.get("title") or "").split())
            preview = ""
            if not title:
                try:
                    recent = service.recent_messages(
                        8, character_id=session.cid, conversation_id=conversation_id
                    )
                    preview = next(
                        (
                            " ".join(str(message.get("content") or "").split())
                            for message in reversed(recent)
                            if message.get("role") == "user"
                            and str(message.get("content") or "").strip()
                        ),
                        "",
                    )
                except Exception:
                    _log.debug("Could not load conversation preview %s", conversation_id, exc_info=True)

            label = title or preview or ("گفتگوی جدید" if lang == "fa" else "New chat")
            if len(label) > 48:
                label = label[:47].rstrip() + "…"

            metadata = record.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            pinned = bool(metadata.get("_ui_pinned"))

            activity = str(record.get("updated_at") or record.get("created_at") or "")
            activity = activity.replace("T", " ").replace("Z", "").strip()[:19]
            date_tooltip = (
                f"آخرین فعالیت: {activity}" if lang == "fa" and activity
                else f"Last activity: {activity}" if activity
                else ("تاریخ در دسترس نیست" if lang == "fa" else "Date unavailable")
            )
            items.append((pinned, conversation_id, label, date_tooltip))

        # Keep the repository's recent-first order within pinned and unpinned groups.
        items.sort(key=lambda item: item[0], reverse=True)

        was_blocked = widget.blockSignals(True)
        try:
            widget.clear()
            selected = None
            for pinned, conversation_id, label, date_tooltip in items:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, conversation_id)
                item.setToolTip(date_tooltip)
                widget.addItem(item)

                row_widget = QWidget(widget)
                row_widget.setObjectName("conversationRow")
                row_widget.setLayoutDirection(Qt.LeftToRight)
                row_widget.setProperty("active", conversation_id == current_id)
                row_widget.setToolTip(date_tooltip)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(2, 0, 2, 0)
                row_layout.setSpacing(3)

                display_label = label if len(label) <= 19 else label[:18].rstrip() + "…"
                open_button = QPushButton(display_label, row_widget)
                open_button.setObjectName("conversationOpenButton")
                open_button.setFlat(True)
                open_button.setMinimumWidth(0)
                open_button.setFixedHeight(32)
                open_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                open_button.setLayoutDirection(Qt.RightToLeft if lang == "fa" else Qt.LeftToRight)
                open_button.setCursor(Qt.PointingHandCursor)
                open_button.setToolTip(date_tooltip)
                open_button.clicked.connect(
                    lambda checked=False, cid=conversation_id: self.switch_conversation(cid)
                )

                if pinned:
                    pin_button = QToolButton(row_widget)
                    pin_button.setObjectName("conversationPinIndicator")
                    pin_button.setIcon(make_icon(
                        "pin", normal="#D5D8E0", hover="#FFFFFF",
                        checked="#FFFFFF", disabled="#8A8F9B",
                    ))
                    pin_button.setIconSize(QSize(14, 14))
                    pin_button.setFixedSize(24, 26)
                    pin_button.setAutoRaise(True)
                    pin_button.setFocusPolicy(Qt.NoFocus)
                    pin_button.setToolTip(
                        "گفتگوی سنجاق‌شده" if lang == "fa" else "Pinned conversation"
                    )

                more_button = QToolButton(row_widget)
                more_button.setObjectName("conversationMenuButton")
                more_button.setText("⋯")
                more_button.setFixedSize(26, 26)
                more_button.setAutoRaise(True)
                more_button.setFocusPolicy(Qt.NoFocus)
                more_button.setCursor(Qt.PointingHandCursor)
                more_button.setToolTip(
                    "گزینه‌های گفتگو" if lang == "fa" else "Conversation options"
                )

                menu = QMenu(more_button)
                menu.setLayoutDirection(Qt.RightToLeft if lang == "fa" else Qt.LeftToRight)
                rename_action = menu.addAction("تغییر نام" if lang == "fa" else "Rename")
                share_action = menu.addAction(
                    "اشتراک‌گذاری (کپی متن)" if lang == "fa" else "Share (copy text)"
                )
                pin_action = menu.addAction(
                    "برداشتن سنجاق" if lang == "fa" and pinned
                    else "سنجاق کردن" if lang == "fa"
                    else "Unpin" if pinned else "Pin"
                )
                menu.addSeparator()
                delete_action = menu.addAction("حذف گفتگو" if lang == "fa" else "Delete conversation")
                rename_action.triggered.connect(
                    lambda checked=False, cid=conversation_id: self.rename_conversation(cid)
                )
                share_action.triggered.connect(
                    lambda checked=False, cid=conversation_id: self.share_conversation(cid)
                )
                pin_action.triggered.connect(
                    lambda checked=False, cid=conversation_id: self.pin_conversation(cid)
                )
                delete_action.triggered.connect(
                    lambda checked=False, cid=conversation_id: self.delete_conversation(cid)
                )
                more_button.setMenu(menu)
                more_button.setPopupMode(QToolButton.InstantPopup)

                row_layout.addWidget(open_button, 1)
                if pinned:
                    row_layout.addWidget(pin_button, 0)
                row_layout.addWidget(more_button, 0)
                item.setSizeHint(QSize(0, 36))
                widget.setItemWidget(item, row_widget)
                if conversation_id == current_id:
                    selected = item

            if selected is not None:
                widget.setCurrentItem(selected)
            widget.setToolTip(
                "برای باز کردن گفتگو انتخابش کن؛ تاریخ با نگه‌داشتن موس نمایش داده می‌شود."
                if lang == "fa"
                else "Select a conversation to reopen it. Hover to see its date."
            )
        finally:
            widget.blockSignals(was_blocked)
        return True

    def _owned_conversation_record(self, conversation_id, session=None):
        session = session or self.context.state.cur
        target_id = str(conversation_id or "").strip()
        if not target_id:
            raise ValueError("conversation_id is required")
        record = self.context.services.chat_application_service.get_conversation(target_id)
        if (
            not isinstance(record, dict)
            or str(record.get("id") or "") != target_id
            or str(record.get("character_id") or "") != str(session.cid)
            or str(record.get("status") or "active") not in ("active", "closed")
        ):
            raise ValueError("این گفتگو برای شخصیت فعال در دسترس نیست.")
        return record

    def rename_conversation(self, conversation_id):
        """Persist a user-defined title for one owned conversation."""
        session = self.context.state.cur
        service = self.context.services.chat_application_service
        lang = self.context.services.settings.get("ui_lang", "en")
        try:
            record = self._owned_conversation_record(conversation_id, session)
            current_title = str(record.get("title") or "")
            title, accepted = QInputDialog.getText(
                self.window,
                "تغییر نام گفتگو" if lang == "fa" else "Rename conversation",
                "نام جدید:" if lang == "fa" else "New title:",
                QLineEdit.Normal,
                current_title,
            )
            if not accepted:
                return False
            title = " ".join(str(title or "").split())
            if not service.update_conversation(str(conversation_id), title=title):
                raise RuntimeError("ذخیره نام جدید انجام نشد.")
            self.refresh_conversation_list()
            self.context.views.status.setText(
                "نام گفتگو ذخیره شد." if lang == "fa" else "Conversation renamed."
            )
            return True
        except Exception as exc:
            _log.exception("Could not rename conversation %s", conversation_id)
            self.context.views.status.setText(
                "تغییر نام ناموفق بود: " + str(exc)[:140]
                if lang == "fa" else "Rename failed: " + str(exc)[:140]
            )
            return False

    def share_conversation(self, conversation_id):
        """Copy a complete plain-text transcript so it can be shared in any app."""
        session = self.context.state.cur
        service = self.context.services.chat_application_service
        lang = self.context.services.settings.get("ui_lang", "en")
        try:
            record = self._owned_conversation_record(conversation_id, session)
            count = service.message_count(session.cid, str(conversation_id))
            messages = (
                service.get_messages(
                    max(1, int(count)),
                    character_id=session.cid,
                    conversation_id=str(conversation_id),
                )
                if count else []
            )
            title = str(record.get("title") or "").strip()
            lines = [f"# {title}" if title else ("گفتگو" if lang == "fa" else "Conversation")]
            for message in messages:
                role = str(message.get("role") or "")
                if role not in ("user", "assistant"):
                    continue
                body = str(message.get("content") or "").strip()
                if not body:
                    continue
                speaker = (
                    "شما" if lang == "fa" and role == "user"
                    else "دستیار" if lang == "fa"
                    else "You" if role == "user"
                    else "Assistant"
                )
                lines.append(f"{speaker}:\n{body}")
            transcript = "\n\n".join(lines)
            QApplication.clipboard().setText(transcript)
            self.context.views.status.setText(
                "متن گفتگو برای اشتراک‌گذاری کپی شد."
                if lang == "fa" else "Conversation transcript copied for sharing."
            )
            return True
        except Exception as exc:
            _log.exception("Could not share conversation %s", conversation_id)
            self.context.views.status.setText(
                "اشتراک‌گذاری ناموفق بود: " + str(exc)[:140]
                if lang == "fa" else "Sharing failed: " + str(exc)[:140]
            )
            return False

    def pin_conversation(self, conversation_id):
        """Persist a pin flag in conversation metadata and move pinned rows to the top."""
        service = self.context.services.chat_application_service
        session = self.context.state.cur
        lang = self.context.services.settings.get("ui_lang", "en")
        try:
            record = self._owned_conversation_record(conversation_id, session)
            metadata = record.get("metadata")
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            pinned = not bool(metadata.get("_ui_pinned"))
            metadata["_ui_pinned"] = pinned
            if not service.update_conversation(str(conversation_id), metadata=metadata):
                raise RuntimeError("ذخیره وضعیت سنجاق انجام نشد.")
            self.refresh_conversation_list()
            self.context.views.status.setText(
                "گفتگو سنجاق شد." if lang == "fa" and pinned
                else "سنجاق گفتگو برداشته شد." if lang == "fa"
                else "Conversation pinned." if pinned
                else "Conversation unpinned."
            )
            return True
        except Exception as exc:
            _log.exception("Could not pin conversation %s", conversation_id)
            self.context.views.status.setText(
                "تغییر وضعیت سنجاق ناموفق بود: " + str(exc)[:140]
                if lang == "fa" else "Pin update failed: " + str(exc)[:140]
            )
            return False

    def delete_conversation(self, conversation_id):
        """Move one owned conversation to trash after explicit user confirmation."""
        session = self.context.state.cur
        service = self.context.services.chat_application_service
        target_id = str(conversation_id or "").strip()
        if not target_id:
            return False

        lang = self.context.services.settings.get("ui_lang", "en")
        if session.busy or service.pending_count(session.session_id):
            self.context.views.status.setText(
                "برای حذف گفتگو، ابتدا پاسخ فعلی را متوقف یا کامل کن."
                if lang == "fa"
                else "Finish or stop the current response before deleting a chat."
            )
            return False

        try:
            record = service.get_conversation(target_id)
            if (
                not isinstance(record, dict)
                or str(record.get("id") or "") != target_id
                or str(record.get("character_id") or "") != str(session.cid)
                or str(record.get("status") or "active") not in ("active", "closed")
            ):
                raise ValueError("این گفتگو برای شخصیت فعال در دسترس نیست.")

            answer = QMessageBox.question(
                self.window,
                "حذف گفتگو" if lang == "fa" else "Delete conversation",
                (
                    "این گفتگو به سطل منتقل می‌شود و تاریخچهٔ آن قابل بازیابی خواهد بود. ادامه می‌دهی؟"
                    if lang == "fa"
                    else "Move this conversation to trash? Its history can still be restored."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False

            was_current = target_id == str(session.conversation_id or "")
            if was_current and not self.new_chat():
                return False

            result = service.trash_conversation(target_id)
            if not getattr(result, "success", False):
                if was_current:
                    self.switch_conversation(target_id)
                raise RuntimeError("ذخیره‌ساز نتوانست گفتگو را به سطل منتقل کند.")

            session._conversation_drafts.pop(target_id, None)
            self.refresh_conversation_list()
            self.context.views.status.setText(
                "گفتگو به سطل منتقل شد."
                if lang == "fa"
                else "Conversation moved to trash."
            )
            return True
        except Exception as exc:
            _log.exception("Could not move conversation %s to trash", target_id)
            self.context.views.status.setText(
                "حذف گفتگو ناموفق بود: " + str(exc)[:160]
                if lang == "fa"
                else "Could not delete conversation: " + str(exc)[:160]
            )
            self.refresh_conversation_list()
            return False

    def switch_conversation(self, conversation_id):
        """Reopen one saved conversation without deleting or merging any history."""
        session = self.context.state.cur
        service = self.context.services.chat_application_service
        target_id = str(conversation_id or "").strip()
        if not target_id:
            return False
        if target_id == str(session.conversation_id or ""):
            self.refresh_conversation_list()
            return True
        if session.busy or service.pending_count(session.session_id):
            self.context.views.status.setText(
                "برای جابه‌جایی گفتگو، ابتدا پاسخ فعلی را متوقف یا کامل کن."
                if self.context.services.settings.get("ui_lang", "en") == "fa"
                else "Finish or stop the current response before switching chats."
            )
            self.refresh_conversation_list()
            return False

        try:
            record = service.get_conversation(target_id)
            if (
                not isinstance(record, dict)
                or str(record.get("id") or "") != target_id
                or str(record.get("character_id") or "") != str(session.cid)
                or str(record.get("status") or "active") not in ("active", "closed")
            ):
                raise ValueError("این گفتگو برای شخصیت فعال در دسترس نیست.")
            message_count = service.message_count(session.cid, target_id)
            history = (
                service.get_messages(
                    max(1, int(message_count)),
                    character_id=session.cid,
                    conversation_id=target_id,
                )
                if message_count else []
            )
            if session.view is None:
                raise RuntimeError("نمای گفتگوی فعال آماده نیست.")

            previous_id = str(session.conversation_id or "")
            previous_draft = self.context.views.input.text()
            previous_html = session.view.toHtml()
            previous_loaded = session.loaded
            drafts = session._conversation_drafts
            if previous_id:
                drafts[previous_id] = previous_draft
            next_draft = drafts.pop(target_id, "")

            try:
                session.view.clear()
                session.conversation_id = target_id
                session.draft = next_draft
                session.loaded = True
                self.context.views.input.setText(next_draft)
                was_suppressed = getattr(self, "_suppress_conversation_refresh", False)
                self._suppress_conversation_refresh = True
                try:
                    with self._as(session):
                        self._render_history_items(history)
                finally:
                    self._suppress_conversation_refresh = was_suppressed
            except Exception:
                session.conversation_id = previous_id or None
                session.draft = previous_draft
                session.loaded = previous_loaded
                drafts[target_id] = next_draft
                self.context.views.input.setText(previous_draft)
                session.view.setHtml(previous_html)
                raise

            bubble = getattr(self.context.adapters, "bubble", None)
            if bubble is not None:
                try:
                    with self._as(session):
                        self.sync_bubble_history(bubble)
                except Exception:
                    _log.debug("Could not refresh companion bubble for reopened conversation", exc_info=True)
            self.refresh_conversation_list()
            self.context.views.status.setText(
                "گفتگوی قبلی باز شد؛ تاریخچهٔ آن حفظ شده است."
                if self.context.services.settings.get("ui_lang", "en") == "fa"
                else "Previous conversation reopened. Its history is intact."
            )
            return True
        except Exception as exc:
            _log.exception("Could not reopen conversation %s", target_id)
            self.context.views.status.setText("باز کردن گفتگو ناموفق بود: " + str(exc)[:160])
            self.refresh_conversation_list()
            return False

    def _schedule_conversation_list_refresh(self):
        """Coalesce refreshes from live message bubbles after persistence has completed."""
        if getattr(self, "_suppress_conversation_refresh", False):
            return
        if getattr(self, "_conversation_list_refresh_scheduled", False):
            return
        self._conversation_list_refresh_scheduled = True
        QTimer.singleShot(350, self._run_conversation_list_refresh)

    def _run_conversation_list_refresh(self):
        self._conversation_list_refresh_scheduled = False
        self.refresh_conversation_list()

    def _render_history_items(self, history):
        """Paint a bounded message page into the selected conversation view."""
        shown = 0
        for item in history:
            role = item.get("role")
            if role == "assistant":
                text = self.context.adapters.director.parse_reply(item.get("content", "")).text
            elif role == "user":
                text = item.get("content", "")
            else:
                continue
            if str(text).strip():
                self.add_chat(role, text)
                shown += 1
        if shown:
            self.add_chat("system", self.t("history_restored"))
        else:
            self.add_chat("assistant", self.greeting_text())
        return shown

    def _ensure_session_conversation(self, session):
        return self.context.services.session_application_service.bind_conversation(session)

    def _publish_session_state_event(self, event):
        """Compatibility callback; event translation belongs to the application service."""
        self.context.services.session_application_service.publish_state_change(event)

    def _ensure_character_tab_button(self, character_id, profile=None):
        """Create the lightweight navigation button without creating a ChatSession."""
        buttons = self.context.views.char_tab_buttons
        button = buttons.get(character_id)
        if button is None:
            button = QPushButton(self.window)
            button.setObjectName("charTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False, c=character_id: self.switch_session(c))
            self.context.views.char_tab_group.addButton(button)
            buttons[character_id] = button
        return button

    def _create_session_vision_router(self, session):
        """Create a cancellation-isolated Vision transport owned by exactly one Session."""
        provider_service = self.context.services.provider_application_service
        router = provider_service.create_isolated_router(
            self.context.services.settings,
            previous_router=session.client,
        )
        manager = getattr(self.context.services, "session_manager", None)
        state = getattr(self.context, "state", None)
        sessions = (
            manager.list_sessions()
            if manager is not None
            else tuple(getattr(state, "sessions", {}).values()) if state is not None else ()
        )
        for other in sessions:
            if other is session:
                continue
            if router is getattr(other, "vision_router", None) or router is getattr(other, "client", None):
                raise RuntimeError("Vision router factory reused a router owned by another Session")
        return router

    def _ensure_session_ui_resources(self, session, profile):
        """Attach Qt resources only when a character chat is opened."""
        if session.view is None:
            session.view = self.make_session_view()
            self.context.views.chat_stack.addWidget(session.view)
            session.timer = QTimer(self.window)
            session.timer.setInterval(60)
            session.relay = SessionRelay(self.context, session, self.window)
            session.timer.timeout.connect(session.relay.tick)
        if session.client is None:
            session.client = self._new_router()
        if getattr(session, "vision_router", None) is None:
            session.vision_router = self._create_session_vision_router(session)
        session.theme = self.theme_for_character(session.cid, profile)

    def _ensure_session(self, cid, profile):
        return self.context.services.session_application_service.ensure_session(
            cid,
            profile,
            ensure_resources=self._ensure_session_ui_resources,
        )

    def _restore_session_history(self, session):
        with self._as(session):
            return self.restore_history()

    def sync_sessions(self):
        """Keep every character selectable while realizing only active/existing Sessions."""
        profiles = self.context.services.character_service.all_profiles(self.context.services.settings)
        active_id = getattr(self.context.state.front, "cid", None) or self.context.services.character_service.active_id(
            self.context.services.settings
        )
        order = self.context.services.session_application_service.sync_sessions(
            profiles,
            ensure_resources=self._ensure_session_ui_resources,
            restore_history=self._restore_session_history,
            active_character_id=active_id,
        )
        for cid in order:
            self._ensure_character_tab_button(cid, profiles.get(cid))

        # Deleted profiles without a realized Session have no resource-release callback.
        for cid in tuple(self.context.views.char_tab_buttons):
            if cid in order:
                continue
            button = self.context.views.char_tab_buttons.pop(cid)
            self.context.views.char_tabs_row.removeWidget(button)
            self.context.views.char_tab_group.removeButton(button)
            button.deleteLater()

        while self.context.views.char_tabs_row.count():
            self.context.views.char_tabs_row.takeAt(0)
        add_button = self._ensure_add_character_button()
        add_button_placed = False
        for cid in order:
            button = self.context.views.char_tab_buttons.get(cid)
            if button is not None:
                self.context.views.char_tabs_row.addWidget(button)
            if cid == "mika":
                self.context.views.char_tabs_row.addWidget(add_button)
                add_button_placed = True
        if not add_button_placed:
            self.context.views.char_tabs_row.addWidget(add_button)
        self.context.views.char_tabs_row.addStretch(1)
        self.refresh_tab_buttons()

    @staticmethod
    def _worker_is_running(worker):
        from ..app.session_application import SessionApplicationService
        return SessionApplicationService.worker_is_running(worker)

    def _session_has_pending_chat_work(self, session):
        if getattr(session, "status", "") == "closing":
            with self._as(session):
                self.feature_controller("attachments_vision")._cancel_vision_worker(session)
        if self.context.services.session_application_service.has_pending_work(session):
            return True
        vision_service = self.context.services.vision_application_service
        return vision_service.has_pending_frame_work(session.session_id)

    def _dispose_chat_session(self, session):
        with self._as(session):
            self.feature_controller("attachments_vision")._cancel_vision_worker(session)
        return self.context.services.session_application_service.close_session(session)

    def _release_chat_session_resources(self, session):
        """Release UI/provider resources after SessionManager confirms the work has drained."""
        self.context.services.vision_application_service.cancel_frame_session(session.session_id)
        self.context.services.chat_application_service.close_session(session.session_id)
        self.context.services.tool_agent.release_session(session.cid)
        session.dispatch_scheduled = False
        getattr(session, "response_relay", None)
        if session.client is not None:
            session.client.cancel()
            session.client = None
        for worker_name in ("worker", "_search_worker"):
            worker = getattr(session, worker_name, None)
            if worker is not None:
                try:
                    worker.deleteLater()
                except RuntimeError:
                    pass
                setattr(session, worker_name, None)
        if session.timer is not None:
            session.timer.stop()
            session.timer.deleteLater()
            session.timer = None
        if session.relay is not None:
            session.relay.deleteLater()
            session.relay = None
        if session.view is not None:
            self.context.views.chat_stack.removeWidget(session.view)
            session.view.deleteLater()
            session.view = None
        button = self.context.views.char_tab_buttons.pop(session.cid, None)
        if button is not None:
            self.context.views.char_tabs_row.removeWidget(button)
            self.context.views.char_tab_group.removeButton(button)
            button.deleteLater()
        if getattr(session, "_vision_session", None) is session:
            vision_worker = getattr(session, "_vision_worker", None)
            if vision_worker is not None:
                try:
                    vision_worker.deleteLater()
                except RuntimeError:
                    pass
                session._vision_worker = None
            session._vision_session = None
        vision_router = getattr(session, "vision_router", None)
        if vision_router is not None:
            vision_router.cancel()
            session.vision_router = None
        session._vision_frame_context = None
        if not getattr(self.context.state, "_closing", False) and (self.context.state.front is session or self.context.state.cur is session):
            fallback = next(
                (item for item in self.context.services.session_manager.list_sessions()
                 if item is not session and item.status not in ("closing", "closed", "failed")),
                None,
            )
            if fallback is not None:
                self.switch_session(fallback.cid)
        return True

    def _ensure_add_character_button(self):
        button = getattr(self, "_char_add_button", None)
        if button is None:
            parent = self.context.views.char_tabs_row.parentWidget()
            button = QPushButton("＋ ساخت کاراکتر جدید", parent)
            button.setObjectName("charAddButton")
            button.setFixedSize(166, 36)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(
                lambda checked=False: self.feature_controller("character_settings").add_character()
            )
            self._char_add_button = button
        lang = self.context.services.settings.get("ui_lang", "en")
        button.setText("＋ ساخت کاراکتر جدید" if lang == "fa" else "＋ New character")
        button.setToolTip(
            "ساخت یک شخصیت جدید" if lang == "fa" else "Create a new character"
        )
        return button

    def refresh_tab_buttons(self):
        profiles = self.context.services.character_service.all_profiles(self.context.services.settings)
        for cid, button in self.context.views.char_tab_buttons.items():
            sess = self.context.state.sessions.get(cid)
            profile = profiles.get(cid) or {}
            name = profile.get("name_fa") if self.context.services.settings.get("ui_lang", "en") == "fa" else profile.get("name")
            mark = ""
            if sess is not None and sess.busy:
                mark = "  ⏳"
            elif sess is not None and sess.unread:
                mark = "  ●"
            button.setText(f"{name or cid}{mark}")
            button.setChecked(sess is self.context.state.front)

    def switch_session(self, cid, save=True):
        """Open a character ChatSession on demand, then bring it to the front."""
        profiles = self.context.services.character_service.all_profiles(self.context.services.settings)
        sess = self.context.state.sessions.get(cid)
        profile = profiles.get(cid)
        # A deleted character may retain an in-flight Session until its work drains.
        # Keep that already-existing conversation reachable; do not create new ones.
        if profile is None and sess is None:
            return
        if profile is None:
            profile = {}
        if sess is None or sess.view is None or sess.client is None:
            sess = self._ensure_session(cid, profile)
            if sess is None:
                return
            self._ensure_character_tab_button(cid, profile)
        if not sess.loaded:
            try:
                restored = self._restore_session_history(sess)
            except Exception:
                _log.exception("Could not restore character history for %s", cid)
                restored = False
            if restored is not False:
                sess.loaded = True
                self.context.services.session_application_service.publish_history_loaded(sess)
        if not self.context.services.session_application_service.activate_session(sess.session_id):
            return
        character_controller = self.context.get_peer_if_materialized("character_settings")
        if cid != self.context.state.front.cid and character_controller is not None:
            character_controller._flush_character_autosave()
        old = self.context.state.front
        if old is not sess:
            old.draft = self.context.views.input.text()
            if old._speech_live:                       # the voice belongs to the chat in front
                old._speech_live = False
            self.feature_controller("runtime").safe_stop_speaker()
            try:
                self.context.services.voice_application_service.stream_reset()
            except Exception:                           # noqa: BLE001
                _log.exception("Could not reset streamed voice while switching characters")
            attachment_controller = self.context.get_peer_if_materialized("attachments_vision")
            if attachment_controller is not None:
                attachment_controller.clear_upload_tiles()
        self.context.state.front = self.context.state.cur = sess
        sess.unread = False
        self.context.services.settings["active_character_id"] = cid
        set_character_placeholder = getattr(self.context.views.input, "set_character_placeholder", None)
        if callable(set_character_placeholder):
            set_character_placeholder(cid, self.context.services.settings.get("ui_lang", "en"))
        self.refresh_navigation_icons()
        try:
            self.context.services.mood_service.set_active_character(cid, self.character_traits(cid, self.context.services.character_service.all_profiles(self.context.services.settings).get(cid)))
        except Exception:                               # noqa: BLE001 - never block switching tabs
            _log.debug("Could not activate character mood runtime", exc_info=True)
        self.context.views.chat_stack.setCurrentWidget(sess.view)
        self.feature_controller("voice_settings").set_news_character(cid)
        if old is not sess:
            self.context.views.input.setText(sess.draft)
        self.apply_chat_theme()
        self.context.adapters.appearance_runtime.apply_character_art()
        self.context.views.gen_stop_btn.setVisible(bool(sess.busy))
        self.context.views.gen_stop_btn.setEnabled(True)
        if sess.busy:
            self.set_status("st_thinking")
        else:
            self.set_status("st_ready")
        phase, info = sess.badge
        self.feature_controller("runtime").set_badge(phase if sess.busy else "idle", info if sess.busy else self.context.session.client.preview_route())
        self.refresh_tab_buttons()
        character_controller = self.context.get_peer_if_materialized("character_settings")
        if hasattr(self.context.views, "character_page"):
            character_controller = self.context.require_peer("character_settings")
            character_controller.refresh_character_choices()
            character_controller.refresh_character_card(cid)
            character_controller.refresh_personality_controls()
        elif character_controller is not None:
            character_controller.refresh_personality_controls()
        self.update_mood_indicator()
        self.refresh_conversation_list()
        bar = sess.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        if save:
            try:
                save_settings(self.context.services.settings)
            except Exception:                           # noqa: BLE001 - never block switching tabs
                _log.exception("Could not persist active character selection")

    def apply_chat_theme(self):
        """Apply the active character's palette and optional character-owned background."""
        settings = self.context.services.settings
        session = self.context.state.front
        theme = session.theme or self.theme_for_character(session.cid)
        profile = self.context.services.character_service.all_profiles(settings).get(session.cid) or {}
        background = self.context.services.character_service.chat_background_file(profile, ROOT)
        self.context.views.chat_page.setStyleSheet(theme_mod.character_style(
            theme, getattr(self.context.state, "_effect", "off"),
            settings.get("appearance", {}), background_image=background,
        ))
        r, g, b = (int(theme["main"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for glow in self.context.views.glow_effects:
            appearance = self.context.services.settings.get("appearance", {})
            intensity = max(0, min(100, int(appearance.get("glow", 34))))
            glow.setBlurRadius(14 + intensity * 0.38)
            glow.setColor(QColor(r, g, b, round(54 + intensity * 0.92)))
        self.context.adapters.appearance_runtime._apply_neon_glow_effects(
            self.context.services.settings.get("appearance", {})
        )

    def greeting_text(self):
        profile = self.context.services.character_service.active(self.context.services.settings)
        if profile["id"] == "kira":
            return self.t("greeting")
        name = profile.get("name_fa") if self.context.services.settings.get("ui_lang", "en") == "fa" else profile.get("name")
        if self.context.services.settings.get("ui_lang", "en") == "fa":
            return f"سلام! من {name} هستم. {profile.get('description', '')}"
        return f"Hi! I'm {name}. {profile.get('description', '')}"

    def sync_bubble_history(self, bubble):
        """Refresh the floating chat transcript for the active character session."""
        session = self.context.session
        history = self.context.services.chat_application_service.recent_messages(
            bubble.KEEP,
            character_id=session.cid,
            conversation_id=session.conversation_id,
        )
        items = []
        ui_dir = "rtl" if self.context.services.settings.get("ui_lang", "en") == "fa" else "ltr"
        assistant_name = self.context.services.character_service.display_name(
            self.context.services.settings
        )
        user_name = self.t("you")
        for item in history:
            role = item.get("role")
            if role == "assistant":
                text = self.context.adapters.director.parse_reply(
                    item.get("content", "")
                ).text
                name = assistant_name
            elif role == "user":
                text = item.get("content", "")
                name = user_name
            else:
                continue
            if str(text).strip():
                items.append((role, name, text))
        bubble.replace_history(items, ui_dir, session_marker(session))

    def restore_history(self, limit=40):
        """Show the saved conversation of the CURRENT chat again after a restart (it is already used as model context)."""
        try:
            self._ensure_session_conversation(self.context.state.cur)
            history = self.context.services.chat_application_service.recent_messages(
                limit, character_id=self.context.state.cur.cid, conversation_id=self.context.state.cur.conversation_id
            )
        except Exception:
            # Leave the Session unloaded so the next synchronization retries history.
            _log.exception("Could not restore persisted chat history")
            return False
        was_suppressed = getattr(self, "_suppress_conversation_refresh", False)
        self._suppress_conversation_refresh = True
        try:
            self._render_history_items(history)
        finally:
            self._suppress_conversation_refresh = was_suppressed
        self.refresh_conversation_list()
        return True

    def add_chat(self, kind, text, name=None, images=None):
        """Append one message bubble; direction is decided per line so Persian reads right-to-left.
        images: attachment dicts whose thumbnails are shown at the top of the bubble."""
        if name is None:
            name = {"user": self.t("you"), "assistant": self.active_character().get("name", "Character"),
                    "error": self.t("error"), "system": ""}.get(kind, "")
        ui_dir = "rtl" if self.context.services.settings.get("ui_lang", "en") == "fa" else "ltr"
        extra = self.thumbnail_html(images)
        footer = self.chat_actions_html(kind, text)
        with bubble_accent(self.accent()):
            self.context.session.view.append(message_html(kind, name, text, ui_dir, extra, footer))
        if getattr(self.context.adapters, "bubble", None) is not None:
            self.context.adapters.bubble.push(kind, name, text, ui_dir)
        bar = self.context.session.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        if kind in ("user", "assistant"):
            self._schedule_conversation_list_refresh()

    def maybe_proactive_checkin(self):
        """Apply desktop-only safety gates, then delegate Initiative policy to its application service."""
        monotonic_now = time.monotonic()
        if monotonic_now - getattr(self, "_initiative_checked_at", -1e9) < 30:
            return False
        self._initiative_checked_at = monotonic_now

        try:
            state = self.context.state
            session = getattr(state, "front", None)
            if session is None or state._closing or state.cur is not session:
                return False

            settings = self.context.services.settings
            character_id = str(getattr(session, "cid", "") or "")
            opt_ins = settings.get("character_initiative")
            # A literal JSON true is the only consent signal; corrupt values fail closed.
            if not character_id or not isinstance(opt_ins, dict) or opt_ins.get(character_id) is not True:
                return False

            # The person is usually away when a check-in is due, so the window need not be the active one (the message waits in the chat).
            if self.window.isMinimized() and not self.window.isVisible():
                return False
            if QApplication.activeModalWidget() is not None:
                return False
            sessions = tuple(state.sessions.values())
            if any(self._session_has_pending_chat_work(item) for item in sessions):
                return False
            if self._worker_is_running(getattr(session, "_vision_worker", None)):
                return False

            input_widget = getattr(self.context.views, "input", None)
            if input_widget is not None:
                for accessor_name in ("text", "toPlainText"):
                    accessor = getattr(input_widget, accessor_name, None)
                    if callable(accessor) and str(accessor() or "").strip():
                        return False

            # Never interrupt microphone capture, wake mode, or audio playback.
            if bool(getattr(state, "awake", False)):
                return False
            if bool(getattr(session, "_speech_live", False)) or bool(getattr(session, "_voice_next", False)):
                return False
            mic_button = getattr(self.context.views, "mic_btn", None)
            if mic_button is not None and callable(getattr(mic_button, "isChecked", None)) and mic_button.isChecked():
                return False
            voice = self.context.services.voice_application_service
            if voice.is_speaking() or getattr(voice, "stopping_listener", None) is not None:
                return False
            listener = getattr(voice, "listener", None)
            if listener is not None:
                running = getattr(listener, "is_running", None)
                if not callable(running) or running():
                    return False

            profiles = self.context.services.character_service.all_profiles(settings)
            traits_by_character = {
                str(profile_id): self.character_traits(str(profile_id), profile_data)
                for profile_id, profile_data in profiles.items()
            }
            result = self.context.services.initiative_application_service.run_checkin(
                session,
                profiles,
                traits_by_character,
                settings,
                sessions,
            )
            if result is None:
                return False

            settings["character_initiative_history"] = (
                self.context.services.initiative_application_service
                .merge_settings_history(settings, result)
            )
            state._save_warned = False
            self.feature_controller("runtime").save_now()
            # add_chat only paints the stored assistant message; there is no TTS or worker.
            self.add_chat("assistant", result.message)
            if not self.window.isActiveWindow():
                QApplication.alert(self.window, 0)          # flash the taskbar button: she wrote something
            return True
        except Exception:  # noqa: BLE001 - this optional feature must never interrupt chat
            _log.exception("Optional proactive Initiative check-in failed")
            return False

    def update_mood_indicator(self):
        """Render the active character's current emotion as a custom neon face; chat-message emoji are untouched."""
        label = getattr(self.context.views, "mood_indicator", None)
        face_label = getattr(self.context.views, "mood_emotion_icon", None)
        if label is None or face_label is None:
            return
        self._sync_mood_character()
        # The existing UI poll is the scheduler; this controller throttles it to 30 seconds.
        # maybe_proactive_checkin owns its logged fail-closed boundary.
        self.maybe_proactive_checkin()

        face_map = {
            "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry",
            "fearful": "fearful", "disgusted": "disgusted", "surprised": "surprised",
            "curious": "curious", "proud": "proud", "arrogant": "smug", "smug": "smug",
            "playful": "playful", "teasing": "teasing", "tsundere": "angry", "bored": "bored",
            "frustrated": "angry", "affectionate": "affectionate", "flirty": "flirty",
            "shy": "shy", "embarrassed": "shy", "jealous": "jealous", "laughing": "laughing",
            "annoyed": "angry", "protective": "protective", "excited": "excited",
            "thinking": "curious", "calm": "calm", "hopeful": "hopeful",
            "disappointed": "sad", "lonely": "sad", "guilty": "sad", "grateful": "affectionate",
            "nostalgic": "soft", "confident": "proud", "confused": "surprised",
            "relieved": "relieved", "content": "calm",
        }
        emotion_colors = {
            "neutral": "#B9D4F5", "calm": "#8FE8F2", "content": "#8FE8F2",
            "happy": "#FFD36E", "excited": "#FFC45E", "laughing": "#FFE078",
            "hopeful": "#A9F0C2", "grateful": "#FF9CE5",
            "sad": "#72B9FF", "disappointed": "#72B9FF", "lonely": "#78A8EE",
            "guilty": "#9AAFEF", "nostalgic": "#B4A8FF",
            "angry": "#FF668C", "frustrated": "#FF718A", "annoyed": "#FF7A91",
            "tsundere": "#FF8AAE", "jealous": "#FF79B8",
            "fearful": "#B59BFF", "disgusted": "#A4D77D",
            "surprised": "#64E7FF", "confused": "#73DFFF", "curious": "#67DFFF",
            "thinking": "#75DDF8", "proud": "#C7A0FF", "arrogant": "#C7A0FF",
            "smug": "#C7A0FF", "confident": "#C7A0FF",
            "playful": "#FFAE78", "teasing": "#FF9CCB",
            "affectionate": "#FF87D2", "flirty": "#FF78C5",
            "shy": "#FF9FCB", "embarrassed": "#FFA0C8",
            "protective": "#80D9C2", "relieved": "#9BEAD7",
            "bored": "#A9B7D2",
        }

        try:
            character_id = str(getattr(self.context.state.cur, "cid", "") or "")
            state = self.context.services.mood_service.current(
                character_id=character_id
            )
            emotion = str(state.get("emotion", "neutral") or "neutral").lower()
            behaviour = str(state.get("behavior", "balanced"))
            energy = str(state.get("energy_label", "normal"))
            intensity = int(state.get("intensity", 0) or 0)
            secondary_items = state.get("secondary_emotions") or []
            secondary_key = tuple(
                (str(item[0]), int(item[1]))
                for item in secondary_items[:2]
                if isinstance(item, (tuple, list)) and len(item) >= 2
            )
            secondary = ", ".join(name for name, _value in secondary_key)
            signature = (
                character_id, emotion, intensity, behaviour, energy, secondary_key
            )
            # Mood is polled periodically, but unchanged state should not rebuild
            # SVG icons, QPixmaps, stylesheets or tooltips every time.
            if signature == getattr(self, "_mood_indicator_signature", None):
                # The header constructs this label hidden; keep the actual emotion face visible
                # even when the persisted mood has not changed since the previous UI poll.
                face_label.setVisible(True)
                return
            icon_name = face_map.get(emotion, "neutral")
            neon = emotion_colors.get(emotion, "#69E5FF")
            face_icon = make_icon(
                f"emotion_{icon_name}", normal=neon, hover=neon,
                checked=neon, disabled="#52617B",
            )
            face_label.setPixmap(face_icon.pixmap(QSize(30, 30)))
            # ChatHeader initially hides both mood labels; the face must be explicitly shown.
            face_label.setVisible(True)
            face_label.setStyleSheet(
                "QLabel#moodEmotionIcon { background: rgba(12, 20, 43, 0.96); "
                f"border: 1px solid {neon}; border-radius: 11px; padding: 2px; }}"
            )
            glow = getattr(self.context.state, "_mood_emotion_glow", None)
            if glow is not None:
                glow_colour = QColor(neon)
                glow_colour.setAlpha(215)
                glow.setColor(glow_colour)

            # Behaviour and energy are represented by vector neon glyphs only.
            # Never place a plain Unicode emoji beside the neon emotion face.
            show_bolt = energy in {"active", "hyper"} or behaviour == "energetic"
            if show_bolt:
                bolt_colour = "#FFE36B" if energy == "hyper" else "#72F4FF"
                bolt = make_icon(
                    "energy_bolt", normal=bolt_colour, hover="#FFFFFF",
                    checked=bolt_colour, disabled="#52617B",
                )
                label.setPixmap(bolt.pixmap(QSize(23, 23)))
                label.setStyleSheet(
                    "QLabel#moodIndicator { background: rgba(22, 28, 65, 0.62); "
                    f"border: 1px solid {bolt_colour}; border-radius: 10px; padding: 2px; }}"
                )
                label.setVisible(True)
            else:
                label.clear()
                label.setVisible(False)
            tooltip = (
                f"احساس: {emotion} ({intensity}/100)\n"
                f"رفتار: {behaviour}\n"
                f"انرژی: {energy}"
            )
            if secondary:
                tooltip += f"\nاحساسات همراه: {secondary}"
            face_label.setToolTip(tooltip)
            label.setToolTip(tooltip)
            self._mood_indicator_signature = signature
        except Exception:                                    # noqa: BLE001 - the indicator must never break the window
            _log.exception("Could not render the active character mood indicator; using neutral fallback")
            fallback = make_icon("emotion_neutral", normal="#B9D4F5", hover="#B9D4F5",
                                 checked="#B9D4F5", disabled="#52617B")
            face_label.setPixmap(fallback.pixmap(QSize(30, 30)))
            face_label.setVisible(True)
            label.clear()
            label.setVisible(False)
            face_label.setToolTip("حال‌وهوای شخصیت فعال")

    def _chat_action_icon_url(self, view, action, icon_name, colour):
        """Register the SVG icon of a message action once per chat view; returns the URL used by <img>."""
        url = f"kira-icon://{action}"
        done = getattr(view, "_kira_icon_urls", None)
        if done is None:
            done = view._kira_icon_urls = set()
        if url not in done:
            pixmap = make_icon(icon_name, normal=colour, hover=colour, checked=colour, disabled=colour).pixmap(QSize(18, 18))
            view.document().addResource(QTextDocument.ImageResource, QUrl(url), pixmap)
            done.add(url)
        return url

    def chat_actions_html(self, kind, text):
        """Render compact, consistently sized message-action icon buttons."""
        if kind not in ("assistant", "user") or not str(text or "").strip():
            return ""
        self.context.state._chat_action_seq += 1
        key = str(self.context.state._chat_action_seq)
        self.context.state._chat_action_texts[key] = str(text)
        actions = [
            ("copy", "copy", "⧉", "#8CF5FF", "#103A52", "#39DFFF", "کپی"),
            ("edit", "pencil", "✎", "#E0C8FF", "#30214F", "#B18AFF", "ویرایش"),
        ]
        if kind == "assistant":
            actions.append(("speak", "speaker", "♫", "#FFC0E9", "#4B2044", "#FF83D0", "خواندن"))

        view = getattr(self.context.session, "view", None)
        cells = []
        for action, icon_name, glyph, colour, background, border, tooltip in actions:
            try:
                url = self._chat_action_icon_url(view, action, icon_name, colour)
                inner = f'<img src="{url}" width="16" height="16" align="middle">'
            except Exception:  # noqa: BLE001 - keep a visible fallback if SVG loading fails
                _log.debug("Could not load the SVG icon for chat action %s", action, exc_info=True)
                inner = f'<span style="color:{colour};font-size:13pt;">{glyph}</span>'
            cells.append(
                f'<td bgcolor="{background}" width="30" height="28" align="center" valign="middle" '
                f'style="border:1px solid {border};border-radius:8px;">'
                f'<a href="kira-action://{action}/{key}" title="{tooltip}" '
                f'style="text-decoration:none;">{inner}</a>'
                f'</td>'
            )
        return (
            '<table dir="rtl" align="right" border="0" cellspacing="4" cellpadding="0" '
            'style="margin-top:5px;border-top:1px solid #314968;padding-top:4px;">'
            f'<tr>{"".join(cells)}</tr></table>'
        )

    def handle_chat_link(self, url):
        """Handle local message actions while preserving normal external links."""
        if url.scheme() == "kira-action":
            action = url.host()
            key = url.path().strip("/")
            text = self.context.state._chat_action_texts.get(key)
            if text is None:
                return
            if action == "copy":
                QApplication.clipboard().setText(text)
                self.set_status("st_ready")
            elif action == "edit":
                self.context.views.input.setText(text)
                self.context.views.input.setFocus()
                self.context.views.input.moveCursor(QTextCursor.End)
            elif action == "speak":
                # Speaker.speak() owns cancellation/replacement of the previous session.
                self.context.services.voice_application_service.speak(text)
            return
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def thumbnail_html(self, images):
        parts = []
        for a in images or []:
            if a.get("kind") != "image":
                continue
            img = QImage()
            if not img.loadFromData(base64.b64decode(a["b64"])):
                continue
            img = img.scaledToWidth(min(220, img.width()), Qt.SmoothTransformation)
            self.context.state._att_seq += 1
            key = f"kira-att://{self.context.state._att_seq}"
            self.context.session.view.document().addResource(QTextDocument.ImageResource, QUrl(key), img)
            parts.append(f'<p style="margin:0 0 6px 0;"><img src="{key}" width="{img.width()}" height="{img.height()}"></p>')
        return "".join(parts)

    def on_input_changed(self, text):
        """Typed text flows in its own direction (Persian right-to-left, English left-to-right)."""
        ui_dir = "rtl" if self.context.services.settings.get("ui_lang", "en") == "fa" else "ltr"
        d = detect_direction(text, ui_dir)
        self.context.views.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)

    def sync_progress(self):
        """Draw Kira's current work stages as small lines at the end of the visible chat."""
        view = getattr(self.context.state.front, "view", None)
        previous = getattr(self, "_progress_view", None)
        if previous is not None and previous is not view:
            clear_progress(previous)               # the person switched tabs mid-request
        self._progress_view = view
        if view is None:
            return
        rtl = self.context.services.settings.get("ui_lang", "en") == "fa"
        apply_progress_to_view(view, self.context.views.kode_activity.visible_rows(), rtl)

    @front_only
    def set_status(self, key, **kw):
        self.context.state._status = (key, kw)
        thinking = key == "st_thinking"
        if thinking:
            # Work stages (incl. "thinking…") are drawn in the chat by sync_progress.
            self.context.views.kode_activity.ensure_running(self.t("st_thinking"))
            self.context.views.status.clear()
            self.context.views.status.hide()
        else:
            self.context.views.status.setText(self.t(key, **kw))
            self.context.views.status.show()

    # ---------- navigation / responsive layout ----------

    def go_tab(self, index):
        self.context.views.tabs.setCurrentIndex(index)
        self._sync_nav()

    def _sync_nav(self, _index=None):
        i = self.context.views.tabs.currentIndex()
        for index, button in enumerate(getattr(self.context.views, "nav_buttons", [])):
            button.setChecked(i == self.context.state._nav_icon_map[index][1])
        self.context.views.save_btn.setVisible(i != 0)            # the chat page needs no Save button
        if hasattr(self.context.views, "voice_page") and i == self.context.views.tab_keys.index("tab_voice"):
            self.feature_controller("voice_settings").refresh_voice_caps()               # Refresh local-only speech status

    def resizeEvent(self, event):
        self.qt_super_event("resizeEvent", event)
        card = getattr(self.context.views, "avatar_card", None)
        if card is not None:                         # narrow window: give the whole width to the conversation
            card.setVisible(self.window.width() >= 640)
            card.setFixedWidth(max(200, min(300, int(self.window.width() * 0.30))))

    # ---------- UI building ----------

    def row(self, form, key, widget):
        lab = QLabel()
        self.reg(lab.setText, key)
        form.addRow(lab, widget)
        return widget

    def group(self, key):
        box = QGroupBox()
        self.reg(box.setTitle, key)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignLeading)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        return box, form

    def page(self, *boxes):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        for b in boxes:
            lay.addWidget(b)
        lay.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(host)
        return sc

    def tidy_forms(self):
        """Use each page's available width instead of fixed pixel caps on controls."""
        for i in range(1, self.context.views.tabs.count()):  # page 0 is the chat
            page = self.context.views.tabs.widget(i)
            for widget in page.findChildren(QSpinBox) + page.findChildren(QDoubleSpinBox):
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            for widget in page.findChildren(QSlider):
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for widget in page.findChildren(QComboBox):
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for widget in page.findChildren(QLineEdit):
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for form in page.findChildren(QFormLayout):
                form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
                form.setRowWrapPolicy(QFormLayout.WrapLongRows)

    def icon_button(self, name, checkable=False):
        """Small neon icon button using the active character's own accent colours."""
        b = QToolButton()
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        profile = self.context.services.character_service.all_profiles(self.context.services.settings).get(cid, {})
        palette = self.theme_for_character(cid, profile)
        b.setProperty("kiraIconName", name)
        b.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                            checked=palette["main"], disabled="#52617B"))
        b.setIconSize(QSize(20, 20))
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def refresh_navigation_icons(self):
        """Keep shared navigation glyphs in sync when the active character changes."""
        cid = self.context.services.character_service.active_id(self.context.services.settings)
        profile = self.context.services.character_service.all_profiles(self.context.services.settings).get(cid, {})
        palette = self.theme_for_character(cid, profile)
        for button, (name, _tab_index) in zip(getattr(self.context.views, "nav_buttons", []), getattr(self.context.state, "_nav_icon_map", [])):
            button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))
        menu_button = getattr(self.context.views, "menu_btn", None)
        if menu_button is not None:
            menu_button.setIcon(make_icon("menu", normal=palette["second"], hover="#FFFFFF",
                                          checked=palette["main"], disabled="#52617B"))
        for action, (name, _tab_index) in zip(getattr(self.context.state, "_menu_actions", []), getattr(self.context.state, "_nav_icon_map", [])):
            action.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))
        badge = getattr(self.context.views, "route_badge", None)
        if badge is not None:
            badge.setIcon(make_icon("chevron_up", normal=palette["second"], hover="#FFFFFF",
                                    checked=palette["main"], disabled="#52617B"))
        self.context.adapters.appearance_runtime._refresh_icon_glow()


# Backward-compatible import name for callers migrating from mixin composition.
SessionMixin = SessionController
