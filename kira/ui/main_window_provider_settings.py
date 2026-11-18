"""Provider settings behavior mixin for the desktop window."""
from .main_window_provider_settings_support import *  # noqa: F401,F403


class ProviderSettingsMixin:
    def refresh_model_catalogs(self):
        if getattr(self, "_model_catalog_worker", None) is not None and self._model_catalog_worker.isRunning():
            return
        self.mcp_registry_panel.set_refreshing(True)
        self.mcp_registry_panel.set_status("در حال بررسی APIها و دریافت مدل‌های تازه…")
        try:
            providers = [
                (pid, dict(self.settings.get("providers", {}).get(pid, {})))
                for pid in api_manager.api_ids(self.settings)
                if self.settings.get("providers", {}).get(pid, {}).get("enabled", True)
            ]
            def refresh():
                results = []
                for pid, cfg in providers:
                    results.append((pid, api_manager.rediscover(pid, cfg, timeout=15)))
                return results
            self._model_catalog_worker = TaskWorker(refresh)
            self._model_catalog_worker.done.connect(self._on_model_catalog_refresh)
            self._model_catalog_worker.start()
            self.scan_ollama()
            self.refresh_local_voice_status()
        except Exception as exc:
            self.mcp_registry_panel.set_refreshing(False)
            self.mcp_registry_panel.set_status("تازه‌سازی کامل نشد: " + str(exc)[:200])

    def _on_model_catalog_refresh(self, result):
        self.mcp_registry_panel.set_refreshing(False)
        ok, value = result
        if not ok:
            self.mcp_registry_panel.set_status("دریافت مدل‌های API ناموفق بود: " + str(value)[:200])
            return
        updated = 0
        failed = []
        for pid, detection in value:
            if detection.ok:
                api_manager.apply_models(self.settings, pid, detection.models, detection.rate_limit)
                updated += len(detection.models)
            else:
                api_manager.apply_failure(self.settings, pid, detection)
                failed.append(pid)
        self.save_now()
        self.refresh_unified_models()
        self.refresh_api_table()
        suffix = ("؛ خطا در " + "، ".join(failed)) if failed else ""
        self.mcp_registry_panel.set_status(f"مدل‌های API تازه‌سازی شد: {updated} مدل از {len(value)} اتصال{suffix}.")

    def build_ai_tab(self):
        """Unified cloud/local model catalogue with advanced route and provider controls."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        # API keys in this section are checked for Chat capability only.
        add_box, list_box, det_box = self.build_api_boxes()
        layout.addWidget(add_box)

        import_row = QHBoxLayout()
        self.import_model_btn = QPushButton("＋ معرفی مدل از فایل یا پوشه‌ی سیستم")
        self.import_model_btn.setToolTip("فایل GGUF برای Chat، مدل CTranslate2/Qwen برای STT یا Piper ONNX برای TTS")
        self.import_model_btn.clicked.connect(self.import_local_model)
        import_row.addWidget(self.import_model_btn)
        import_row.addStretch(1)
        layout.addLayout(import_row)

        self.build_mcp_registry_group(layout)
        cloud_box, cloud_form = self.group("مدل‌های Chat Cloud")
        model_list = QListWidget()
        model_list.setAlternatingRowColors(True)
        model_list.setMinimumHeight(105)
        model_list.setMaximumHeight(170)
        model_list.itemChanged.connect(lambda item: self.on_cloud_model_item_changed("chat", item))
        self.cloud_model_lists = {"chat": model_list}
        cloud_form.addRow(model_list)
        layout.addWidget(cloud_box)

        local_box, local_form = self.group("مدل‌های Local")
        local_form.setContentsMargins(8, 6, 8, 6)
        local_form.setHorizontalSpacing(8)
        local_form.setVerticalSpacing(4)
        self.local_model_tabs = QTabWidget()
        self.local_model_tabs.setMaximumHeight(255)

        # Local Chat: Ollama remains the provider, but every installed model is listed here.
        local_chat = QWidget()
        local_chat_layout = QVBoxLayout(local_chat)
        local_chat_layout.setContentsMargins(3, 3, 3, 3)
        local_chat_layout.addWidget(self.build_ollama_group())
        self.local_model_list = QListWidget()
        self.local_model_list.setAlternatingRowColors(True)
        self.local_model_list.setMinimumHeight(90)
        self.local_model_list.setMaximumHeight(150)
        self.local_model_list.itemChanged.connect(self.on_local_chat_item_changed)
        local_chat_layout.addWidget(QLabel("مدل‌های چت نصب‌شده‌ی Ollama"))
        local_chat_layout.addWidget(self.local_model_list)
        self.route_scan_btn = QPushButton("یافتن مدل‌های نصب‌شده")
        self.route_scan_btn.clicked.connect(self.scan_ollama)
        local_chat_layout.addWidget(self.route_scan_btn)
        self.local_model_tabs.addTab(local_chat, "Chat")

        # Local STT: Qwen ASR and faster-whisper can use a downloaded local directory.
        local_stt = QWidget()
        local_stt_layout = QVBoxLayout(local_stt)
        local_stt_layout.setContentsMargins(2, 2, 2, 2)
        local_stt_layout.setSpacing(4)
        self.local_asr_chk = QCheckBox("استفاده از Qwen3-ASR محلی")
        self.local_asr_chk.setChecked(bool(self.settings.get("local_voice_asr", True)))
        self.local_asr_chk.toggled.connect(lambda on: self.set_local_voice_option("local_voice_asr", on))
        local_stt_layout.addWidget(self.local_asr_chk)
        self.local_asr_model_list = QComboBox()
        self.local_asr_model_list.setToolTip("مدل‌های STT موجود در کش Hugging Face")
        self.local_asr_model_list.setMaximumHeight(30)
        self.local_asr_model_list.currentIndexChanged.connect(self.select_local_asr_model)
        local_stt_layout.addWidget(QLabel("مدل‌های دانلودشده‌ی STT"))
        local_stt_layout.addWidget(self.local_asr_model_list)
        # Keep the optional custom path internally; the normal flow needs no manual path entry.
        self.local_asr_path_edit = QLineEdit(str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B"))
        self.local_asr_path_edit.setVisible(False)
        self.local_asr_browse_btn = QPushButton("انتخاب پوشه")
        self.local_asr_browse_btn.clicked.connect(self.choose_local_asr_folder)
        asr_actions = QHBoxLayout()
        self.local_asr_download_btn = QPushButton("نصب خودکار Qwen + مدل")
        self.local_asr_download_btn.clicked.connect(self.download_local_qwen_model)
        self.local_asr_load_btn = QPushButton("بارگذاری مدل")
        self.local_asr_load_btn.clicked.connect(self.load_local_asr)
        asr_actions.addWidget(self.local_asr_download_btn)
        asr_actions.addWidget(self.local_asr_load_btn)
        local_stt_layout.addLayout(asr_actions)
        # Whisper selection and one-click installation are available in the main Voice settings above.
        self.local_whisper_path = QLineEdit(str(self.settings.get("whisper_model") or "small"))
        self.local_whisper_path.setVisible(False)
        self.local_model_tabs.addTab(local_stt, "STT")

        # Local TTS: bundled Persian Piper or a user-selected ONNX voice.
        local_tts = QWidget()
        local_tts_layout = QVBoxLayout(local_tts)
        local_tts_layout.setContentsMargins(2, 2, 2, 2)
        local_tts_layout.setSpacing(4)
        self.local_tts_chk = QCheckBox("استفاده از Piper محلی")
        self.local_tts_chk.setChecked(bool(self.settings.get("local_voice_tts", True)))
        self.local_tts_chk.toggled.connect(lambda on: self.set_local_voice_option("local_voice_tts", on))
        local_tts_layout.addWidget(self.local_tts_chk)
        self.local_tts_model_list = QComboBox()
        self.local_tts_model_list.setToolTip("صداهای Piper دانلودشده و صدای فارسی پیش‌فرض")
        self.local_tts_model_list.setMaximumHeight(30)
        self.local_tts_model_list.currentIndexChanged.connect(self.select_local_tts_model)
        local_tts_layout.addWidget(QLabel("مدل‌های دانلودشده‌ی TTS"))
        local_tts_layout.addWidget(self.local_tts_model_list)
        self.local_tts_model_path = QLineEdit(str(self.settings.get("local_voice_tts_model") or ""))
        self.local_tts_model_path.setPlaceholderText("مسیر فایل Piper ONNX یا شناسه مخزن Hugging Face؛ خالی = صدای پیش‌فرض")
        self.local_tts_model_path.setLayoutDirection(Qt.LeftToRight)
        tts_path_row = QHBoxLayout()
        tts_path_row.addWidget(self.local_tts_model_path, 1)
        self.local_tts_browse_btn = QPushButton("انتخاب ONNX")
        self.local_tts_browse_btn.clicked.connect(self.choose_local_tts_model)
        tts_path_row.addWidget(self.local_tts_browse_btn)
        self.local_tts_download_btn = QPushButton("نصب خودکار Piper + صدا")
        self.local_tts_download_btn.clicked.connect(self.download_local_tts_model)
        tts_path_row.addWidget(self.local_tts_download_btn)
        local_tts_layout.addLayout(tts_path_row)
        self.local_tts_test_btn = QPushButton("تست TTS")
        self.local_tts_test_btn.clicked.connect(self.test_local_tts)
        local_tts_layout.addWidget(self.local_tts_test_btn)
        self.local_model_tabs.addTab(local_tts, "TTS")

        self.local_voice_status = QLabel()
        self.local_voice_status.setWordWrap(True)
        self.local_voice_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.local_voice_status.setMaximumHeight(96)
        self.local_voice_status.setObjectName("hint")
        self.local_voice_copy_btn = QPushButton("کپی لاگ")
        self.local_voice_copy_btn.setMaximumWidth(90)
        self.local_voice_copy_btn.clicked.connect(self.copy_local_voice_log)
        self.local_voice_progress = QProgressBar()
        self.local_voice_progress.setRange(0, 0)
        self.local_voice_progress.setTextVisible(False)
        self.local_voice_progress.setMaximumHeight(7)
        self.local_voice_progress.hide()
        local_form.addRow(self.local_model_tabs)
        local_status_row = QHBoxLayout()
        local_status_row.addWidget(self.local_voice_status, 1)
        local_status_row.addWidget(self.local_voice_copy_btn)
        local_form.addRow(local_status_row)
        local_form.addRow(self.local_voice_progress)
        self.local_voice_box = local_box
        local_test_row = QHBoxLayout()
        self.local_stt_test_btn = QPushButton("تست STT")
        self.local_stt_test_btn.clicked.connect(self.test_local_stt)
        local_test_row.addWidget(self.local_stt_test_btn)
        local_test_row.addStretch(1)
        local_form.addRow(local_test_row)
        layout.addWidget(local_box)

        # Advanced controls remain available but are collapsed by default.
        self.connections_advanced_btn = QToolButton()
        self.connections_advanced_btn.setText("تنظیمات پیشرفته و مدیریت Providerها")
        self.connections_advanced_btn.setCheckable(True)
        self.connections_advanced_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.connections_advanced_btn.setArrowType(Qt.RightArrow)
        self.connections_advanced_body = QWidget()
        advanced_layout = QVBoxLayout(self.connections_advanced_body)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addWidget(list_box)
        advanced_layout.addWidget(det_box)

        # RouteEditor owns route/failover controls; MainWindow only handles intents.
        self.route_editor = RouteEditor(
            self.settings,
            model_combo_factory=ModelCombo,
            parent=self,
        )
        for name in (
            "route_list", "route_manual_lbl", "failover_chk", "route_up_btn",
            "route_down_btn", "route_add_btn", "route_del_btn", "route_default_btn",
            "route_use_btn", "route_auto_btn", "route_provider_lbl", "route_model_edit",
            "route_enabled_chk", "route_timeout", "route_cooldown", "route_ctx",
            "route_predict", "route_status", "route_test_btn", "route_bench_btn",
            "route_bench_all_btn", "bench_out",
        ):
            setattr(self, name, getattr(self.route_editor, name))

        self.route_editor.selection_changed.connect(self.on_route_selected)
        self.route_editor.order_changed.connect(self.on_routes_reordered)
        self.route_editor.failover_changed.connect(self.on_failover_toggled)
        self.route_editor.move_requested.connect(self.move_selected)
        self.route_editor.add_requested.connect(self.add_route_dialog)
        self.route_editor.delete_requested.connect(self.delete_selected_route)
        self.route_editor.default_requested.connect(self.default_selected_route)
        self.route_editor.select_manual_requested.connect(
            lambda: self.select_route(self._selected_route_id() or "")
        )
        self.route_editor.select_auto_requested.connect(lambda: self.select_route(""))
        self.route_editor.test_requested.connect(self.test_selected_route)
        self.route_editor.benchmark_requested.connect(self.run_benchmark)
        self.route_editor.details_changed.connect(self.route_edit_changed)
        advanced_layout.addWidget(self.route_editor)

        self.connections_advanced_body.setVisible(False)
        self.connections_advanced_btn.toggled.connect(self.connections_advanced_body.setVisible)
        self.connections_advanced_btn.toggled.connect(
            lambda on: self.connections_advanced_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        )
        layout.addWidget(self.connections_advanced_btn)
        layout.addWidget(self.connections_advanced_body)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, "")
        self.refresh_route_list()
        self.refresh_api_table()
        self.refresh_unified_models()
        self.refresh_local_voice_status()

    def _make_model_list(self, kind, cloud=True):
        model_list = QListWidget()
        model_list.setAlternatingRowColors(True)
        model_list.setMinimumHeight(105)
        model_list.setMaximumHeight(170)
        model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        if cloud:
            model_list.itemChanged.connect(lambda item, category=kind: self.on_cloud_model_item_changed(category, item))
        else:
            model_list.itemChanged.connect(self.on_local_chat_item_changed)
        return model_list

    def refresh_unified_models(self):
        """Populate the three cloud capability lists and the three local model lists."""
        if not hasattr(self, "cloud_model_lists"):
            return
        for widget in self.cloud_model_lists.values():
            widget.blockSignals(True)
            widget.clear()
        api_manager.ensure_registry(self.settings)
        free_only = str(self.settings.get("model_filter_mode") or "all") == "free"
        for pid, entry in api_manager.registry(self.settings).items():
            cfg = self.settings.get("providers", {}).get(pid, {})
            label = route_model.provider_label(pid, cfg)
            for mid, meta in (entry.get("models") or {}).items():
                if meta.get("status") == "unavailable" or meta.get("text") == "No":
                    continue
                low = str(mid).lower()
                if any(token in low for token in ("tts", "text-to-speech", "embedding", "whisper", "speech-to-text",
                                                   "speech", "transcription", "audio", "asr")):
                    continue
                if free_only and meta.get("free") is not True:
                    continue
                item = QListWidgetItem(f"{label}  ·  {mid}" + ("  · رایگان" if meta.get("free") is True else ""))
                item.setData(Qt.UserRole, {"provider": pid, "model": mid})
                item.setToolTip(f"Text: {meta.get('text') or 'Unknown'} | Vision: {meta.get('vision') or 'Unknown'} | Tools: {meta.get('tools') or 'Unknown'}")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                enabled = any(r.get("provider") == pid and r.get("model") == mid and r.get("enabled")
                              for r in route_model.get_routes(self.settings))
                item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                self.cloud_model_lists["chat"].addItem(item)
        for kind, widget in self.cloud_model_lists.items():
            if widget.count() == 0:
                if free_only:
                    message = "مدل رایگانِ تأییدشده‌ای پیدا نشد."
                else:
                    message = "برای نمایش مدل‌ها ابتدا API مربوط را اضافه و شناسایی کن."
                empty = QListWidgetItem(message)
                empty.setFlags(Qt.NoItemFlags)
                widget.addItem(empty)
            widget.blockSignals(False)

        if hasattr(self, "local_model_list"):
            self.local_model_list.blockSignals(True)
            self.local_model_list.clear()
            for route in route_model.get_routes(self.settings):
                if route.get("provider") != "ollama" or not route.get("model"):
                    continue
                item = QListWidgetItem(route["model"])
                item.setData(Qt.UserRole, route.get("id"))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if route.get("enabled") else Qt.Unchecked)
                self.local_model_list.addItem(item)
            self.local_model_list.blockSignals(False)

    def on_cloud_model_item_changed(self, kind, item):
        if kind != "chat":
            return
        data = item.data(Qt.UserRole) or {}
        provider, model = data.get("provider"), data.get("model")
        if not provider or not model:
            return
        checked = item.checkState() == Qt.Checked
        try:
            api_manager.set_model_enabled(self.settings, provider, model, checked)
        except Exception as exc:
            self.api_add_status.setText("✕ " + str(exc))
        self._api_changed(provider)
        self.refresh_unified_models()

    def on_local_chat_item_changed(self, item):
        route_id = item.data(Qt.UserRole)
        if not route_id:
            return
        route_model.update_route(self.settings, route_id, enabled=item.checkState() == Qt.Checked)
        self.save_now()
        self.refresh_route_list()
        self.refresh_unified_models()

    def _discover_unified_api_key(self, key, account=""):
        """Detect chat-model capability only; audio never uses remote APIs."""
        return api_manager.detect(key, account)

    def api_add(self):
        if self._api_busy():
            return
        key = self.api_key_edit.text().strip()
        problem = api_manager.key_problem(key)
        if problem:
            self.api_add_status.setText("✕ " + problem)
            return
        self.api_add_btn.setEnabled(False)
        self.api_add_status.setText("در حال شناسایی مدل‌های Chat از API…")
        self._api_worker = TaskWorker(lambda: self._discover_unified_api_key(key))
        self._api_worker.done.connect(lambda result, k=key: self.on_api_detected(result, k))
        self._api_worker.start()

    def on_api_detected(self, result, key, account=""):
        self.api_add_btn.setEnabled(True)
        ok, detection = result
        if not ok:
            self.api_add_status.setText("✕ " + str(detection))
            return
        if detection and detection.state == "needs_account" and not account:
            account_id, accepted = QInputDialog.getText(self, "Cloudflare", "Account ID:")
            if accepted and account_id.strip():
                self.api_add_btn.setEnabled(False)
                self.api_add_status.setText("در حال تکمیل شناسایی Cloudflare…")
                self._api_worker = TaskWorker(lambda: self._discover_unified_api_key(key, account_id.strip()))
                self._api_worker.done.connect(lambda res, k=key, a=account_id.strip(): self.on_api_detected(res, k, a))
                self._api_worker.start()
            return

        chat_added = ""
        if detection and detection.ok:
            duplicate = api_manager.find_duplicate(self.settings, key)
            if not duplicate:
                try:
                    chat_added = api_manager.register(self.settings, detection, key)
                except ValueError as exc:
                    self.api_add_status.setText("✕ " + str(exc))
            else:
                chat_added = duplicate
        if chat_added:
            self._api_changed(chat_added)
            self.api_key_edit.clear()
            label = route_model.provider_label(chat_added, self.settings["providers"][chat_added])
            self.api_add_status.setText("✓ اتصال Chat ثبت شد: " + label)
        else:
            message = api_manager.describe_failure(detection) if detection else "هیچ مدل Chat قابل استفاده‌ای از این API شناسایی نشد."
            self.api_add_status.setText("✕ " + message + "؛ کلید ثبت نشد.")
        self.refresh_unified_models()

    def build_local_model_group(self):
        """Backwards-compatible name for the Route local-provider group."""
        return self.build_ollama_group()

    def build_ollama_group(self):
        """Host the Ollama settings widget and delegate its intents to the app controller."""
        self.ollama_panel = OllamaProviderPanel(self.settings, parent=self)
        self.route_ollama_enabled = self.ollama_panel.enabled
        self.ollama_url_edit = self.ollama_panel.url_edit
        self.ollama_edit_btn = self.ollama_panel.edit_btn
        self.ollama_save_btn = self.ollama_panel.save_btn
        self.ollama_cancel_btn = self.ollama_panel.cancel_btn
        self.ollama_panel.enabled_changed.connect(lambda *_: self.provider_changed())
        self.ollama_panel.cancel_requested.connect(lambda: self.ollama_edit_mode(False))
        self.ollama_panel.save_requested.connect(self.save_ollama_edit)
        return self.ollama_panel

    def collect_provider_settings(self):
        """Only the local Ollama switch lives in the form now; API keys / enabled flags are changed by the API Manager actions directly."""
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["enabled"] = self.route_ollama_enabled.isChecked()
        route_model.ensure_routes(self.settings)

    def ollama_edit_mode(self, on):
        self.ollama_panel.set_edit_mode(bool(on), self.settings.get("ollama_url") if not on else None)

    def save_ollama_edit(self):
        url = self.ollama_url_edit.text().strip().rstrip("/")
        if not re.match(r"^https?://\S+$", url, re.I):
            self.route_status.setText("✕ آدرس Ollama باید با http:// یا https:// شروع شود.")
            return
        self.settings["ollama_url"] = url
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = url
        self.url.setText(url)                                # same address as the Assistant tab
        self.save_now()
        self.ollama_edit_mode(False)
        self.route_status.setText("✓ آدرس Ollama ذخیره شد.")

    # ---------- API Manager ----------
    API_COLUMNS = ["Provider", "API Status", "مدل‌های قابل‌دسترسی", "مدل‌های فعال", "آخرین اعتبارسنجی", "اولویت", "فعال"]
    MODEL_COLUMNS = ["فعال", "Model ID", "Status", "Context Window", "Max Output", "Text", "Vision", "Tool Calling", "روی API دیگر هم"]
    STATUS_FA = {"valid": "✓ معتبر", "invalid": "✕ نامعتبر", "error": "⚠ خطا (بعداً دوباره امتحان کن)", "disabled": "غیرفعال",
                 "no key": "بدون کلید", "not validated yet": "هنوز اعتبارسنجی نشده"}

    def build_api_boxes(self):
        """Compose independent API credential form with the registered API/detail tables."""
        self.api_add_panel = ApiAddPanel(
            self.settings,
            filter_options=(
                ("all", "همه‌ی مدل‌ها"),
                ("free", "فقط مدل‌های رایگانِ تأییدشده"),
            ),
            parent=self,
        )
        self.api_key_edit = self.api_add_panel.key_edit
        self.api_account_edit = self.api_add_panel.account_edit
        self.api_add_btn = self.api_add_panel.add_btn
        self.model_filter = self.api_add_panel.model_filter
        self.api_add_status = self.api_add_panel.status
        self.api_add_panel.add_requested.connect(self.api_add)
        self.api_add_panel.filter_changed.connect(self.on_model_filter_changed)
        add_box = self.api_add_panel
        list_box, lf = self.group("Registered APIs")
        self.api_table = QTableWidget(0, len(self.API_COLUMNS))
        self.api_table.setHorizontalHeaderLabels(self.API_COLUMNS)
        self.api_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.api_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.api_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.api_table.verticalHeader().setVisible(False)
        self.api_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.api_table.setMinimumHeight(150)
        self.api_table.itemSelectionChanged.connect(self.show_api_details)
        lf.addRow(self.api_table)
        buttons = QHBoxLayout()
        self.api_btns = {}
        for key, text, fn in (("details", "View Details", self.show_api_details), ("refresh", "Refresh / Rediscover Models", lambda: self.api_refresh(self._api_selected())),
                              ("edit", "Edit", lambda: self.api_edit(self._api_selected())), ("toggle", "Enable / Disable", lambda: self.api_toggle(self._api_selected())),
                              ("delete", "Delete", lambda: self.api_delete(self._api_selected())), ("up", "▲", lambda: self.api_move(self._api_selected(), -1)),
                              ("down", "▼", lambda: self.api_move(self._api_selected(), 1))):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, f=fn: f())
            self.api_btns[key] = btn
            buttons.addWidget(btn)
        lf.addRow(buttons)
        adv = QPushButton("افزودن Provider سفارشی / سرور محلی سازگار با OpenAI (پیشرفته)")
        adv.clicked.connect(self.add_provider_dialog)
        lf.addRow(adv)
        self.api_status = QLabel("")
        self.api_status.setWordWrap(True)
        lf.addRow(self.api_status)

        det_box, df = self.group("API Details")
        self.api_det_info = QLabel("یک API را از فهرست بالا انتخاب کن.")
        self.api_det_info.setWordWrap(True)
        self.api_det_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        df.addRow(self.api_det_info)
        self.api_models = QTableWidget(0, len(self.MODEL_COLUMNS))
        self.api_models.setHorizontalHeaderLabels(self.MODEL_COLUMNS)
        self.api_models.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.api_models.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.api_models.verticalHeader().setVisible(False)
        self.api_models.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.api_models.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.api_models.setMinimumHeight(200)
        self.api_models.itemChanged.connect(self.on_api_model_toggled)
        df.addRow(self.api_models)
        note = QLabel("هر چیزی که Provider گزارش نکرده «Unknown» یا «Not Available» نمایش داده می‌شود؛ هیچ عدد یا قابلیتی حدس زده نمی‌شود. "
                      "اولویت مدل‌ها همان ترتیب فهرست Route پایین صفحه است. بودن مدل در فهرست به معنی تضمین سهمیه نیست.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        df.addRow(note)
        self._api_loading = False
        self._api_worker = None
        return add_box, list_box, det_box

    def on_model_filter_changed(self, *_):
        self.settings["model_filter_mode"] = self.model_filter.currentData() or "all"
        self.save_now()
        self.refresh_unified_models()

    def _api_selected(self):
        row = self.api_table.currentRow()
        item = self.api_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _api_busy(self):
        worker = getattr(self, "_api_worker", None)
        if worker is not None and worker.isRunning():
            self.api_status.setText("صبر کن؛ عملیات قبلی هنوز تمام نشده است.")
            return True
        return False

    def _api_changed(self, select=None, refresh_details=True):
        """After any change: reset cooldowns (a fixed key gets another chance), save, redraw."""
        self.client.reset_cooldowns()
        self.save_now()
        self.refresh_api_table(select)
        if hasattr(self, "cloud_model_lists"):
            self.refresh_unified_models()
        self.refresh_route_list()
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def refresh_api_table(self, select=None):
        api_manager.ensure_registry(self.settings)
        keep = select or self._api_selected()
        rows = api_manager.api_rows(self.settings)
        self._api_loading = True
        self.api_table.blockSignals(True)
        self.api_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            service = "" if r["service"] in ("custom",) else f" · {r['service']}"
            cells = [f"{r['label']}  ({r['key']})" if r["key"] else r["label"], self.STATUS_FA.get(r["status"], r["status"]),
                     "Unknown" if r["accessible"] is None else str(r["accessible"]), str(r["active"]), api_manager.fmt_time(r["checked_at"]),
                     str(r["priority"]), "✓" if r["enabled"] else "—"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, r["id"])
                if c == 1 and r["error"]:
                    item.setToolTip(r["error"])
                self.api_table.setItem(i, c, item)
        self.api_table.blockSignals(False)
        self._api_loading = False
        target = next((i for i, r in enumerate(rows) if r["id"] == keep), 0 if rows else -1)
        if target >= 0:
            self.api_table.selectRow(target)
        self.show_api_details()

    def show_api_details(self):
        pid = self._api_selected()
        self._api_loading = True
        self.api_models.blockSignals(True)
        self.api_models.setRowCount(0)
        have = bool(pid) and pid in self.settings.get("providers", {})
        for key, btn in self.api_btns.items():
            btn.setEnabled(have or key == "details")
        if not have:
            self.api_det_info.setText("یک API را از فهرست بالا انتخاب کن.")
            self.api_models.blockSignals(False)
            self._api_loading = False
            return
        d = api_manager.api_details(self.settings, pid)
        rl = d["rate_limit"]
        rl_text = ("\n    " + "\n    ".join(f"{k}: {v}" for k, v in sorted(rl.items())) + f"\n    (زمان گزارش: {api_manager.fmt_time(d['rate_limit_as_of'])})") if rl else "Not Available"
        self.api_det_info.setText(
            f"Provider: {d['label']}  ·  سرویس: {d['service']}  ·  کلید: {d['key'] or '—'}\n"
            f"Status: {self.STATUS_FA.get(d['status'], d['status'])}  ·  آخرین بررسی: {api_manager.fmt_time(d['checked_at'])}"
            + (f"\nآخرین خطا: {d['error']}" if d["error"] else "") +
            f"\nToken Usage: Not Available  ·  Remaining Quota: Not Available\nRate Limit: {rl_text}")
        self.api_models.setRowCount(len(d["models"]))
        for i, m in enumerate(d["models"]):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if m["enabled"] else Qt.Unchecked)
            check.setData(Qt.UserRole, m["id"])
            self.api_models.setItem(i, 0, check)
            status = {"available": "✓ در دسترس", "unavailable": "✕ دیگر در دسترس نیست", "unknown": "Unknown (هنوز بررسی نشده)"}.get(m["status"], m["status"])
            cells = [m["id"], status, "Not Available" if m["context"] is None else f"{m['context']:,}",
                     "Not Available" if m["max_output"] is None else f"{m['max_output']:,}", m["text"], m["vision"], m["tools"],
                     "، ".join(m["also_on"]) if m["also_on"] else "—"]
            for c, text in enumerate(cells, start=1):
                self.api_models.setItem(i, c, QTableWidgetItem(text))
        self.api_models.blockSignals(False)
        self._api_loading = False

    def on_api_model_toggled(self, item):
        if self._api_loading or item.column() != 0:
            return
        pid = self._api_selected()
        if not pid:
            return
        try:
            api_manager.set_model_enabled(self.settings, pid, item.data(Qt.UserRole), item.checkState() == Qt.Checked)
        except ValueError as exc:
            self.api_status.setText("✕ " + str(exc))
        QTimer.singleShot(0, lambda p=pid: self._api_changed(p))          # redraw after this signal has finished (the table is rebuilt)

    # ---- Add ----
    # ---- Refresh / Rediscover ----

    def api_refresh(self, pid, quiet=False):
        if not pid or pid not in self.settings.get("providers", {}) or self._api_busy():
            return
        cfg = dict(self.settings["providers"][pid])
        self.api_status.setText("در حال اعتبارسنجی و دریافت دوباره‌ی مدل‌ها…")
        self._api_worker = TaskWorker(lambda: api_manager.rediscover(pid, cfg))
        self._api_worker.done.connect(lambda result, p=pid, q=quiet: self.on_api_refreshed(p, result, q))
        self._api_worker.start()

    def on_api_refreshed(self, pid, result, quiet=False):
        if pid not in self.settings.get("providers", {}):
            return
        ok, det = result
        label = route_model.provider_label(pid, self.settings["providers"][pid])
        if not ok:
            det = api_manager.Detection("error", "", str(det))
        if det.ok:
            diff = api_manager.apply_models(self.settings, pid, det.models, det.rate_limit)
            msg = f"✓ {label}: {len(det.models)} مدل در دسترس"
            if diff["new"]:
                msg += f" · {len(diff['new'])} مدل جدید"
            if diff["gone"]:
                msg += f" · {len(diff['gone'])} مدل دیگر در دسترس نیست"
            self.api_status.setText(msg)
        else:
            api_manager.apply_failure(self.settings, pid, det)
            self.api_status.setText(f"{label}: " + api_manager.describe_failure(det))
        self._api_changed(pid)

    # ---- Edit ----

    def api_edit(self, pid):
        if not pid or pid not in self.settings.get("providers", {}) or self._api_busy():
            return
        cfg = self.settings["providers"][pid]
        service = api_manager.service_of(pid, cfg)
        custom = pid not in route_model.BUILTIN
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit API")
        form = QFormLayout(dlg)
        name = QLineEdit(route_model.provider_label(pid, cfg))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText("کلید جدید (اختیاری) — خالی = کلید فعلی حفظ می‌شود")
        account = QLineEdit(str(cfg.get("account_id", "")))
        base = QLineEdit(str(cfg.get("base_url", "")))
        if custom:
            form.addRow("نام", name)
        form.addRow(f"API Key (فعلی: {api_manager.mask_key(cfg.get('api_key')) or '—'})", key)
        if service == "cloudflare":
            form.addRow("Account ID", account)
        if custom and service == "custom":
            form.addRow("Base URL", base)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() != QDialog.Accepted:
            return
        new_key = key.text().strip()
        fields = {"label": name.text() if custom else None, "account_id": (account.text() or None) if service == "cloudflare" else None,
                  "base_url": base.text() if (custom and service == "custom") else None}
        if not new_key:
            self.apply_api_edit(pid, fields, None, None)
            return
        problem = api_manager.key_problem(new_key)
        dup = api_manager.find_duplicate(self.settings, new_key)
        if problem or (dup and dup != pid):
            self.api_status.setText("✕ " + (problem or "این کلید قبلاً برای API دیگری ثبت شده است."))
            return
        test_cfg = {**cfg, "api_key": new_key}
        if fields["account_id"]:
            test_cfg["account_id"] = fields["account_id"].strip()
        self.api_status.setText("در حال اعتبارسنجی کلید جدید…")
        self._api_worker = TaskWorker(lambda: api_manager.rediscover(pid, test_cfg))
        self._api_worker.done.connect(lambda result, p=pid, f=fields, k=new_key: self.on_api_edit_validated(p, f, k, result))
        self._api_worker.start()

    def on_api_edit_validated(self, pid, fields, new_key, result):
        ok, det = result
        if not ok or not det.ok:                                  # the old key stays untouched
            self.api_status.setText("✕ کلید جدید ذخیره نشد. " + (api_manager.describe_failure(det) if ok else str(det)))
            return
        self.apply_api_edit(pid, fields, new_key, det)

    def apply_api_edit(self, pid, fields, new_key, det):
        try:
            route_model.update_provider(self.settings, pid, label=fields["label"], base_url=fields["base_url"],
                                        account_id=fields["account_id"], api_key=new_key)
        except ValueError as exc:
            self.api_status.setText("✕ " + str(exc))
            return
        if det is not None:
            api_manager.apply_models(self.settings, pid, det.models, det.rate_limit)
        route_model.ensure_routes(self.settings)
        self.api_status.setText("✓ تغییرات ذخیره شد." + (" کلید جدید معتبر بود و مدل‌ها دوباره خوانده شدند." if det is not None else ""))
        self._api_changed(pid)

    # ---- Enable / Disable, Delete, Priority ----

    def api_toggle(self, pid):
        if not pid or pid not in self.settings.get("providers", {}):
            return
        on = not bool(self.settings["providers"][pid].get("enabled"))
        api_manager.set_api_enabled(self.settings, pid, on)
        self.api_status.setText("✓ API فعال شد." if on else "API غیرفعال شد (کلید و مدل‌ها حفظ شدند).")
        self._api_changed(pid)

    def api_delete(self, pid):
        if not pid or pid not in self.settings.get("providers", {}):
            return
        cfg = self.settings["providers"][pid]
        n = sum(1 for r in route_model.get_routes(self.settings) if r["provider"] == pid)
        builtin_note = "\n(کلید پاک و Routeهای این API غیرفعال می‌شوند.)" if pid in route_model.BUILTIN else f"\n({n} Route آن هم حذف می‌شود.)"
        if QMessageBox.question(self, "حذف API", f"«{route_model.provider_label(pid, cfg)}» حذف شود؟{builtin_note}") != QMessageBox.Yes:
            return
        api_manager.delete_api(self.settings, pid)
        self.api_status.setText("✓ API حذف شد.")
        self._api_changed()

    def api_move(self, pid, delta):
        if not pid:
            return
        try:
            api_manager.move_api(self.settings, pid, delta)
        except KeyError:
            self.api_status.setText("این API هنوز Route ندارد؛ اول یک مدل برایش فعال کن.")
            return
        self._api_changed(pid)

    # ---------- Route Manager ----------
    HEALTH_TXT = {"unknown": "— بدون تست", "healthy": "● سالم", "degraded": "◐ مشکل موقت", "down": "✕ خراب"}

    def _selected_route_id(self):
        item = self.route_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    @front_only
    def refresh_route_list(self):
        if not hasattr(self, "route_list"):
            return
        keep = self._selected_route_id()
        status = {x["name"]: x for x in self.client.status()}
        manual, default = self.settings.get("manual_route_id", ""), self.settings.get("default_route_id", "")
        providers = self.settings.get("providers", {})
        self.route_list.blockSignals(True)
        self.route_list.clear()
        for i, r in enumerate(route_model.get_routes(self.settings)):
            st = status.get(r["id"], {})
            label = route_model.provider_label(r["provider"], providers.get(r["provider"]))
            icon = "☁" if st.get("kind", route_model.provider_kind(r["provider"], providers.get(r["provider"]))) == "cloud" else "⌂"
            marks = ("★ دستی  " if r["id"] == manual else "") + ("⚑ پیش‌فرض  " if r["id"] == default else "")
            health = self.HEALTH_TXT.get(st.get("health", "unknown"), "")
            extra = (f" {st['last_ms']}ms" if st.get("last_ms") is not None else "") + \
                    (f" · استراحت {st['cooldown']}s" if st.get("cooldown") else "")
            reason = "" if st.get("enabled") or st.get("cooldown") else {"disabled": " · غیرفعال", "no_key": " · بدون کلید",
                                                                          "provider_off": " · Provider غیرفعال"}.get(st.get("reason"), " · غیرفعال")
            item = QListWidgetItem(f"{i + 1}.  {icon} {label} / {r['model'] or '(بدون مدل)'}   {marks}{health}{extra}{reason}")
            item.setData(Qt.UserRole, r["id"])
            if reason:
                item.setForeground(QBrush(QColor("#8d93ab")))
            self.route_list.addItem(item)
        for i in range(self.route_list.count()):
            if self.route_list.item(i).data(Qt.UserRole) == keep:
                self.route_list.setCurrentRow(i)
                break
        else:
            if self.route_list.count():
                self.route_list.setCurrentRow(0)
        self.route_list.blockSignals(False)
        self.route_manual_lbl.setText("انتخاب دستی: " + (manual or "خودکار (بر اساس اولویت)") +
                                      ("" if self.settings.get("failover_enabled", True) else " · Failover خاموش است"))
        self.on_route_selected()

    def on_route_selected(self):
        rid = self._selected_route_id()
        route = route_model.find_route(self.settings, rid) if rid else None
        self._loading_route = True
        try:
            for w in (self.route_model_edit, self.route_enabled_chk, self.route_timeout, self.route_cooldown, self.route_ctx,
                      self.route_predict, self.route_test_btn, self.route_del_btn, self.route_default_btn, self.route_use_btn,
                      self.route_up_btn, self.route_down_btn, self.route_bench_btn):
                w.setEnabled(route is not None)
            if not route:
                self.route_provider_lbl.setText("-")
                self.route_status.setText("Route‌ای انتخاب نشده.")
                return
            cfg = self.settings.get("providers", {}).get(route["provider"], {})
            local = route_model.provider_kind(route["provider"], cfg) == "local"
            self.route_provider_lbl.setText(f"{route_model.provider_label(route['provider'], cfg)}  ({'Local' if local else 'Cloud'})  ·  {route['id']}")
            if route["provider"] == "ollama" and self._ollama_models:
                self.route_model_edit.set_models(self._ollama_models)
            self.route_model_edit.setText(route["model"])
            self.route_enabled_chk.setChecked(bool(route.get("enabled", True)))
            lo, hi = route_model.LOCAL_TIMEOUT if local else route_model.CLOUD_TIMEOUT
            self.route_timeout.setRange(lo, hi)
            self.route_timeout.setValue(int(route.get("timeout", 18)))
            self.route_cooldown.setValue(int(route.get("cooldown", 45)))
            is_ollama = route["provider"] == "ollama"
            self.route_ctx.setEnabled(is_ollama)
            self.route_predict.setEnabled(is_ollama)
            self.route_ctx.setValue(int(route.get("num_ctx", 0)))
            self.route_predict.setValue(int(route.get("num_predict", 0)))
            st = next((x for x in self.client.status() if x["name"] == rid), {})
            parts = [self.HEALTH_TXT.get(st.get("health", "unknown"), "")]
            if st.get("last_ms") is not None:
                parts.append(f"آخرین پاسخ {st['last_ms']} ms")
            if st.get("cooldown"):
                parts.append(f"استراحت {st['cooldown']}s")
            if st.get("last_error"):
                parts.append("آخرین خطا: " + st["last_error"])
            self.route_status.setText("  ·  ".join(p for p in parts if p))
        finally:
            self._loading_route = False

    def after_route_change(self, select=None):
        self.sync_ollama_primary()
        self.save_now()
        self.refresh_route_list()
        if select:
            for i in range(self.route_list.count()):
                if self.route_list.item(i).data(Qt.UserRole) == select:
                    self.route_list.setCurrentRow(i)
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def sync_ollama_primary(self):
        """Route 'ollama' is the model of the Assistant tab: keep the two in step both ways."""
        r = route_model.find_route(self.settings, "ollama")
        if r and r["model"] and r["model"] != self.settings.get("model"):
            self.settings["model"] = r["model"]
            self.settings.setdefault("providers", {}).setdefault("ollama", {})["model"] = r["model"]
            self.model.setText(r["model"])

    def route_edit_changed(self):
        if self._loading_route:
            return
        rid = self._selected_route_id()
        if not rid:
            return
        try:
            route_model.update_route(self.settings, rid, model=self.route_model_edit.text(), enabled=self.route_enabled_chk.isChecked(),
                                     timeout=self.route_timeout.value(), cooldown=self.route_cooldown.value(),
                                     num_ctx=self.route_ctx.value(), num_predict=self.route_predict.value())
        except ValueError as exc:
            self.route_status.setText("✕ " + str(exc))
            return
        self.client.reset_cooldowns(rid)
        self.after_route_change()

    def on_routes_reordered(self):
        """Drag & drop finished: the new visual order becomes the priority / failover order."""
        if self._loading_route:
            return
        ids = [self.route_list.item(i).data(Qt.UserRole) for i in range(self.route_list.count())]
        route_model.reorder(self.settings, ids)
        self.save_now()
        QTimer.singleShot(0, self.refresh_route_list)           # renumber labels after the drop has fully finished
        QTimer.singleShot(0, lambda: None if self.busy else self.set_badge("idle", self.client.preview_route()))

    def move_selected(self, delta):
        rid = self._selected_route_id()
        if not rid:
            return
        ids = [r["id"] for r in route_model.get_routes(self.settings)]
        route_model.move_route(self.settings, rid, ids.index(rid) + delta)
        self.after_route_change(select=rid)

    def default_selected_route(self):
        rid = self._selected_route_id()
        if rid:
            route_model.set_default(self.settings, rid)
            self.after_route_change(select=rid)

    def delete_selected_route(self):
        rid = self._selected_route_id()
        if not rid:
            return
        if QMessageBox.question(self, "حذف Route", "این Route حذف شود؟ (Provider و API Key آن دست‌نخورده می‌مانند.)") != QMessageBox.Yes:
            return
        route_model.remove_route(self.settings, rid)
        self.client.reset_cooldowns(rid)
        self.after_route_change()

    def on_failover_toggled(self, on):
        self.settings["failover_enabled"] = bool(on)
        self.save_now()
        self.refresh_route_list()

    def add_route_from_values(self, provider, model, enabled=True):
        try:
            route = route_model.add_route(self.settings, provider, model, enabled=enabled)
        except ValueError as exc:
            self.route_status.setText("✕ " + str(exc))
            return None
        self.after_route_change(select=route["id"])
        return route

    def add_route_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("افزودن Route")
        form = QFormLayout(dlg)
        prov = QComboBox()
        providers = self.settings.get("providers", {})
        for name in providers:
            prov.addItem(route_model.provider_label(name, providers[name]), name)
        model = ModelCombo("")
        def fill():
            if prov.currentData() == "ollama":
                model.set_models(self._ollama_models)
        prov.currentIndexChanged.connect(lambda *_: fill())
        form.addRow("Provider", prov)
        form.addRow("Model ID", model)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() == QDialog.Accepted:
            self.add_route_from_values(prov.currentData(), model.text())

    def add_provider_from_values(self, label, base_url, api_key="", local=False, first_model=""):
        try:
            pid = route_model.add_provider(self.settings, label, base_url, api_key, local)
            if first_model.strip():
                route_model.add_route(self.settings, pid, first_model)
        except ValueError as exc:
            self.route_status.setText("✕ " + str(exc))
            return None
        route_model.ensure_routes(self.settings)
        self.save_now()
        self.refresh_api_table(pid)
        self.refresh_route_list()
        return pid

    def add_provider_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("افزودن Provider")
        form = QFormLayout(dlg)
        name, url, key, model = QLineEdit(), QLineEdit("https://"), QLineEdit(), QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        local = QCheckBox("سرور محلی (بدون API Key، مثل LM Studio)")
        form.addRow("نام", name)
        form.addRow("Base URL (تا /v1)", url)
        form.addRow("API Key", key)
        form.addRow(local)
        form.addRow("اولین Model ID", model)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() == QDialog.Accepted:
            pid = self.add_provider_from_values(name.text(), url.text(), key.text(), local.isChecked(), model.text())
            if pid and key.text().strip():
                self.api_refresh(pid, quiet=True)

    def remove_provider_ui(self, pid):
        n = sum(1 for r in route_model.get_routes(self.settings) if r["provider"] == pid)
        if QMessageBox.question(self, "حذف Provider", f"این Provider و {n} Route آن حذف شوند؟") != QMessageBox.Yes:
            return
        route_model.remove_provider(self.settings, pid)
        api_manager.registry(self.settings).pop(pid, None)
        self.client.reset_cooldowns()
        self.save_now()
        self.refresh_api_table()
        self.refresh_route_list()

    def provider_changed(self):
        """Key / enable / URL edited in a provider box: autosave (an empty key field keeps the saved key)."""
        if getattr(self, "_loading_route", False) or not hasattr(self, "route_ollama_enabled"):
            return
        self.collect_provider_settings()
        self.client.reset_cooldowns()
        self.save_now()
        self.refresh_route_list()
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def test_selected_route(self):
        rid = self._selected_route_id()
        if not rid:
            return
        self.route_test_btn.setEnabled(False)
        self.route_status.setText("در حال تست…")
        self._route_worker = TaskWorker(lambda: self.client.test_route(rid))
        self._route_worker.done.connect(self.on_route_test_done)
        self._route_worker.start()

    def on_route_test_done(self, result):
        ok, value = result
        self.route_test_btn.setEnabled(True)
        self.refresh_route_list()
        if ok:
            good, msg, ms = value
            self.route_status.setText(("✓ " if good else "✕ ") + msg + (f"  ({ms} ms)" if ms is not None else ""))
        else:
            self.route_status.setText("✕ " + value)

    def scan_ollama(self):
        self.route_scan_btn.setEnabled(False)
        self.route_status.setText("در حال جست‌وجوی مدل‌های نصب‌شده‌ی Ollama…")
        client = OllamaClient.from_settings(self.settings)
        def task():
            ok, models = client.status()
            if not ok:
                raise RuntimeError(models)
            return models
        self._scan_worker = TaskWorker(task)
        self._scan_worker.done.connect(self.on_scan_done)
        self._scan_worker.start()

    def on_scan_done(self, result):
        ok, value = result
        self.route_scan_btn.setEnabled(True)
        if not ok:
            self.route_status.setText("✕ " + value)
            return
        self._ollama_models = list(value)
        self.model.set_models(value)
        added = route_model.add_ollama_models(self.settings, value)
        self.save_now()
        self.refresh_route_list()
        self.route_status.setText(f"✓ {len(value)} مدل نصب‌شده پیدا شد؛ {len(added)} Route جدید اضافه شد (به‌صورت غیرفعال تا خودت فعال کنی).")
        self.refresh_unified_models()

    def run_benchmark(self, all_enabled):
        if self.busy:
            self.route_status.setText("✕ یک پاسخ در حال تولید است؛ بعد از پایان آن Benchmark بگیر.")
            return
        if all_enabled:
            ids = [i["route_id"] for i in self.client.available_routes()]
        else:
            ids = [self._selected_route_id()] if self._selected_route_id() else []
        if not ids:
            self.route_status.setText("✕ Route فعالی برای Benchmark نیست.")
            return
        cloud = [i for i in ids if route_model.provider_kind((route_model.find_route(self.settings, i) or {}).get("provider", ""),
                 self.settings.get("providers", {}).get((route_model.find_route(self.settings, i) or {}).get("provider", ""))) == "cloud"]
        if cloud and QMessageBox.question(self, "Benchmark", f"{len(cloud)} Route ابری هرکدام یک درخواست کوتاه (حدود ۴۸ توکن) از سهمیه‌ی API مصرف می‌کند. ادامه بدهم؟\n"
                                                           "Routeها یکی‌یکی تست می‌شوند، نه هم‌زمان.") != QMessageBox.Yes:
            return
        self.busy = True
        self._bench_busy = True
        self.bench_out.setPlainText("در حال اجرا…")
        self._bench_lines = []
        self._bench_worker = BenchWorker(self.client, ids)
        self._bench_worker.progress.connect(self.on_bench_progress)
        self._bench_worker.done.connect(self.on_bench_done)
        self._bench_worker.start()

    def on_bench_progress(self, e):
        if e.get("phase") == "running":
            self.bench_out.setPlainText("\n".join(self._bench_lines + [f"… {e['label']} / {e['model']}"]))
        else:
            self._bench_lines.append(self.format_bench_row(e))
            self.bench_out.setPlainText("\n".join(self._bench_lines))

    @staticmethod
    def format_bench_row(r):
        fmt = lambda v: "-" if v is None else f"{v}"                              # noqa: E731
        if not r.get("ok"):
            return f"✕ {r['label']} / {r['model']}: {r.get('error') or 'ناموفق'}"
        return (f"✓ {r['label']} / {r['model']} [{'Local' if r['kind'] == 'local' else 'Cloud'}]  connect {fmt(r['connect_ms'])} ms · "
                f"first token {fmt(r['first_token_ms'])} ms · total {fmt(r['total_ms'])} ms · {fmt(r['speed'])} {r['unit']}"
                + (f" · load {r['load_ms']} ms" if r.get("load_ms") else "")
                + (f" · {r['model_gb']}GB, GPU {r['gpu_pct']}%" if r.get("gpu_pct") is not None else ""))

    def on_bench_done(self, result):
        self.busy = False
        self._speech_live = False
        self._bench_busy = False
        ok, value = result
        if not ok:
            self.bench_out.setPlainText("✕ " + value)
        else:
            ranked = sorted([r for r in value if r["ok"] and r["first_token_ms"] is not None], key=lambda r: r["first_token_ms"])
            lines = [self.format_bench_row(r) for r in value]
            if ranked:
                lines.append(f"\nسریع‌ترین اولین Token: {ranked[0]['label']} / {ranked[0]['model']} ({ranked[0]['first_token_ms']} ms)")
            self.bench_out.setPlainText("\n".join(lines))
        self.refresh_route_list()
        self._send_next_pending()

    # ---------- settings ----------
    # ---- Windows 11 glass ----
