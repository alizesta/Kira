"""Session-aware window coordination extracted from the legacy MainWindow."""

import contextlib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QPushButton, QTextBrowser

from .. import mood, theme as theme_mod
from ..characters.kira import PROFILE as KIRA_PROFILE
from ..config import save_settings
from ..hybrid_ai import HybridRouter
from .session_relay import SessionRelay


class SessionWindowMixin:
    """Owns character-session lifecycle and the window adapters it requires."""

    @contextlib.contextmanager
    def _as(self, session):
        """Run code as `session` (its history, router, stream state and character). Used by every worker / timer callback,
        so a reply for a background tab is handled exactly like one for the visible tab - just without voice / face / status."""
        prev, prev_cid = self.cur, self.settings.get("active_character_id", "kira")
        self.cur = session
        self.settings["active_character_id"] = session.cid
        try:
            yield session
        finally:
            self.cur = prev if self.sessions.get(prev.cid) is prev else self.front
            self.settings["active_character_id"] = prev_cid

    def theme_for_character(self, character_id, profile=None):
        """Resolve a character palette with the saved user-selected accent colour."""
        cid = str(character_id or "kira")
        selected = dict(profile or self.character_service.all_profiles(self.settings).get(cid, {}))
        custom = (self.settings.get("character_theme_colors") or {}).get(cid)
        if custom:
            selected["theme_color"] = custom
        return theme_mod.character_theme(cid, selected)

    def accent(self):
        theme = getattr(self.cur, "theme", None)
        return theme_mod.chat_accent(theme) if theme else None

    def _new_router(self):
        """Router of one chat. Cooldowns / health are shared with the other chats (a failing key is failing for everyone)."""
        router = HybridRouter(self.settings)
        base = next((sess.client for sess in self.sessions.values() if sess.client is not None), None)
        if base is not None:
            router.cooldowns, router.states = base.cooldowns, base.states
        return router

    def make_session_view(self):
        view = QTextBrowser()                              # read-only chat whose links open in the default browser
        view.setObjectName("chatView")
        view.setOpenLinks(False)                           # links are handled in on_chat_link (web pages + the Ai1 Code approve / reject links)
        view.setOpenExternalLinks(False)
        view.anchorClicked.connect(self.on_chat_link)
        view.setReadOnly(True)
        view.setFrameShape(QFrame.NoFrame)
        return view

    def on_chat_link(self, url):
        """Web / mail links open in the default app; kira-code:// links are the Diff approve / reject buttons of Ai1 Code mode;
        kira-action:// links are the per-message copy / edit / speak chips."""
        if url.scheme() == "kira-action":
            self.handle_chat_link(url)
            return
        if url.scheme() == "kira-code":
            code_chat = getattr(self, "code_chat", None)
            if code_chat is not None:
                code_chat.on_link(url)
            return
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def active_character(self):
        """Full profile of the character in front. Kira keeps her canonical identity (the profiles list only carries UI data)."""
        cid = getattr(getattr(self, "cur", None), "cid", "") or self.character_service.active_id(self.settings)
        if cid == "kira":
            profile = dict(KIRA_PROFILE)
        else:
            profile = dict(self.character_service.all_profiles(self.settings).get(cid) or self.character_service.active(self.settings))
        traits = (self.settings.get("character_traits") or {}).get(cid)
        if isinstance(traits, dict):
            profile["traits"] = {**profile.get("traits", {}), **traits}
        return profile

    def character_traits(self, cid, profile=None):
        """Baseline traits of one character (settings overrides win over the built-in defaults)."""
        profile = profile if isinstance(profile, dict) else (self.character_service.all_profiles(self.settings).get(cid) or {})
        traits = dict(profile.get("traits") or {})
        override = (self.settings.get("character_traits") or {}).get(cid)
        if isinstance(override, dict):
            traits.update(override)
        return traits

    def _sync_mood_character(self):
        """Point the persisted mood at the character in front so its neon chips and prompt follow that profile."""
        cid = getattr(getattr(self, "cur", None), "cid", "") or self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(cid) or {}
        try:
            mood.set_active_character(cid, self.character_traits(cid, profile))
        except Exception:                                   # noqa: BLE001 - mood is a bonus, never block the UI
            pass

    @staticmethod
    def _schedule_chat_callback(callback):
        QTimer.singleShot(0, callback)

    def _ensure_session_conversation(self, session):
        """Bind one character session to its durable conversation without blocking chat on storage errors."""
        if getattr(session, "conversation_id", None):
            return session.conversation_id
        try:
            record = self.chat_application_service.get_or_create_conversation(session.cid)
            conversation_id = (
                record.get("id") or record.get("conversation_id")
                if isinstance(record, dict) else None
            )
            session.conversation_id = str(conversation_id) if conversation_id else None
        except Exception:
            session.conversation_id = None
        return session.conversation_id

    def _publish_session_state_event(self, event):
        publisher = getattr(self, "chat_event_publisher", None)
        if publisher is None:
            return
        event_type = {
            "created": "session_created",
            "active": "session_activated",
            "idle": "session_deactivated",
            "closed": "session_closed",
            "failed": "session_failed",
        }.get(str(event.status))
        if event_type is None:
            return
        try:
            publisher.publish(
                event_type,
                session_id=event.session_id,
                payload={
                    "character_id": event.character_id,
                    "previous_status": event.previous_status,
                    "status": event.status,
                },
            )
        except Exception:
            # Notifications are best-effort and must not interrupt Session lifecycle.
            return

    def _ensure_session(self, cid, profile):
        sess = self.session_manager.get_session_for_character(cid)
        if sess is not None and sess.status == "closing":
            if not self.session_manager.reopen_session(sess.session_id):
                return None
        elif sess is not None and sess.status == "failed":
            if not self.session_manager.close_session(sess.session_id):
                return None
            sess = None
        if sess is None:
            sess = self.session_manager.create_session(cid)
        self._ensure_session_conversation(sess)
        if sess.view is None:
            sess.view = self.make_session_view()
            self.chat_stack.addWidget(sess.view)
            sess.timer = QTimer(self)
            sess.timer.setInterval(60)
            sess.relay = SessionRelay(self, sess)
            sess.timer.timeout.connect(sess.relay.tick)
        if sess.client is None:
            sess.client = self._new_router()
        sess.theme = self.theme_for_character(cid, profile)
        if sess.cid not in self.char_tab_buttons:
            button = QPushButton()
            button.setObjectName("charTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False, c=cid: self.switch_session(c))
            self.char_tab_group.addButton(button)
            self.char_tab_buttons[cid] = button
        return sess

    def sync_sessions(self):
        """Make the tabs match the characters that exist now (built-in ones + custom ones, minus deleted ones)."""
        profiles = self.character_service.all_profiles(self.settings)
        order = [c for c in ("kira", "ren", "mika") if c in profiles] + [c for c in profiles if c not in ("kira", "ren", "mika")]
        for cid in order:
            sess = self._ensure_session(cid, profiles[cid])
            if sess is None:
                continue
            if not sess.loaded:
                sess.loaded = True
                with self._as(sess):
                    self.restore_history()
                publisher = getattr(self, "chat_event_publisher", None)
                if publisher is not None:
                    try:
                        publisher.publish(
                            "history_loaded",
                            session_id=sess.session_id,
                            payload={
                                "character_id": sess.cid,
                                "conversation_id": sess.conversation_id,
                            },
                        )
                    except Exception:
                        pass
        order += [c for c in self.sessions if c not in order]          # a deleted character that is still answering keeps its tab for now
        for cid in [c for c in self.sessions if c not in profiles]:      # a deleted character stays until its queued/active work is drained
            sess = self.sessions[cid]
            if self._session_has_pending_chat_work(sess):
                continue
            self._dispose_chat_session(sess)
        while self.char_tabs_row.count():                                # rebuild the row in character order
            self.char_tabs_row.takeAt(0)
        for cid in order:
            if cid in self.char_tab_buttons:
                self.char_tabs_row.addWidget(self.char_tab_buttons[cid])
        self.char_tabs_row.addStretch(1)
        self.refresh_tab_buttons()

    @staticmethod
    def _worker_is_running(worker):
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            return False

    def _session_has_pending_chat_work(self, session):
        if (session.busy
                or self.chat_application_service.has_active_request(session.session_id)
                or self.chat_application_service.has_pending_work(session.session_id)):
            return True
        if self._worker_is_running(getattr(session, "worker", None)) or self._worker_is_running(
            getattr(session, "_search_worker", None)
        ):
            return True
        return (getattr(self, "_vision_session", None) is session
                and self._worker_is_running(getattr(self, "_vision_worker", None)))

    def _dispose_chat_session(self, session):
        """Request lifecycle closure; SessionManager owns the state transition."""
        return self.session_manager.close_session(session.session_id)

    def _release_chat_session_resources(self, session):
        """Release UI/provider resources after SessionManager confirms the work has drained."""
        self.chat_application_service.close_session(session.session_id)
        session.dispatch_scheduled = False
        response_relay = getattr(session, "response_relay", None)
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
            self.chat_stack.removeWidget(session.view)
            session.view.deleteLater()
            session.view = None
        button = self.char_tab_buttons.pop(session.cid, None)
        if button is not None:
            self.char_tabs_row.removeWidget(button)
            self.char_tab_group.removeButton(button)
            button.deleteLater()
        if getattr(self, "_vision_session", None) is session:
            vision_worker = getattr(self, "_vision_worker", None)
            if vision_worker is not None:
                try:
                    vision_worker.deleteLater()
                except RuntimeError:
                    pass
                self._vision_worker = None
            self._vision_session = None
        if not getattr(self, "_closing", False) and (self.front is session or self.cur is session):
            fallback = next(
                (item for item in self.session_manager.list_sessions()
                 if item is not session and item.status not in ("closing", "closed", "failed")),
                None,
            )
            if fallback is not None:
                self.switch_session(fallback.cid)
        return True

    def refresh_tab_buttons(self):
        profiles = self.character_service.all_profiles(self.settings)
        for cid, button in self.char_tab_buttons.items():
            sess = self.sessions.get(cid)
            profile = profiles.get(cid) or {}
            name = profile.get("name_fa") if self.settings.get("ui_lang", "fa") == "fa" else profile.get("name")
            mark = ""
            if sess is not None and sess.busy:
                mark = "  ⏳"
            elif sess is not None and sess.unread:
                mark = "  ●"
            button.setText(f"{name or cid}{mark}")
            button.setChecked(sess is self.front)

    def switch_session(self, cid, save=True):
        """Bring one character's chat to the front: its conversation, its colours, its picture. Other chats keep working."""
        sess = self.sessions.get(cid)
        if sess is None or not self.session_manager.activate_session(sess.session_id):
            return
        if cid != self.front.cid:
            self._flush_character_autosave()
        old = self.front
        if old is not sess:
            old.draft = self.input.text()
            if old._speech_live:                       # the voice belongs to the chat in front
                old._speech_live = False
            self.safe_stop_speaker()
            try:
                self.speaker.stream_reset()
            except Exception:                           # noqa: BLE001
                pass
            self.clear_upload_tiles()
        self.front = self.cur = sess
        sess.unread = False
        self.settings["active_character_id"] = cid
        self.refresh_navigation_icons()
        try:
            mood.set_active_character(cid, self.character_traits(cid, self.character_service.all_profiles(self.settings).get(cid)))
        except Exception:                               # noqa: BLE001 - never block switching tabs
            pass
        self.chat_stack.setCurrentWidget(sess.view)
        if old is not sess:
            self.input.setText(sess.draft)
        self.apply_chat_theme()
        self.apply_character_art()
        self.gen_stop_btn.setVisible(bool(sess.busy))
        self.gen_stop_btn.setEnabled(True)
        if sess.busy:
            self.set_status("st_thinking")
        else:
            self.set_status("st_ready")
        phase, info = sess.badge
        self.set_badge(phase if sess.busy else "idle", info if sess.busy else self.client.preview_route())
        self.refresh_tab_buttons()
        if hasattr(self, "character_page"):
            self.refresh_character_choices()
            self.refresh_character_card(cid)
        self.refresh_personality_controls()
        self.update_mood_indicator()
        bar = sess.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        if save:
            try:
                save_settings(self.settings)
            except Exception:                           # noqa: BLE001 - never block switching tabs
                pass
