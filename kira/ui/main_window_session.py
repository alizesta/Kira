"""Session behavior mixin for the desktop window."""
from .main_window_session_support import *  # noqa: F401,F403


class SessionMixin:
    @property
    def _attach_worker(self):
        controller = getattr(self, "attachment_controller", None)
        return controller.worker if controller is not None else None

    def t(self, key, **kw):
        s = STR.get(self.settings.get("ui_lang", "fa"), STR["fa"]).get(key, key)
        return s.format(**kw) if kw else s

    def reg(self, setter, key):
        self._tr.append((setter, key))

    def retranslate(self):
        lang = self.settings.get("ui_lang", "fa")
        QApplication.setLayoutDirection(Qt.RightToLeft if lang == "fa" else Qt.LeftToRight)
        for setter, key in self._tr:
            setter(self.t(key))
        self.input.setPlaceholderText(self.t("input_ph"))
        if hasattr(self, "_menu_actions"):
            for action, key in zip(self._menu_actions, self.tab_keys):
                action.setText(self.t(key))
        self.setWindowTitle(f"Project {self.settings['assistant_name']}  {VERSION}")
        self.title.setText(f"Project {self.settings['assistant_name']}")
        self.set_status(*self._status[:1], **self._status[1])
        self.update_companion_btn()
        self.update_engine_label()
        self.refresh_tab_buttons()
        if hasattr(self, "help_page"):
            self.help_page.retranslate()
        if hasattr(self, "assistant_page"):
            self.assistant_page.retranslate()
        if hasattr(self, "preferences_page"):
            self.preferences_page.retranslate()
        if hasattr(self, "voice_page"):
            self.voice_page.retranslate()
        if hasattr(self, "appearance_page"):
            self.appearance_page.retranslate()
        if hasattr(self, "character_page"):
            self.character_page.retranslate()
        if hasattr(self, "_menu_actions"):
            for action, key in zip(self._menu_actions, self.tab_keys):
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
                self.voice_application_service.stream_reset()
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

    def apply_chat_theme(self):
        """Glass + neon colours of the chat in front (same glass, the character's own colours)."""
        theme = self.front.theme or self.theme_for_character(self.front.cid)
        self.chat_page.setStyleSheet(theme_mod.character_style(theme, getattr(self, "_effect", "off"), self.settings.get("appearance", {})))
        r, g, b = (int(theme["main"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for glow in self.glow_effects:
            appearance = self.settings.get("appearance", {})
            intensity = max(0, min(100, int(appearance.get("glow", 34))))
            glow.setBlurRadius(14 + intensity * 0.38)
            glow.setColor(QColor(r, g, b, round(54 + intensity * 0.92)))
        self._apply_neon_glow_effects(self.settings.get("appearance", {}))

    def greeting_text(self):
        profile = self.character_service.active(self.settings)
        if profile["id"] == "kira":
            return self.t("greeting")
        name = profile.get("name_fa") if self.settings.get("ui_lang", "fa") == "fa" else profile.get("name")
        if self.settings.get("ui_lang", "fa") == "fa":
            return f"سلام! من {name} هستم. {profile.get('description', '')}"
        return f"Hi! I'm {name}. {profile.get('description', '')}"

    def restore_history(self, limit=40):
        """Show the saved conversation of the CURRENT chat again after a restart (it is already used as model context)."""
        try:
            self._ensure_session_conversation(self.cur)
            history = self.chat_application_service.recent_messages(
                limit, character_id=self.cur.cid, conversation_id=self.cur.conversation_id
            )
        except Exception:
            history = []
        shown = 0
        for item in history:
            role = item.get("role")
            if role == "assistant":
                text = self.director.parse_reply(item.get("content", "")).text      # emotion tags never shown
            elif role == "user":
                text = item.get("content", "")
            else:
                continue
            if text.strip():
                self.add_chat(role, text)
                shown += 1
        if shown:
            self.add_chat("system", self.t("history_restored"))
        else:
            self.add_chat("assistant", self.greeting_text())

    def add_chat(self, kind, text, name=None, images=None):
        """Append one message bubble; direction is decided per line so Persian reads right-to-left.
        images: attachment dicts whose thumbnails are shown at the top of the bubble."""
        if name is None:
            name = {"user": self.t("you"), "assistant": self.active_character().get("name", "Character"),
                    "error": self.t("error"), "system": ""}.get(kind, "")
        ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
        extra = self.thumbnail_html(images)
        footer = self.chat_actions_html(kind, text)
        with bubble_accent(self.accent()):
            self.chat.append(message_html(kind, name, text, ui_dir, extra, footer))
        if getattr(self, "bubble", None) is not None:
            self.bubble.push(kind, name, text, ui_dir)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def update_mood_indicator(self):
        """Render the active character's current emotion as a custom neon face; chat-message emoji are untouched."""
        label = getattr(self, "mood_indicator", None)
        face_label = getattr(self, "mood_emotion_icon", None)
        if label is None or face_label is None:
            return
        self._sync_mood_character()

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
            state = mood.current()
            emotion = str(state.get("emotion", "neutral") or "neutral").lower()
            icon_name = face_map.get(emotion, "neutral")
            neon = emotion_colors.get(emotion, "#69E5FF")
            face_icon = make_icon(
                f"emotion_{icon_name}", normal=neon, hover=neon,
                checked=neon, disabled="#52617B",
            )
            face_label.setPixmap(face_icon.pixmap(QSize(30, 30)))
            face_label.setStyleSheet(
                "QLabel#moodEmotionIcon { background: rgba(12, 20, 43, 0.96); "
                f"border: 1px solid {neon}; border-radius: 11px; padding: 2px; }}"
            )
            glow = getattr(self, "_mood_emotion_glow", None)
            if glow is not None:
                glow_colour = QColor(neon)
                glow_colour.setAlpha(215)
                glow.setColor(glow_colour)

            # Behaviour and energy are represented by vector neon glyphs only.
            # Never place a plain Unicode emoji beside the neon emotion face.
            behaviour = str(state.get("behavior", "balanced"))
            energy = str(state.get("energy_label", "normal"))
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
            intensity = int(state.get("intensity", 0))
            secondary = ", ".join(name for name, _ in state.get("secondary_emotions", [])[:2])
            tooltip = (
                f"احساس: {emotion} ({intensity}/100)\n"
                f"رفتار: {behaviour}\n"
                f"انرژی: {energy}"
            )
            if secondary:
                tooltip += f"\nاحساسات همراه: {secondary}"
            face_label.setToolTip(tooltip)
            label.setToolTip(tooltip)
        except Exception:                                    # noqa: BLE001 - the indicator must never break the window
            fallback = make_icon("emotion_neutral", normal="#B9D4F5", hover="#B9D4F5",
                                 checked="#B9D4F5", disabled="#52617B")
            face_label.setPixmap(fallback.pixmap(QSize(30, 30)))
            label.setText("")
            face_label.setToolTip("حال‌وهوای شخصیت فعال")

    def chat_actions_html(self, kind, text):
        """Neon icon chips with generous separation; labels stay in tooltips to keep the chat compact."""
        if kind not in ("assistant", "user") or not str(text or "").strip():
            return ""
        self._chat_action_seq += 1
        key = str(self._chat_action_seq)
        self._chat_action_texts[key] = str(text)
        # Keep action targets for all messages currently present in the chat view.
        actions = [
            ("copy", "⧉", "#8CF5FF", "#103A52", "#39DFFF", "کپی"),
            ("edit", "✎", "#E0C8FF", "#30214F", "#B18AFF", "ویرایش"),
        ]
        if kind == "assistant":
            actions.append(("speak", "♫", "#FFC0E9", "#4B2044", "#FF83D0", "خواندن"))
        cells = []
        for action, glyph, colour, background, border, tooltip in actions:
            cells.append(
                f'<td bgcolor="{background}" style="border:1px solid {border};border-radius:10px;'
                f'padding:4px 11px;">'
                f'<a href="kira-action://{action}/{key}" title="{tooltip}" '
                f'style="color:{colour};text-decoration:none;font-size:13pt;font-weight:700;">{glyph}</a>'
                f'</td>'
            )
        links = "".join(cells)
        return (
            '<table dir="rtl" align="right" border="0" cellspacing="9" cellpadding="0" '
            'style="margin-top:10px;border-top:1px solid #314968;padding-top:7px;">'
            f'<tr>{links}</tr></table>'
        )

    def handle_chat_link(self, url):
        """Handle local message actions while preserving normal external links."""
        if url.scheme() == "kira-action":
            action = url.host()
            key = url.path().strip("/")
            text = self._chat_action_texts.get(key)
            if text is None:
                return
            if action == "copy":
                QApplication.clipboard().setText(text)
                self.set_status("st_ready")
            elif action == "edit":
                self.input.setText(text)
                self.input.setFocus()
                self.input.moveCursor(QTextCursor.End)
            elif action == "speak":
                # Speaker.speak() owns cancellation/replacement of the previous session.
                self.voice_application_service.speak(text)
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
            self._att_seq += 1
            key = f"kira-att://{self._att_seq}"
            self.chat.document().addResource(QTextDocument.ImageResource, QUrl(key), img)
            parts.append(f'<p style="margin:0 0 6px 0;"><img src="{key}" width="{img.width()}" height="{img.height()}"></p>')
        return "".join(parts)

    def on_input_changed(self, text):
        """Typed text flows in its own direction (Persian right-to-left, English left-to-right)."""
        ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
        d = detect_direction(text, ui_dir)
        self.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)

    @front_only
    def set_status(self, key, **kw):
        self._status = (key, kw)
        self.status.setText(self.t(key, **kw))

    # ---------- navigation / responsive layout ----------

    def go_tab(self, index):
        self.tabs.setCurrentIndex(index)
        self._sync_nav()

    def _sync_nav(self, _index=None):
        i = self.tabs.currentIndex()
        for index, button in enumerate(getattr(self, "nav_buttons", [])):
            button.setChecked(i == self._nav_icon_map[index][1])
        self.save_btn.setVisible(i != 0)            # the chat page needs no Save button
        if hasattr(self, "voice_page") and i == self.tab_keys.index("tab_voice"):
            self.refresh_voice_caps()               # Refresh local-only speech status

    def resizeEvent(self, event):
        super().resizeEvent(event)
        card = getattr(self, "avatar_card", None)
        if card is not None:                         # narrow window: give the whole width to the conversation
            card.setVisible(self.width() >= 640)
            card.setFixedWidth(max(200, min(300, int(self.width() * 0.30))))

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

    FIELD_LIMITS = {"spin": 110, "slider": 280, "combo": 240, "combo_edit": 340, "line": 520}

    def tidy_forms(self):
        """Short fields (numbers, choices, sliders) keep a size that fits their content; long text fields keep the room they need.
        Nothing stretches to the end of the window for no reason."""
        lim = self.FIELD_LIMITS
        for i in range(1, self.tabs.count()):                          # page 0 is the chat: left as it is
            page = self.tabs.widget(i)
            for w in page.findChildren(QSpinBox) + page.findChildren(QDoubleSpinBox):
                w.setMaximumWidth(lim["spin"])
            for w in page.findChildren(QSlider):
                w.setMaximumWidth(lim["slider"])
            for w in page.findChildren(QComboBox):
                w.setMaximumWidth(lim["combo_edit"] if w.isEditable() else lim["combo"])
            for form in page.findChildren(QFormLayout):
                form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
                for r in range(form.rowCount()):
                    item = form.itemAt(r, QFormLayout.FieldRole)
                    widget = item.widget() if item is not None else None
                    if isinstance(widget, QLineEdit):
                        widget.setMaximumWidth(lim["line"])

    def icon_button(self, name, checkable=False):
        """Small neon icon button using the active character's own accent colours."""
        b = QToolButton()
        cid = self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(cid, {})
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
        cid = self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(cid, {})
        palette = self.theme_for_character(cid, profile)
        for button, (name, _tab_index) in zip(getattr(self, "nav_buttons", []), getattr(self, "_nav_icon_map", [])):
            button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))
        menu_button = getattr(self, "menu_btn", None)
        if menu_button is not None:
            menu_button.setIcon(make_icon("menu", normal=palette["second"], hover="#FFFFFF",
                                          checked=palette["main"], disabled="#52617B"))
        for action, (name, _tab_index) in zip(getattr(self, "_menu_actions", []), getattr(self, "_nav_icon_map", [])):
            action.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))
        badge = getattr(self, "route_badge", None)
        if badge is not None:
            badge.setIcon(make_icon("chevron_up", normal=palette["second"], hover="#FFFFFF",
                                    checked=palette["main"], disabled="#52617B"))
        if hasattr(self, "_refresh_icon_glow"):
            self._refresh_icon_glow()
