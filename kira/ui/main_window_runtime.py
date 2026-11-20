"""Runtime feature controller for the desktop window."""
from PySide6.QtCore import Slot
import logging

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
    message_html,
    random,
    save_settings,
    scrub_lines,
    storage,
    time,
)


from .window_feature_controller import WindowFeatureController
from ..emotion.lifecycle import should_observe_message


_log = logging.getLogger(__name__)


class RuntimeController(WindowFeatureController):
    def _check_chat_command_permission(self, command, _request):
        reason = self.context.services.game_mode_application_service.command_denial_reason(
            self.context.state._game_mode_profile, command.required_permissions
        )
        return PermissionDecision(False, reason) if reason else True

    def body_active(self):
        """True while Kira's VRM body is on screen in the front chat and the setting 'body_control' is on."""
        return bool(self.context.services.settings.get("body_control", True) and getattr(self.context.adapters.animator, "body_enabled", False)
                    and getattr(self.context.adapters.animator, "kira_art_active", True))

    def run_body(self, names):
        """Perform body commands, each name once per message (a streamed reply is parsed again and again)."""
        if not names or not self.body_active():
            return
        fresh = [n for n in names if n not in self.context.session._body_done]
        if not fresh:
            return
        self.context.session._body_done.extend(fresh)
        try:
            self.context.adapters.animator.body.emit(body_ctl.payload(fresh))
        except Exception:                                      # noqa: BLE001 - a body move must never break the chat
            pass

    # ---- live text ----

    def display_text(self, raw):
        """User-visible part of a (possibly unfinished) streamed reply: emotion tag removed, half-written tag hidden."""
        head = raw.lstrip()
        if head.startswith("[") and "]" not in head and len(head) < 62:       # a tag still being typed by the model
            return ""
        return scrub_lines(self.context.adapters.director.parse_reply(raw).text)       # echoed router / system notes are never shown

    def _stream_begin(self):
        self.context.session._stream_text, self.context.session._stream_pos, self.context.session._stream_dirty, self.context.session._stream_mood = "", None, False, None
        self.context.session._emotion_applied = False
        self.context.session._t_req = time.monotonic()
        self.context.session._t_first = None
        self.context.session._speech_live = False                                   # speech of THIS reply has started while it is still being written
        self.context.services.voice_application_service.stream_reset()
        self.context.session.timer.start()

    def _speak_stream(self, text):
        """Speech starts from the first finished sentence while the model is still writing (setting: stream_speech)."""
        if not (self.context.views.voice_btn.isChecked() and self.context.services.settings.get("stream_speech", True)):
            return
        try:
            self.context.services.voice_application_service.stream_text(text)
            self.context.session._speech_live = True
        except Exception as exc:                                    # noqa: BLE001
            self.feature_controller("session").on_voice_error(f"صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def on_stream_chunk(self, piece, accumulated_content=None):
        # ResponseHandler owns ordered aggregation; the window keeps only the
        # current text snapshot required by its existing incremental renderer.
        self.context.session._stream_text = (str(accumulated_content) if accumulated_content is not None
                             else self.context.session._stream_text + str(piece))
        self.context.session._stream_dirty = True

    def _stream_flush(self, final=False):
        if not self.context.session._stream_dirty and not final:
            return
        self.context.session._stream_dirty = False
        meta = self.context.adapters.director.parse_reply(self.context.session._stream_text)         # pure parse: no side effects
        self.run_body(meta.body)                                    # [body:...] tags written by the model
        text = self.display_text(self.context.session._stream_text)
        # Explicit model tags are applied immediately; keyword-inferred emotions are
        # applied only once the reply is complete, so partial text cannot keep changing
        # the voice profile while the stream is still arriving.
        apply_emotion = meta.source == "tag" or (final and meta.source == "keywords")
        if apply_emotion and not self.context.session._emotion_applied:
            self.context.session._emotion_applied = True
            self.context.services.voice_application_service.set_emotion(meta.emotions, meta.intensity)
            self.context.adapters.director.on_reply(meta)
        if not text.strip():
            return
        self._speak_stream(text)
        name = self.context.services.character_service.display_name(self.context.services.settings)
        ui_dir = "rtl" if self.context.services.settings.get("ui_lang", "fa") == "fa" else "ltr"
        footer = self.feature_controller("session").chat_actions_html("assistant", text) if final else ""     # copy / edit / speak once the reply is complete
        html = message_html("assistant", name, text, ui_dir, footer_html=footer, accent=self.feature_controller("session").accent())
        doc = self.context.session.view.document()
        cur = QTextCursor(doc)
        if self.context.session._stream_pos is None:
            self.context.session._stream_pos = max(0, doc.characterCount() - 1)
        cur.setPosition(self.context.session._stream_pos)
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        if self.context.session._stream_pos > 0:
            cur.insertBlock()
        cur.insertHtml(html)
        if getattr(self.context.adapters, "bubble", None) is not None:
            self.context.adapters.bubble.set_live(name, text, ui_dir)
        bar = self.context.session.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ---- indicator ----
    BADGE_HEAD = {"idle": "● Ready", "connecting": "◌ Connecting", "waiting": "◌ Processing", "streaming": "● Connected",
                  "failover": "↪ Failover", "done": "✓ Done", "stopped": "■ Stopped", "error": "✕ Error"}

    def set_badge(self, phase, info=None):
        """Indicator next to the input. `info` comes straight from the router (never guessed from settings)."""
        self.context.session._badge_phase = phase
        if info:
            self.context.session._route_info = info
        self.context.state.cur.badge = (phase, info)
        if self.context.state.cur is not self.context.state.front:
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
        self.context.views.route_badge.setText(text, display=compact)             # full text for tests/tooltips, short one on the chip
        self.context.views.route_badge.setToolTip(tip)

    MENU_ROUTES = 500                                          # effectively all models: the menus scroll (menu-scrollable) instead of cutting the list

    def build_badge_menu(self):
        menu = self.context.views.route_menu
        menu.clear()
        menu.addAction("جزئیات Route فعال…", self.show_route_details)
        menu.addAction(self.feature_controller("session").t("route_open"), lambda: self.feature_controller("session").go_tab(self.context.views.tab_keys.index("tab_ai")))
        menu.addSeparator()
        manual = self.context.services.settings.get("manual_route_id", "")
        auto = menu.addAction("خودکار (بر اساس اولویت)")
        auto.setCheckable(True)
        auto.setChecked(not manual)
        auto.triggered.connect(lambda checked=False: self.select_route(""))
        routes = self.context.session.client.available_routes()
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
            more.triggered.connect(lambda checked=False: self.feature_controller("session").go_tab(self.context.views.tab_keys.index("tab_ai")))

    def show_route_details(self):
        info = self.context.session._route_info or self.context.session.client.preview_route()
        if not info:
            QMessageBox.information(self.window, "Route", "هیچ Route فعالی آماده نیست.")
            return
        st = next((x for x in self.context.session.client.status() if x["name"] == info["route_id"]), {})
        route = self.context.services.provider_application_service.find_route(self.context.services.settings, info["route_id"]) or {}
        manual = self.context.services.settings.get("manual_route_id", "")
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
            self.context.services.provider_application_service.set_manual_route(self.context.services.settings, route_id)
        except KeyError:
            return
        if route_id:
            self.context.session.client.reset_cooldowns(route_id)
        self.save_now()
        self.feature_controller("provider_settings").refresh_route_list()
        if not self.context.session.busy:
            self.set_badge("idle", self.context.session.client.preview_route())

    def save_now(self):
        """Route Manager autosave."""
        try:
            save_settings(self.context.services.settings)
            return True
        except Exception as exc:                                  # noqa: BLE001
            if hasattr(self.context.views, "route_status"):
                self.context.views.route_status.setText(f"✕ ذخیره‌ی خودکار ناموفق بود: {exc}")
            return False

    # ---- events / completion ----

    def on_stream_event(self, e):
        phase = e.get("phase")
        self.feature_controller("attachments_vision").on_upload_event(phase, e.get("percent"))
        if phase == "uploading":                                   # request body (images / files) being sent to the model
            self.context.views.status.setText(f"در حال ارسال ضمیمه‌ها به مدل… {e.get('percent', 0)}%")
            return
        self.set_badge(phase, e)
        if phase == "streaming" and self.context.session._t_first is None:
            self.context.session._t_first = time.monotonic() - (self.context.session._t_req or time.monotonic())
            mode = getattr(self.context.session, "_turn_mode", None)
            self.context.views.status.setText(f"اولین Token بعد از {int(self.context.session._t_first * 1000)} ms · {e['label']} / {e['model']}"
                                + (f" · حالت: {self.feature_controller("chat").MODE_LABELS[mode.name]}" if mode else ""))
        elif phase == "failover":
            self.context.views.status.setText(f"Failover → {e['label']} / {e['model']}")
        elif phase in ("connecting", "waiting"):
            self.feature_controller("session").set_status("st_thinking")

    def on_tool_event(self, e):
        """Status line while a tool runs (no layout change). The real outcome is always reported by Kira's answer."""
        phase = e.get("phase")
        if phase == "tool_start":
            self.context.views.status.setText(f"🔧 {e.get('label', '')}…")
        elif phase == "plan_step":
            self.context.views.status.setText(f"🧭 مرحله {e.get('i', '?')} از {e.get('n', '?')}: {e.get('title', '')}")
        elif phase == "plan_ready":
            self.context.views.status.setText(f"🧭 برنامه آماده شد: {e.get('n', '?')} مرحله" + (f" — {e['estimate']}" if e.get("estimate") else ""))

    def on_stream_done(self, res):
        if self.context.state._closing:
            return
        self.context.session.timer.stop()
        raw = res.get("text", "")
        meta = self.context.adapters.director.parse_reply(raw)
        self.run_body(meta.body)
        text = meta.text
        if not text.strip() and not res.get("stopped") and not res.get("interrupted") and not getattr(self.context.session, "_plain_retry", False):
            self.context.session._plain_retry = True            # model answered with a tag only: ask again without tags (counted as a retry)
            self.context.adapters.director.event("response_failed")
            self.feature_controller("chat").start_worker(plain=True)
            return
        if not res.get("stopped") and not res.get("interrupted"):
            request_id = getattr(self.context.state.cur, "application_request_id", None)
            if request_id:
                self.context.services.chat_application_service.complete_request(
                    request_id, raw, metadata=res, persist=bool(text.strip())
                )
        self._stream_flush(final=True)
        self.context.session._stream_pos = None
        self.context.adapters.bubble.commit_live()
        self.finish_request(res)
        if res.get("stopped"):
            self.context.adapters.director.event("response_cancelled")
            if text.strip():
                self.save_message("assistant", raw, status="cancelled", metadata={"stream": "stopped"}, persist=False, observe=False)
            self.feature_controller("session").add_chat("system", "تولید پاسخ متوقف شد." + (" متن دریافت‌شده نگه داشته شد." if text.strip() else ""))
            if self.context.session._speech_live:
                self.safe_stop_speaker()                           # the Stop button also silences the rest of the spoken reply
            self.context.adapters.animator.set_expression("neutral", hold=2)
        elif res.get("interrupted"):
            self.save_message("assistant", raw, status="interrupted", metadata={"stream": "provider_interrupted"}, persist=False, observe=False)
            self.feature_controller("session").add_chat("error", f"ارتباط وسط پاسخ قطع شد؛ بخش دریافت‌شده نگه داشته شد و تکرار نمی‌شود.\n{res['interrupted']}")
            if self.context.session._speech_live:
                self.context.services.voice_application_service.stream_end()                          # what arrived is still spoken to its end
            self.context.adapters.director.event("response_failed")
        elif not text.strip():
            self.feature_controller("session").add_chat("error", self.feature_controller("session").t("empty"))
            self.context.adapters.director.event("response_failed")
        else:
            self.context.adapters.director.event("response_finished")
            self.save_message("assistant", raw, persist=False)
            try:                                                   # quiet second look (rules; optional background model call)
                self.context.services.reflection_application_service.after_turn(
                    self.context.session.client,
                    self.context.services.settings,
                    getattr(self.context.session, "_brain", self.context.services.brain_application_service.default_decision()),
                    getattr(self.context.session, "_brain_user_text", ""),
                    text,
                    res.get("tools"),
                    getattr(self.context.session, "_brain_mode_name", None),
                    bool(self.context.session._tool_plan),
                    character_id=self.context.state.cur.cid,
                )
            except Exception:                                      # noqa: BLE001
                pass
            if not self.context.session._emotion_applied:                          # no tag from the model: tag-less fallback (keywords / neutral)
                self.context.adapters.director.on_reply(meta)
                self.context.services.voice_application_service.set_emotion(meta.emotions, meta.intensity)
            if self.context.session._speech_live:
                self.context.services.voice_application_service.stream_end()                          # the sentences were spoken while it was written: say the tail
            else:
                self.say(text)
        if self.context.session._web_found and text.strip():
            self.feature_controller("chat").add_sources(self.context.session._web_found)
        self.context.session._web_found = None
        self._send_next_pending()

    def on_error(self, error):
        if self.context.state._closing:
            return
        self.context.session.timer.stop()
        self._stream_flush(final=True)
        self.context.session._stream_pos = None
        if getattr(self.context.session, "_speech_live", False):
            self.context.services.voice_application_service.stream_end()
        self.feature_controller("session").add_chat("error", self.feature_controller("session").t("reply_err", e=error))
        self.context.adapters.director.event("response_failed")
        self.finish_request(None)
        self.set_badge("error")
        self.feature_controller("lifecycle").check_status()
        self._send_next_pending()

    def _schedule_chat_callback(self, callback):
        QTimer.singleShot(0, callback)

    def _send_next_pending(self, session=None):
        """Ask the Chat application service to drain only the completed session's FIFO queue."""
        session = session or self.context.state.cur
        if self.context.state._closing or self.context.state.sessions.get(session.cid) is not session:
            return
        if self.context.session._vision_session is session and not self.feature_controller("session")._worker_is_running(self.context.session._vision_worker):
            worker = self.context.session._vision_worker
            if worker is not None:
                try:
                    worker.deleteLater()
                except RuntimeError:
                    pass
                self.context.session._vision_worker = None
            self.context.session._vision_session = None
        self.context.services.chat_application_service.dispatch_next(session.session_id, busy=session.busy)
        profiles = self.context.services.character_service.all_profiles(self.context.services.settings)
        if session.cid not in profiles and not self.feature_controller("session")._session_has_pending_chat_work(session):
            self.feature_controller("session")._schedule_chat_callback(self.feature_controller("session").sync_sessions)

    def finish_request(self, res=None):
        self.feature_controller("attachments_vision").clear_upload_tiles()
        self.context.session.busy = False
        if self.context.state.cur is not self.context.state.front:
            self.context.state.cur.unread = True                                 # an answer arrived for a tab you are not looking at
        self.feature_controller("session").refresh_tab_buttons()
        self.context.session._speech_live = False
        self.context.views.gen_stop_btn.hide()
        self.context.views.gen_stop_btn.setEnabled(True)
        self.context.views.send_btn.setEnabled(True)
        self.context.views.input.setEnabled(True)
        self.context.views.input.setFocus()
        self.feature_controller("session").set_status("st_ready")
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
            self.context.views.status.setText(detail)
            self.set_badge("stopped" if res.get("stopped") else "done",
                           {"route_id": res["route_id"], "provider": res["provider"], "label": res["label"],
                            "model": res["model"], "kind": res["kind"]})
        elif res is not None:
            self.set_badge("idle", self.context.session.client.preview_route())
        self.feature_controller("provider_settings").refresh_route_list()

    def reply_local(self, text, expression="happy"):
        self.feature_controller("session").add_chat("assistant", text)
        self.save_message("assistant", text, observe=False)
        self.context.services.chat_application_service.complete_local_request(self.context.state.cur.application_request_id)
        self.context.adapters.animator.set_expression(expression, hold=4)
        self.say(text)

    def save_message(self, role, content, *, status="complete", metadata=None, persist=True, observe=True):
        """Persist through ChatApplicationService; keep character memory/mood observation in the UI adapter."""
        if persist:
            outcome = self.context.services.chat_application_service.persist_message(
                self.context.state.cur.session_id, role, content,
                request_id=getattr(self.context.state.cur, "application_request_id", None),
                conversation_id=getattr(self.context.state.cur, "conversation_id", None),
                status=status, character_id=self.context.state.cur.cid, metadata=metadata,
            )
            ok = outcome.ok
        else:
            ok = True
        should_observe = should_observe_message(role, status, observe=observe)
        if should_observe:
            self.context.services.memory_service.observe(self.context.state.cur.cid, role, content)
            try:
                self.feature_controller("session")._sync_mood_character()
                if role == "user":
                    self.context.services.mood_service.on_user_message(
                        content, character_id=self.context.state.cur.cid
                    )
                    if self.context.state.cur is self.context.state.front:
                        self.apply_mood_to_avatar()
                elif role == "assistant":
                    meta = self.context.adapters.director.parse_reply(content)
                    if meta is not None:
                        self.context.services.mood_service.on_reply(
                            meta.emotions, meta.intensity, text=meta.text,
                            character_id=self.context.state.cur.cid,
                        )
            except Exception:                                     # noqa: BLE001 - mood is a bonus, never block the chat
                _log.warning("Unable to update conversation memory/emotion state", exc_info=True)
        if persist and ok:
            self.context.state._save_warned = False
        elif persist and not ok and not self.context.state._save_warned:
            self.context.state._save_warned = True
            self.feature_controller("session").add_chat("error", "ذخیره‌ی گفتگو روی دیسک ناموفق بود. گفتگو تا بسته‌شدن برنامه در حافظه می‌ماند و با اولین ذخیره‌ی موفق نوشته می‌شود."
                                   f"\nعلت: {self.context.services.chat_application_service.last_persistence_error}")
        return ok

    def safe_stop_speaker(self):
        """Stopping the voice must never be able to stop the app from doing its real work (sending a chat message)."""
        try:
            self.context.services.voice_application_service.stop_speaking()
        except Exception as exc:                                  # noqa: BLE001
            self.feature_controller("session").on_voice_error(f"توقف صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def say(self, text):
        if self.context.views.voice_btn.isChecked():
            try:
                self.context.services.voice_application_service.speak(text)
            except Exception as exc:                              # noqa: BLE001
                self.feature_controller("session").on_voice_error(f"صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def on_mood_changed(self, mood):
        if mood == "bored" and self.context.services.settings.get("idle_talk", True) and not self.context.session.busy \
                and time.time() - getattr(self, "_last_idle", 0) > 180:
            self._last_idle = time.time()
            lines = self.context.state.reactions.get("_idle", {}).get(self.context.services.settings.get("ui_lang", "fa"), [])
            if lines and self.context.views.voice_btn.isChecked():
                self.context.services.voice_application_service.speak(random.choice(lines), -5, -3, cache=True)

    # ---------- click reactions ----------

    def on_region_clicked(self, region):
        if not self.context.services.settings.get("click_reactions", True):
            return
        cfg = self.context.state.reactions.get(region)
        if not cfg:
            return
        variants = cfg.get("variants")
        if variants:                                             # several reactions per area: random, never the same twice in a row
            last = self.context.state._last_variant.get(region, -1)
            pool = [i for i in range(len(variants)) if i != last] or [0]
            pick = random.choice(pool)
            self.context.state._last_variant[region] = pick
            cfg = {**{k: v for k, v in cfg.items() if k != "variants"}, **variants[pick]}
        self.context.adapters.animator.touch()
        if cfg.get("gesture"):
            self.context.adapters.animator.gesture.emit(str(cfg["gesture"]))
        now = time.time()
        hist = [x for x in self.context.state._clicks.get(region, []) if now - x < 6] + [now]
        self.context.state._clicks[region] = hist
        if len(hist) >= 4 and cfg.get("annoyed"):
            cfg = {**cfg, **cfg["annoyed"]}
        rig = self.context.adapters.animator.rig
        for part, ch, val in cfg.get("kicks", []):
            rig.kick(part, ch, val)
        self.context.adapters.animator.set_expression(cfg.get("expression", "happy"), hold=2.5)
        files = [f for f in (SOUNDS_DIR / region).glob("*") if f.suffix.lower() in (".wav", ".mp3", ".ogg")] \
            if (SOUNDS_DIR / region).exists() else []
        if files:
            self.context.services.voice_application_service.play_file(random.choice(files))
            return
        lang = self.context.services.settings.get("ui_lang", "fa")
        lines = cfg.get(lang) or cfg.get("fa") or []
        if lines and self.context.views.voice_btn.isChecked():
            self.context.services.voice_application_service.speak(random.choice(lines), cfg.get("rate"), cfg.get("pitch"), cache=True)

    # ---------- voice, microphone, wake mode ----------

    def set_voice_enabled(self, on):
        self.context.services.settings["speak_replies"] = bool(on)
        for w in (self.context.views.voice_btn, self.context.views.voice_page.speak_chk):
            w.blockSignals(True)
            w.setChecked(bool(on))
            w.blockSignals(False)
        save_settings(self.context.services.settings)
        if not on:
            self.safe_stop_speaker()

    def on_stop_clicked(self):
        if self.context.services.voice_application_service.is_speaking():
            self.context.adapters.director.event("user_interrupt")
        self.safe_stop_speaker()

    @Slot()
    def on_speech_started(self):
        self.context.adapters.director.event("tts_started")           # real audio playback has begun
        self.context.services.voice_application_service.begin_speaking()
        self.feature_controller("session").set_status("st_speaking")

    @Slot()
    def on_speech_finished(self):
        self.context.adapters.director.event("tts_stopped")           # playback ended or was stopped
        self.context.services.voice_application_service.end_speaking()
        QTimer.singleShot(500, self.unmute)
        if self.context.listener:
            self.on_listener_state("listening")
        else:
            self.feature_controller("session").set_status("st_ready")

    @Slot(float)
    def _on_kira_level(self, level):
        if self.context.listener:
            self.context.listener.kira_level = float(level)

    @Slot()
    def on_user_barge_in(self):
        """The person started talking over Kira: she stops at once, and what they say is still heard as the next message."""
        if self.context.services.voice_application_service.is_speaking():
            self.context.adapters.director.event("user_interrupt")
        self.safe_stop_speaker()

    def unmute(self):
        self.context.services.voice_application_service.unmute_if_idle()

    def _sync_voice_mode_badge(self, state=None):
        """Show the real microphone pipeline, not a misleading Realtime label."""
        badge = getattr(self.context.views, "voice_mode_badge", None)
        if badge is None:
            return
        mic_on = bool(self.context.views.mic_btn.isChecked())
        wake_on = bool(self.context.views.wake_btn.isChecked())
        if not mic_on:
            text = "میکروفن خاموش"
        elif wake_on and not self.context.state.awake:
            text = "منتظر کلمه بیدارباش · STT"
        elif state == "transcribing":
            text = "در حال تبدیل گفتار · STT"
        elif state == "hearing":
            text = "در حال دریافت صدا · STT"
        elif state == "loading":
            text = "آماده‌سازی STT…"
        else:
            text = "شنود پیوسته · STT محلی"
        badge.setText(text)
        badge.setProperty("listening", mic_on)
        badge.setToolTip(
            "مسیر فعال: میکروفن → Qwen3-ASR/Whisper → مدل چت → Piper"
            if mic_on else "میکروفن غیرفعال است."
        )

    def _sync_live_toggle(self, enabled):
        page = getattr(self.context.views, "voice_page", None)
        toggle = getattr(page, "live_toggle", None) if page is not None else None
        if toggle is not None:
            previous = toggle.blockSignals(True)
            toggle.setChecked(bool(enabled))
            toggle.blockSignals(previous)
            toggle.setText("توقف شنود پیوسته" if enabled else "شروع شنود پیوسته")
        self._sync_voice_mode_badge()

    def set_live_listening(self, enabled):
        """Start/stop continuous local STT listening from the Voice page."""
        if self.context.state._closing:
            self._sync_live_toggle(False)
            return
        mic = self.context.views.mic_btn
        try:
            if enabled:
                # Continuous listening must speak its answers and must not remain in
                # wake-word sleep mode (which intentionally ignores ordinary speech).
                wake = self.context.views.wake_btn
                if wake.isChecked():
                    previous = wake.blockSignals(True)
                    wake.setChecked(False)
                    wake.blockSignals(previous)
                    self.context.views.wake_timer.stop()
                    self.context.state.awake = False
                    self.context.adapters.animator.set_sleeping(False)
                self.set_voice_enabled(True)
                if not mic.isChecked():
                    previous = mic.blockSignals(True)
                    mic.setChecked(True)
                    mic.blockSignals(previous)
                    self.start_listener()
                self._sync_live_toggle(True)
            else:
                if mic.isChecked():
                    previous = mic.blockSignals(True)
                    mic.setChecked(False)
                    mic.blockSignals(previous)
                    self.stop_listener()
                self._sync_live_toggle(False)
        except Exception as exc:
            self._sync_live_toggle(False)
            self.feature_controller("session").on_voice_error(
                f"شروع/توقف شنود پیوسته ناموفق بود: {type(exc).__name__}: {exc}"
            )

    def toggle_mic(self):
        if self.context.views.mic_btn.isChecked():
            self._sync_live_toggle(True)
            self.start_listener()
        else:
            self._sync_live_toggle(False)
            if self.context.views.wake_btn.isChecked():
                self.context.views.wake_btn.setChecked(False)
                self.toggle_wake()
            self.stop_listener()

    def _create_voice_listener(self):
        return Listener(
            self.context.services.settings["whisper_model"],
            self.context.services.settings["stt_language"],
            self,
            sensitivity=self.context.services.settings.get("mic_sensitivity", 100),
            barge_in=self.context.services.settings.get("barge_in", True),
            settings=self.context.services.settings,
        )

    def start_listener(self):
        self.context.services.voice_application_service.start_recording()

    def stop_listener(self):
        self.context.services.voice_application_service.stop_recording()
        self.feature_controller("session").set_status("st_ready")
        self.update_engine_label()

    @Slot(object, bool, bool)
    def _on_voice_listener_finished(self, listener, was_current, restart_requested):
        if was_current:
            self.context.views.mic_btn.setChecked(False)
            self._sync_live_toggle(False)
        self.update_engine_label()
        if self.context.state._closing:
            return
        if restart_requested and self.context.views.mic_btn.isChecked():
            QTimer.singleShot(0, self.start_listener)
        elif was_current:
            self.feature_controller("session").set_status("st_ready")

    @Slot(str)
    def on_listener_error(self, msg):
        self.feature_controller("session").add_chat("error", msg)
        self.context.views.mic_btn.setChecked(False)
        self._sync_live_toggle(False)
        self._sync_voice_mode_badge()
        if self.context.views.wake_btn.isChecked():
            self.context.views.wake_btn.setChecked(False)
            self.context.adapters.animator.set_sleeping(False)
            self.context.views.wake_timer.stop()
        # Keep the worker owned until its stream has closed; stop() is non-blocking.
        self.stop_listener()

    @Slot(str)
    def on_listener_state(self, state):
        self._sync_voice_mode_badge(state)
        if state == "listening":
            self.update_engine_label()
            self.feature_controller("session").set_status("st_sleeping" if (self.context.views.wake_btn.isChecked() and not self.context.state.awake) else "st_listening")
        else:
            self.feature_controller("session").set_status({"loading": "st_loading", "hearing": "st_hearing", "transcribing": "st_transcribing"}.get(state, "st_ready"))

    def update_engine_label(self):
        eng = getattr(self.context.listener, "engine", None) if self.context.listener else None
        via = getattr(self.context.listener, "via", "") if self.context.listener else ""
        if via == "local:qwen3-asr":
            label = "Qwen3-ASR · Local"
        elif via == "local:whisper" or eng == "whisper":
            label = "Whisper · Local"
        elif self.context.listener is not None and self.context.listener.isRunning():
            label = "STT محلی"
        else:
            label = "—"
        self.context.views.voice_page.engine_lbl.setText(label)

    def toggle_wake(self):
        if self.context.views.wake_btn.isChecked():
            if not self.context.views.mic_btn.isChecked():
                self.context.views.mic_btn.setChecked(True)
                self.start_listener()
            self.go_sleep()
        else:
            self.context.views.wake_timer.stop()
            self.context.state.awake = False
            self.context.adapters.animator.set_sleeping(False)

    def go_sleep(self):
        self.context.views.wake_timer.stop()
        self.context.state.awake = False
        if self.context.views.wake_btn.isChecked():
            self.context.adapters.animator.set_sleeping(True)
            self.on_listener_state("listening")

    def wake_up(self):
        self.context.state.awake = True
        self.context.adapters.animator.set_sleeping(False)
        self.context.adapters.animator.set_expression("happy", hold=2)
        self.context.views.wake_timer.start(int(self.context.services.settings["wake_timeout"]) * 1000)

    @Slot(str)
    def on_heard(self, text):
        self.context.adapters.animator.touch()
        decision = self.context.services.voice_application_service.interpret_transcript(
            text,
            wake_enabled=self.context.views.wake_btn.isChecked(),
            awake=self.context.state.awake,
        )
        if decision.action == "ignore":
            return
        if decision.action == "wake_only":
            self.wake_up()
            self.reply_local(self.feature_controller("session").t("yes"))
            return
        if decision.action == "wake_submit":
            self.wake_up()
            text = decision.text
        elif decision.action == "sleep":
            self.feature_controller("session").add_chat("user", text)
            self.go_sleep()
            self.say(self.feature_controller("session").t("night"))
            return
        elif decision.action == "stop":
            if self.context.views.wake_btn.isChecked() and self.context.state.awake:
                self.context.views.wake_timer.start(int(self.context.services.settings["wake_timeout"]) * 1000)
            self.safe_stop_speaker()
            return
        elif self.context.views.wake_btn.isChecked() and self.context.state.awake:
            self.context.views.wake_timer.start(int(self.context.services.settings["wake_timeout"]) * 1000)
        self.context.session._voice_next = True
        self.feature_controller("chat").submit(text)

    # ---------- companion window ----------

    def toggle_companion(self):
        if self.context.adapters.companion.isVisible():
            self.context.adapters.companion.hide()
        else:
            self.context.adapters.companion.show()
            self.context.adapters.companion.raise_()

    def on_companion_visibility(self, _):
        self.update_companion_btn()

    def update_companion_btn(self):
        shown = self.context.adapters.companion.isVisible()
        self.context.views.companion_btn.setToolTip(self.feature_controller("session").t("hide_char" if shown else "show_char"))
        self.context.views.companion_btn.setChecked(shown)

    def _running_background_workers(self):
        """Return owned threads and processes that must finish before Qt destroys the window."""
        workers = list(self.context.state._provider_workers)
        for session in getattr(self.context.state, "sessions", {}).values():
            workers.extend((
                getattr(session, "worker", None),
                getattr(session, "_search_worker", None),
                getattr(session, "_vision_worker", None),
            ))
        for name in (
            "_local_voice_worker", "_local_stt_test_listener", "_mcp_registry_worker",
            "_model_catalog_worker", "_api_worker", "_route_worker", "_bench_worker", "_scan_worker",
            "_provider_test_worker", "_ollama_worker", "_vision_worker", "_web_test_worker",
            "_attach_worker", "_model_import_worker", "_stopping_listener",
            "_stopping_game_audio_listener", "game_audio_listener", "listener",
        ):
            workers.append(self.context.resource(name))
        code_chat = getattr(self.context.views, "code_chat", None)
        if code_chat is not None:
            workers.extend(code_chat.background_workers())
        unique = []
        seen = set()
        for worker in workers:
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            try:
                is_running = getattr(worker, "isRunning", None)
                if callable(is_running):
                    running = is_running()
                else:
                    process_state = getattr(worker, "state", None)
                    running = False
                    if callable(process_state):
                        state = process_state()
                        state_name = getattr(state, "name", None)
                        if state_name is not None:
                            running = state_name != "NotRunning"
                        else:
                            not_running = getattr(worker, "NotRunning", None)
                            running = state != not_running if not_running is not None else bool(state)
                if running:
                    unique.append(worker)
            except RuntimeError:
                continue
        return unique

    @Slot()
    def _resume_close_after_workers(self):
        if getattr(self.context.state, "_closing", False):
            QTimer.singleShot(0, self.window.close)

    def _clear_chat_coordinator_queues(self):
        """Cancel work now; keep attachments/command resources alive for Session teardown."""
        self.context.services.chat_application_service.begin_shutdown()

    def _dispose_chat_application_service(self) -> bool:
        """Release Chat-owned registries only after SessionManager released each Session."""
        try:
            self.context.services.chat_application_service.dispose()
            return True
        except Exception:
            return False

    def _dispose_window_feature_services(self) -> bool:
        """Release per-window application services after their Qt workers have drained."""
        voice_service = getattr(self.context.services, "voice_application_service", None)
        if voice_service is not None:
            try:
                if not voice_service.dispose():
                    return False
            except Exception:
                return False
        vision_service = getattr(self.context.services, "vision_application_service", None)
        if vision_service is not None:
            try:
                vision_service.reset()
            except Exception:
                return False
        return True

    def closeEvent(self, event):
        if (getattr(self.context.views, "tray", None) is not None and self.context.services.settings.get("close_to_tray")
                and not getattr(self.context.state, "_quitting", False)):
            event.ignore()                                           # X only hides; "Exit" in the tray menu really quits
            self.feature_controller("lifecycle").hide_to_tray()
            return
        if getattr(self.context.state, "_closing", False):
            if self._running_background_workers():
                event.ignore()
                return
            if not self._dispose_window_feature_services():
                event.ignore()
                QTimer.singleShot(100, self.window.close)
                return
            for session in self.context.services.session_application_service.list_sessions():
                session.busy = False
            if not self.context.services.session_application_service.dispose():
                event.ignore()
                QTimer.singleShot(100, self.window.close)
                return
            if not self._dispose_chat_application_service():
                event.ignore()
                QTimer.singleShot(100, self.window.close)
                return
            event.accept()
            QTimer.singleShot(0, QApplication.quit)
            return
        model_import_worker = self.context.resource("_model_import_worker")
        if model_import_worker is not None and model_import_worker.isRunning():
            if getattr(model_import_worker, "cancellable", False):
                model_import_worker.cancel()
        local_worker = self.context.resource("_local_voice_worker")
        if local_worker is not None and local_worker.isRunning():
            if getattr(local_worker, "cancellable", False):
                # Installer subprocesses are stopped as part of shutdown instead of
                # forcing the user to close their console window or wait for pip.
                local_worker.cancel()
            else:
                if not getattr(self.context.state, "_close_after_local_voice", False):
                    self.context.state._close_after_local_voice = True
                    self.feature_controller("session").add_chat("system", "بارگذاری یا آزمایش موتور صوتی هنوز در حال اجراست؛ Kira پس از پایان امن آن بسته می‌شود.")
                event.ignore()
                return
        # ChatApplicationService owns cancellation and persists partial output once.
        self.context.state._closing = True
        self._clear_chat_coordinator_queues()
        if getattr(self.context.views, "code_chat", None) is not None:
            self.context.views.code_chat.shutdown()
        if getattr(self.context.views, "tray", None) is not None:
            self.context.views.tray.hide()
        self.context.adapters.bubble.close()
        self.context.services.tool_agent.request_cancel()
        # Stop attachment reads as soon as shutdown starts; a large file must not
        # keep the window alive for the full read when the user already cancelled.
        self.feature_controller("attachments_vision").cancel_attachments()
        for sess in self.context.state.sessions.values():
            if sess.client is not None:
                sess.client.cancel()
            if sess.timer is not None:
                sess.timer.stop()
            vision_worker = getattr(sess, "_vision_worker", None)
            if vision_worker is not None and vision_worker.isRunning():
                vision_worker.cancel_request()
        for timer_name in ("wake_timer", "_game_poll_timer", "_game_capture_timer", "_mood_ui_timer"):
            timer = self.context.resource(timer_name)
            if timer is not None:
                timer.stop()
        self.feature_controller("attachments_vision")._set_game_vision_capture(False)
        self.feature_controller("attachments_vision")._stop_game_audio_listener()
        self.context.adapters.game_mode.set_enabled(False)
        # Never wait() on a worker from the GUI thread. All owned QThreads are
        # collected below and the close is resumed by their finished signals.
        self.feature_controller("voice_settings").stop_local_stt_test(update_ui=False)
        self.stop_listener()
        self.safe_stop_speaker()
        self.context.adapters.companion.close()
        running = self._running_background_workers()
        if running:
            self.feature_controller("session").add_chat(
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
                QTimer.singleShot(0, self.window.close)
            return
        if not self._dispose_window_feature_services():
            event.ignore()
            QTimer.singleShot(100, self.window.close)
            return
        for session in self.context.services.session_application_service.list_sessions():
            session.busy = False
        if not self.context.services.session_application_service.dispose():
            event.ignore()
            QTimer.singleShot(100, self.window.close)
            return
        if not self._dispose_chat_application_service():
            event.ignore()
            QTimer.singleShot(100, self.window.close)
            return
        event.accept()
        QTimer.singleShot(0, QApplication.quit)                     # the tray keeps 'last window closed' from quitting by itself

    def reload_chat_view(self):
        for sess in self.context.state.sessions.values():             # every character's conversation is shown again from the database
            if sess.view is None:
                continue
            with self.feature_controller("session")._as(sess):
                self.context.session.view.clear()
                self.feature_controller("session").restore_history(200)

    def clear_chat(self):
        who = self.context.services.character_service.display_name(self.context.services.settings)
        question = (f"تاریخچه‌ی گفتگوی «{who}» پاک شود؟ (گفتگوی بقیه‌ی کاراکترها دست‌نخورده می‌ماند)"
                    if self.context.services.settings.get("ui_lang", "fa") == "fa" else f"Delete the saved history of {who}? (the other characters' chats stay)")
        if QMessageBox.question(self.window, self.feature_controller("session").t("clear_t"), question) == QMessageBox.Yes:
            try:
                self.context.services.chat_application_service.clear_history(self.context.state.cur.cid)      # only THIS character's conversation; saves a snapshot first, nothing is deleted if that fails
                # Facts, moments and habits remain in the character's own memory file.
                self.context.services.memory_service.forget_conversation(self.context.state.cur.cid)
                self.context.services.tool_agent.clear_session(self.context.state.cur.cid) # clear only this character's tasks, tool context, grants and temporary research
                self.context.services.brain_application_service.reset_state(self.context.state.cur.cid)
            except ChatHistoryError as exc:
                QMessageBox.warning(self.window, self.feature_controller("session").t("clear_t"), str(exc))
                return
            self.context.session.view.clear()
            self.feature_controller("session").add_chat("system", self.feature_controller("session").t("mem_cleared") + " (اگر اشتباه بود: تنظیمات ← عمومی ← «بازگرداندن آخرین پاک‌سازی».)")

    def apply_mood_to_avatar(self):
        """A quick front-session avatar reaction; background Sessions never drive the visible avatar."""
        if self.context.state.cur is not self.context.state.front:
            return
        try:
            hint = self.context.services.mood_service.avatar_hint(
                character_id=self.context.state.cur.cid
            )
            eid = self.context.adapters.director.library.resolve_name(hint[0]) if hint else None
            if eid:
                self.context.adapters.director.engine.request([eid], hint[1], 3.0, "event", self.context.adapters.director.clock(), tag="mood")
        except Exception:                                         # noqa: BLE001
            pass

    def open_memory_dialog(self):
        character_id = self.context.services.character_service.active_id(self.context.services.settings)
        profile = self.context.services.character_service.all_profiles(self.context.services.settings).get(character_id, {})
        character_name = profile.get("name") or character_id.title()
        MemoryDialog(
            self.window,
            character_id,
            character_name=character_name,
            memory_service=self.context.services.memory_service,
            mood_service=self.context.services.mood_service,
        ).exec()

    def restore_cleared_chat(self):
        try:
            n = self.context.services.chat_application_service.restore_history()
        except ChatHistoryError as exc:
            QMessageBox.information(self.window, "بازگرداندن گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.feature_controller("session").add_chat("system", f"{n} پیام بازگردانده شد." if n else "همه‌ی پیام‌های آن پاک‌سازی از قبل در گفتگو بودند.")

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
            n = self.context.services.chat_application_service.import_history(path)
        except ChatHistoryError as exc:
            QMessageBox.warning(self.window, "ورود گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.feature_controller("session").add_chat("system", f"{n} پیام از فایل قدیمی وارد شد." if n else "پیام جدیدی در آن فایل نبود (همه از قبل وجود داشتند).")

    @staticmethod
    def html(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


# Backward-compatible import name for callers migrating from mixin composition.
RuntimeMixin = RuntimeController
