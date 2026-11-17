"""Chat behavior mixin for the desktop window."""
from .main_window_support import *  # noqa: F401,F403


class ChatMixin:
    def send_message(self):
        if self.attach_loading():
            self.status.setText("ضمیمه‌ها هنوز در حال بارگذاری‌اند؛ چند لحظه صبر کن.")
            return
        text = self.input.text().strip()
        files = [t.att for t in self._tiles if t.att]
        if text or files:
            self.clear_attachments()
            self.input.clear()
            self.submit(text, files)

    def _cancel_application_provider(self, request, _worker):
        session = self.session_manager.get_session(request.session_id)
        if session is not None and session.client is not None:
            with self._as(session):
                session.client.cancel()

    def _dispatch_application_request(self, request):
        session = self.session_manager.get_session(request.session_id)
        if self._closing or session is None:
            self.chat_application_service.complete_local_request(request.request_id)
            return
        with self._as(session):
            session.application_request_id = request.request_id
            self._process_chat_request(request.text, list(request.attachments), request.voice)

    def _on_chat_application_event(self, event):
        session = self.session_manager.get_session(event.session_id)
        if session is None or self._closing:
            return
        if event.kind is ApplicationEventKind.REQUEST_STARTED:
            return
        if getattr(session, "application_request_id", None) != event.request_id:
            if event.kind is ApplicationEventKind.REQUEST_FAILED and not getattr(session, "application_request_id", None):
                session.application_request_id = event.request_id
            else:
                return
        with self._as(session):
            if (event.persistence_ok is False
                    and event.kind in (
                        ApplicationEventKind.REQUEST_COMPLETED,
                        ApplicationEventKind.REQUEST_FAILED,
                        ApplicationEventKind.REQUEST_CANCELLED,
                    )
                    and not self._save_warned):
                self._save_warned = True
                self.add_chat(
                    "error",
                    "ذخیره‌ی پاسخ روی دیسک ناموفق بود. پاسخ تا اولین ذخیره‌ی موفق در حافظه نگه داشته می‌شود."
                    + (f"\nعلت: {event.error}" if event.error else ""),
                )
            if event.kind is ApplicationEventKind.PROVIDER_CHUNK:
                self.on_stream_chunk(event.chunk, event.content)
            elif event.kind is ApplicationEventKind.PROVIDER_FINAL and event.result is not None:
                result = event.result
                response = dict(result.metadata)
                response.update({
                    "text": result.content,
                    "response_status": result.status.value,
                    "request_id": event.request_id,
                    "session_id": event.session_id,
                })
                self.on_stream_done(response)
            elif event.kind is ApplicationEventKind.REQUEST_CANCELLED:
                self.on_stream_done({
                    "text": event.content,
                    "stopped": True,
                    "request_id": event.request_id,
                    "session_id": event.session_id,
                })
            elif event.kind is ApplicationEventKind.REQUEST_FAILED:
                if event.metadata.get("interrupted"):
                    self.on_stream_done({
                        "text": event.content,
                        "interrupted": event.error or "Provider stream interrupted",
                        "request_id": event.request_id,
                        "session_id": event.session_id,
                    })
                else:
                    self.on_error(event.error or "Chat request failed")

    def submit(self, text, attachments=None, _voice=None):
        if self.cur.status in ("closing", "closed", "failed"):
            return
        if _voice is None:
            voice, self._voice_next = self._voice_next, False
        else:
            voice, self._voice_next = bool(_voice), False
        vision_worker = getattr(self, "_vision_worker", None)
        wait_for_vision = (
            not self.busy and vision_worker is not None and vision_worker.isRunning()
            and getattr(vision_worker, "router", None) is self.client
        )
        if self.busy and not attachments:
            try:
                control_dispatch = self.chat_application_service.dispatch_control_commands(
                    self.cur.session_id,
                    text,
                    metadata={"character_id": self.cur.cid},
                )
            except Exception:  # noqa: BLE001 - a control message must never block normal chat
                control_dispatch = None
            if control_dispatch is not None and control_dispatch.handled:
                if control_dispatch.reply_text:
                    self.add_chat("system", control_dispatch.reply_text)
                return
        self._ensure_session_conversation(self.cur)
        result = self.chat_application_service.submit_message(
            self.cur.session_id, text, attachments, voice,
            busy=self.busy, force_queue=wait_for_vision,
            conversation_id=self.cur.conversation_id,
            character_id=self.cur.cid,
        )
        if not result.accepted:
            return
        if result.queued:
            count = self.chat_application_service.pending_count(self.cur.session_id)
            if wait_for_vision:
                self.status.setText(
                    f"پیام در صف است ({count}) — تحلیل Vision متوقف می‌شود و پیام بعد از آن ارسال خواهد شد."
                )
                vision_worker.cancel_request()
                if not vision_worker.isRunning():
                    QTimer.singleShot(0, lambda owner=self.cur: self._send_pending_for_session(owner))
            else:
                self.status.setText(f"پیام در صف است ({count}) — بعد از پایان پاسخ فعلی ارسال می‌شود.")
            return

    def _process_chat_request(self, text, attachments=None, _voice=False):
        voice = bool(_voice)
        if not attachments and getattr(self, "code_chat", None) is not None and self.code_chat.handle(text, voice):
            self.chat_application_service.complete_local_request(self.cur.application_request_id)
            return                                              # Coding Agent owns this separate execution lifecycle
        if self._game_mode_enabled and len(attachments or []) < att.MAX_FILES:
            frame = self._game_vision_attachment()
            if frame is not None:
                attachments = list(attachments or []) + [frame]
                try:
                    self.chat_application_service.add_request_attachment(
                        self.cur.application_request_id, frame
                    )
                except (AttributeError, ValueError):
                    # A non-application request can still use the legacy payload.
                    pass
        self._turn_voice = voice
        if self.speaker._began:
            self.director.event("user_interrupt")
        self.safe_stop_speaker()
        self.animator.touch()
        self._body_done = []
        original_text = str(text or "")
        self.tool_agent.begin_turn(self.cur.cid)
        has_image = any(item.get("kind") == "image" for item in (attachments or []))
        command_dispatch = self.chat_application_service.dispatch_commands(
            self.cur.application_request_id,
            original_text,
            metadata={
                "has_attachments": bool(attachments),
                "has_image": has_image,
                "character_id": self.cur.cid,
            },
        )
        text = command_dispatch.rewritten_text or original_text
        force_img = bool(command_dispatch.metadata.get("force_image_search"))
        force_web = bool(command_dispatch.metadata.get("force_web_search"))
        img_search = bool(
            has_image and (force_img or self.settings.get("image_search", False))
        )
        packed = None
        if self.cur.application_request_id:
            try:
                packed = self.chat_application_service.prepare_request_attachments(
                    self.cur.application_request_id, text=text, search=img_search
                )
            except (AttributeError, ValueError):
                packed = None
        if packed is None and attachments:
            packed = att.compose(text, attachments, search=img_search)
        if packed is not None:
            # Search must only run with a successfully prepared image payload.
            img_search = bool(packed.get("images")) and (force_img or self.settings.get("image_search", False))
        if packed and packed.get("errors"):
            self.show_attach_error(packed["errors"])
            if not packed.get("prepared_count") and not text.strip():
                self.chat_application_service.fail_request(
                    self.cur.application_request_id,
                    "No attachment content could be prepared.",
                )
                return
        if packed is not None and force_web:
            # Preserve the user's literal /web command in the visible and durable chat history.
            presentation = att.compose(original_text, attachments, search=img_search)
            packed["display"] = presentation["display"]
            packed["stored"] = presentation["stored"]
        self._turn_extra = packed
        self._turn_attach_kinds = [str(item.get("kind")) for item in (attachments or [])]
        self.add_chat(
            "user",
            packed["display"] if packed else original_text,
            images=attachments if packed else None,
        )
        self._tool_plan = (
            None
            if command_dispatch.handled and not command_dispatch.continue_chat
            else self.tool_agent.plan(text)
        )
        self.save_message("user", packed["stored"] if packed else original_text)
        if command_dispatch.handled and not command_dispatch.continue_chat:
            self.reply_local(command_dispatch.reply_text or "فرمان اجرا شد.")
            return
        self.busy = True
        self.gen_stop_btn.show()
        self.set_status("st_thinking")
        self.set_badge("connecting", self.client.preview_route())
        self.show_upload_tiles(attachments)
        self.director.event("user_message")
        self.director.event("response_started")
        self._plain_retry = False
        self._web_found = None
        self._image_search_turn = False
        if img_search and packed:
            self._image_search_turn = True
            self.begin_image_search(text, packed, packed["images"])
            return
        query, forced = (
            websearch.plan(text)
            if self.settings.get("web_search", True) or text.lstrip().startswith("/") or force_web
            else (None, False)
        )
        if force_web:
            query, forced = str(text or "").strip()[:300], True
        if query and not forced and self._tool_plan is not None and self._tool_plan.strong:
            query = None                                          # a request about this PC (files, apps, RAM...) is not a web question
        if query and not forced and self._tool_plan is not None and getattr(self._tool_plan, "web", False):
            query = None                                          # research / "read this page" requests go through the web tools (kira/webintel), not the one-shot search
        if query:
            self.begin_web_search(query, packed if packed else text, packed["images"] if packed else [])
            return
        self.begin_reply()

    def begin_reply(self):
        try:
            self.start_worker(plain=False)
        except Exception as exc:                                  # noqa: BLE001 - never leave the window stuck in 'busy'
            self.chat_application_service.fail_request(
                self.cur.application_request_id, f"{type(exc).__name__}: {exc}"
            )

    # ---- web search ----

    def toggle_web_search(self, on):
        self.settings["web_search"] = bool(on)
        save_settings(self.settings)
        self.update_web_tip()

    def update_web_tip(self):
        self.web_btn.setToolTip("جست‌وجوی وب: " + ("روشن — کیرا وقتی سؤال به اطلاعات روز نیاز دارد (قیمت، خبر، امروز…) یا بگویی «سرچ کن» در وب می‌گردد. "
                                                  "برای اجبار: /web عبارت" if self.web_btn.isChecked() else "خاموش — فقط با نوشتن /web عبارت جست‌وجو می‌کند"))

    # ---- image search (a picture is looked up on the web) ----
    def toggle_image_search(self, on):
        on = bool(on)
        self.settings["image_search"] = on
        save_settings(self.settings)
        for widget in (getattr(self, "img_search_btn", None),):
            if widget is not None and widget.isChecked() != on:
                widget.blockSignals(True)
                widget.setChecked(on)
                widget.blockSignals(False)
        bubble = getattr(self, "bubble", None)
        if bubble is not None and bubble.img_btn.isChecked() != on:
            bubble.set_image_search(on)
        self.update_image_search_tip()

    def update_image_search_tip(self):
        btn = getattr(self, "img_search_btn", None)
        if btn is not None:
            btn.setToolTip("جست‌وجوی تصویری: " + ("روشن — عکسی که می‌فرستی در وب جست‌وجو می‌شود تا معلوم شود چیست. "
                                                  "ترتیب: Gemini (با خودِ عکس) ← توصیف عکس و جست‌وجو با Tavily ← DuckDuckGo. "
                                                  "برای یک پیام: /img" if btn.isChecked() else
                                                  "خاموش — عکس فقط به مدل داده می‌شود. برای جست‌وجوی یک عکس، پیام را با /img شروع کن."))

    def begin_image_search(self, hint, base_text, images):
        options = self.web_search_service.image_search_options(
            self.settings, hint, images, self.client
        )
        self._search_token += 1
        self._search_base = (base_text, images)
        self.status.setText("🔎 در حال جست‌وجوی تصویر در وب…")
        self._search_worker = SearchWorker(
            self._search_token,
            options.query,
            options.api_key,
            options.depth,
            user_text=options.user_text,
            gemini=options.gemini,
            fallback=options.fallback,
            images=list(options.images),
            describe=options.describe,
        )
        self._search_worker.done.connect(self.cur.relay.search_done)
        self._search_worker.start()

    def begin_web_search(self, query, base_text, images):
        if not self.web_search_service.can_search(self.settings):
            self.add_chat("system", self.web_search_service.MISSING_KEY_MESSAGE)
            self.begin_reply()
            return
        self._search_token += 1
        self._search_base = (base_text, images)
        self.status.setText(f"🌐 در حال جست‌وجوی وب: «{query[:60]}»…")
        conversation_id = self._ensure_session_conversation(self.cur)
        history = self.chat_application_service.conversation_context(
            8, session_id=self.cur.cid, conversation_id=conversation_id
        )
        options = self.web_search_service.web_search_options(
            self.settings, query, history, self.client
        )
        self._search_worker = SearchWorker(
            self._search_token,
            options.query,
            options.api_key,
            options.depth,
            rewrite=options.rewrite,
            user_text=options.user_text,
            gemini=options.gemini,
            fallback=options.fallback,
        )
        self._search_worker.done.connect(self.cur.relay.search_done)
        self._search_worker.start()

    def test_web_search(self):
        """Settings button: one real Tavily search with the key typed in the box (no need to save first)."""
        key, depth = self.tavily_key.text().strip(), self.web_depth.currentData()
        gem = self.web_search_service.gemini_credentials(self.settings)
        self.web_test_btn.setEnabled(False)
        self.web_test_btn.setText("در حال آزمایش (چند ثانیه)…")
        self._web_test_worker = TaskWorker(lambda: websearch.diagnose(key, depth, self.web_search_service.WEB_TEST_QUERY, gem))
        self._web_test_worker.done.connect(self.on_web_test_done)
        self._web_test_worker.start()

    def on_web_test_done(self, res):
        self.web_test_btn.setEnabled(True)
        self.web_test_btn.setText("آزمایش جست‌وجوی وب")
        ok, rep = res
        if not ok:
            QMessageBox.warning(self, "آزمایش جست‌وجوی وب", f"آزمایش انجام نشد:\n{rep}")
            return
        lines = []
        for name, label in (("tavily", "Tavily (اول)"), ("google", "Google / Gemini (دوم)"), ("ddg", "DuckDuckGo (سوم)")):
            e = rep["engines"][name]
            lines.append(f"{label}: " + (f"✓ کار می‌کند — {e['sources']} منبع · «{e['first'][:50]}»" if e["ok"] else f"✕ {e['error']}"))
        extra = self.web_search_service.assessment_text(rep.get("assessment"))
        QMessageBox.information(self, "آزمایش جست‌وجوی وب",
                                "\n".join(lines) + f"\n\nعبارت آزمایش: «{rep['probe']}»" + (f"\n{extra}" if extra else "")
                                + "\nکیرا به همین ترتیب امتحان می‌کند و از اولین موتور سالم استفاده می‌شود.")

    def add_sources(self, found):
        html = sources_html(found.get("results"), f"منابع ({websearch.ENGINE_NAMES.get(found.get('engine'), 'وب')}) · جست‌وجو برای «{found.get('query', '')}»")
        a = found.get("assessment") or {}
        if html and a.get("phrase"):
            text = self.web_search_service.assessment_text(a)
            colour = "#7fd99a" if a.get("matched") else "#ffb86b"
            html += f'<p dir="rtl" align="right" style="margin:3px 0 0 0;color:{colour};">{text if text.startswith("⚠") else "✓ " + text}</p>'
        if html:
            ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
            self.chat.append(message_html("system", "", "", ui_dir, html))
            bar = self.chat.verticalScrollBar()
            bar.setValue(bar.maximum())

    def on_web_done(self, token, ok, result):
        if self._closing or token != self._search_token or not self.busy:
            return                                                   # stopped / superseded meanwhile
        if ok:
            base, images = self._search_base
            self._web_found = result
            if result.get("note"):
                self.add_chat("system", "🌐 " + result["note"])
            self._turn_extra = self.web_search_service.merge_search_content(
                base, images, websearch.format_block(result),
                image_search=bool(getattr(self, "_image_search_turn", False)),
            )
            self.status.setText(f"{'🔎 Google' if result.get('engine') == 'google' else ('🦆 DuckDuckGo' if result.get('engine') == 'ddg' else '🌐 Tavily')}: {len(result['results'])} منبع پیدا شد؛ در حال پاسخ دادن…")
        elif getattr(self, "_image_search_turn", False):
            # the picture itself is still in the request: she answers from what she sees and says what is unconfirmed
            self.add_chat("system", f"🔎 جست‌وجوی تصویری انجام نشد: {result}")
            base, images = self._search_base
            self._turn_extra = self.web_search_service.merge_search_content(
                base, images,
                "[جست‌وجوی وب برای این تصویر انجام نشد. فقط از روی چیزی که در تصویر می‌بینی جواب بده، "
                "حدس نزن و هر چیزی که مطمئن نیستی را صریح «تأییدنشده» بگو.]",
                image_search=False,
            )
        else:
            # no usable web result: do not let the model improvise from memory; Kira says she does not know
            self.add_chat("system", f"🌐 جست‌وجوی وب انجام نشد: {result}")
            self._turn_extra = None
            self.reply_local(websearch.failure_reply(result), "sad")
            self.finish_request(None)
            self._send_next_pending()
            return
        self.begin_reply()

    def start_worker(self, plain):
        window = int(self.settings.get("memory_context_limit", 12))
        conversation_id = self._ensure_session_conversation(self.cur)
        history = self.chat_application_service.conversation_context(
            window, character_id=self.cur.cid, conversation_id=conversation_id
        )
        mode = self.detect_mode(history)                          # Active Mode of THIS message (None = switched off in settings)
        try:
            older = self.chat_application_service.recent_messages(
                window + 40, character_id=self.cur.cid, conversation_id=conversation_id
            )[:-window] if window else []
            # Every character has its own saved conversation; only Kira owns the legacy evidence index.
            character_id = self.cur.cid
            memory_block = self.memory_service.build_block(
                character_id,
                older,
                voice_samples=(mode is None or mode.name == modes.CHAT),
                query=evidence_memory.query_from_context(history) if character_id == "kira" else None,
                budget=evidence_memory.budget_for(self.settings, self.client),
            )
            total = self.chat_application_service.message_count(
                character_id, conversation_id
            )
            if self.memory_service.needs_summary(character_id, total, window):
                self.memory_service.maintain(
                    character_id,
                    self.chat_application_service.recent_messages(
                        min(total, 3000), character_id=character_id, conversation_id=conversation_id
                    ),
                    window,
                )
        except Exception:                                         # noqa: BLE001 - memory is a bonus, never block a reply
            memory_block = ""
        try:                                                      # her persisted mood + how he seems right now (same text for every provider)
            mood_block = mood.build_block(mode.name if mode else modes.CHAT)
        except Exception:                                         # noqa: BLE001
            mood_block = ""

        # Brain planning remains application policy; only its prompt contribution
        # is injected into the independent ContextBuilder.
        try:
            extra0 = self._turn_extra
            has_att = bool(self._turn_attach_kinds or (extra0 and (extra0.get("images") or "--- فایل ضمیمه" in str(extra0.get("model", "")))))
            last_user = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")
            self._brain_user_text = str(last_user)
            self._brain_mode_name = mode.name if mode else None
            self._brain = brain.decide(last_user, mode, self._tool_plan, has_att, self.tool_agent.tasks.active() is not None, self.settings)
        except Exception:                                         # noqa: BLE001
            self._brain = brain.Decision()

        character_layer = self.character_service.prompt_for(self.settings)
        body_context = ""
        if self.body_active():                                    # preserve existing 3D body instruction and completed-action note
            body_context = ("" if plain else body_ctl.format_hint()) + body_ctl.done_note(self._body_done)

        context = {
            "messages": history,
            "character_id": self.cur.cid,
            "character_profile": self.active_character(),
            "settings": self.settings,
            "memory": memory_block,
            "mood": mood_block,
            "character_context": character_layer,
            "format_hint": "" if plain else self.director.format_hint(),
            "voice_input": self._turn_voice,
            "mode": mode,
            "body_context": body_context,
            "active_capabilities": tuple(sorted(getattr(self._tool_plan, "categories", ()) or ())),
            "turn_extra": self._turn_extra,
            "max_context_chars": self.settings.get("chat_context_char_limit", 0),
        }

        self._stream_begin()
        temperature = modes.temperature_for(mode, self.settings["temperature"]) if mode else self.settings["temperature"]
        relay = self.cur.relay
        request_id = self.cur.application_request_id
        if not request_id:
            raise RuntimeError("No active Chat application request is associated with this session")
        self.worker = self.chat_application_service.start_provider_request(
            request_id, context,
            provider_callbacks={"tool_event": relay.tool, "event": relay.stream_event},
            provider_event_dispatcher=relay.provider_event.emit,
            router=self.client, temperature=temperature,
            retry_index=1 if plain else 0, agent=self.tool_agent, plan=self._tool_plan,
            role=self._brain.stage, route_id=self._brain.route_id,
        )
        self.refresh_tab_buttons()

    MODE_LABELS = {"chat": "گپ", "task": "کار / کمک", "strict": "فقط جواب"}

    def detect_mode(self, context):
        """Active Mode for the message being answered (see kira/modes.py). Never raises: on any problem the old prompt is used."""
        self._turn_mode = None
        if not self.settings.get("active_modes", True):
            return None
        try:
            users = [m["content"] for m in context if m.get("role") == "user"]
            extra = self._turn_extra
            # an image or a file is attached: the structured kinds decide (the text markers are only a fallback)
            has_attachment = bool(self._turn_attach_kinds or (extra and (extra.get("images") or "--- فایل ضمیمه" in str(extra.get("model", "")))))
            earlier = users[:-1]
            try:                                                   # a "no jokes" request must outlive the short context window
                conversation_id = self.cur.conversation_id
                longer = [
                    m["content"] for m in self.chat_application_service.recent_messages(
                        80, character_id=self.cur.cid, conversation_id=conversation_id
                    ) if m.get("role") == "user"
                ]
                if len(longer) > len(users):
                    earlier = longer[:-1]
            except Exception:                                      # noqa: BLE001
                pass
            self._turn_mode = modes.detect(users[-1] if users else "", earlier, has_attachment)
        except Exception:                                         # noqa: BLE001
            self._turn_mode = None
        return self._turn_mode

    def stop_generation(self):
        """Stop button: ends the answer now; text received so far is kept."""
        if getattr(self, "code_chat", None) is not None and self.code_chat.stop(self.cur):
            self.chat_application_service.complete_local_request(self.cur.application_request_id)
            return                                                # the Coding Agent owns its separate task lifecycle
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_token += 1                                   # the late search result is ignored
            self.add_chat("system", "جست‌وجو متوقف شد.")
            self.chat_application_service.cancel_request(self.cur.application_request_id)
            return
        if not any(o.busy for o in self.sessions.values() if o is not self.cur):
            self.tool_agent.request_cancel()                      # also stops a tool loop between two steps (the tool agent is shared:
                                                                  # not while another character is in the middle of its own task)
        self.chat_application_service.cancel_request(self.cur.application_request_id)
        self.gen_stop_btn.setEnabled(False)

    # ---- body control (the 3D body moves on chat commands: kira/body.py) ----

    def _install_chat_commands(self):
        """Wire the existing feature owners into the shared chat command registry."""
        registry = create_default_command_registry(
            permission_checker=self._check_chat_command_permission,
            usage_parser=usage.parse_command,
            usage_report=usage.report,
            body_parser=body_ctl.parse_user_command,
            body_is_active=self.body_active,
            body_handler=self.run_body,
            web_parser=websearch.plan,
            image_parser=websearch.image_command,
            task_control_parser=parse_tool_task_control,
            task_running_checker=self.tool_agent.is_task_running,
            tool_agent=self.tool_agent,
            desktop_action_matcher=match_safe_action,
            desktop_action_handler=lambda text: run_safe_action(text, allow_desktop=True),
        )
        self.chat_application_service.set_command_registry(registry)
        self.command_registry = registry
