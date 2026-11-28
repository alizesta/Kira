"""Chat feature controller for the desktop window."""
from PySide6.QtCore import Slot
from ..chat.context_builder import latest_user_text
from ..vision_pipeline import refers_to_screen, reply_was_unreadable, wants_detail_capture
from .main_window_chat_support import (
    ApplicationEventKind,
    QMessageBox,
    QTimer,
    body_ctl,
    create_default_command_registry,
    evidence_memory,
    match_safe_action,
    message_html,
    modes,
    parse_tool_task_control,
    run_safe_action,
    save_settings,
    sources_html,
    usage,
)


from .window_feature_controller import WindowFeatureController


class ChatController(WindowFeatureController):
    def bind_attachment_controller(self, controller):
        """Inject the independent attachment workflow after UI composition."""
        if controller is None:
            raise TypeError("attachment controller is required")
        self._attachment_controller = controller

    @property
    def attachment_controller(self):
        try:
            return self._attachment_controller
        except AttributeError as exc:
            raise RuntimeError("ChatController attachment dependency is not composed") from exc

    def send_message(self):
        attachments = self.attachment_controller
        if attachments.is_loading():
            self.context.views.status.setText("ضمیمه‌ها هنوز در حال بارگذاری‌اند؛ چند لحظه صبر کن.")
            return
        text = self.context.views.input.text().strip()
        files = attachments.attachments
        if text or files:
            attachments.clear()
            self.context.views.input.clear()
            self.submit(text, files)

    def _cancel_application_provider(self, request, _worker):
        session = self.context.services.session_manager.get_session(request.session_id)
        if session is not None and session.client is not None:
            with self.feature_controller("session")._as(session):
                session.client.cancel()

    def _dispatch_application_request(self, request):
        session = self.context.services.session_manager.get_session(request.session_id)
        if self.context.state._closing or session is None:
            self.context.services.chat_application_service.complete_local_request(request.request_id)
            return
        with self.feature_controller("session")._as(session):
            session.application_request_id = request.request_id
            self._process_chat_request(request.text, list(request.attachments), request.voice)

    def _on_chat_application_event(self, event):
        session = self.context.services.session_manager.get_session(event.session_id)
        if session is None or self.context.state._closing:
            return
        if event.kind is ApplicationEventKind.REQUEST_STARTED:
            return
        if getattr(session, "application_request_id", None) != event.request_id:
            if event.kind is ApplicationEventKind.REQUEST_FAILED and not getattr(session, "application_request_id", None):
                session.application_request_id = event.request_id
            else:
                return
        with self.feature_controller("session")._as(session):
            if (event.persistence_ok is False
                    and event.kind in (
                        ApplicationEventKind.REQUEST_COMPLETED,
                        ApplicationEventKind.REQUEST_FAILED,
                        ApplicationEventKind.REQUEST_CANCELLED,
                    )
                    and (
                        not self.context.state._save_warned
                        or (event.error and "ذخیره یا صف‌بندی نشد" in event.error)
                    )):
                self.context.state._save_warned = True
                warning = (
                    "ذخیره‌ی پاسخ روی دیسک ناموفق بود. پاسخ در صف اضطراری نگه داشته شده است؛ "
                    "Kira را تا بازیابی ذخیره‌سازی نبند."
                )
                if event.error and "ذخیره یا صف‌بندی نشد" in event.error:
                    warning = (
                        "یک پیام به دلیل پرشدن/خرابی صف ذخیره‌سازی نه روی دیسک ذخیره شد و نه در صف قرار گرفت. "
                        "برنامه را نبند و فوراً مشکل ذخیره‌سازی را برطرف کن."
                    )
                self.feature_controller("session").add_chat(
                    "error",
                    warning + (f"\nعلت: {event.error}" if event.error else ""),
                )
            if event.kind is ApplicationEventKind.PROVIDER_CHUNK:
                if session is self.context.state.front:
                    self.context.views.kode_activity.update("در حال نوشتن پاسخ…")
                self.feature_controller("runtime").on_stream_chunk(event.chunk, event.content)
            elif event.kind is ApplicationEventKind.PROVIDER_FINAL and event.result is not None:
                if session is self.context.state.front:
                    self.context.views.kode_activity.complete("پاسخ آماده شد")
                result = event.result
                response = dict(result.metadata)
                response.update({
                    "text": result.content,
                    "response_status": result.status.value,
                    "request_id": event.request_id,
                    "session_id": event.session_id,
                })
                self.feature_controller("runtime").on_stream_done(response)
            elif event.kind is ApplicationEventKind.REQUEST_CANCELLED:
                if session is self.context.state.front:
                    self.context.views.kode_activity.cancel("درخواست متوقف شد")
                self.feature_controller("runtime").on_stream_done({
                    "text": event.content,
                    "stopped": True,
                    "request_id": event.request_id,
                    "session_id": event.session_id,
                })
            elif event.kind is ApplicationEventKind.REQUEST_FAILED:
                if session is self.context.state.front:
                    self.context.views.kode_activity.fail("پاسخ با خطا متوقف شد")
                if event.metadata.get("interrupted"):
                    self.feature_controller("runtime").on_stream_done({
                        "text": event.content,
                        "interrupted": event.error or "Provider stream interrupted",
                        "request_id": event.request_id,
                        "session_id": event.session_id,
                    })
                else:
                    self.feature_controller("runtime").on_error(event.error or "Chat request failed")

    def _maybe_attach_eye_frame(self, text, attachments, *, detail=False):
        """Eye Mode only: attach ONE fresh screenshot when the question is about the screen.

        Never attaches while busy (a queued frame would be stale), never when the user attached something,
        and never accumulates: each turn gets its own latest frame. Small-text questions use 1280x720.
        """
        self.context.session._eye_auto_turn = None
        if attachments or self.context.session.busy or not self.context.state._game_mode_enabled:
            return attachments
        if not (detail or refers_to_screen(text)):
            return attachments
        if not self.context.services.settings.get("eye_auto_screenshot", True):
            return attachments
        try:
            frame = self.feature_controller("attachments_vision")._live_vision_attachment(text, detail=detail)
        except Exception:  # noqa: BLE001 - a failed capture must never block ordinary chat
            return attachments
        if not frame:
            return attachments
        self.context.session._eye_auto_turn = {"text": str(text), "detail": bool(detail or wants_detail_capture(text))}
        return [frame]

    def maybe_retry_eye_detail(self, reply):
        """After an unreadable reply to an auto screenshot, resend ONCE at 1280x720 (never loops)."""
        turn = getattr(self.context.session, "_eye_auto_turn", None)
        self.context.session._eye_auto_turn = None
        if not turn or turn.get("detail") or not reply_was_unreadable(reply):
            return
        session = self.context.state.cur

        def run():
            if self.context.state._closing or self.context.state.cur is not session or session.busy:
                return
            with self.feature_controller("session")._as(session):
                try:                                              # she could not make out the screen: a small, honest "confused"
                    self.context.adapters.director.event("vision_unclear")
                    self.context.services.mood_service.on_event("vision_unclear", "eye", character_id=session.cid)
                except Exception:  # noqa: BLE001 - feeling is a bonus; the retry must still happen
                    pass
                self.feature_controller("session").add_chat(
                    "system", "🔍 متن برای مدل ریز بود؛ یک بار دیگر با رزولوشن بالاتر (۱۲۸۰×۷۲۰) می‌فرستم."
                )
                self.submit(turn["text"], None, None, _eye_detail=True)

        QTimer.singleShot(0, run)

    def submit(self, text, attachments=None, _voice=None, *, _eye_detail=False):
        if self.context.state.cur.status in ("closing", "closed", "failed"):
            return
        if _voice is None:
            voice, self.context.session._voice_next = self.context.session._voice_next, False
        else:
            voice, self.context.session._voice_next = bool(_voice), False
        if self.context.session.busy and not attachments:
            try:
                control_dispatch = self.context.services.chat_application_service.dispatch_control_commands(
                    self.context.state.cur.session_id,
                    text,
                    metadata={"character_id": self.context.state.cur.cid},
                )
            except Exception:  # noqa: BLE001 - a control message must never block normal chat
                control_dispatch = None
            if control_dispatch is not None and control_dispatch.handled:
                if control_dispatch.reply_text:
                    self.feature_controller("session").add_chat("system", control_dispatch.reply_text)
                return
        attachments = self._maybe_attach_eye_frame(text, attachments, detail=_eye_detail)
        self.feature_controller("session")._ensure_session_conversation(self.context.state.cur)
        result = self.context.services.chat_application_service.submit_message(
            self.context.state.cur.session_id, text, attachments, voice,
            busy=self.context.session.busy,
            conversation_id=self.context.state.cur.conversation_id,
            character_id=self.context.state.cur.cid,
        )
        if not result.accepted:
            return
        if result.queued:
            count = self.context.services.chat_application_service.pending_count(self.context.state.cur.session_id)
            self.context.views.status.setText(
                f"پیام در صف است ({count}) — بعد از پایان پاسخ فعلی ارسال می‌شود."
            )
            return

    def _process_chat_request(self, text, attachments=None, _voice=False):
        voice = bool(_voice)
        if self.context.services.coding_agent_application_service.dispatch(
            code_chat=getattr(self.context.views, "code_chat", None),
            text=text,
            voice=voice,
            attachments=attachments,
            request_id=self.context.state.cur.application_request_id,
            complete_local_request=self.context.services.chat_application_service.complete_local_request,
        ):
            return  # Coding Agent owns this separate execution lifecycle.
        self.context.session._turn_voice = voice
        if self.context.services.voice_application_service.is_speaking():
            self.context.adapters.director.event("user_interrupt")
        self.feature_controller("runtime").safe_stop_speaker()
        self.context.adapters.animator.touch()
        self.context.session._body_done = []
        original_text = str(text or "")
        self.context.services.tool_agent.begin_turn(self.context.state.cur.cid)
        if not attachments:
            self.context.services.tool_agent.prepare_control_dispatch(
                original_text, session_id=self.context.state.cur.cid
            )
        has_image = any(item.get("kind") == "image" for item in (attachments or []))
        command_dispatch = self.context.services.chat_application_service.dispatch_commands(
            self.context.state.cur.application_request_id,
            original_text,
            metadata={
                "has_attachments": bool(attachments),
                "has_image": has_image,
                "character_id": self.context.state.cur.cid,
            },
        )
        text = command_dispatch.rewritten_text or original_text
        force_img = bool(command_dispatch.metadata.get("force_image_search"))
        force_web = bool(command_dispatch.metadata.get("force_web_search"))
        img_search = bool(
            has_image
            and not self.context.services.web_search_service.explicit_no_web(text)
            and (force_img or self.context.services.settings.get("image_search", False))
        )
        # Live perception is sent as a bounded text context. Raw frames are sent only
        # through explicit image attachments or the user's manual screenshot action.
        packed = None
        if self.context.state.cur.application_request_id:
            try:
                packed = self.context.services.chat_application_service.prepare_request_attachments(
                    self.context.state.cur.application_request_id, text=text, search=img_search
                )
            except (AttributeError, ValueError):
                packed = None
        if packed is None and attachments:
            packed = self.context.services.chat_application_service.compose_attachments(
                text, attachments, search=img_search
            )
        if packed is not None:
            img_search = bool(packed.get("images")) and (
                not self.context.services.web_search_service.explicit_no_web(text)
                and (force_img or self.context.services.settings.get("image_search", False))
            )
        if packed and packed.get("errors"):
            self.attachment_controller.show_error(packed["errors"])
            if not packed.get("prepared_count") and not text.strip():
                self.context.services.chat_application_service.fail_request(
                    self.context.state.cur.application_request_id,
                    "No attachment content could be prepared.",
                )
                return
        if packed is not None and force_web:
            # Preserve the user's literal /web command in the visible and durable chat history.
            presentation = self.context.services.chat_application_service.compose_attachments(original_text, attachments, search=img_search)
            packed["display"] = presentation["display"]
            packed["stored"] = presentation["stored"]
        self.context.session._turn_extra = packed
        self.context.session._turn_attach_kinds = [str(item.get("kind")) for item in (attachments or [])]
        self.feature_controller("session").add_chat(
            "user",
            packed["display"] if packed else original_text,
            images=attachments if packed else None,
        )
        self.context.session._tool_plan = (
            None
            if command_dispatch.handled and not command_dispatch.continue_chat
            else self.context.services.tool_agent.plan(text, session_id=self.context.state.cur.cid)
        )
        self.feature_controller("runtime").save_message("user", packed["stored"] if packed else original_text)
        if command_dispatch.handled and not command_dispatch.continue_chat:
            self.feature_controller("runtime").reply_local(command_dispatch.reply_text or "فرمان اجرا شد.")
            return
        self.context.session.busy = True
        if self.context.state.cur is self.context.state.front:
            self.context.views.kode_activity.start("در حال فکر کردن…")
        self.context.views.gen_stop_btn.show()
        self.feature_controller("session").set_status("st_thinking")
        self.feature_controller("runtime").set_badge("connecting", self.context.session.client.preview_route())
        self.feature_controller("attachments_vision").show_upload_tiles(attachments)
        self.context.adapters.director.event("user_message")
        self.context.adapters.director.event("response_started")
        self.context.session._plain_retry = False
        self.context.session._web_found = None
        self.context.session._image_search_turn = False
        if img_search and packed:
            self.context.session._image_search_turn = True
            self.begin_image_search(text, packed, packed["images"])
            return
        query, forced = self.context.services.web_search_service.plan_request(
            text, self.context.services.settings, self.context.session._tool_plan, force_web=force_web
        )
        if query:
            self.begin_web_search(
                query, packed if packed else text,
                packed["images"] if packed else [], request_text=text,
            )
            return
        self.begin_reply()

    def begin_reply(self):
        try:
            self.start_worker(plain=False)
        except Exception as exc:                                  # noqa: BLE001 - never leave the window stuck in 'busy'
            self.context.adapters.director.event("response_failed")
            self.context.services.chat_application_service.fail_request(
                self.context.state.cur.application_request_id, f"{type(exc).__name__}: {exc}"
            )

    # ---- web search ----

    def toggle_web_search(self, on):
        self.context.services.settings["web_search"] = bool(on)
        save_settings(self.context.services.settings)
        self.update_web_tip()

    def update_web_tip(self):
        self.context.views.web_btn.setToolTip("جست‌وجوی وب: " + ("روشن — کیرا وقتی سؤال به اطلاعات روز نیاز دارد (قیمت، خبر، امروز…) یا بگویی «سرچ کن» در وب می‌گردد. "
                                                  "برای اجبار: /web عبارت" if self.context.views.web_btn.isChecked() else "خاموش — فقط با نوشتن /web عبارت جست‌وجو می‌کند"))

    # ---- image search (a picture is looked up on the web) ----
    def toggle_image_search(self, on):
        on = bool(on)
        self.context.services.settings["image_search"] = on
        save_settings(self.context.services.settings)
        for widget in (getattr(self.context.views, "img_search_btn", None),):
            if widget is not None and widget.isChecked() != on:
                widget.blockSignals(True)
                widget.setChecked(on)
                widget.blockSignals(False)
        bubble = getattr(self.context.adapters, "bubble", None)
        if bubble is not None and bubble.img_btn.isChecked() != on:
            bubble.set_image_search(on)
        self.update_image_search_tip()

    def update_image_search_tip(self):
        btn = getattr(self.context.views, "img_search_btn", None)
        if btn is not None:
            btn.setToolTip("جست‌وجوی تصویری: " + ("روشن — عکسی که می‌فرستی در وب جست‌وجو می‌شود تا معلوم شود چیست. "
                                                  "ترتیب: Gemini (با خودِ عکس) ← توصیف عکس و جست‌وجو با Tavily ← DuckDuckGo. "
                                                  "برای یک پیام: /img" if btn.isChecked() else
                                                  "خاموش — عکس فقط به مدل داده می‌شود. برای جست‌وجوی یک عکس، پیام را با /img شروع کن."))

    def begin_image_search(self, hint, base_text, images):
        from .workers import SearchWorker

        options = self.context.services.web_search_service.image_search_options(
            self.context.services.settings, hint, images, self.context.session.client
        )
        self.context.session._search_token += 1
        self.context.session._search_base = (base_text, images)
        if self.context.state.cur is self.context.state.front:
            self.context.views.kode_activity.start("در حال جست‌وجوی تصویر در وب…")
        self.context.views.status.setText("🔎 در حال جست‌وجوی تصویر در وب…")
        self.context.session._search_worker = SearchWorker(
            self.context.session._search_token,
            options.query,
            options.api_key,
            options.depth,
            user_text=options.user_text,
            gemini=options.gemini,
            fallback=options.fallback,
            images=list(options.images),
            describe=options.describe,
        )
        self.context.session._search_worker.done.connect(self.context.state.cur.relay.search_done)
        self.context.session._search_worker.start()

    def begin_web_search(self, query, base_text, images, request_text=None):
        from .workers import SearchWorker

        if not self.context.services.web_search_service.can_search(self.context.services.settings):
            self.feature_controller("session").add_chat("system", self.context.services.web_search_service.missing_key_message())
            self.begin_reply()
            return
        self.context.session._search_token += 1
        self.context.session._search_base = (base_text, images)
        if self.context.state.cur is self.context.state.front:
            self.context.views.kode_activity.start(f"در حال جست‌وجوی وب: «{query[:60]}»…")
        self.context.views.status.setText(f"🌐 در حال جست‌وجوی وب: «{query[:60]}»…")
        conversation_id = self.feature_controller("session")._ensure_session_conversation(self.context.state.cur)
        history = self.context.services.chat_application_service.conversation_context(
            8, session_id=self.context.state.cur.cid, conversation_id=conversation_id
        )
        options = self.context.services.web_search_service.web_search_options(
            self.context.services.settings, query, history, self.context.session.client,
            character_id=self.context.state.cur.cid,
            request_text=request_text or query,
        )
        self.context.session._search_worker = SearchWorker(
            self.context.session._search_token,
            options.query,
            options.api_key,
            options.depth,
            rewrite=options.rewrite,
            user_text=options.user_text,
            gemini=options.gemini,
            fallback=options.fallback,
        )
        self.context.session._search_worker.done.connect(self.context.state.cur.relay.search_done)
        self.context.session._search_worker.start()

    def test_web_search(self):
        """Settings button: one real Tavily search with the key typed in the box (no need to save first)."""
        from .workers import TaskWorker

        key, depth = self.context.views.tavily_key.text().strip(), self.context.views.web_depth.currentData()
        gem = self.context.services.web_search_service.gemini_credentials(self.context.services.settings)
        self.context.views.web_test_btn.setEnabled(False)
        self.context.views.web_test_btn.setText("در حال آزمایش (چند ثانیه)…")
        self.context.state._web_test_worker = TaskWorker(lambda: self.context.services.web_search_service.diagnose(key, depth, self.context.services.web_search_service.value("WEB_TEST_QUERY"), gem))
        self.context.state._web_test_worker.done.connect(self.on_web_test_done)
        self.context.state._web_test_worker.start()

    @Slot(object)
    def on_web_test_done(self, res):
        self.context.views.web_test_btn.setEnabled(True)
        self.context.views.web_test_btn.setText("آزمایش جست‌وجوی وب")
        ok, rep = res
        if not ok:
            QMessageBox.warning(self.window, "آزمایش جست‌وجوی وب", f"آزمایش انجام نشد:\n{rep}")
            return
        lines = []
        for name, label in (("tavily", "Tavily (اول)"), ("google", "Google / Gemini (دوم)"), ("ddg", "DuckDuckGo (سوم)")):
            e = rep["engines"][name]
            lines.append(f"{label}: " + (f"✓ کار می‌کند — {e['sources']} منبع · «{e['first'][:50]}»" if e["ok"] else f"✕ {e['error']}"))
        extra = self.context.services.web_search_service.assessment_text(rep.get("assessment"))
        QMessageBox.information(self.window, "آزمایش جست‌وجوی وب",
                                "\n".join(lines) + f"\n\nعبارت آزمایش: «{rep['probe']}»" + (f"\n{extra}" if extra else "")
                                + "\nکیرا به همین ترتیب امتحان می‌کند و از اولین موتور سالم استفاده می‌شود.")

    def add_sources(self, found):
        html = sources_html(found.get("results"), f"منابع ({self.context.services.web_search_service.engine_label(found.get('engine'))}) · جست‌وجو برای «{found.get('query', '')}»")
        a = found.get("assessment") or {}
        if html and a.get("phrase"):
            text = self.context.services.web_search_service.assessment_text(a)
            colour = "#7fd99a" if a.get("matched") else "#ffb86b"
            html += f'<p dir="rtl" align="right" style="margin:3px 0 0 0;color:{colour};">{text if text.startswith("⚠") else "✓ " + text}</p>'
        if html:
            ui_dir = "rtl" if self.context.services.settings.get("ui_lang", "fa") == "fa" else "ltr"
            self.context.session.view.append(message_html("system", "", "", ui_dir, html))
            bar = self.context.session.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def on_web_done(self, token, ok, result):
        if self.context.state._closing or token != self.context.session._search_token or not self.context.session.busy:
            return                                                   # stopped / superseded meanwhile
        if ok:
            base, images = self.context.session._search_base
            self.context.session._web_found = result
            if result.get("note"):
                self.feature_controller("session").add_chat("system", "🌐 " + result["note"])
            self.context.session._turn_extra = self.context.services.web_search_service.merge_search_content(
                base, images, self.context.services.web_search_service.format_evidence(result),
                image_search=bool(getattr(self.context.session, "_image_search_turn", False)),
            )
            if self.context.state.cur is self.context.state.front:
                self.context.views.kode_activity.update(f"{len(result['results'])} منبع پیدا شد؛ در حال بررسی و آماده‌سازی پاسخ…")
            self.context.views.status.setText(f"{'🔎 Google' if result.get('engine') == 'google' else ('🦆 DuckDuckGo' if result.get('engine') == 'ddg' else '🌐 Tavily')}: {len(result['results'])} منبع پیدا شد؛ در حال پاسخ دادن…")
        elif getattr(self.context.session, "_image_search_turn", False):
            # the picture itself is still in the request: she answers from what she sees and says what is unconfirmed
            self.feature_controller("session").add_chat("system", f"🔎 جست‌وجوی تصویری انجام نشد: {result}")
            base, images = self.context.session._search_base
            self.context.session._turn_extra = self.context.services.web_search_service.merge_search_content(
                base, images,
                "[جست‌وجوی وب برای این تصویر انجام نشد. فقط از روی چیزی که در تصویر می‌بینی جواب بده، "
                "حدس نزن و هر چیزی که مطمئن نیستی را صریح «تأییدنشده» بگو.]",
                image_search=False,
            )
        else:
            # no usable web result: do not let the model improvise from memory; Kira says she does not know
            self.context.adapters.director.event("response_failed")
            if self.context.state.cur is self.context.state.front:
                self.context.views.kode_activity.fail("جست‌وجوی وب ناموفق بود")
            self.feature_controller("session").add_chat("system", f"🌐 جست‌وجوی وب انجام نشد: {result}")
            self.context.session._turn_extra = None
            self.feature_controller("runtime").reply_local(self.context.services.web_search_service.failure_reply(result), "sad")
            self.feature_controller("runtime").finish_request(None)
            self.feature_controller("runtime")._send_next_pending()
            return
        self.begin_reply()

    def start_worker(self, plain):
        window = int(self.context.services.settings.get("memory_context_limit", 12))
        conversation_id = self.feature_controller("session")._ensure_session_conversation(self.context.state.cur)
        history = self.context.services.chat_application_service.conversation_context(
            window, character_id=self.context.state.cur.cid, conversation_id=conversation_id
        )
        mode = self.detect_mode(history)                          # Active Mode of THIS message (None = switched off in settings)
        try:
            older = self.context.services.chat_application_service.recent_messages(
                window + 40, character_id=self.context.state.cur.cid, conversation_id=conversation_id
            )[:-window] if window else []
            # Every character has its own saved conversation; only Kira owns the legacy evidence index.
            character_id = self.context.state.cur.cid
            memory_block = self.context.services.memory_service.build_block(
                character_id,
                older,
                voice_samples=(mode is None or mode.name == modes.CHAT),
                query=evidence_memory.query_from_context(history),
                budget=evidence_memory.budget_for(self.context.services.settings, self.context.session.client),
            )
            total = self.context.services.chat_application_service.message_count(
                character_id, conversation_id
            )
            if self.context.services.memory_service.needs_summary(character_id, total, window):
                self.context.services.memory_service.maintain(
                    character_id,
                    self.context.services.chat_application_service.recent_messages(
                        min(total, 3000), character_id=character_id, conversation_id=conversation_id
                    ),
                    window,
                )
        except Exception:                                         # noqa: BLE001 - memory is a bonus, never block a reply
            memory_block = ""
        try:                                                      # her persisted mood + how he seems right now (same text for every provider)
            mood_query = latest_user_text(history)
            mood_block = self.context.services.mood_service.build_block(
                mode.name if mode else modes.CHAT,
                query=mood_query,
                character_id=self.context.state.cur.cid,
            )
        except Exception:                                         # noqa: BLE001
            mood_block = ""

        # Brain planning remains application policy; only its prompt contribution
        # is injected into the independent ContextBuilder.
        try:
            extra0 = self.context.session._turn_extra
            # Eye Mode context is a rolling timeline of observations produced by
            # the background monitor loop. Do not capture/attach a fresh image for
            # every chat turn; build_chat_vision_context injects the accumulated facts.
            has_att = bool(self.context.session._turn_attach_kinds or (extra0 and (extra0.get("images") or "--- فایل ضمیمه" in str(extra0.get("model", "")))))
            last_user = latest_user_text(history)
            self.context.session._brain_user_text = str(last_user)
            self.context.session._brain_mode_name = mode.name if mode else None
            self.context.session._brain = self.context.services.brain_application_service.decide(
                last_user,
                mode,
                self.context.session._tool_plan,
                has_att,
                self.context.services.tool_agent.tasks.active(self.context.state.cur.cid) is not None,
                self.context.services.settings,
            )
        except Exception:                                         # noqa: BLE001
            self.context.session._brain = self.context.services.brain_application_service.default_decision()

        character_layer = self.context.services.character_service.prompt_for(self.context.services.settings)
        body_context = ""
        if self.feature_controller("runtime").body_active():                                    # preserve existing 3D body instruction and completed-action note
            body_context = ("" if plain else body_ctl.format_hint()) + body_ctl.done_note(self.context.session._body_done)

        context = {
            "messages": history,
            "character_id": self.context.state.cur.cid,
            "character_profile": self.feature_controller("session").active_character(),
            "settings": self.context.services.settings,
            "memory": memory_block,
            "mood": mood_block,
            "character_context": character_layer,
            "format_hint": "" if plain else self.context.adapters.director.format_hint(),
            "voice_input": self.context.session._turn_voice,
            "mode": mode,
            "body_context": body_context,
            "tool_context": self.feature_controller("attachments_vision").build_chat_vision_context(
                self.context.session._turn_extra
            ),
            "active_capabilities": tuple(sorted(getattr(self.context.session._tool_plan, "categories", ()) or ())),
            "turn_extra": self.context.session._turn_extra,
            "max_context_chars": self.context.services.settings.get("chat_context_char_limit", 0),
        }

        self.feature_controller("runtime")._stream_begin()
        temperature = modes.temperature_for(mode, self.context.services.settings["temperature"]) if mode else self.context.services.settings["temperature"]
        relay = self.context.state.cur.relay
        request_id = self.context.state.cur.application_request_id
        if not request_id:
            raise RuntimeError("No active Chat application request is associated with this session")
        self.context.session.worker = self.context.services.chat_application_service.start_provider_request(
            request_id, context,
            provider_callbacks={"tool_event": relay.tool, "event": relay.stream_event},
            provider_event_dispatcher=relay.provider_event.emit,
            router=self.context.session.client, temperature=temperature,
            retry_index=1 if plain else 0, agent=self.context.services.tool_agent, plan=self.context.session._tool_plan,
            role=self.context.session._brain.stage, route_id=self.context.session._brain.route_id,
        )
        self.feature_controller("session").refresh_tab_buttons()

    MODE_LABELS = {"chat": "گپ", "task": "کار / کمک", "strict": "فقط جواب"}

    def detect_mode(self, context):
        """Active Mode for the message being answered (see kira/modes.py). Never raises: on any problem the old prompt is used."""
        self.context.session._turn_mode = None
        if not self.context.services.settings.get("active_modes", True):
            return None
        try:
            users = [m["content"] for m in context if m.get("role") == "user"]
            extra = self.context.session._turn_extra
            # an image or a file is attached: the structured kinds decide (the text markers are only a fallback)
            has_attachment = bool(self.context.session._turn_attach_kinds or (extra and (extra.get("images") or "--- فایل ضمیمه" in str(extra.get("model", "")))))
            earlier = users[:-1]
            try:                                                   # a "no jokes" request must outlive the short context window
                conversation_id = self.context.state.cur.conversation_id
                longer = [
                    m["content"] for m in self.context.services.chat_application_service.recent_messages(
                        80, character_id=self.context.state.cur.cid, conversation_id=conversation_id
                    ) if m.get("role") == "user"
                ]
                if len(longer) > len(users):
                    earlier = longer[:-1]
            except Exception:                                      # noqa: BLE001
                pass
            self.context.session._turn_mode = modes.detect(users[-1] if users else "", earlier, has_attachment)
        except Exception:                                         # noqa: BLE001
            self.context.session._turn_mode = None
        return self.context.session._turn_mode

    def stop_generation(self):
        """Stop button: ends the answer now; text received so far is kept."""
        if self.context.services.coding_agent_application_service.stop_session(getattr(self.context.views, "code_chat", None), self.context.state.cur):
            self.context.services.chat_application_service.complete_local_request(self.context.state.cur.application_request_id)
            return                                                # the Coding Agent owns its separate task lifecycle
        if self.context.session._search_worker is not None and self.context.session._search_worker.isRunning():
            self.context.session._search_token += 1                                   # the late search result is ignored
            self.feature_controller("session").add_chat("system", "جست‌وجو متوقف شد.")
            self.context.services.chat_application_service.cancel_request(self.context.state.cur.application_request_id)
            return
        self.context.services.tool_agent.request_cancel(self.context.state.cur.cid)
        self.context.services.chat_application_service.cancel_request(self.context.state.cur.application_request_id)
        self.context.views.gen_stop_btn.setEnabled(False)

    # ---- body control (the 3D body moves on chat commands: kira/body.py) ----

    def _install_chat_commands(self):
        """Wire the existing feature owners into the shared chat command registry."""
        registry = create_default_command_registry(
            permission_checker=self.feature_controller("runtime")._check_chat_command_permission,
            usage_parser=usage.parse_command,
            usage_report=usage.report,
            body_parser=body_ctl.parse_user_command,
            body_is_active=self.feature_controller("runtime").body_active,
            body_handler=self.feature_controller("runtime").run_body,
            web_parser=self.context.services.web_search_service.parse_web_command,
            image_parser=self.context.services.web_search_service.parse_image_command,
            task_control_parser=parse_tool_task_control,
            task_running_checker=self.context.services.tool_agent.is_task_running,
            tool_agent=self.context.services.tool_agent,
            desktop_action_matcher=match_safe_action,
            desktop_action_handler=lambda text: run_safe_action(text, allow_desktop=True),
            game_mode_handler=lambda action: self.feature_controller("attachments_vision").handle_game_mode_command(action),
        )
        self.context.services.chat_application_service.set_command_registry(registry)
        self.command_registry = registry


# Backward-compatible import name for callers migrating from mixin composition.
ChatMixin = ChatController
