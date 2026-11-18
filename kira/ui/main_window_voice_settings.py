"""Voice settings behavior mixin for the desktop window."""
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
    KiraAvatar,
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
    subprocess,
    time,
)


from .window_feature_controller import WindowFeatureController


class VoiceSettingsMixin(WindowFeatureController):
    def build_chat_tab(self):
        page = QWidget()
        self.chat_page = page
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        # --- character tabs: one tab (= one independent conversation) per character
        self.char_tabs = QFrame()
        self.char_tabs.setObjectName("charTabs")
        self.char_tabs_row = QHBoxLayout(self.char_tabs)
        self.char_tabs_row.setContentsMargins(2, 0, 2, 0)
        self.char_tabs_row.setSpacing(8)
        self.char_tab_group = QButtonGroup(self)
        self.char_tab_group.setExclusive(True)
        self.char_tab_buttons = {}
        outer.addWidget(self.char_tabs)
        body = QHBoxLayout()
        body.setSpacing(10)
        outer.addLayout(body, 1)
        root = body
        # --- dedicated avatar area (same PNG and loader; the view keeps the image's aspect ratio)
        self.avatar_card = QFrame()
        self.avatar_card.setObjectName("avatarCard")
        av = QVBoxLayout(self.avatar_card)
        av.setContentsMargins(8, 8, 8, 10)
        av.setSpacing(4)
        self.avatar = KiraAvatar(self.animator, view="card")
        self.avatar.setMinimumSize(150, 190)
        self.avatar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        av.addWidget(self.avatar, 1)
        self.tagline = QLabel()
        self.tagline.setObjectName("hint")
        self.tagline.setAlignment(Qt.AlignCenter)
        self.reg(self.tagline.setText, "tagline")
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        av.addWidget(self.tagline)
        av.addWidget(self.status)
        self.avatar_card.setFixedWidth(250)
        root.addWidget(self.avatar_card)
        # --- chat card: compact header, conversation, composer
        chat_card = QFrame()
        chat_card.setObjectName("chatCard")
        cv = QVBoxLayout(chat_card)
        cv.setContentsMargins(12, 8, 12, 10)
        cv.setSpacing(6)
        self.chat_header = ChatHeader(self.icon_button("user", True), parent=chat_card)
        self.title = self.chat_header.title
        self.mood_emotion_icon = self.chat_header.mood_emotion_icon
        self.mood_indicator = self.chat_header.mood_indicator
        self.companion_btn = self.chat_header.companion_btn
        self.companion_btn.clicked.connect(self.toggle_companion)
        cv.addWidget(self.chat_header)
        self.chat_stack = QStackedWidget()                 # one read-only chat view per character (created in make_session_view)
        cv.addWidget(self.chat_stack, 1)
        self.chat_composer = ChatComposer(
            self,
            chat_input_factory=ChatInput,
            route_chip_factory=RouteChip,
            code_chat_factory=CodeChat,
            make_icon=make_icon,
            story_mode=self.game_mode_application_service.STORY_MODE,
            competitive_safe_mode=self.game_mode_application_service.COMPETITIVE_SAFE_MODE,
            parent=chat_card,
        )
        composer = self.chat_composer
        cv.addWidget(self.chat_composer)
        root.addWidget(chat_card, 1)
        self.glow_effects = []                             # neon glow around the composer (colour follows the character); not on the animated avatar: an effect would re-render it every frame
        for widget in (composer,):
            glow = QGraphicsDropShadowEffect(widget)
            glow.setBlurRadius(30)
            glow.setOffset(0, 0)
            glow.setColor(QColor(143, 107, 255, 150))
            widget.setGraphicsEffect(glow)
            self.glow_effects.append(glow)
        self.tabs.addTab(page, "")

    def build_assistant_section(self):
        """Host the independent assistant settings page and bind application actions."""
        ollama = self.settings.get("providers", {}).get("ollama", {})
        self.assistant_page = AssistantPage(
            self.settings,
            self.t,
            model_combo_factory=ModelCombo,
            num_ctx=clamp_num_ctx(ollama.get("num_ctx", DEFAULT_NUM_CTX)),
            num_predict=clamp_num_predict(ollama.get("num_predict", DEFAULT_NUM_PREDICT)),
            keep_alive=str(ollama.get("keep_alive", DEFAULT_KEEP_ALIVE)),
            parent=self,
        )
        # Compatibility aliases keep existing persistence/controller code stable while
        # the remaining settings orchestration is extracted in later steps.
        for name in (
            "name", "persona", "modes_chk", "temp", "model", "url", "use_qwen_btn",
            "num_ctx", "num_predict", "keep_alive", "conn_btn", "load_btn",
            "unload_btn", "speed_btn", "conn_lbl",
        ):
            setattr(self, name, getattr(self.assistant_page, name))

        self.assistant_page.test_connection_requested.connect(self.test_connection)
        self.assistant_page.load_model_requested.connect(self.load_local_model)
        self.assistant_page.unload_model_requested.connect(self.unload_local_model)
        self.assistant_page.speed_test_requested.connect(self.speed_test)
        self.tabs.addTab(self.assistant_page, "")

    def build_voice_tab(self):
        """Compose the independent Voice page and connect its intent signals."""
        self.voice_page = VoicePage(self.settings, self.t, parent=self)
        self.voice_page.voice_enabled_requested.connect(self.set_voice_enabled)
        self.voice_page.choose_whisper_folder_requested.connect(self.choose_local_whisper_folder)
        self.voice_page.download_whisper_requested.connect(self.download_local_whisper_model)
        self.voice_page.autosave_requested.connect(self.autosave_voice)
        self.tabs.addTab(self.voice_page, "")
        self.fill_mic_devices(str(self.settings.get("mic_device") or ""))
        self.fill_output_devices(str(self.settings.get("output_device") or ""))
        self.refresh_voice_caps()

    def set_local_voice_option(self, key, enabled):
        self.settings[key] = bool(enabled)
        self.save_now()

    def choose_local_asr_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه‌ی مدل STT را انتخاب کن", str(Path.home()))
        if not folder:
            return
        self.local_asr_path_edit.setText(folder)
        self.settings["local_voice_asr_model"] = folder
        self.save_now()
        self.refresh_local_voice_status()

    def download_local_qwen_model(self):
        model_id = str(self.local_asr_path_edit.text() or "").strip() or "Qwen/Qwen3-ASR-0.6B"
        if Path(model_id).expanduser().is_dir():
            self.local_voice_status.setText("این مدل از قبل روی سیستم وجود دارد.")
            self.refresh_local_voice_status()
            return
        if "/" not in model_id:
            self.local_voice_status.setText("شناسه مخزن Hugging Face را به شکل owner/repository وارد کن.")
            return
        self.local_voice_status.setText("در حال آماده‌سازی موتور Qwen و دانلود مدل از Hugging Face؛ ممکن است چند گیگابایت باشد…")
        from .. import local_voice
        self._run_local_voice_task(lambda: local_voice.install_and_download_qwen_asr(model_id),
                                   self.local_asr_download_btn, self._on_local_qwen_downloaded)

    def _on_local_qwen_downloaded(self, result):
        ok, value = result
        if not ok:
            self.local_voice_status.setText(f"دانلود مدل Qwen ناموفق بود: {value}")
            return
        model_id = str(self.local_asr_path_edit.text() or "").strip() or "Qwen/Qwen3-ASR-0.6B"
        self.settings["local_voice_asr_model"] = model_id
        self.local_asr_path_edit.setText(model_id)
        self.save_now()
        self.refresh_local_voice_status()
        from .. import local_voice
        self.local_voice_status.setText(
            f"Qwen نصب و فعال شد.\nمسیر مدل: {value}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
        )

    def choose_local_whisper_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه مدل Whisper را انتخاب کن", str(Path.home()))
        if not folder:
            return
        self.voice_page.whisper.setCurrentText(folder)
        self.settings["whisper_model"] = folder
        self.save_now()
        self.local_voice_status.setText(f"مدل Whisper از سیستم انتخاب شد: {folder}")

    def download_local_whisper_model(self):
        value = str(self.voice_page.whisper.currentText() or "").strip()
        if value.casefold() == "qwen/qwen3-asr-0.6b":
            self.local_asr_path_edit.setText(value)
            self.local_voice_status.setText("در حال نصب موتور Qwen ASR و دانلود مدل محلی…")
            from .. import local_voice
            self._run_local_voice_task(
                lambda: local_voice.install_and_download_qwen_asr(value),
                self.voice_page.whisper_download_btn, self._on_local_qwen_downloaded
            )
            return
        if Path(value).expanduser().is_dir():
            self.local_voice_status.setText("این مدل Whisper از قبل روی سیستم وجود دارد.")
            return
        aliases = {
            "tiny": "Systran/faster-whisper-tiny",
            "base": "Systran/faster-whisper-base",
            "small": "Systran/faster-whisper-small",
            "medium": "Systran/faster-whisper-medium",
            "large-v3": "Systran/faster-whisper-large-v3",
            "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        }
        repo_id = aliases.get(value, value)
        if "/" not in repo_id:
            self.local_voice_status.setText("برای دانلود، یک شناسه Hugging Face معتبر انتخاب کن.")
            return
        from .. import local_voice
        self.local_voice_status.setText("در حال نصب موتور faster-whisper و دانلود مدل…")
        self._run_local_voice_task(lambda: local_voice.install_and_download_whisper(repo_id),
                                   self.voice_page.whisper_download_btn, self._on_whisper_downloaded)

    def _on_whisper_downloaded(self, result):
        ok, value = result
        if not ok:
            self.local_voice_status.setText(f"دانلود مدل STT ناموفق بود: {value}")
            return
        self.settings["whisper_model"] = str(value)
        self.voice_page.whisper.setCurrentText(str(value))
        self.save_now()
        from .. import local_voice
        self.local_voice_status.setText(
            f"Whisper نصب و فعال شد.\nمسیر مدل: {value}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
        )

    def download_local_tts_model(self):
        repo_id = str(self.local_tts_model_path.text() or "").strip()
        if "/" not in repo_id or "\\" in repo_id:
            self.local_voice_status.setText("شناسه مخزن Piper در Hugging Face را در کادر مدل TTS وارد کن.")
            return
        from .. import local_voice
        self.local_voice_status.setText("در حال نصب Piper و دانلود صدای انتخاب‌شده…")
        self._run_local_voice_task(lambda: local_voice.install_and_download_piper_voice(repo_id),
                                   self.local_tts_download_btn, self._on_local_tts_downloaded)

    def _on_local_tts_downloaded(self, result):
        ok, value = result
        if not ok:
            self.local_voice_status.setText(f"دانلود مدل TTS ناموفق بود: {value}")
            return
        try:
            candidates = sorted(Path(value).rglob("*.onnx"))
            if not candidates:
                raise RuntimeError("در مخزن دانلودشده فایل Piper ONNX پیدا نشد.")
            self._install_piper_voice(candidates[0])
            from .. import local_voice
            self.local_voice_status.setText(
                f"Piper نصب شد و صدا فعال شد: {candidates[0].name}\n"
                f"مسیر فایل: {candidates[0]}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
            )
        except Exception as exc:
            self.local_voice_status.setText(f"نصب مدل TTS ناموفق بود: {type(exc).__name__}: {exc}")

    def apply_local_whisper_model(self):
        value = self.local_whisper_path.text().strip() or "small"
        self.settings["whisper_model"] = value
        if hasattr(self, "whisper"):
            if self.voice_page.whisper.findText(value) < 0:
                self.voice_page.whisper.addItem(value)
            self.voice_page.whisper.setCurrentText(value)
        self.save_now()
        self.add_chat("system", "مدل STT محلی به‌روزرسانی شد.")

    def choose_local_tts_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "مدل Piper ONNX", str(Path.home()), "Piper ONNX (*.onnx)")
        if path:
            self._install_piper_voice(Path(path))

    def _install_piper_voice(self, source):
        source = Path(source).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".onnx":
            QMessageBox.warning(self, "مدل TTS", "فایل انتخاب‌شده باید Piper ONNX باشد.")
            return
        metadata = Path(str(source) + ".json")
        if not metadata.is_file():
            sibling = source.with_suffix(".json")
            metadata = sibling if sibling.is_file() else metadata
        if not metadata.is_file():
            QMessageBox.warning(self, "مدل TTS", "فایل پیکربندی کنار مدل (.onnx.json یا .json) پیدا نشد.")
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
            self.settings["local_voice_tts_model"] = str(target)
            self.local_tts_model_path.setText(str(target))
            self.save_now()
            self.refresh_local_voice_status()
            self.api_add_status.setText("مدل Piper به پوشه‌ی داده‌ی Kira کپی شد و برای TTS انتخاب شد.")
        except OSError as exc:
            QMessageBox.warning(self, "مدل TTS", str(exc))

    def import_local_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "معرفی مدل به Kira", str(Path.home()),
            "Model files (*.gguf *.onnx *.bin *.safetensors *.pt *.pth *.json);;All files (*)"
        )
        if not path:
            path = QFileDialog.getExistingDirectory(self, "یا پوشه‌ی مدل را انتخاب کن", str(Path.home()))
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
            elif (source / "model.bin").is_file():
                self.local_whisper_path.setText(str(source))
                self.apply_local_whisper_model()
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
                if any(token in signature for token in ("whisper", "qwen3asr", "qwen_asr", "speechrecognition", "speech_to_text", "audioencoderdecoder")):
                    self.local_asr_path_edit.setText(str(source))
                    self.settings["local_voice_asr_model"] = str(source)
                    self.save_now()
                    self.refresh_local_voice_status()
                    return
                if any(token in signature for token in ("causallm", "forcausallm", "textgeneration", "llama", "qwen3for")):
                    QMessageBox.information(self, "مدل Chat شناسایی شد",
                        "این پوشه یک مدل متنی Hugging Face است، اما Ollama مستقیماً پوشه‌ی Transformers را وارد نمی‌کند. نسخه‌ی GGUF همین مدل را انتخاب کن.")
                    return
                category, ok = QInputDialog.getItem(
                    self, "نوع مدل", "معماری مدل از روی فایل‌هایش قطعی نبود؛ نوع واقعی را انتخاب کن.",
                    ["STT · Qwen3-ASR", "STT · Whisper", "TTS · Piper ONNX", "Chat · GGUF"], 0, False)
                if not ok:
                    return
                if category.startswith("STT · Qwen"):
                    self.local_asr_path_edit.setText(str(source))
                    self.settings["local_voice_asr_model"] = str(source)
                    self.save_now()
                    self.refresh_local_voice_status()
                    return
                if category.startswith("STT · Whisper"):
                    self.local_whisper_path.setText(str(source))
                    self.apply_local_whisper_model()
                    return
                QMessageBox.information(self, "معرفی مدل", "برای TTS فایل Piper ONNX و برای Chat فایل GGUF را انتخاب کن.")
                return
            else:
                QMessageBox.warning(self, "مدل شناسایی نشد", "در پوشه، فایل GGUF، Piper ONNX، model.bin یا config.json پیدا نشد.")
                return

        if source.name.lower().endswith(".onnx.json"):
            candidate = Path(str(source)[:-5])
            if candidate.is_file():
                source = candidate
        if source.suffix.lower() == ".gguf":
            self._create_ollama_model(source)
        elif source.suffix.lower() == ".onnx":
            self._install_piper_voice(source)
        elif source.name.lower() == "model.bin":
            self.local_whisper_path.setText(str(source.parent))
            self.apply_local_whisper_model()
        elif source.suffix.lower() in (".json", ".safetensors", ".pt", ".pth"):
            self._import_local_model_path(source.parent)
        else:
            QMessageBox.warning(self, "مدل شناسایی نشد", "پسوند فایل پشتیبانی نمی‌شود. GGUF برای Chat، Piper ONNX برای TTS و پوشه‌ی مدل برای STT را انتخاب کن.")

    def _create_ollama_model(self, source):
        if not shutil.which("ollama"):
            QMessageBox.warning(self, "Ollama", "Ollama روی سیستم پیدا نشد.")
            return
        name = re.sub(r"[^a-zA-Z0-9._-]+", "-", source.stem.lower()).strip("-._")[:48] or "imported-model"
        self.import_model_btn.setEnabled(False)
        self.api_add_status.setText(f"در حال وارد کردن {source.name} به Ollama…")

        def work():
            target = DATA_DIR / "ollama_import"
            target.mkdir(parents=True, exist_ok=True)
            modelfile = target / f"{name}.Modelfile"
            escaped = source.as_posix().replace('"', '\\"')
            modelfile.write_text(f'FROM "{escaped}"\n', encoding="utf-8")
            result = subprocess.run(["ollama", "create", name, "-f", str(modelfile)],
                                    capture_output=True, text=True, timeout=1800, check=False)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout or "ollama create failed")[-3000:])
            return name

        self._model_import_worker = TaskWorker(work)
        self._model_import_worker.done.connect(self.on_local_model_imported)
        self._model_import_worker.finished.connect(lambda: setattr(self, "_model_import_worker", None))
        self._model_import_worker.start()

    def on_local_model_imported(self, result):
        self.import_model_btn.setEnabled(True)
        ok, value = result
        if not ok:
            self.api_add_status.setText("✕ واردکردن مدل ناموفق بود: " + str(value))
            return
        model = str(value)
        if hasattr(self, "model"):
            if self.model.findText(model) < 0:
                self.model.addItem(model)
            self.model.setCurrentText(model)
        self.settings["model"] = model
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["model"] = model
        self.provider_application_service.ensure_routes(self.settings)
        self.provider_application_service.add_ollama_models(self.settings, [model])
        self.save_now()
        self.refresh_route_list()
        self.refresh_unified_models()
        self.api_add_status.setText(f"✓ مدل «{model}» به Ollama اضافه شد.")

    def select_local_asr_model(self, index):
        combo = getattr(self, "local_asr_model_list", None)
        if combo is None or index < 0:
            return
        value = str(combo.itemData(index) or "").strip()
        if not value:
            return
        self.local_asr_path_edit.setText(value)
        self.settings["local_voice_asr_model"] = value
        self.save_now()
        self.refresh_local_voice_status()

    def select_local_tts_model(self, index):
        combo = getattr(self, "local_tts_model_list", None)
        if combo is None or index < 0:
            return
        value = str(combo.itemData(index) or "").strip()
        self.local_tts_model_path.setText(value)
        self.settings["local_voice_tts_model"] = value
        self.save_now()
        self.refresh_local_voice_status()

    def refresh_local_voice_status(self):
        try:
            from .. import local_voice
            asr_model = str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B")
            tts_model = str(self.settings.get("local_voice_tts_model") or "")
            discovered = local_voice.discover_cached_models()

            asr_combo = getattr(self, "local_asr_model_list", None)
            if asr_combo is not None:
                asr_combo.blockSignals(True)
                asr_combo.clear()
                asr_entries = discovered.get("asr", [])
                if not any(item.get("id") == asr_model for item in asr_entries):
                    asr_combo.addItem(f"{asr_model} · هنوز در کش پیدا نشد", asr_model)
                for item in asr_entries:
                    asr_combo.addItem(f"{item['id']} · دانلودشده", item["id"])
                selected = next((i for i in range(asr_combo.count())
                                 if str(asr_combo.itemData(i)) == asr_model), 0)
                asr_combo.setCurrentIndex(selected)
                asr_combo.blockSignals(False)

            tts_combo = getattr(self, "local_tts_model_list", None)
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
            asr_loaded = bool(state["asr_loaded"] and state.get("asr_model") == asr_model)
            tts_loaded = bool(state["tts_loaded"] and (
                (tts_model and state.get("tts_model") and Path(state["tts_model"]).resolve() == Path(tts_model).expanduser().resolve())
                or (not tts_model and state.get("tts_model") == "bundled")
            ))
            asr_cached = any(item.get("id") == asr_model for item in discovered.get("asr", []))
            asr = "پکیج Python نصب است" if state["asr_installed"] else "پکیج Python نصب نیست"
            asr += " · فایل‌های مدل در کش موجود است" if asr_cached else " · فایل‌های مدل هنوز دانلود نشده"
            asr += " · همین مدل در حافظه است" if asr_loaded else " · مدل هنوز بارگذاری نشده"
            if state.get("asr_error"):
                asr += " · " + state["asr_error"]
            tts = "Piper در دسترس است" if state["tts_installed"] else "Piper نصب نیست"
            tts += " · همین صدا بارگذاری شده" if tts_loaded else " · صدای انتخابی هنوز بارگذاری نشده"
            if state.get("tts_error"):
                tts += " · " + state["tts_error"]
            selected_tts = tts_model or "Mana Persian Piper · صدای فارسی پیش‌فرض"
            self.local_voice_status.setText(
                f"STT · Qwen3-ASR: {asr}\nمدل STT: {asr_model}\n"
                f"TTS · Piper: {tts}\nمدل TTS: {selected_tts}\n"
                f"مدل‌های Piper مستقل: {len(discovered.get('tts', []))}\n"
                f"کش مدل‌ها: {local_voice.cache_directory()}"
            )
        except Exception as exc:
            self.local_voice_status.setText(f"بررسی موتورهای صوتی ناموفق بود: {type(exc).__name__}: {exc}")

    def _run_local_voice_task(self, fn, button, callback):
        worker = getattr(self, "_local_voice_worker", None)
        if worker is not None and worker.isRunning():
            return
        button.setEnabled(False)
        if hasattr(self, "local_voice_progress"):
            self.local_voice_progress.show()
        worker = TaskWorker(fn)
        self._local_voice_worker = worker
        def completed(result):
            button.setEnabled(True)
            if hasattr(self, "local_voice_progress"):
                self.local_voice_progress.hide()
            callback(result)

        def worker_finished():
            if self._local_voice_worker is worker:
                self._local_voice_worker = None
            if getattr(self, "_close_after_local_voice", False):
                self._close_after_local_voice = False
                QTimer.singleShot(0, self.close)

        worker.done.connect(completed)
        worker.finished.connect(worker_finished)
        worker.start()

    def load_local_asr(self):
        from .. import local_voice
        model_name = str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B")
        self._run_local_voice_task(lambda: local_voice.load_asr(model_name), self.local_asr_load_btn, self._on_local_asr_loaded)

    def _on_local_asr_loaded(self, result):
        ok, value = result
        if ok:
            self.local_voice_status.setText("Qwen3-ASR با موفقیت بارگذاری شد. تشخیص گفتار محلی آماده است.")
        else:
            self.local_voice_status.setText(f"بارگذاری Qwen3-ASR ناموفق بود: {value}")
        self.refresh_local_voice_status()

    def copy_local_voice_log(self):
        text = self.local_voice_status.text().strip()
        if text:
            QApplication.clipboard().setText(text)

    def test_local_tts(self):
        from .. import local_voice
        self._run_local_voice_task(
            lambda: local_voice.synthesize_persian(
                "سلام، من کیرا هستم. این صدای فارسی محلی من است.",
                self.settings.get("local_voice_tts_model", "")
            ),
            self.local_tts_test_btn, self._on_local_tts_tested
        )

    def test_local_stt(self):
        listener = getattr(self, "_local_stt_test_listener", None)
        if listener is not None and listener.isRunning():
            listener.stop()
            self.local_stt_test_btn.setText("تست STT")
            self.local_voice_status.setText("آزمایش STT متوقف شد.")
            return

        from ..listener import Listener
        model_name = str(self.settings.get("whisper_model") or "small")
        language = str(self.settings.get("stt_language") or "fa")
        listener = Listener(
            model_name, language, self,
            sensitivity=int(self.settings.get("mic_sensitivity", 100)),
            barge_in=False, settings=self.settings,
        )
        self._local_stt_test_listener = listener
        listener.heard.connect(self._on_local_stt_test_heard)
        listener.error.connect(self._on_local_stt_test_error)
        listener.state.connect(self._on_local_stt_test_state)
        listener.finished.connect(lambda current=listener: self._on_local_stt_test_finished(current))
        self.local_stt_test_btn.setText("توقف تست STT")
        self.local_voice_status.setText("در حال آماده‌سازی میکروفن؛ صحبت کن تا متن تشخیص‌داده‌شده نمایش داده شود.")
        listener.start()

    def _on_local_stt_test_state(self, state):
        labels = {
            "loading": "در حال آماده‌سازی موتور STT…",
            "listening": "میکروفن آماده است؛ صحبت کن…",
            "hearing": "صدایت دریافت شد؛ در حال ضبط…",
            "transcribing": "در حال تبدیل گفتار به متن…",
        }
        if state in labels:
            self.local_voice_status.setText(labels[state])

    def _on_local_stt_test_heard(self, text):
        listener = getattr(self, "_local_stt_test_listener", None)
        if listener is not None:
            listener.stop()
        self.local_voice_status.setText(f"نتیجه تست STT: {text}")

    def _on_local_stt_test_error(self, message):
        self.local_voice_status.setText(f"تست STT ناموفق بود: {message}")
        listener = getattr(self, "_local_stt_test_listener", None)
        if listener is not None:
            listener.stop()

    def _on_local_stt_test_finished(self, listener):
        if getattr(self, "_local_stt_test_listener", None) is listener:
            self._local_stt_test_listener = None
        if hasattr(self, "local_stt_test_btn"):
            self.local_stt_test_btn.setText("تست STT")

    def _on_local_tts_tested(self, result):
        ok, value = result
        if not ok:
            # Keep the actionable synthesis error visible; a status refresh here used
            # to overwrite it immediately with the generic installed/not-loaded text.
            self.local_voice_status.setText(f"تولید صدای Piper ناموفق بود: {value}")
            return
        try:
            if not isinstance(value, (bytes, bytearray)) or not value.startswith(b"RIFF"):
                raise RuntimeError("موتور TTS خروجی WAV معتبر تولید نکرد.")
            test_path = DATA_DIR / "voice_cache" / "local_persian_test.wav"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_bytes(value)
            self._local_tts_test_active = False
            self.voice_application_service.play_file(str(test_path))
            self._local_tts_test_active = True
            model = str(self.settings.get("local_voice_tts_model") or "Mana Persian Piper · صدای پیش‌فرض")
            self.local_voice_status.setText(
                f"تولید WAV موفق بود · مدل: {model} · حجم: {len(value):,} بایت\nدر انتظار شروع پخش از دستگاه خروجی…"
            )
        except Exception as exc:
            self._local_tts_test_active = False
            self.local_voice_status.setText(f"ساخت یا پخش فایل آزمایشی ناموفق بود: {type(exc).__name__}: {exc}")

    def _on_local_tts_playback_started(self):
        if self._local_tts_test_active:
            self.local_voice_status.setText("تولید WAV موفق بود · پخش TTS شروع شد.")

    def _on_local_tts_playback_finished(self):
        if self._local_tts_test_active:
            self._local_tts_test_active = False
            self.local_voice_status.setText("تست TTS موفق بود: صدا کامل پخش شد.")

    def _on_local_tts_playback_error(self, message):
        if self._local_tts_test_active:
            self._local_tts_test_active = False
            self.local_voice_status.setText(f"تولید صدا موفق بود، اما پخش شکست خورد: {message}")

    def _on_local_tts_playback_cancelled(self):
        if self._local_tts_test_active:
            self._local_tts_test_active = False
            self.local_voice_status.setText("تست TTS متوقف شد؛ پخش کامل نشد.")

    # ---- voice: devices, supported controls, autosave ----

    def fill_output_devices(self, current):
        self.voice_page.out_device.clear()
        self.voice_page.out_device.addItem(self.t("dev_default"), "")
        try:
            from PySide6.QtMultimedia import QMediaDevices
            seen = set()
            for dev in QMediaDevices.audioOutputs():
                name = dev.description()
                if name and name not in seen:
                    seen.add(name)
                    self.voice_page.out_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - no audio backend: only the default entry
            pass
        i = self.voice_page.out_device.findData(current)
        self.voice_page.out_device.setCurrentIndex(i if i >= 0 else 0)

    def fill_mic_devices(self, current):
        self.voice_page.mic_device.clear()
        self.voice_page.mic_device.addItem(self.t("dev_default"), "")
        try:
            import sounddevice as sd
            seen = set()
            for dev in sd.query_devices():
                name = str(dev.get("name") or "")
                if dev.get("max_input_channels", 0) > 0 and name and name not in seen:
                    seen.add(name)
                    self.voice_page.mic_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - sounddevice missing: only the default entry
            pass
        i = self.voice_page.mic_device.findData(current)
        self.voice_page.mic_device.setCurrentIndex(i if i >= 0 else 0)

    def refresh_voice_caps(self):
        """State the local-only speech policy in the Voice page."""
        self.voice_page.voice_caps_note.setText("میکروفن و بلندگو با STT/TTS محلی کار می‌کنند؛ هیچ صدای ابری یا آنلاین استفاده نمی‌شود.")

    def collect_voice_settings(self):
        s = self.settings
        s.update({"voice_rate": self.voice_page.rate.value(), "voice_volume": self.voice_page.volume.value() / 100.0,
                  "output_device": self.voice_page.out_device.currentData() or "", "mic_device": self.voice_page.mic_device.currentData() or "",
                  "mic_gain": self.voice_page.mic_gain.value(), "mic_sensitivity": self.voice_page.mic_sens.value()})

    def autosave_voice(self):
        """Voice sliders / devices are saved as soon as they are changed (the Save button is not needed for them)."""
        self.collect_voice_settings()
        self.apply_character_voice_settings()
        self.save_now()

    def show_voice_routes(self):
        """Open the local STT model controls in Connections."""
        self.go_tab(self.tab_keys.index("tab_ai"))
        if hasattr(self, "local_model_tabs"):
            self.local_model_tabs.setCurrentIndex(1)

    def set_route_view(self, index):
        if hasattr(self, "local_model_tabs") and int(index) in (1, 2):
            self.local_model_tabs.setCurrentIndex(int(index))

    def on_voice_note(self, message):
        """Show local ASR fallback and warmup notes without flooding the conversation."""
        now = time.monotonic()
        last = getattr(self, "_voice_note_at", {})
        if now - last.get(message, -999) > 60:
            last[message] = now
            self._voice_note_at = last
            self.add_chat("system", "🎙️ " + message)
