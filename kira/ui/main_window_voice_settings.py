"""Voice settings feature controller."""
import logging

from .components.composer_owner import ComposerOwner
from .main_window_voice_settings_support import (
    AssistantPage,
    ChatComposer,
    ChatHeader,
    ChatInput,
    CodeChat,
    DATA_DIR,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_PREDICT,
    AvatarView,
    Listener,
    ModelCombo,
    Path,
    QApplication,
    QButtonGroup,
    QColor,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QTimer,
    Slot,
    QVBoxLayout,
    QWidget,
    Qt,
    RouteChip,
    TaskWorker,
    VoicePage,
    clamp_num_ctx,
    clamp_num_predict,
    json,
    make_icon,
    re,
    shutil,
    time,
)


from .window_feature_controller import WindowFeatureController


class VoiceSettingsController(WindowFeatureController):
    def build_chat_tab(self):
        page = QWidget()
        self.context.views.chat_page = page
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        # --- character tabs: one tab (= one independent conversation) per character
        self.char_tabs = QFrame()
        self.char_tabs.setObjectName("charTabs")
        self.context.views.char_tabs_row = QHBoxLayout(self.char_tabs)
        self.context.views.char_tabs_row.setContentsMargins(2, 0, 2, 0)
        self.context.views.char_tabs_row.setSpacing(8)
        self.context.views.char_tab_group = QButtonGroup(self.window)
        self.context.views.char_tab_group.setExclusive(True)
        self.context.views.char_tab_buttons = {}
        outer.addWidget(self.char_tabs)
        body = QHBoxLayout()
        body.setSpacing(10)
        outer.addLayout(body, 1)
        root = body
        # --- dedicated avatar area (same PNG and loader; the view keeps the image's aspect ratio)
        self.context.views.avatar_card = QFrame()
        self.context.views.avatar_card.setObjectName("avatarCard")
        av = QVBoxLayout(self.context.views.avatar_card)
        av.setContentsMargins(8, 8, 8, 10)
        av.setSpacing(4)
        self.context.views.avatar = AvatarView(self.context.adapters.animator, view="card")
        self.context.views.avatar.setMinimumSize(150, 190)
        self.context.views.avatar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        av.addWidget(self.context.views.avatar, 1)
        self.tagline = QLabel()
        self.tagline.setObjectName("hint")
        self.tagline.setAlignment(Qt.AlignCenter)
        self.feature_controller("session").reg(self.tagline.setText, "tagline")
        self.context.views.status = QLabel()
        self.context.views.status.setObjectName("status")
        self.context.views.status.setAlignment(Qt.AlignCenter)
        self.context.views.status.setWordWrap(True)
        av.addWidget(self.tagline)
        av.addWidget(self.context.views.status)
        self.context.views.avatar_card.setFixedWidth(250)
        root.addWidget(self.context.views.avatar_card)
        # --- chat card: compact header, conversation, composer
        chat_card = QFrame()
        chat_card.setObjectName("chatCard")
        cv = QVBoxLayout(chat_card)
        cv.setContentsMargins(12, 8, 12, 10)
        cv.setSpacing(6)
        self.chat_header = ChatHeader(self.feature_controller("session").icon_button("user", True), parent=chat_card)
        self.context.views.title = self.chat_header.title
        self.context.views.voice_mode_badge = self.chat_header.voice_mode_badge
        self.context.views.mood_emotion_icon = self.chat_header.mood_emotion_icon
        self.context.views.mood_indicator = self.chat_header.mood_indicator
        self.context.views.companion_btn = self.chat_header.companion_btn
        self.context.views.companion_btn.clicked.connect(self.feature_controller("runtime").toggle_companion)
        cv.addWidget(self.chat_header)
        self.context.views.chat_stack = QStackedWidget()                 # one read-only chat view per character (created in make_session_view)
        cv.addWidget(self.context.views.chat_stack, 1)
        self.context.views.chat_composer = ChatComposer(
            ComposerOwner(
                self.feature_controller("chat").context,
                self.window,
                view_context=self.window.presentation_context,
            ),
            chat_input_factory=ChatInput,
            route_chip_factory=RouteChip,
            code_chat_factory=CodeChat,
            make_icon=make_icon,
            story_mode=self.context.services.game_mode_application_service.STORY_MODE,
            competitive_safe_mode=self.context.services.game_mode_application_service.COMPETITIVE_SAFE_MODE,
            parent=chat_card,
        )
        composer = self.context.views.chat_composer
        cv.addWidget(self.context.views.chat_composer)
        root.addWidget(chat_card, 1)
        self.context.views.glow_effects = []                             # neon glow around the composer (colour follows the character); not on the animated avatar: an effect would re-render it every frame
        for widget in (composer,):
            glow = QGraphicsDropShadowEffect(widget)
            glow.setBlurRadius(30)
            glow.setOffset(0, 0)
            glow.setColor(QColor(143, 107, 255, 150))
            widget.setGraphicsEffect(glow)
            self.context.views.glow_effects.append(glow)
        self.context.views.tabs.addTab(page, "")

    def build_assistant_section(self):
        """Host the independent assistant settings page and bind application actions."""
        ollama = self.context.services.settings.get("providers", {}).get("ollama", {})
        self.context.views.assistant_page = AssistantPage(
            self.context.services.settings,
            self.feature_controller("session").t,
            model_combo_factory=ModelCombo,
            num_ctx=clamp_num_ctx(ollama.get("num_ctx", DEFAULT_NUM_CTX)),
            num_predict=clamp_num_predict(ollama.get("num_predict", DEFAULT_NUM_PREDICT)),
            keep_alive=str(ollama.get("keep_alive", DEFAULT_KEEP_ALIVE)),
            parent=self.window,
        )
        # Compatibility aliases keep existing persistence/controller code stable while
        # the remaining settings orchestration is extracted in later steps.
        for name in (
            "name", "persona", "modes_chk", "temp", "model", "url", "use_qwen_btn",
            "num_ctx", "num_predict", "keep_alive", "conn_btn", "load_btn",
            "unload_btn", "speed_btn", "conn_lbl",
        ):
            setattr(self.context.views, name, getattr(self.context.views.assistant_page, name))

        self.context.views.assistant_page.test_connection_requested.connect(self.feature_controller("lifecycle").test_connection)
        self.context.views.assistant_page.load_model_requested.connect(self.feature_controller("lifecycle").load_local_model)
        self.context.views.assistant_page.unload_model_requested.connect(self.feature_controller("lifecycle").unload_local_model)
        self.context.views.assistant_page.speed_test_requested.connect(self.feature_controller("lifecycle").speed_test)
        # No tab of its own: build_characters_tab() and build_ai_tab() host its two sections.
        # The emptied page stays alive (it owns the widgets, signals and translations) but is never shown.
        self.context.views.assistant_page.hide()

    def build_voice_tab(self):
        """Compose the independent Voice page and connect its intent signals."""
        self.context.views.voice_page = VoicePage(self.context.services.settings, self.feature_controller("session").t, parent=self.window)
        self.context.views.voice_page.voice_enabled_requested.connect(self.feature_controller("runtime").set_voice_enabled)
        self.context.views.voice_page.live_requested.connect(self.feature_controller("runtime").set_live_listening)
        self.context.views.voice_page.download_shenava_requested.connect(self.download_local_shenava_model)
        self.context.views.voice_page.test_shenava_file_requested.connect(self.test_shenava_file)
        self.context.views.voice_page.shenava_variant.currentIndexChanged.connect(
            self.select_shenava_variant
        )
        page = self.context.views.voice_page
        self.context.views.local_voice_status = page.local_voice_status
        self.context.views.local_tts_model_list = page.local_tts_model
        self.context.views.local_tts_download_btn = page.piper_download_btn
        self.context.views.local_tts_test_btn = page.piper_test_btn
        page.local_asr_enabled_requested.connect(
            lambda enabled: self.set_local_voice_option("local_voice_asr", enabled)
        )
        page.local_tts_enabled_requested.connect(
            lambda enabled: self.set_local_voice_option("local_voice_tts", enabled)
        )
        page.download_piper_requested.connect(self.download_local_tts_model)
        page.test_piper_requested.connect(self.test_local_tts)
        page.test_kitten_requested.connect(self.test_kitten_tts)
        page.choose_piper_file_requested.connect(self.choose_local_tts_model)
        page.select_piper_requested.connect(self.select_piper_model)
        self.context.views.voice_page.realtime_asr_requested.connect(
            self.feature_controller("runtime").set_realtime_asr
        )
        self.context.views.voice_page.autosave_requested.connect(self.autosave_voice)
        self.context.views.tabs.addTab(self.context.views.voice_page, "")
        self.fill_mic_devices(str(self.context.services.settings.get("mic_device") or ""))
        self.fill_output_devices(str(self.context.services.settings.get("output_device") or ""))
        self.refresh_voice_caps()

    def select_shenava_variant(self, index):
        """Select the INT8 or FP32 Shenava download and runtime model."""
        from .. import local_voice

        page = self.context.views.voice_page
        repo_id = str(page.shenava_variant.currentData() or local_voice.SHENAVA_INT8_REPO_ID)
        if repo_id not in local_voice.SHENAVA_MODEL_FILENAMES:
            repo_id = local_voice.SHENAVA_INT8_REPO_ID
        settings = self.context.services.settings
        settings["local_voice_asr_backend"] = "shenava"
        settings["local_voice_asr_model"] = repo_id
        runtime = self.feature_controller("runtime")
        if getattr(runtime, "_voice_mode", "") in ("local_fallback", "local_primary", "local_stt"):
            runtime.set_live_listening(False)
        self.stop_local_stt_test(update_ui=False)
        self.feature_controller("runtime").save_now()
        if hasattr(self.context.views, "local_voice_status"):
            self.refresh_local_voice_status()


    def set_local_voice_option(self, key, enabled):
        self.context.services.settings[key] = bool(enabled)
        self.feature_controller("runtime").save_now()

    def choose_local_asr_folder(self):
        folder = QFileDialog.getExistingDirectory(self.window, "پوشه‌ی مدل STT را انتخاب کن", str(Path.home()))
        if not folder:
            return
        self.context.views.local_asr_path_edit.setText(folder)
        self.context.services.settings["local_voice_asr_model"] = folder
        self.feature_controller("runtime").save_now()
        self.refresh_local_voice_status()

    def download_local_shenava_model(self):
        """Install sherpa-onnx and download the currently selected Shenava variant."""
        from .. import local_voice

        page = self.context.views.voice_page
        repo_id = str(page.shenava_variant.currentData() or local_voice.SHENAVA_INT8_REPO_ID)
        size_mb = local_voice.SHENAVA_MODEL_SIZES_MB.get(repo_id, 126)
        precision = "FP32" if repo_id == local_voice.SHENAVA_FP32_REPO_ID else "INT8"
        page.shenava_result.setText(
            f"در حال نصب sherpa-onnx و دانلود شنوا {precision} (حدود {size_mb} مگابایت)…"
        )
        self._run_local_voice_task(
            lambda cancel: local_voice.install_and_download_shenava_asr(
                repo_id, cancel_event=cancel
            ),
            page.shenava_download_btn,
            lambda result: self._on_local_shenava_downloaded(result, repo_id),
            cancellable=True,
        )


    def _on_local_shenava_downloaded(self, result, repo_id=None):
        ok, value = result
        page = self.context.views.voice_page
        if not ok:
            page.shenava_result.setText(
                f"نصب یا دانلود شنوا ناموفق بود: {value}"
            )
            return
        from .. import local_voice

        repo_id = str(repo_id or page.shenava_variant.currentData() or local_voice.SHENAVA_INT8_REPO_ID)
        if repo_id not in local_voice.SHENAVA_MODEL_FILENAMES:
            repo_id = local_voice.SHENAVA_INT8_REPO_ID
        self.context.services.settings["local_voice_asr_backend"] = "shenava"
        self.context.services.settings["local_voice_asr_model"] = repo_id
        page.shenava_variant.blockSignals(True)
        page.shenava_variant.setCurrentIndex(max(0, page.shenava_variant.findData(repo_id)))
        page.shenava_variant.blockSignals(False)
        page._update_shenava_download_label()
        self.feature_controller("runtime").save_now()
        self.refresh_local_voice_status()
        precision = "FP32" if repo_id == local_voice.SHENAVA_FP32_REPO_ID else "INT8"
        page.shenava_result.setText(
            f"✓ شنوا {precision} دانلود و انتخاب شد. موتور sherpa-onnx آماده است؛ "
            "برای سنجش دقت، یک فایل WAV انتخاب کن.\n"
            f"مسیر مدل: {value}"
        )


    def test_shenava_file(self):
        """Run a one-shot offline test against the selected Shenava model; no microphone is opened."""
        page = self.context.views.voice_page
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "انتخاب فایل صوتی برای آزمایش شنوا",
            str(Path.home()),
            "WAV صوتی (*.wav)",
        )
        if not path:
            return
        runtime = self.feature_controller("runtime")
        # A file-based benchmark must not run beside either local mic capture or Gemini Live.
        runtime.set_live_listening(False)
        self.stop_local_stt_test(update_ui=False)
        from .. import local_voice

        repo_id = str(page.shenava_variant.currentData() or local_voice.SHENAVA_INT8_REPO_ID)
        precision = "FP32" if repo_id == local_voice.SHENAVA_FP32_REPO_ID else "INT8"
        page.shenava_result.setText(
            f"در حال خواندن و تبدیل فایل «{Path(path).name}» با شنوا {precision}؛ میکروفن استفاده نمی‌شود…"
        )
        self._run_local_voice_task(
            lambda: local_voice.transcribe_shenava_file(
                path, model_path=repo_id
            ),
            page.shenava_test_btn,
            lambda result: self._on_local_shenava_file_tested(result, path, repo_id),
        )


    def _on_local_shenava_file_tested(self, result, path, repo_id=None):
        ok, value = result
        page = self.context.views.voice_page
        if not ok:
            page.shenava_result.setText(
                f"✕ تست شنوا ناموفق بود: {value}"
            )
            return
        transcript = str(value or "").strip()
        if not transcript:
            transcript = "متنی تشخیص داده نشد."
        page.shenava_result.setText(
            f"فایل: {Path(path).name}\nنتیجه‌ی شنوا:\n{transcript}"
        )
        from .. import local_voice

        repo_id = str(repo_id or page.shenava_variant.currentData() or local_voice.SHENAVA_INT8_REPO_ID)
        if repo_id not in local_voice.SHENAVA_MODEL_FILENAMES:
            repo_id = local_voice.SHENAVA_INT8_REPO_ID
        self.context.services.settings["local_voice_asr_backend"] = "shenava"
        self.context.services.settings["local_voice_asr_model"] = repo_id
        page.shenava_variant.blockSignals(True)
        page.shenava_variant.setCurrentIndex(max(0, page.shenava_variant.findData(repo_id)))
        page.shenava_variant.blockSignals(False)
        self.feature_controller("runtime").save_now()


    def download_local_tts_model(self):
        repo_id, accepted = QInputDialog.getText(
            self.window, "دانلود صدای Piper",
            "شناسه مخزن صدای Piper در Hugging Face:",
            text="",
        )
        repo_id = str(repo_id or "").strip()
        if not accepted or "/" not in repo_id or "\\" in repo_id:
            return
        from .. import local_voice
        self.context.views.local_voice_status.setText("در حال نصب Piper و دانلود صدا…")
        self._run_local_voice_task(
            lambda cancel: local_voice.install_and_download_piper_voice(repo_id, cancel_event=cancel),
            self.context.views.local_tts_download_btn,
            self._on_local_tts_downloaded,
            cancellable=True,
        )

    def select_piper_model(self, value):
        self.context.services.settings["local_voice_tts_model"] = str(value or "")
        self.feature_controller("runtime").save_now()
        self.refresh_local_voice_status()

    def _on_local_tts_downloaded(self, result):
        ok, value = result
        if not ok:
            self.context.views.local_voice_status.setText(f"دانلود مدل TTS ناموفق بود: {value}")
            return
        try:
            candidates = sorted(Path(value).rglob("*.onnx"))
            if not candidates:
                raise RuntimeError("در مخزن دانلودشده فایل Piper ONNX پیدا نشد.")
            self._install_piper_voice(candidates[0])
            from .. import local_voice
            self.context.views.local_voice_status.setText(
                f"Piper نصب شد و صدا فعال شد: {candidates[0].name}\n"
                f"مسیر فایل: {candidates[0]}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
            )
        except Exception as exc:
            self.context.views.local_voice_status.setText(f"نصب مدل TTS ناموفق بود: {type(exc).__name__}: {exc}")

    def choose_local_tts_model(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "مدل Piper ONNX", str(Path.home()), "Piper ONNX (*.onnx)")
        if path:
            self._install_piper_voice(Path(path))

    def _install_piper_voice(self, source):
        source = Path(source).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".onnx":
            QMessageBox.warning(self.window, "مدل TTS", "فایل انتخاب‌شده باید Piper ONNX باشد.")
            return
        metadata = Path(str(source) + ".json")
        if not metadata.is_file():
            sibling = source.with_suffix(".json")
            metadata = sibling if sibling.is_file() else metadata
        if not metadata.is_file():
            QMessageBox.warning(self.window, "مدل TTS", "فایل پیکربندی کنار مدل (.onnx.json یا .json) پیدا نشد.")
            return
        try:
            target_dir = DATA_DIR / "voice_models"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / source.name
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            target_meta = Path(str(target) + ".json")
            if metadata.resolve() != target_meta.resolve():
                shutil.copy2(metadata, target_meta)
            self.context.services.settings["local_voice_tts_model"] = str(target)
            self.feature_controller("runtime").save_now()
            self.refresh_local_voice_status()
            self.context.views.api_add_status.setText("مدل Piper به پوشه‌ی داده‌ی Kira کپی شد و برای TTS انتخاب شد.")
        except OSError as exc:
            QMessageBox.warning(self.window, "مدل TTS", str(exc))

    def import_local_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window, "معرفی مدل به Kira", str(Path.home()),
            "Model files (*.gguf *.onnx *.bin *.safetensors *.pt *.pth *.json);;All files (*)"
        )
        if not path:
            path = QFileDialog.getExistingDirectory(self.window, "یا پوشه‌ی مدل را انتخاب کن", str(Path.home()))
        if not path:
            return
        self._import_local_model_path(Path(path))

    def _import_local_model_path(self, source):
        source = Path(source).expanduser().resolve()
        if source.is_dir():
            gguf = sorted(source.glob("*.gguf"))
            onnx = sorted(source.glob("*.onnx"))
            if gguf:
                source = gguf[0]
            elif onnx:
                self._install_piper_voice(onnx[0])
                return
            elif (source / "config.json").is_file():
                try:
                    config_text = (source / "config.json").read_text(encoding="utf-8", errors="replace").lower()
                except OSError:
                    config_text = ""
                try:
                    config_data = json.loads((source / "config.json").read_text(encoding="utf-8", errors="replace"))
                except (OSError, ValueError, TypeError):
                    config_data = {}
                model_type = str(config_data.get("model_type") or "").lower()
                architectures = " ".join(str(x) for x in (config_data.get("architectures") or [])).lower()
                signature = " ".join((model_type, architectures, source.name.lower()))
                if any(token in signature for token in ("causallm", "forcausallm", "textgeneration", "llama", "qwen3for")):
                    QMessageBox.information(self.window, "مدل Chat شناسایی شد",
                        "این پوشه یک مدل متنی Hugging Face است، اما Ollama مستقیماً پوشه‌ی Transformers را وارد نمی‌کند. نسخه‌ی GGUF همین مدل را انتخاب کن.")
                    return
                category, ok = QInputDialog.getItem(
                    self.window, "نوع مدل", "معماری مدل از روی فایل‌هایش قطعی نبود؛ نوع واقعی را انتخاب کن.",
                    ["TTS · Piper ONNX", "Chat · GGUF"], 0, False)
                if not ok:
                    return
                QMessageBox.information(self.window, "معرفی مدل", "برای TTS فایل Piper ONNX و برای Chat فایل GGUF را انتخاب کن.")
                return
            else:
                QMessageBox.warning(self.window, "مدل شناسایی نشد", "در پوشه، فایل GGUF، Piper ONNX، model.bin یا config.json پیدا نشد.")
                return

        if source.name.lower().endswith(".onnx.json"):
            candidate = Path(str(source)[:-5])
            if candidate.is_file():
                source = candidate
        if source.suffix.lower() == ".gguf":
            self._create_ollama_model(source)
        elif source.suffix.lower() == ".onnx":
            self._install_piper_voice(source)
        elif source.suffix.lower() in (".json", ".safetensors", ".pt", ".pth"):
            self._import_local_model_path(source.parent)
        else:
            QMessageBox.warning(self.window, "مدل شناسایی نشد", "پسوند فایل پشتیبانی نمی‌شود. GGUF برای Chat، Piper ONNX برای TTS و پوشه‌ی مدل برای STT را انتخاب کن.")

    def _create_ollama_model(self, source):
        if not shutil.which("ollama"):
            QMessageBox.warning(self.window, "Ollama", "Ollama روی سیستم پیدا نشد.")
            return
        name = re.sub(r"[^a-zA-Z0-9._-]+", "-", source.stem.lower()).strip("-._")[:48] or "imported-model"
        self.context.views.import_model_btn.setEnabled(False)
        self.context.views.api_add_status.setText(f"در حال وارد کردن {source.name} به Ollama…")

        def work(cancel_event):
            from .. import local_voice

            target = DATA_DIR / "ollama_import"
            target.mkdir(parents=True, exist_ok=True)
            modelfile = target / f"{name}.Modelfile"
            escaped = source.as_posix().replace('"', '\\"')
            modelfile.write_text(f'FROM "{escaped}"\n', encoding="utf-8")
            result = local_voice._run_install_command(
                ["ollama", "create", name, "-f", str(modelfile)],
                timeout=1800, cancel_event=cancel_event,
            )
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout or "ollama create failed")[-3000:])
            return name

        worker = TaskWorker(work, cancellable=True)
        self.context.state._model_import_worker = worker
        worker.done.connect(self.on_local_model_imported)
        worker.finished.connect(self._clear_model_import_worker)
        worker.start()

    @Slot()
    def _clear_model_import_worker(self):
        worker = self.sender()
        if self.context.state._model_import_worker is worker:
            self.context.state._model_import_worker = None
        if worker is not None:
            worker.deleteLater()

    @Slot(object)
    def on_local_model_imported(self, result):
        if self.context.state._closing:
            return
        self.context.views.import_model_btn.setEnabled(True)
        ok, value = result
        if not ok:
            self.context.views.api_add_status.setText("✕ واردکردن مدل ناموفق بود: " + str(value))
            return
        model = str(value)
        if hasattr(self.context.views, "model"):
            if self.context.views.model.findText(model) < 0:
                self.context.views.model.addItem(model)
            self.context.views.model.setCurrentText(model)
        self.context.services.settings["model"] = model
        self.context.services.settings.setdefault("providers", {}).setdefault("ollama", {})["model"] = model
        self.context.services.provider_application_service.ensure_routes(self.context.services.settings)
        self.context.services.provider_application_service.add_ollama_models(self.context.services.settings, [model])
        self.feature_controller("runtime").save_now()
        self.feature_controller("provider_settings").refresh_route_list()
        self.feature_controller("provider_settings").refresh_unified_models()
        self.context.views.api_add_status.setText(f"✓ مدل «{model}» به Ollama اضافه شد.")

    def select_local_asr_model(self, index):
        combo = getattr(self.context.views, "local_asr_model_list", None)
        if combo is None or index < 0:
            return
        value = str(combo.itemData(index) or "").strip()
        if not value:
            return
        from .. import local_voice
        if value not in local_voice.SHENAVA_MODEL_FILENAMES:
            value = local_voice.SHENAVA_INT8_REPO_ID
        self.context.services.settings["local_voice_asr_backend"] = "shenava"
        self.context.services.settings["local_voice_asr_model"] = value
        self.feature_controller("runtime").save_now()
        self.refresh_local_voice_status()

    def select_local_tts_model(self, index):
        combo = getattr(self.context.views, "local_tts_model_list", None)
        if combo is None or index < 0:
            return
        value = str(combo.itemData(index) or "").strip()
        self.context.services.settings["local_voice_tts_model"] = value
        self.feature_controller("runtime").save_now()
        self.refresh_local_voice_status()

    def refresh_local_voice_status(self):
        try:
            from .. import local_voice
            asr_model = str(self.context.services.settings.get("local_voice_asr_model") or local_voice.SHENAVA_INT8_REPO_ID)
            tts_model = str(self.context.services.settings.get("local_voice_tts_model") or "")
            discovered = local_voice.discover_cached_models()

            page = self.context.views.voice_page
            page.shenava_variant.blockSignals(True)
            page.shenava_variant.setCurrentIndex(max(0, page.shenava_variant.findData(asr_model)))
            page.shenava_variant.blockSignals(False)

            tts_combo = getattr(self.context.views, "local_tts_model_list", None)
            if tts_combo is not None:
                tts_combo.blockSignals(True)
                tts_combo.clear()
                tts_combo.addItem("Mana Persian Piper · صدای پیش‌فرض", "")
                for item in discovered.get("tts", []):
                    tts_combo.addItem(f"{item['name']} · دانلودشده", item["path"])
                selected = next((i for i in range(tts_combo.count())
                                 if str(tts_combo.itemData(i) or "") == tts_model), 0)
                tts_combo.setCurrentIndex(selected)
                tts_combo.blockSignals(False)

            state = local_voice.status(tts_model)
            asr_loaded = bool(state.get("shenava_loaded"))
            asr_installed = bool(state.get("shenava_installed"))
            asr_error = state.get("shenava_error")
            asr_label = "Shenava · sherpa-onnx"
            tts_loaded = bool(state["tts_loaded"] and (
                (tts_model and state.get("tts_model") and Path(state["tts_model"]).resolve() == Path(tts_model).expanduser().resolve())
                or (not tts_model and state.get("tts_model") == "bundled")
            ))
            asr_cached = any(item.get("id") == asr_model for item in discovered.get("asr", []))
            asr = f"{asr_label} نصب است" if asr_installed else f"{asr_label} نصب نیست"
            asr += " · فایل‌های مدل در کش موجود است" if asr_cached else " · فایل‌های مدل هنوز دانلود نشده"
            asr += " · همین مدل در حافظه است" if asr_loaded else " · مدل هنوز بارگذاری نشده"
            if asr_error:
                asr += " · " + str(asr_error)
            tts = "Piper در دسترس است" if state["tts_installed"] else "Piper نصب نیست"
            tts += " · همین صدا بارگذاری شده" if tts_loaded else " · صدای انتخابی هنوز بارگذاری نشده"
            if state.get("tts_error"):
                tts += " · " + state["tts_error"]
            ezafe = state.get("tts_ezafe") or {}
            if not ezafe.get("enabled", True):
                ezafe_text = "پیش‌پردازش اضافه فارسی: غیرفعال"
            elif ezafe.get("loaded"):
                ezafe_text = "پیش‌پردازش اضافه فارسی: مدل ALBERT بارگذاری شده"
            else:
                ezafe_text = "پیش‌پردازش اضافه فارسی: مدل اختیاری هنوز بارگذاری نشده؛ Piper با متن اصلی کار می‌کند"
            if ezafe.get("error"):
                ezafe_text += " · " + str(ezafe["error"])
            if ezafe.get("retry_in_seconds"):
                ezafe_text += f" · تلاش دوباره پس از {ezafe['retry_in_seconds']} ثانیه"
            selected_tts = tts_model or "Mana Persian Piper · صدای فارسی پیش‌فرض"
            self.context.views.local_voice_status.setText(
                f"STT · {asr_label}: {asr}\nمدل STT: {asr_model}\n"
                f"TTS · Piper: {tts}\nمدل TTS: {selected_tts}\n"
                f"{ezafe_text}\n"
                f"مدل‌های Piper مستقل: {len(discovered.get('tts', []))}\n"
                f"کش مدل‌ها: {local_voice.cache_directory()}"
            )
        except Exception as exc:
            self.context.views.local_voice_status.setText(f"بررسی موتورهای صوتی ناموفق بود: {type(exc).__name__}: {exc}")

    def _run_local_voice_task(self, fn, button, callback, *, cancellable=False):
        if (
            self.context.state._closing
            or getattr(self.context.state, "_close_after_local_voice", False)
        ):
            return
        worker = getattr(self.context.state, "_local_voice_worker", None)
        if worker is not None and worker.isRunning():
            return
        button.setEnabled(False)
        if hasattr(self.context.views, "local_voice_progress"):
            self.context.views.local_voice_progress.show()
        worker = TaskWorker(fn, cancellable=cancellable)
        self.context.state._local_voice_worker = worker
        worker._ui_button = button
        worker._ui_completion_callback = callback
        worker.done.connect(self._on_local_voice_worker_done)
        worker.finished.connect(self._on_local_voice_worker_finished)
        worker.start()

    @Slot(object)
    def _on_local_voice_worker_done(self, result):
        worker = self.sender()
        if (
            worker is None
            or self.context.state._closing
            or getattr(self.context.state, "_close_after_local_voice", False)
            or self.context.state._local_voice_worker is not worker
        ):
            return
        button = getattr(worker, "_ui_button", None)
        if button is not None:
            button.setEnabled(True)
        if hasattr(self.context.views, "local_voice_progress"):
            self.context.views.local_voice_progress.hide()
        callback = getattr(worker, "_ui_completion_callback", None)
        if callback is not None:
            callback(result)

    @Slot()
    def _on_local_voice_worker_finished(self):
        worker = self.sender()
        if worker is not None and self.context.state._local_voice_worker is worker:
            self.context.state._local_voice_worker = None
        if worker is not None:
            worker.deleteLater()
        if (
            getattr(self.context.state, "_close_after_local_voice", False)
            and self.context.state._local_voice_worker is None
        ):
            self.context.state._close_after_local_voice = False
            QTimer.singleShot(0, self.window.close)

    def load_local_asr(self):
        from .. import local_voice
        model_name = str(self.context.services.settings.get("local_voice_asr_model") or local_voice.SHENAVA_INT8_REPO_ID)
        self.context.services.settings["local_voice_asr_backend"] = "shenava"
        self._run_local_voice_task(lambda: local_voice.load_shenava(model_name), self.context.views.local_asr_load_btn, self._on_local_asr_loaded)

    def _on_local_asr_loaded(self, result):
        ok, value = result
        label = "شنوا"
        if ok:
            self.context.views.local_voice_status.setText(f"{label} با موفقیت بارگذاری شد. تشخیص گفتار محلی آماده است.")
        else:
            self.context.views.local_voice_status.setText(f"بارگذاری {label} ناموفق بود: {value}")
        self.refresh_local_voice_status()

    def copy_local_voice_log(self):
        text = self.context.views.local_voice_status.text().strip()
        if text:
            QApplication.clipboard().setText(text)

    def test_local_tts(self):
        from .. import local_voice
        self._run_local_voice_task(
            lambda: local_voice.synthesize_persian(
                "سلام، من کیرا هستم. این صدای فارسی محلی من است.",
                self.context.services.settings.get("local_voice_tts_model", "")
            ),
            self.context.views.local_tts_test_btn, self._on_local_tts_tested
        )

    def test_local_stt(self):
        listener = self.context.resource("_local_stt_test_listener")
        if listener is not None and listener.isRunning():
            self.stop_local_stt_test()
            return
        if (
            self.context.state._closing
            or getattr(self.context.state, "_close_after_local_voice", False)
        ):
            return

        from ..listener import Listener
        from .. import local_voice
        model_name = str(self.context.services.settings.get("local_voice_asr_model") or local_voice.SHENAVA_INT8_REPO_ID)
        language = str(self.context.services.settings.get("stt_language") or "fa")
        listener = Listener(
            model_name, language, self,
            sensitivity=int(self.context.services.settings.get("mic_sensitivity", 100)),
            barge_in=False, settings=self.context.services.settings,
        )
        self.context.state._local_stt_test_listener = listener
        # QObject-bound slots ensure worker-thread signals are marshalled back
        # to this controller's GUI thread before updating widgets.
        listener.heard.connect(self._on_local_stt_test_heard)
        listener.error.connect(self._on_local_stt_test_error)
        listener.state.connect(self._on_local_stt_test_state)
        listener.finished.connect(self._on_local_stt_test_finished)
        self.context.views.local_stt_test_btn.setText("توقف تست STT")
        self.context.views.local_voice_status.setText("در حال آماده‌سازی میکروفن؛ صحبت کن تا متن تشخیص‌داده‌شده نمایش داده شود.")
        listener.start()

    def stop_local_stt_test(self, *, update_ui=True):
        """Stop the standalone STT test and retain its QThread until it has exited."""
        listener = self.context.resource("_local_stt_test_listener")
        if listener is None:
            return
        if listener.isRunning():
            listener.stop()
        if update_ui and not self.context.state._closing:
            self.context.views.local_stt_test_btn.setText("در حال توقف تست STT…")
            self.context.views.local_voice_status.setText("در حال توقف آزمایش STT…")

    @Slot(str)
    def _on_local_stt_test_state(self, state):
        listener = self.sender()
        if (
            listener is None
            or self.context.state._closing
            or self.context.state._local_stt_test_listener is not listener
        ):
            return
        labels = {
            "loading": "در حال آماده‌سازی موتور STT…",
            "listening": "میکروفن آماده است؛ صحبت کن…",
            "hearing": "صدایت دریافت شد؛ در حال ضبط…",
            "transcribing": "در حال تبدیل گفتار به متن…",
        }
        if state in labels:
            self.context.views.local_voice_status.setText(labels[state])

    @Slot(str)
    def _on_local_stt_test_heard(self, text):
        listener = self.sender()
        if listener is None or self.context.state._local_stt_test_listener is not listener:
            return
        listener.stop()
        if not self.context.state._closing:
            self.context.views.local_voice_status.setText(f"نتیجه تست STT: {text}")

    @Slot(str)
    def _on_local_stt_test_error(self, message):
        listener = self.sender()
        if listener is None or self.context.state._local_stt_test_listener is not listener:
            return
        if not self.context.state._closing:
            self.context.views.local_voice_status.setText(f"تست STT ناموفق بود: {message}")
        listener.stop()

    @Slot()
    def _on_local_stt_test_finished(self):
        listener = self.sender()
        if listener is None:
            return
        if self.context.state._local_stt_test_listener is listener:
            self.context.state._local_stt_test_listener = None
        listener.deleteLater()
        current = self.context.resource("_local_stt_test_listener")
        if not self.context.state._closing and hasattr(self.context.views, "local_stt_test_btn"):
            self.context.views.local_stt_test_btn.setText(
                "توقف تست STT" if current is not None and current.isRunning() else "تست STT"
            )

    def _on_local_tts_tested(self, result):
        ok, value = result
        if not ok:
            # Keep the actionable synthesis error visible; a status refresh here used
            # to overwrite it immediately with the generic installed/not-loaded text.
            self.context.views.local_voice_status.setText(f"تولید صدای Piper ناموفق بود: {value}")
            return
        try:
            if not isinstance(value, (bytes, bytearray)) or not value.startswith(b"RIFF"):
                raise RuntimeError("موتور TTS خروجی WAV معتبر تولید نکرد.")
            test_path = DATA_DIR / "voice_cache" / "local_persian_test.wav"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_bytes(value)
            self.context.state._local_tts_test_active = False
            self.context.services.voice_application_service.play_file(str(test_path))
            self.context.state._local_tts_test_active = True
            model = str(self.context.services.settings.get("local_voice_tts_model") or "Mana Persian Piper · صدای پیش‌فرض")
            self.context.views.local_voice_status.setText(
                f"تولید WAV موفق بود · مدل: {model} · حجم: {len(value):,} بایت\nدر انتظار شروع پخش از دستگاه خروجی…"
            )
        except Exception as exc:
            self.context.state._local_tts_test_active = False
            self.context.views.local_voice_status.setText(f"ساخت یا پخش فایل آزمایشی ناموفق بود: {type(exc).__name__}: {exc}")

    def _on_local_tts_playback_started(self):
        if self.context.state._local_tts_test_active:
            self.context.views.local_voice_status.setText("تولید WAV موفق بود · پخش TTS شروع شد.")

    def _on_local_tts_playback_finished(self):
        if self.context.state._local_tts_test_active:
            self.context.state._local_tts_test_active = False
            self.context.views.local_voice_status.setText("تست TTS موفق بود: صدا کامل پخش شد.")

    def _on_local_tts_playback_error(self, message):
        if self.context.state._local_tts_test_active:
            self.context.state._local_tts_test_active = False
            self.context.views.local_voice_status.setText(f"تولید صدا موفق بود، اما پخش شکست خورد: {message}")

    def _on_local_tts_playback_cancelled(self):
        if self.context.state._local_tts_test_active:
            self.context.state._local_tts_test_active = False
            self.context.views.local_voice_status.setText("تست TTS متوقف شد؛ پخش کامل نشد.")

    # ---- voice: devices, supported controls, autosave ----

    def fill_output_devices(self, current):
        self.context.views.voice_page.out_device.clear()
        self.context.views.voice_page.out_device.addItem(self.feature_controller("session").t("dev_default"), "")
        try:
            from PySide6.QtMultimedia import QMediaDevices
            seen = set()
            for dev in QMediaDevices.audioOutputs():
                name = dev.description()
                if name and name not in seen:
                    seen.add(name)
                    self.context.views.voice_page.out_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - no audio backend: only the default entry
            pass
        i = self.context.views.voice_page.out_device.findData(current)
        self.context.views.voice_page.out_device.setCurrentIndex(i if i >= 0 else 0)

    def fill_mic_devices(self, current):
        page = self.context.views.voice_page
        combo = page.mic_device
        combo.clear()
        combo.addItem(self.feature_controller("session").t("dev_default"), "")
        try:
            import sounddevice as sd
            from ..audio_devices import input_device_entries, resolve_input_device

            entries = input_device_entries(sd)
            for entry in entries:
                combo.addItem(entry["label"], entry["value"])

            # Migrate an old name-only setting to the matching host-API token.
            selected_index = resolve_input_device(sd, current)
            if selected_index is not None:
                selected = next(
                    (i for i, entry in enumerate(entries) if entry["index"] == selected_index),
                    None,
                )
                combo.setCurrentIndex(selected + 1 if selected is not None else 0)
            else:
                combo.setCurrentIndex(0)
        except Exception as exc:                              # noqa: BLE001 - retain the system-default option
            combo.setCurrentIndex(0)
            logging.getLogger("kira.audio").warning(
                "Unable to enumerate microphone input devices: %s", exc
            )

    def refresh_gemini_providers(self):
        """Keep the Live provider selector synchronized with Connections changes."""
        page = self.context.views.voice_page
        page.refresh_gemini_providers(self.context.services.settings)

    def refresh_voice_caps(self):
        """Refresh Google credentials and describe the actual Gemini-primary/local-fallback pipeline."""
        page = self.context.views.voice_page
        page.refresh_gemini_providers(self.context.services.settings)
        page.voice_caps_note.setText(
            "Gemini Live ورودی و خروجی صوتی مستقیم دارد؛ STT/TTS محلی فقط در حالت محلی یا هنگام قطع Live استفاده می‌شود."
        )
        page.live_config_note.setText(
            "کلید Google از بخش اتصالات خوانده می‌شود و کلید جداگانه‌ای اینجا ذخیره نمی‌شود. "
            "صدای زنده با Gemini پردازش می‌شود؛ در صورت قطع اتصال، مسیر محلی شنوا + مدل چت + Piper فعال می‌شود."
        )

    def collect_voice_settings(self):
        s = self.context.services.settings
        page = self.context.views.voice_page
        s.update({
            "voice_rate": page.rate.value(),
            "voice_volume": page.volume.value() / 100.0,
            "output_device": page.out_device.currentData() or "",
            "mic_device": page.mic_device.currentData() or "",
            "mic_gain": page.mic_gain.value(),
            "mic_sensitivity": page.mic_sens.value(),
            "stt_language": page.stt_lang.currentText(),
            "stream_speech": page.stream_chk.isChecked(),
            "voice_engine": page.voice_engine.currentData() or "local",
            "gemini_live_provider": page.gemini_provider.currentData() or "",
            "gemini_live_model": page.gemini_model.currentText().strip() or "gemini-3.8-live",
            "voice_local_fallback": page.local_fallback_chk.isChecked(),
            "local_voice_asr_backend": "shenava",
            "realtime_asr_enabled": page.real_time_asr_chk.isChecked(),
        })

    def autosave_voice(self):
        """Voice sliders / devices are saved as soon as they are changed (the Save button is not needed for them)."""
        self.collect_voice_settings()
        self.feature_controller("character_settings").apply_character_voice_settings()
        self.feature_controller("runtime").save_now()

    def show_voice_routes(self):
        """Open the unified voice settings page containing STT and TTS controls."""
        self.feature_controller("session").go_tab(self.context.views.tab_keys.index("tab_voice"))

    def set_route_view(self, index):
        self.show_voice_routes()

    def on_voice_note(self, message):
        """Show local ASR fallback and warmup notes without flooding the conversation."""
        now = time.monotonic()
        last = getattr(self, "_voice_note_at", {})
        if now - last.get(message, -999) > 60:
            last[message] = now
            self._voice_note_at = last
            self.feature_controller("session").add_chat("system", "🎙️ " + message)


# Backward-compatible import name for callers migrating from mixin composition.
VoiceSettingsMixin = VoiceSettingsController
