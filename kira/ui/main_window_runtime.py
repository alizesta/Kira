"""Runtime feature controller for the desktop window."""
from .main_window_runtime_support import (
    ChatHistoryError,
    Listener,
    MemoryDialog,
    Path,
    PermissionDecision,
    QApplication,
    QFileDialog,
    QMessageBox,
    QTextCursor,
    QTimer,
    ROOT,
    SOUNDS_DIR,
    body_ctl,
    brain,
    message_html,
    mood,
    random,
    save_settings,
    scrub_lines,
    storage,
    time,
)


from .window_feature_controller import WindowFeatureController


class RuntimeController(WindowFeatureController):
    def _check_chat_command_permission(self, command, _request):
        reason = self.game_mode_application_service.command_denial_reason(
            self._game_mode_profile, command.required_permissions
        )
        return PermissionDecision(False, reason) if reason else True

    def body_active(self):
        """True while Kira's VRM body is on screen in the front chat and the setting 'body_control' is on."""
        return bool(self.settings.get("body_control", True) and getattr(self.animator, "body_enabled", False)
                    and getattr(self.animator, "kira_art_active", True))

    def run_body(self, names):
        """Perform body commands, each name once per message (a streamed reply is parsed again and again)."""
        if not names or not self.body_active():
            return
        fresh = [n for n in names if n not in self._body_done]
        if not fresh:
            return
        self._body_done.extend(fresh)
        try:
            self.animator.body.emit(body_ctl.payload(fresh))
        except Exception:                                      # noqa: BLE001 - a body move must never break the chat
            pass

    # ---- live text ----

    def display_text(self, raw):
        """User-visible part of a (possibly unfinished) streamed reply: emotion tag removed, half-written tag hidden."""
        head = raw.lstrip()
        if head.startswith("[") and "]" not in head and len(head) < 62:       # a tag still being typed by the model
            return ""
        return scrub_lines(self.director.parse_reply(raw).text)       # echoed router / system notes are never shown

    def _stream_begin(self):
        self._stream_text, self._stream_pos, self._stream_dirty, self._stream_mood = "", None, False, None
        self._emotion_applied = False
        self._t_req = time.monotonic()
        self._t_first = None
        self._speech_live = False                                   # speech of THIS reply has started while it is still being written
        self.voice_application_service.stream_reset()
        self._stream_timer.start()

    def _speak_stream(self, text):
        """Speech starts from the first finished sentence while the model is still writing (setting: stream_speech)."""
        if not (self.voice_btn.isChecked() and self.settings.get("stream_speech", True)):
            return
        try:
            self.voice_application_service.stream_text(text)
            self._speech_live = True
        except Exception as exc:                                    # noqa: BLE001
            self.on_voice_error(f"صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def on_stream_chunk(self, piece, accumulated_content=None):
        # ResponseHandler owns ordered aggregation; the window keeps only the
        # current text snapshot required by its existing incremental renderer.
        self._stream_text = (str(accumulated_content) if accumulated_content is not None
                             else self._stream_text + str(piece))
        self._stream_dirty = True

    def _stream_flush(self, final=False):
        if not self._stream_dirty and not final:
            return
        self._stream_dirty = False
        meta = self.director.parse_reply(self._stream_text)         # pure parse: no side effects
        self.run_body(meta.body)                                    # [body:...] tags written by the model
        text = self.display_text(self._stream_text)
        if meta.source == "tag" and not self._emotion_applied:     # the model's own tag arrived: react right away
            self._emotion_applied = True
            self.director.on_reply(meta)
        if not text.strip():
            return
        self._speak_stream(text)
        name = self.character_service.display_name(self.settings)
        ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
        html = message_html("assistant", name, text, ui_dir, accent=self.accent())
        doc = self.chat.document()
        cur = QTextCursor(doc)
        if self._stream_pos is None:
            self._stream_pos = max(0, doc.characterCount() - 1)
        cur.setPosition(self._stream_pos)
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        if self._stream_pos > 0:
            cur.insertBlock()
        cur.insertHtml(html)
        if getattr(self, "bubble", None) is not None:
            self.bubble.set_live(name, text, ui_dir)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ---- indicator ----
    BADGE_HEAD = {"idle": "● Ready", "connecting": "◌ Connecting", "waiting": "◌ Processing", "streaming": "● Connected",
                  "failover": "↪ Failover", "done": "✓ Done", "stopped": "■ Stopped", "error": "✕ Error"}

    def set_badge(self, phase, info=None):
        """Indicator next to the input. `info` comes straight from the router (never guessed from settings)."""
        self._badge_phase = phase
        if info:
            self._route_info = info
        self.cur.badge = (phase, info)
        if self.cur is not self.front:
            return
        if phase == "error":
            text, tip = self.BADGE_HEAD["error"], "آخرین درخواست ناموفق بود."
        elif not info:
            text = self.BADGE_HEAD[phase] + (" · No active route" if phase == "idle" else "")
            tip = "هیچ Route فعالی آماده نیست. تب Route را ببین."
        else:
            kind = "Cloud" if info.get("kind") == "cloud" else "Local"
            text = f"{self.BADGE_HEAD[phase]} · {info['label']} / {info['model']} · {kind}"
            tip = (f"Provider: {info['label']}\nModel: {info['model']}\nنوع: {kind}\nRoute: {info.get('route_id', '')}\n"
                   "کلیک: جزئیات و انتخاب دستی مدل")
        glyph = text.split(" ", 1)[0]
        compact = f"{glyph} {info['label']} / {info['model']}" if (info and phase != "error") else text
        self.route_badge.setText(text, display=compact)             # full text for tests/tooltips, short one on the chip
        self.route_badge.setToolTip(tip)

    MENU_ROUTES = 500                                          # effectively all models: the menus scroll (menu-scrollable) instead of cutting the list

    def build_badge_menu(self):
        menu = self.route_menu
        menu.clear()
        menu.addAction("جزئیات Route فعال…", self.show_route_details)
        menu.addAction(self.t("route_open"), lambda: self.go_tab(self.tab_keys.index("tab_ai")))
        menu.addSeparator()
        manual = self.settings.get("manual_route_id", "")
        auto = menu.addAction("خودکار (بر اساس اولویت)")
        auto.setCheckable(True)
        auto.setChecked(not manual)
        auto.triggered.connect(lambda checked=False: self.select_route(""))
        routes = self.client.available_routes()
        shown = routes[: self.MENU_ROUTES]
        chosen = next((r for r in routes if r["route_id"] == manual), None)
        if chosen is not None and chosen not in shown:         # the manually selected route is always visible
            shown = shown[:-1] + [chosen]
        for info in shown:
            icon = "☁" if info["kind"] == "cloud" else "⌂"
            model = info["model"] if len(info["model"]) <= 38 else info["model"][:37] + "…"
            act = menu.addAction(f"{icon}  {info['label']} / {model}")
            act.setCheckable(True)
            act.setChecked(info["route_id"] == manual)
            act.triggered.connect(lambda checked=False, rid=info["route_id"]: self.select_route(rid))
        if len(routes) > len(shown):
            menu.addSeparator()
            more = menu.addAction(f"{len(routes) - len(shown)} Route دیگر در مدیریت Route…")
            more.triggered.connect(lambda checked=False: self.go_tab(self.tab_keys.index("tab_ai")))

    def show_route_details(self):
        info = self._route_info or self.client.preview_route()
        if not info:
            QMessageBox.information(self.window, "Route", "هیچ Route فعالی آماده نیست.")
            return
        st = next((x for x in self.client.status() if x["name"] == info["route_id"]), {})
        route = self.provider_application_service.find_route(self.settings, info["route_id"]) or {}
        manual = self.settings.get("manual_route_id", "")
        lines = [f"Provider: {info['label']}", f"Model: {info['model']}", f"نوع اتصال: {'Cloud' if info['kind'] == 'cloud' else 'Local'}",
                 f"Route: {info['route_id']}  ({'انتخاب دستی' if manual == info['route_id'] else 'انتخاب خودکار'})",
                 f"وضعیت سلامت: {st.get('health', 'unknown')}", f"Timeout: {route.get('timeout', '-')}s · Cooldown: {route.get('cooldown', '-')}s"]
        if st.get("last_ms") is not None:
            lines.append(f"آخرین پاسخ موفق: {st['last_ms']} ms")
        if st.get("last_error"):
            lines.append(f"آخرین خطا: {st['last_error']}")
        QMessageBox.information(self.window, "جزئیات Route فعال", "\n".join(lines))

    def select_route(self, route_id):
        """Manual choice ('' = automatic). Wins over priority; failover (if on) may still move on when it fails."""
        try:
            self.provider_application_service.set_manual_route(self.settings, route_id)
        except KeyError:
            return
        if route_id:
            self.client.reset_cooldowns(route_id)
        self.save_now()
        self.refresh_route_list()
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def save_now(self):
        """Route Manager autosave."""
        try:
            save_settings(self.settings)
            return True
        except Exception as exc:                                  # noqa: BLE001
            if hasattr(self, "route_status"):
                self.route_status.setText(f"✕ ذخیره‌ی خودکار ناموفق بود: {exc}")
            return False

    # ---- events / completion ----

    def on_stream_event(self, e):
        phase = e.get("phase")
        self.on_upload_event(phase, e.get("percent"))
        if phase == "uploading":                                   # request body (images / files) being sent to the model
            self.status.setText(f"در حال ارسال ضمیمه‌ها به مدل… {e.get('percent', 0)}%")
            return
        self.set_badge(phase, e)
        if phase == "streaming" and self._t_first is None:
            self._t_first = time.monotonic() - (self._t_req or time.monotonic())
            mode = getattr(self, "_turn_mode", None)
            self.status.setText(f"اولین Token بعد از {int(self._t_first * 1000)} ms · {e['label']} / {e['model']}"
                                + (f" · حالت: {self.MODE_LABELS[mode.name]}" if mode else ""))
        elif phase == "failover":
            self.status.setText(f"Failover → {e['label']} / {e['model']}")
        elif phase in ("connecting", "waiting"):
            self.set_status("st_thinking")

    def on_tool_event(self, e):
        """Status line while a tool runs (no layout change). The real outcome is always reported by Kira's answer."""
        phase = e.get("phase")
        if phase == "tool_start":
            self.status.setText(f"🔧 {e.get('label', '')}…")
        elif phase == "plan_step":
            self.status.setText(f"🧭 مرحله {e.get('i', '?')} از {e.get('n', '?')}: {e.get('title', '')}")
        elif phase == "plan_ready":
            self.status.setText(f"🧭 برنامه آماده شد: {e.get('n', '?')} مرحله" + (f" — {e['estimate']}" if e.get("estimate") else ""))

    def on_stream_done(self, res):
        if self._closing:
            return
        self._stream_timer.stop()
        raw = res.get("text", "")
        meta = self.director.parse_reply(raw)
        self.run_body(meta.body)
        text = meta.text
        if not text.strip() and not res.get("stopped") and not res.get("interrupted") and not getattr(self, "_plain_retry", False):
            self._plain_retry = True            # model answered with a tag only: ask again without tags (counted as a retry)
            self.start_worker(plain=True)
            return
        if not res.get("stopped") and not res.get("interrupted"):
            request_id = getattr(self.cur, "application_request_id", None)
            if request_id:
                self.chat_application_service.complete_request(
                    request_id, raw, metadata=res, persist=bool(text.strip())
                )
        self._stream_flush(final=True)
        self._stream_pos = None
        self.bubble.commit_live()
        self.finish_request(res)
        if res.get("stopped"):
            if text.strip():
                self.save_message("assistant", raw, status="cancelled", metadata={"stream": "stopped"}, persist=False)
            self.add_chat("system", "تولید پاسخ متوقف شد." + (" متن دریافت‌شده نگه داشته شد." if text.strip() else ""))
            if self._speech_live:
                self.safe_stop_speaker()                           # the Stop button also silences the rest of the spoken reply
            self.animator.set_expression("neutral", hold=2)
        elif res.get("interrupted"):
            self.save_message("assistant", raw, status="interrupted", metadata={"stream": "provider_interrupted"}, persist=False)
            self.add_chat("error", f"ارتباط وسط پاسخ قطع شد؛ بخش دریافت‌شده نگه داشته شد و تکرار نمی‌شود.\n{res['interrupted']}")
            if self._speech_live:
                self.voice_application_service.stream_end()                          # what arrived is still spoken to its end
            self.director.event("response_failed")
        elif not text.strip():
            self.add_chat("error", self.t("empty"))
            self.director.event("response_failed")
        else:
            self.save_message("assistant", raw, persist=False)
            try:                                                   # quiet second look (rules; optional background model call)
                brain.after_turn(self.client, self.settings, getattr(self, "_brain", brain.Decision()), getattr(self, "_brain_user_text", ""),
                                 text, res.get("tools"), getattr(self, "_brain_mode_name", None), bool(self._tool_plan),
                                 character_id=self.cur.cid)
            except Exception:                                      # noqa: BLE001
                pass
            if not self._emotion_applied:                          # no tag from the model: tag-less fallback (keywords / neutral)
                self.director.on_reply(meta)
            if self._speech_live:
                self.voice_application_service.stream_end()                          # the sentences were spoken while it was written: say the tail
            else:
                self.say(text)
        if self._web_found and text.strip():
            self.add_sources(self._web_found)
        self._web_found = None
        self._send_next_pending()

    def on_error(self, error):
        if self._closing:
            return
        self._stream_timer.stop()
        self._stream_flush(final=True)
        self._stream_pos = None
        if getattr(self, "_speech_live", False):
            self.voice_application_service.stream_end()
        self.add_chat("error", self.t("reply_err", e=error))
        self.director.event("response_failed")
        self.finish_request(None)
        self.set_badge("error")
        self.check_status()
        self._send_next_pending()

    def _schedule_chat_callback(self, callback):
        QTimer.singleShot(0, callback)

    def _send_next_pending(self, session=None):
        """Ask the Chat application service to drain only the completed session's FIFO queue."""
        session = session or self.cur
        if self._closing or self.sessions.get(session.cid) is not session:
            return
        if self._vision_session is session and not self._worker_is_running(self._vision_worker):
            worker = self._vision_worker
            if worker is not None:
                try:
                    worker.deleteLater()
                except RuntimeError:
                    pass
                self._vision_worker = None
            self._vision_session = None
        self.chat_application_service.dispatch_next(session.session_id, busy=session.busy)
        profiles = self.character_service.all_profiles(self.settings)
        if session.cid not in profiles and not self._session_has_pending_chat_work(session):
            self._schedule_chat_callback(self.sync_sessions)

    def finish_request(self, res=None):
        self.clear_upload_tiles()
        self.busy = False
        if self.cur is not self.front:
            self.cur.unread = True                                 # an answer arrived for a tab you are not looking at
        self.refresh_tab_buttons()
        self._speech_live = False
        self.gen_stop_btn.hide()
        self.gen_stop_btn.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input.setEnabled(True)
        self.input.setFocus()
        self.set_status("st_ready")
        if res and res.get("provider"):
            m = res.get("metrics") or {}
            detail = f"آخرین پاسخ: {res['provider']} / {res['model']}"
            if m.get("total_ms") is not None:
                detail += f" ({m['total_ms']} ms"
                if m.get("first_token_ms") is not None:
                    detail += f" · اولین Token {m['first_token_ms']} ms"
                detail += ")"
            if m.get("failovers"):
                detail += f" · Failover×{m['failovers']}"
            self.status.setText(detail)
            self.set_badge("stopped" if res.get("stopped") else "done",
                           {"route_id": res["route_id"], "provider": res["provider"], "label": res["label"],
                            "model": res["model"], "kind": res["kind"]})
        elif res is not None:
            self.set_badge("idle", self.client.preview_route())
        self.refresh_route_list()

    def reply_local(self, text, expression="happy"):
        self.add_chat("assistant", text)
        self.save_message("assistant", text)
        self.chat_application_service.complete_local_request(self.cur.application_request_id)
        self.animator.set_expression(expression, hold=4)
        self.say(text)

    def save_message(self, role, content, *, status="complete", metadata=None, persist=True):
        """Persist through ChatApplicationService; keep character memory/mood observation in the UI adapter."""
        if persist:
            outcome = self.chat_application_service.persist_message(
                self.cur.session_id, role, content,
                request_id=getattr(self.cur, "application_request_id", None),
                conversation_id=getattr(self.cur, "conversation_id", None),
                status=status, character_id=self.cur.cid, metadata=metadata,
            )
            ok = outcome.ok
        else:
            ok = True
        self.memory_service.observe(self.cur.cid, role, content)
        try:
            self._sync_mood_character()
            if role == "user":
                mood.on_user_message(content)
                if self.cur is self.front:
                    self.apply_mood_to_avatar()
            elif role == "assistant":
                meta = self.director.parse_reply(content)
                if meta is not None:
                    mood.on_reply(meta.emotions, meta.intensity)
        except Exception:                                         # noqa: BLE001 - mood is a bonus, never block the chat
            pass
        if persist and ok:
            self._save_warned = False
        elif persist and not ok and not self._save_warned:
            self._save_warned = True
            self.add_chat("error", "ذخیره‌ی گفتگو روی دیسک ناموفق بود. گفتگو تا بسته‌شدن برنامه در حافظه می‌ماند و با اولین ذخیره‌ی موفق نوشته می‌شود."
                                   f"\nعلت: {self.chat_application_service.last_persistence_error}")
        return ok

    def safe_stop_speaker(self):
        """Stopping the voice must never be able to stop the app from doing its real work (sending a chat message)."""
        try:
            self.voice_application_service.stop_speaking()
        except Exception as exc:                                  # noqa: BLE001
            self.on_voice_error(f"توقف صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def say(self, text):
        if self.voice_btn.isChecked():
            try:
                self.voice_application_service.speak(text)
            except Exception as exc:                              # noqa: BLE001
                self.on_voice_error(f"صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def on_mood_changed(self, mood):
        if mood == "bored" and self.settings.get("idle_talk", True) and not self.busy \
                and time.time() - getattr(self, "_last_idle", 0) > 180:
            self._last_idle = time.time()
            lines = self.reactions.get("_idle", {}).get(self.settings.get("ui_lang", "fa"), [])
            if lines and self.voice_btn.isChecked():
                self.voice_application_service.speak(random.choice(lines), -5, -3, cache=True)

    # ---------- click reactions ----------

    def on_region_clicked(self, region):
        if not self.settings.get("click_reactions", True):
            return
        cfg = self.reactions.get(region)
        if not cfg:
            return
        variants = cfg.get("variants")
        if variants:                                             # several reactions per area: random, never the same twice in a row
            last = self._last_variant.get(region, -1)
            pool = [i for i in range(len(variants)) if i != last] or [0]
            pick = random.choice(pool)
            self._last_variant[region] = pick
            cfg = {**{k: v for k, v in cfg.items() if k != "variants"}, **variants[pick]}
        self.animator.touch()
        if cfg.get("gesture"):
            self.animator.gesture.emit(str(cfg["gesture"]))
        now = time.time()
        hist = [x for x in self._clicks.get(region, []) if now - x < 6] + [now]
        self._clicks[region] = hist
        if len(hist) >= 4 and cfg.get("annoyed"):
            cfg = {**cfg, **cfg["annoyed"]}
        rig = self.animator.rig
        for part, ch, val in cfg.get("kicks", []):
            rig.kick(part, ch, val)
        self.animator.set_expression(cfg.get("expression", "happy"), hold=2.5)
        files = [f for f in (SOUNDS_DIR / region).glob("*") if f.suffix.lower() in (".wav", ".mp3", ".ogg")] \
            if (SOUNDS_DIR / region).exists() else []
        if files:
            self.voice_application_service.play_file(random.choice(files))
            return
        lang = self.settings.get("ui_lang", "fa")
        lines = cfg.get(lang) or cfg.get("fa") or []
        if lines and self.voice_btn.isChecked():
            self.voice_application_service.speak(random.choice(lines), cfg.get("rate"), cfg.get("pitch"), cache=True)

    # ---------- voice, microphone, wake mode ----------

    def set_voice_enabled(self, on):
        self.settings["speak_replies"] = bool(on)
        for w in (self.voice_btn, self.voice_page.speak_chk):
            w.blockSignals(True)
            w.setChecked(bool(on))
            w.blockSignals(False)
        save_settings(self.settings)
        if not on:
            self.safe_stop_speaker()

    def on_stop_clicked(self):
        if self.voice_application_service.is_speaking():
            self.director.event("user_interrupt")
        self.safe_stop_speaker()

    def on_speech_started(self):
        self.director.event("tts_started")           # real audio playback has begun
        self.voice_application_service.begin_speaking()
        self.set_status("st_speaking")

    def on_speech_finished(self):
        self.director.event("tts_stopped")           # playback ended or was stopped
        self.voice_application_service.end_speaking()
        QTimer.singleShot(500, self.unmute)
        if self.listener:
            self.on_listener_state("listening")
        else:
            self.set_status("st_ready")

    def _on_kira_level(self, level):
        if self.listener:
            self.listener.kira_level = float(level)

    def on_user_barge_in(self):
        """The person started talking over Kira: she stops at once, and what they say is still heard as the next message."""
        if self.voice_application_service.is_speaking():
            self.director.event("user_interrupt")
        self.safe_stop_speaker()

    def unmute(self):
        self.voice_application_service.unmute_if_idle()

    def toggle_mic(self):
        if self.mic_btn.isChecked():
            self.start_listener()
        else:
            if self.wake_btn.isChecked():
                self.wake_btn.setChecked(False)
                self.toggle_wake()
            self.stop_listener()

    def _create_voice_listener(self):
        return Listener(
            self.settings["whisper_model"],
            self.settings["stt_language"],
            self,
            sensitivity=self.settings.get("mic_sensitivity", 100),
            barge_in=self.settings.get("barge_in", True),
            settings=self.settings,
        )

    def start_listener(self):
        self.voice_application_service.start_recording()

    def stop_listener(self):
        self.voice_application_service.stop_recording()
        self.set_status("st_ready")
        self.update_engine_label()

    def _on_voice_listener_finished(self, listener, was_current, restart_requested):
        if was_current:
            self.mic_btn.setChecked(False)
        self.update_engine_label()
        if self._closing:
            return
        if restart_requested and self.mic_btn.isChecked():
            QTimer.singleShot(0, self.start_listener)
        elif was_current:
            self.set_status("st_ready")

    def on_listener_error(self, msg):
        self.add_chat("error", msg)
        self.mic_btn.setChecked(False)
        if self.wake_btn.isChecked():
            self.wake_btn.setChecked(False)
            self.animator.set_sleeping(False)
            self.wake_timer.stop()
        # Keep the worker owned until its stream has closed; stop() is non-blocking.
        self.stop_listener()

    def on_listener_state(self, state):
        if state == "listening":
            self.update_engine_label()
            self.set_status("st_sleeping" if (self.wake_btn.isChecked() and not self.awake) else "st_listening")
        else:
            self.set_status({"loading": "st_loading", "hearing": "st_hearing", "transcribing": "st_transcribing"}.get(state, "st_ready"))

    def update_engine_label(self):
        eng = getattr(self.listener, "engine", None) if self.listener else None
        via = getattr(self.listener, "via", "") if self.listener else ""
        if via == "local:qwen3-asr":
            label = "Qwen3-ASR · Local"
        elif via == "local:whisper" or eng == "whisper":
            label = "Whisper · Local"
        elif self.listener is not None and self.listener.isRunning():
            label = "STT محلی"
        else:
            label = "—"
        self.voice_page.engine_lbl.setText(label)

    def toggle_wake(self):
        if self.wake_btn.isChecked():
            if not self.mic_btn.isChecked():
                self.mic_btn.setChecked(True)
                self.start_listener()
            self.go_sleep()
        else:
            self.wake_timer.stop()
            self.awake = False
            self.animator.set_sleeping(False)

    def go_sleep(self):
        self.wake_timer.stop()
        self.awake = False
        if self.wake_btn.isChecked():
            self.animator.set_sleeping(True)
            self.on_listener_state("listening")

    def wake_up(self):
        self.awake = True
        self.animator.set_sleeping(False)
        self.animator.set_expression("happy", hold=2)
        self.wake_timer.start(int(self.settings["wake_timeout"]) * 1000)

    def on_heard(self, text):
        self.animator.touch()
        decision = self.voice_application_service.interpret_transcript(
            text,
            wake_enabled=self.wake_btn.isChecked(),
            awake=self.awake,
        )
        if decision.action == "ignore":
            return
        if decision.action == "wake_only":
            self.wake_up()
            self.reply_local(self.t("yes"))
            return
        if decision.action == "wake_submit":
            self.wake_up()
            text = decision.text
        elif decision.action == "sleep":
            self.add_chat("user", text)
            self.go_sleep()
            self.say(self.t("night"))
            return
        elif decision.action == "stop":
            if self.wake_btn.isChecked() and self.awake:
                self.wake_timer.start(int(self.settings["wake_timeout"]) * 1000)
            self.safe_stop_speaker()
            return
        elif self.wake_btn.isChecked() and self.awake:
            self.wake_timer.start(int(self.settings["wake_timeout"]) * 1000)
        self._voice_next = True
        self.submit(text)

    # ---------- companion window ----------

    def toggle_companion(self):
        if self.companion.isVisible():
            self.companion.hide()
        else:
            self.companion.show()
            self.companion.raise_()

    def on_companion_visibility(self, _):
        self.update_companion_btn()

    def update_companion_btn(self):
        shown = self.companion.isVisible()
        self.companion_btn.setToolTip(self.t("hide_char" if shown else "show_char"))
        self.companion_btn.setChecked(shown)

    def _running_background_workers(self):
        """Return every owned QThread that must finish before Qt destroys the window."""
        workers = []
        for session in getattr(self, "sessions", {}).values():
            workers.extend((getattr(session, "worker", None), getattr(session, "_search_worker", None)))
        for name in (
            "_local_voice_worker", "_api_worker", "_route_worker", "_bench_worker",
            "_scan_worker", "_provider_test_worker", "_ollama_worker", "_vision_worker",
            "_web_test_worker", "_attach_worker", "_model_import_worker", "_stopping_listener",
            "_stopping_game_audio_listener", "game_audio_listener", "listener",
        ):
            workers.append(getattr(self, name, None))
        unique = []
        seen = set()
        for worker in workers:
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            try:
                if worker.isRunning():
                    unique.append(worker)
            except RuntimeError:
                continue
        return unique

    def _resume_close_after_workers(self):
        if getattr(self, "_closing", False):
            QTimer.singleShot(0, self.close)

    def _clear_chat_coordinator_queues(self):
        """Cancel work now; keep attachments/command resources alive for Session teardown."""
        self.chat_application_service.begin_shutdown()

    def _dispose_chat_application_service(self) -> bool:
        """Release Chat-owned registries only after SessionManager released each Session."""
        try:
            self.chat_application_service.dispose()
            return True
        except Exception:
            return False

    def _dispose_window_feature_services(self) -> bool:
        """Release per-window application services after their Qt workers have drained."""
        voice_service = getattr(self, "voice_application_service", None)
        if voice_service is not None:
            try:
                if not voice_service.dispose():
                    return False
            except Exception:
                return False
        vision_service = getattr(self, "vision_application_service", None)
        if vision_service is not None:
            try:
                vision_service.reset()
            except Exception:
                return False
        return True

    def closeEvent(self, event):
        if (getattr(self, "tray", None) is not None and self.settings.get("close_to_tray")
                and not getattr(self, "_quitting", False)):
            event.ignore()                                           # X only hides; "Exit" in the tray menu really quits
            self.hide_to_tray()
            return
        if getattr(self, "_closing", False):
            if self._running_background_workers():
                event.ignore()
                return
            if not self._dispose_window_feature_services():
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
            for session in self.session_application_service.list_sessions():
                session.busy = False
            if not self.session_application_service.dispose():
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
            if not self._dispose_chat_application_service():
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
            event.accept()
            QTimer.singleShot(0, QApplication.quit)
            return
        local_worker = getattr(self, "_local_voice_worker", None)
        if local_worker is not None and local_worker.isRunning():
            if not getattr(self, "_close_after_local_voice", False):
                self._close_after_local_voice = True
                self.add_chat("system", "بارگذاری یا آزمایش موتور صوتی هنوز در حال اجراست؛ Kira پس از پایان امن آن بسته می‌شود.")
            event.ignore()
            return
        # ChatApplicationService owns cancellation and persists partial output once.
        self._closing = True
        self._clear_chat_coordinator_queues()
        if getattr(self, "code_chat", None) is not None:
            self.code_chat.shutdown()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        self.bubble.close()
        self.tool_agent.request_cancel()
        # Stop attachment reads as soon as shutdown starts; a large file must not
        # keep the window alive for the full read when the user already cancelled.
        self.cancel_attachments()
        for sess in self.sessions.values():
            if sess.client is not None:
                sess.client.cancel()
            if sess.timer is not None:
                sess.timer.stop()
        for timer_name in ("wake_timer", "_game_poll_timer", "_game_capture_timer", "_mood_ui_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        self._set_game_vision_capture(False)
        self._stop_game_audio_listener()
        self.game_mode.set_enabled(False)
        for sess in self.sessions.values():
            for w in (sess.worker, sess._search_worker):
                if w is not None and w.isRunning():
                    w.wait(3000)
        for name in ("_api_worker", "_route_worker", "_bench_worker", "_scan_worker", "_provider_test_worker",
                     "_ollama_worker", "_vision_worker", "_web_test_worker", "_attach_worker"):
            w = getattr(self, name, None)
            if w is not None and w.isRunning():
                w.wait(5000)
        self.stop_listener()
        self.safe_stop_speaker()
        self.companion.close()
        running = self._running_background_workers()
        if running:
            self.add_chat(
                "system",
                "چند کار پس‌زمینه هنوز در حال پایان‌اند؛ پنجره بعد از پایان امن آن‌ها بسته می‌شود."
            )
            for worker in running:
                try:
                    worker.finished.connect(self._resume_close_after_workers)
                except RuntimeError:
                    pass
            event.ignore()
            # Cover the race where a worker finishes while its finished slot is connected.
            if not self._running_background_workers():
                QTimer.singleShot(0, self.close)
            return
        if not self._dispose_window_feature_services():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        for session in self.session_application_service.list_sessions():
            session.busy = False
        if not self.session_application_service.dispose():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        if not self._dispose_chat_application_service():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        event.accept()
        QTimer.singleShot(0, QApplication.quit)                     # the tray keeps 'last window closed' from quitting by itself

    def reload_chat_view(self):
        for sess in self.sessions.values():             # every character's conversation is shown again from the database
            if sess.view is None:
                continue
            with self._as(sess):
                self.chat.clear()
                self.restore_history(200)

    def clear_chat(self):
        who = self.character_service.display_name(self.settings)
        question = (f"تاریخچه‌ی گفتگوی «{who}» پاک شود؟ (گفتگوی بقیه‌ی کاراکترها دست‌نخورده می‌ماند)"
                    if self.settings.get("ui_lang", "fa") == "fa" else f"Delete the saved history of {who}? (the other characters' chats stay)")
        if QMessageBox.question(self.window, self.t("clear_t"), question) == QMessageBox.Yes:
            try:
                self.chat_application_service.clear_history(self.cur.cid)      # only THIS character's conversation; saves a snapshot first, nothing is deleted if that fails
                # Facts, moments and habits remain in the character's own memory file.
                self.memory_service.forget_conversation(self.cur.cid)
                self.tool_agent.clear_session(self.cur.cid) # clear only this character's tasks, tool context, grants and temporary research
                brain.reset_state(self.cur.cid)
            except ChatHistoryError as exc:
                QMessageBox.warning(self.window, self.t("clear_t"), str(exc))
                return
            self.chat.clear()
            self.add_chat("system", self.t("mem_cleared") + " (اگر اشتباه بود: تنظیمات ← عمومی ← «بازگرداندن آخرین پاک‌سازی».)")

    def apply_mood_to_avatar(self):
        """A quick front-session avatar reaction; background Sessions never drive the visible avatar."""
        if self.cur is not self.front:
            return
        try:
            hint = mood.avatar_hint()
            eid = self.director.library.resolve_name(hint[0]) if hint else None
            if eid:
                self.director.engine.request([eid], hint[1], 3.0, "event", self.director.clock(), tag="mood")
        except Exception:                                         # noqa: BLE001
            pass

    def open_memory_dialog(self):
        character_id = self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(character_id, {})
        character_name = profile.get("name") or character_id.title()
        MemoryDialog(
            self.window,
            character_id,
            character_name=character_name,
            memory_service=self.memory_service,
            mood_service=self.mood_service,
        ).exec()

    def restore_cleared_chat(self):
        try:
            n = self.chat_application_service.restore_history()
        except ChatHistoryError as exc:
            QMessageBox.information(self.window, "بازگرداندن گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.add_chat("system", f"{n} پیام بازگردانده شد." if n else "همه‌ی پیام‌های آن پاک‌سازی از قبل در گفتگو بودند.")

    def import_old_chat(self, path=None):
        """Merge chats from an older Kira database (nothing is overwritten; duplicates are skipped)."""
        if path is None:
            start = ""
            for folder in storage.legacy_candidates(ROOT):
                start = str(Path(folder))
                break
            path, _ = QFileDialog.getOpenFileName(self.window, "انتخاب فایل گفتگوی قدیمی (kira_memory.sqlite3)", start or str(ROOT),
                                                  "SQLite (*.sqlite3 *.db);;All files (*)")
            if not path:
                return
        try:
            n = self.chat_application_service.import_history(path)
        except ChatHistoryError as exc:
            QMessageBox.warning(self.window, "ورود گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.add_chat("system", f"{n} پیام از فایل قدیمی وارد شد." if n else "پیام جدیدی در آن فایل نبود (همه از قبل وجود داشتند).")

    @staticmethod
    def html(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


# Backward-compatible import name for callers migrating from mixin composition.
RuntimeMixin = RuntimeController
