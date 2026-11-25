"""Provider settings feature controller."""
import copy
import logging
import re
import time

from PySide6.QtCore import Slot

from .. import api_manager
from .. import model_catalog
from .. import routes as route_model
from ..settings_schema import DEFAULTS as SETTINGS_DEFAULTS
_log = logging.getLogger(__name__)


from .main_window_provider_settings_support import (
    ApiPanel,
    ModelsPanel,
    BenchWorker,
    ModelCombo,
    OllamaProviderPanel,
    QAbstractItemView,
    QBrush,
    QCheckBox,
    QColor,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    Qt,
    RouteEditor,
    TaskWorker,
    front_only,
)

from .window_feature_controller import WindowFeatureController
from .components.switch_checkbox import SwitchCheckBox


class ProviderSettingsController(WindowFeatureController):
    def refresh_model_catalogs(self):
        if self.context.state._closing:
            return
        worker = self.context.resource("_model_catalog_worker")
        if worker is not None and worker.isRunning():
            return
        self.models_panel.refresh_btn.setEnabled(False)
        self.models_panel.status.setText("در حال بررسی APIها و دریافت مدل‌های تازه…")
        try:
            providers = [
                (pid, dict(self.context.services.settings.get("providers", {}).get(pid, {})))
                for pid in self.context.services.provider_application_service.api_ids(self.context.services.settings)
                if self.context.services.settings.get("providers", {}).get(pid, {}).get("enabled", True)
            ]

            def refresh():
                results = []
                for pid, cfg in providers:
                    results.append((pid, self.context.services.provider_application_service.rediscover(pid, cfg, timeout=15)))
                return results

            worker = TaskWorker(refresh)
            self.context.state._model_catalog_worker = worker
            worker.done.connect(self._on_model_catalog_refresh)
            worker.finished.connect(self._clear_model_catalog_worker)
            worker.start()
            self.scan_ollama()
            self.feature_controller("voice_settings").refresh_local_voice_status()
        except Exception as exc:
            self.models_panel.refresh_btn.setEnabled(True)
            self.models_panel.status.setText("تازه‌سازی کامل نشد: " + str(exc)[:200])

    @Slot()
    def _clear_model_catalog_worker(self):
        worker = self.sender()
        if self.context.state._model_catalog_worker is worker:
            self.context.state._model_catalog_worker = None
        if worker is not None:
            worker.deleteLater()

    @Slot(object)
    def _on_model_catalog_refresh(self, result):
        worker = self.sender()
        if (
            worker is None
            or self.context.state._model_catalog_worker is not worker
            or self.context.state._closing
        ):
            return
        self.models_panel.refresh_btn.setEnabled(True)
        ok, value = result
        if not ok:
            self.models_panel.status.setText("دریافت مدل‌های API ناموفق بود: " + str(value)[:200])
            return
        updated = 0
        removed_routes = 0
        disabled_routes = 0
        failed = []
        settings = self.context.services.settings
        for pid, detection in value:
            if detection.ok and detection.models:
                self.context.services.provider_application_service.apply_models(settings, pid, detection.models, detection.rate_limit)
                service = self.context.services.provider_application_service
                free = route_model.catalog_free(detection.models)
                prefer = api_manager.SERVICES.get(service.service_of(pid, settings.get("providers", {}).get(pid)), {}).get("default_models", ())
                removed_routes += len(route_model.reconcile_provider_models(
                    settings, pid, route_model.catalog_ids(detection.models), free=free, prefer=prefer,
                    capabilities=self.context.services.provider_application_service.detected_capabilities))
                disabled_routes += len(route_model.disable_non_free_routes(
                    settings, pid, free,
                    capabilities=self.context.services.provider_application_service.detected_capabilities,
                ))
                updated += len(detection.models)
            elif detection.ok:
                # An empty discovery response is not reliable evidence that every old model was deleted.
                failed.append(pid + " (فهرست خالی؛ اطلاعات قبلی حفظ شد)")
            else:
                self.context.services.provider_application_service.apply_failure(settings, pid, detection)
                failed.append(pid)
        if updated:
            self.context.services.provider_application_service.set_model_catalog_refreshed_at(int(time.time()))
        self.feature_controller("runtime").save_now()
        self.refresh_unified_models()
        self.refresh_api_table()
        self.refresh_route_list()
        suffix = ("؛ خطا در " + "، ".join(failed)) if failed else ""
        removed_suffix = f"؛ {removed_routes} مسیر مدل منسوخ حذف/جایگزین شد" if removed_routes else ""
        disabled_suffix = f"؛ {disabled_routes} مسیر غیررایگان غیرفعال شد" if disabled_routes else ""
        self.models_panel.status.setText(
            f"مدل‌های API تازه‌سازی شد: {updated} مدل از {len(value)} اتصال{removed_suffix}{disabled_suffix}{suffix}.")

    CATALOG_MAX_AGE_SECONDS = 12 * 3600

    def auto_refresh_model_catalogs(self):
        """Startup hook: refresh the model catalogs in the background when the last refresh is older than 12 hours."""
        if self.context.state._closing:
            return
        settings = self.context.services.settings
        # Ollama is a local daemon, not part of the cloud API catalogue TTL.
        # Scan it on every startup so installed local models are always selectable,
        # even when cloud model metadata is still fresh.
        self.scan_ollama()
        if time.time() - self.context.services.provider_application_service.model_catalog_refreshed_at < self.CATALOG_MAX_AGE_SECONDS:
            return
        self.refresh_model_catalogs()

    def build_ai_tab(self):
        """Unified cloud/local model catalogue with advanced route and provider controls."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        # This panel validates Chat-model access; a registered Google key is also selectable by the separate Gemini Live audio transport.
        layout.addWidget(self.build_api_boxes())

        import_row = QHBoxLayout()
        self.context.views.import_model_btn = QPushButton("＋ معرفی مدل از فایل یا پوشه‌ی سیستم")
        self.context.views.import_model_btn.setToolTip("فایل GGUF برای Chat، مدل شنوا برای STT یا Piper ONNX برای TTS")
        self.context.views.import_model_btn.clicked.connect(self.feature_controller("voice_settings").import_local_model)
        import_row.addWidget(self.context.views.import_model_btn)
        import_row.addStretch(1)
        layout.addLayout(import_row)

        self.feature_controller("character_settings").build_mcp_registry_group(layout)
        self.models_panel = ModelsPanel(self.window)
        self.models_panel.refresh_requested.connect(self.refresh_model_catalogs)
        self.models_panel.toggle_requested.connect(self.on_model_toggle)
        self.models_panel.test_requested.connect(self.test_catalog_model)
        self.models_panel.archive_requested.connect(self.on_model_archive)
        self.models_panel.restore_requested.connect(self.on_model_restore)
        layout.addWidget(self.models_panel)

        assistant_page = getattr(self.context.views, "assistant_page", None)
        if assistant_page is not None:
            layout.addWidget(assistant_page.model_box)        # local Ollama model settings (formerly in the Assistant tab)

        # Advanced controls remain available but are collapsed by default.
        self.connections_advanced_btn = QToolButton()
        self.connections_advanced_btn.setText("تنظیمات پیشرفته و مدیریت Providerها")
        self.connections_advanced_btn.setCheckable(True)
        self.connections_advanced_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.connections_advanced_btn.setArrowType(Qt.RightArrow)
        self.connections_advanced_body = QWidget()
        advanced_layout = QVBoxLayout(self.connections_advanced_body)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        # RouteEditor owns route/failover controls; MainWindow only handles intents.
        self.route_editor = RouteEditor(
            self.context.services.settings,
            model_combo_factory=ModelCombo,
            parent=self.window,
        )
        for name in (
            "route_list", "route_manual_lbl", "failover_chk",
            "route_add_btn", "route_del_btn",
            "route_use_btn", "route_auto_btn", "route_provider_lbl", "route_model_edit",
            "route_enabled_chk", "route_timeout", "route_cooldown", "route_ctx",
            "route_predict", "route_status", "route_test_btn", "route_bench_btn",
            "bench_out",
        ):
            setattr(self.context.views, name, getattr(self.route_editor, name))

        self.route_editor.selection_changed.connect(self.on_route_selected)
        self.route_editor.order_changed.connect(self.on_routes_reordered)
        self.route_editor.failover_changed.connect(self.on_failover_toggled)
        self.route_editor.add_requested.connect(self.add_route_dialog)
        self.route_editor.delete_requested.connect(self.delete_selected_route)
        self.route_editor.select_manual_requested.connect(
            lambda: self.feature_controller("runtime").select_route(self._selected_route_id() or "")
        )
        self.route_editor.select_auto_requested.connect(lambda: self.feature_controller("runtime").select_route(""))
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
        self.context.views.tabs.addTab(scroll, "")
        self.refresh_route_list()
        self.refresh_api_table()
        self.refresh_unified_models()
        self.feature_controller("voice_settings").refresh_local_voice_status()

    def refresh_unified_models(self):
        """Populate the three cloud capability lists and the three local model lists."""
        if hasattr(self, "models_panel"):
            service = self.context.services.provider_application_service
            service.ensure_registry(self.context.services.settings)
            rows = model_catalog.model_rows(
                self.context.services.settings, capabilities=service.detected_capabilities
            )
            self.models_panel.set_rows(rows, model_catalog.tab_counts(rows))
            for key in getattr(self, "_model_test_workers", {}):
                self.models_panel.set_testing(*key, True)

        if "local_model_list" in self.context.views:
            self.context.views.local_model_list.blockSignals(True)
            self.context.views.local_model_list.clear()
            for route in self.context.services.provider_application_service.get_routes(self.context.services.settings):
                if route.get("provider") != "ollama" or not route.get("model"):
                    continue
                item = QListWidgetItem(route["model"])
                item.setData(Qt.UserRole, route.get("id"))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if route.get("enabled") else Qt.Unchecked)
                self.context.views.local_model_list.addItem(item)
            self.context.views.local_model_list.blockSignals(False)

    # ---------- models box ----------
    def _after_model_change(self, provider=None):
        QTimer.singleShot(0, lambda: self._api_changed(provider))          # redraw after the emitting widget's signal has finished

    def on_model_toggle(self, provider, model, on):
        try:
            self.context.services.provider_application_service.set_model_enabled(self.context.services.settings, provider, model, bool(on))
        except Exception as exc:                                            # noqa: BLE001
            self.models_panel.status.setText("✕ " + str(exc))
        self._after_model_change(provider)

    def on_model_archive(self, provider, model):
        model_catalog.archive_model(self.context.services.settings, provider, model)
        self.models_panel.status.setText(f"{model} به «منسوخ / غیرفعال» منتقل و خاموش شد.")
        self._after_model_change(provider)

    def on_model_restore(self, provider, model):
        model_catalog.restore_model(
            self.context.services.settings, provider, model,
            capabilities=self.context.services.provider_application_service.detected_capabilities,
        )
        self.models_panel.status.setText(f"{model} بازگردانده شد؛ برای استفاده، کلید روشن/خاموش آن را روشن کن.")
        self._after_model_change(provider)

    def test_catalog_model(self, provider, model):
        """One tiny real request to ONE model (the same probe as the Route test). Uses a throw-away copy of the settings."""
        key = (provider, model)
        workers = self.__dict__.setdefault("_model_test_workers", {})
        if key in workers or self.context.state._closing:
            return
        settings = copy.deepcopy(self.context.services.settings)
        service = self.context.services.provider_application_service
        service.ensure_registry(settings)
        existing = next((r for r in service.get_routes(settings) if r.get("provider") == provider and r.get("model") == model), None)
        route = existing or service.add_route(settings, provider, model, enabled=False)
        try:
            router = service.create_router(settings)
        except Exception as exc:                                            # noqa: BLE001
            self.models_panel.status.setText("ساخت موتور تست ناموفق بود: " + str(exc)[:240])
            return
        rid = route["id"]
        worker = TaskWorker(lambda: router.test_route(rid))
        worker._model_key = key
        worker._model_test_terminal = False
        workers[key] = worker
        worker.done.connect(self._on_model_test_done)
        worker.finished.connect(self._clear_model_test_worker)
        self.models_panel.set_testing(provider, model, True)
        self.models_panel.status.setText(f"در حال تست {model} (یک درخواست خیلی کوتاه)…")
        worker.start()

    @Slot(object)
    def _on_model_test_done(self, result):
        worker = self.sender()
        key = getattr(worker, "_model_key", None)
        if key is None or self.context.state._closing:
            return
        try:
            ok, value = result
            if ok:
                good, message, ms = value
            else:
                good, message, ms = False, str(value), None
        except Exception as exc:  # noqa: BLE001 - malformed worker result must still release the indicator
            good, message, ms = False, f"نتیجهٔ تست قابل‌خواندن نبود: {type(exc).__name__}", None
        worker._model_test_terminal = True
        try:
            model_catalog.record_test(self.context.services.settings, key[0], key[1], good, ms, message, capabilities=self.context.services.provider_application_service.detected_capabilities)
            self.feature_controller("runtime").save_now()
            self.models_panel.status.setText(
                (f"✓ {key[1]}: سالم ({ms} ms)" if good else f"✕ {key[1]}: {message[:240]}")
            )
        except Exception as exc:  # noqa: BLE001 - a UI/persistence error must not leave the spinner active
            self.models_panel.status.setText(f"✕ ثبت نتیجهٔ تست {key[1]} ناموفق بود: {str(exc)[:180]}")
        finally:
            self.__dict__.get("_model_test_workers", {}).pop(key, None)
            try:
                self.models_panel.set_testing(key[0], key[1], False)
                self.refresh_unified_models()
            except Exception:  # noqa: BLE001 - keep the model-test worker lifecycle recoverable
                _log.exception("Could not reset the model test indicator for %s", key[1])

    @Slot()
    def _clear_model_test_worker(self):
        worker = self.sender()
        key = getattr(worker, "_model_key", None)
        self.__dict__.get("_model_test_workers", {}).pop(key, None)
        if key is not None and worker is not None and not getattr(worker, "_model_test_terminal", False):
            if not self.context.state._closing:
                try:
                    model_catalog.record_test(
                        self.context.services.settings, key[0], key[1], False, None,
                        "تست پیش از دریافت نتیجه متوقف شد."
                    )
                    self.feature_controller("runtime").save_now()
                    self.models_panel.status.setText(
                        f"✕ تست {key[1]} بدون دریافت نتیجه متوقف شد."
                    )
                    self.models_panel.set_testing(key[0], key[1], False)
                    self.refresh_unified_models()
                except Exception:  # noqa: BLE001
                    _log.exception("Could not recover an unfinished model test for %s", key[1])
                    try:
                        self.models_panel.set_testing(key[0], key[1], False)
                    except Exception:
                        pass
        if worker is not None:
            worker.deleteLater()

    def on_local_chat_item_changed(self, item):
        route_id = item.data(Qt.UserRole)
        if not route_id:
            return
        self.context.services.provider_application_service.update_route(self.context.services.settings, route_id, enabled=item.checkState() == Qt.Checked)
        self.feature_controller("runtime").save_now()
        self.refresh_route_list()
        self.refresh_unified_models()

    def _discover_unified_api_key(self, key, account=""):
        """Detect Chat model capability; Gemini Live reuses the Google key through its dedicated audio transport."""
        return self.context.services.provider_application_service.detect(key, account=account)

    def api_add(self):
        if self._api_busy():
            return
        key = self.api_key_edit.text().strip()
        problem = self.context.services.provider_application_service.key_problem(key)
        if problem:
            self.context.views.api_add_status.setText("✕ " + problem)
            return
        self.api_add_btn.setEnabled(False)
        self.context.views.api_add_status.setText("در حال شناسایی مدل‌های Chat از API…")
        worker = TaskWorker(lambda: self._discover_unified_api_key(key))
        self._start_api_worker(worker, lambda result: self.on_api_detected(result, key))

    def on_api_detected(self, result, key, account=""):
        self.api_add_btn.setEnabled(True)
        ok, detection = result
        if not ok:
            self.context.views.api_add_status.setText("✕ " + str(detection))
            return
        if detection and detection.state == "needs_account" and not account:
            account_id, accepted = QInputDialog.getText(self.window, "Cloudflare", "Account ID:")
            if accepted and account_id.strip():
                self.api_add_btn.setEnabled(False)
                self.context.views.api_add_status.setText("در حال تکمیل شناسایی Cloudflare…")
                account = account_id.strip()
                worker = TaskWorker(lambda: self._discover_unified_api_key(key, account))
                self._start_api_worker(worker, lambda res: self.on_api_detected(res, key, account))
            return

        chat_added = ""
        if detection and detection.ok:
            duplicate = self.context.services.provider_application_service.find_duplicate(self.context.services.settings, key)
            if not duplicate:
                try:
                    chat_added = self.context.services.provider_application_service.register(self.context.services.settings, detection, key)
                except ValueError as exc:
                    self.context.views.api_add_status.setText("✕ " + str(exc))
            else:
                chat_added = duplicate
        if chat_added:
            self._api_changed(chat_added)
            self.api_key_edit.clear()
            label = self.context.services.provider_application_service.provider_label(chat_added, self.context.services.settings["providers"][chat_added])
            self.context.views.api_add_status.setText("✓ اتصال Chat ثبت شد: " + label)
        else:
            message = self.context.services.provider_application_service.describe_failure(detection) if detection else "هیچ مدل Chat قابل استفاده‌ای از این API شناسایی نشد."
            self.context.views.api_add_status.setText("✕ " + message + "؛ کلید ثبت نشد.")
        self.refresh_unified_models()

    def build_local_model_group(self):
        """Backwards-compatible name for the Route local-provider group."""
        return self.build_ollama_group()

    def build_ollama_group(self):
        """Host the Ollama settings widget and delegate its intents to the app controller."""
        self.ollama_panel = OllamaProviderPanel(self.context.services.settings, parent=self.window)
        self.context.views.route_ollama_enabled = self.ollama_panel.enabled
        self.ollama_url_edit = self.ollama_panel.url_edit
        self.ollama_edit_btn = self.ollama_panel.edit_btn
        self.ollama_save_btn = self.ollama_panel.save_btn
        self.ollama_cancel_btn = self.ollama_panel.cancel_btn
        self.ollama_panel.enabled_changed.connect(lambda *_: self.provider_changed())
        self.ollama_panel.cancel_requested.connect(lambda: self.ollama_edit_mode(False))
        self.ollama_panel.save_requested.connect(self.save_ollama_edit)
        return self.ollama_panel

    def collect_provider_settings(self):
        """Apply the local Provider master switch through the Route model's consistency rules."""
        route_model.set_provider_enabled(
            self.context.services.settings,
            "ollama",
            self.context.views.route_ollama_enabled.isChecked(),
        )
        self.context.services.provider_application_service.ensure_routes(self.context.services.settings)

    def ollama_edit_mode(self, on):
        self.ollama_panel.set_edit_mode(bool(on), self.context.services.settings.get("ollama_url") if not on else None)

    def save_ollama_edit(self):
        try:
            url = self.context.services.provider_application_service.update_ollama_url(
                self.context.services.settings, self.ollama_url_edit.text()
            )
        except ValueError as exc:
            self.context.views.route_status.setText("✕ " + str(exc))
            return
        self.context.views.url.setText(url)                                # same address as the Assistant tab
        self.feature_controller("runtime").save_now()
        self.ollama_edit_mode(False)
        self.context.views.route_status.setText("✓ آدرس Ollama ذخیره شد.")

    # ---------- API Manager ----------
    API_COLUMNS = ["Provider", "API Status", "مدل‌های قابل‌دسترسی", "مدل‌های فعال", "آخرین اعتبارسنجی", "اولویت", "فعال"]
    MODEL_COLUMNS = ["فعال", "Model ID", "Status", "Context Window", "Max Output", "Text", "Vision", "Tool Calling", "روی API دیگر هم"]
    STATUS_FA = {"valid": "✓ معتبر", "invalid": "✕ نامعتبر", "error": "⚠ خطا (بعداً دوباره امتحان کن)", "disabled": "غیرفعال",
                 "no key": "بدون کلید", "not validated yet": "هنوز اعتبارسنجی نشده"}

    def build_api_boxes(self):
        """The "API" box: key entry + registered APIs (refresh / delete per row)."""
        self.api_panel = ApiPanel(self.window)
        self.api_key_edit = self.api_panel.key_edit
        self.api_account_edit = self.api_panel.account_edit
        self.api_add_btn = self.api_panel.add_btn
        self.api_table = self.api_panel.table
        self.api_status = self.api_panel.status
        self.context.views.api_add_status = self.api_panel.status
        self.api_panel.add_requested.connect(self.api_add)
        self.api_panel.refresh_requested.connect(lambda pid: self.api_refresh(pid))
        self.api_panel.delete_requested.connect(lambda pid: QTimer.singleShot(0, lambda: self.api_delete(pid)))
        self.api_panel.edit_requested.connect(lambda pid: self.api_edit(pid))
        self.api_panel.custom_requested.connect(self.add_provider_dialog)
        self._api_loading = False
        self.context.state._api_worker = None
        return self.api_panel

    def _api_selected(self):
        return self.api_panel.selected_id() or None

    def _start_api_worker(self, worker, callback):
        """Deliver TaskWorker results through a QObject slot on the GUI thread."""
        self.context.state._api_worker = worker
        worker._ui_done_callback = callback
        worker.done.connect(self._relay_api_worker_done)
        worker.finished.connect(self._clear_api_worker)
        worker.start()

    @Slot(object)
    def _relay_api_worker_done(self, result):
        worker = self.sender()
        callback = getattr(worker, "_ui_done_callback", None) if worker is not None else None
        if (
            callback is not None
            and self.context.state._api_worker is worker
            and not self.context.state._closing
        ):
            callback(result)

    @Slot()
    def _clear_api_worker(self):
        worker = self.sender()
        if self.context.state._api_worker is worker:
            self.context.state._api_worker = None
        if worker is not None:
            worker.deleteLater()

    def _api_busy(self):
        worker = getattr(self.context.state, "_api_worker", None)
        if worker is not None and worker.isRunning():
            self.api_status.setText("صبر کن؛ عملیات قبلی هنوز تمام نشده است.")
            return True
        return False

    def _api_changed(self, select=None, refresh_details=True):
        """After any change: reset cooldowns (a fixed key gets another chance), save, redraw."""
        self.context.session.client.reset_cooldowns()
        self.feature_controller("runtime").save_now()
        self.refresh_api_table(select)
        self.refresh_unified_models()
        self.refresh_route_list()
        self.feature_controller("voice_settings").refresh_gemini_providers()
        if not self.context.session.busy:
            self.feature_controller("runtime").set_badge("idle", self.context.session.client.preview_route())

    def refresh_api_table(self, select=None):
        service = self.context.services.provider_application_service
        service.ensure_registry(self.context.services.settings)
        rows = service.api_rows(self.context.services.settings)
        self.api_panel.set_rows(rows, status_text=lambda code: self.STATUS_FA.get(code, code),
                                time_text=service.fmt_time, select=select or "")

    # ---- Add ----
    # ---- Refresh / Rediscover ----

    def api_refresh(self, pid, quiet=False):
        if not pid or pid not in self.context.services.settings.get("providers", {}) or self._api_busy():
            return
        cfg = dict(self.context.services.settings["providers"][pid])
        self.api_status.setText("در حال اعتبارسنجی و دریافت دوباره‌ی مدل‌ها…")
        worker = TaskWorker(lambda: self.context.services.provider_application_service.rediscover(pid, cfg))
        self._start_api_worker(worker, lambda result: self.on_api_refreshed(pid, result, quiet))

    def on_api_refreshed(self, pid, result, quiet=False):
        if pid not in self.context.services.settings.get("providers", {}):
            return
        ok, det = result
        label = self.context.services.provider_application_service.provider_label(pid, self.context.services.settings["providers"][pid])
        if not ok:
            det = self.context.services.provider_application_service.Detection("error", "", str(det))
        if det.ok:
            diff = self.context.services.provider_application_service.apply_models(self.context.services.settings, pid, det.models, det.rate_limit)
            msg = f"✓ {label}: {len(det.models)} مدل در دسترس"
            if diff["new"]:
                msg += f" · {len(diff['new'])} مدل جدید"
            if diff["gone"]:
                msg += f" · {len(diff['gone'])} مدل دیگر در دسترس نیست"
            self.api_status.setText(msg)
        else:
            self.context.services.provider_application_service.apply_failure(self.context.services.settings, pid, det)
            self.api_status.setText(f"{label}: " + self.context.services.provider_application_service.describe_failure(det))
        self._api_changed(pid)

    # ---- Edit ----

    def api_edit(self, pid):
        if not pid or pid not in self.context.services.settings.get("providers", {}) or self._api_busy():
            return
        cfg = self.context.services.settings["providers"][pid]
        service = self.context.services.provider_application_service.service_of(pid, cfg)
        custom = pid not in self.context.services.provider_application_service.BUILTIN
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Edit API")
        form = QFormLayout(dlg)
        name = QLineEdit(self.context.services.provider_application_service.provider_label(pid, cfg))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText("کلید جدید (اختیاری) — خالی = کلید فعلی حفظ می‌شود")
        account = QLineEdit(str(cfg.get("account_id", "")))
        base = QLineEdit(str(cfg.get("base_url", "")))
        quota_scope = QLineEdit(str(cfg.get("quota_scope", "")))
        quota_scope.setPlaceholderText("برای کلیدهای یک پروژه، مقدار یکسان وارد کن")
        is_google = route_model.is_google(pid, cfg)
        if custom:
            form.addRow("نام", name)
        form.addRow(f"API Key (فعلی: {self.context.services.provider_application_service.mask_key(cfg.get('api_key')) or '—'})", key)
        if is_google:
            form.addRow("گروه سهمیهٔ پروژهٔ Google", quota_scope)
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
                  "base_url": base.text() if (custom and service == "custom") else None,
                  "quota_scope": quota_scope.text() if is_google else None}
        if not new_key:
            self.apply_api_edit(pid, fields, None, None)
            return
        problem = self.context.services.provider_application_service.key_problem(new_key)
        dup = self.context.services.provider_application_service.find_duplicate(self.context.services.settings, new_key)
        if problem or (dup and dup != pid):
            self.api_status.setText("✕ " + (problem or "این کلید قبلاً برای API دیگری ثبت شده است."))
            return
        test_cfg = {**cfg, "api_key": new_key}
        if fields["account_id"]:
            test_cfg["account_id"] = fields["account_id"].strip()
        self.api_status.setText("در حال اعتبارسنجی کلید جدید…")
        worker = TaskWorker(lambda: self.context.services.provider_application_service.rediscover(pid, test_cfg))
        self._start_api_worker(
            worker, lambda result: self.on_api_edit_validated(pid, fields, new_key, result)
        )

    def on_api_edit_validated(self, pid, fields, new_key, result):
        ok, det = result
        if not ok or not det.ok:                                  # the old key stays untouched
            self.api_status.setText("✕ کلید جدید ذخیره نشد. " + (self.context.services.provider_application_service.describe_failure(det) if ok else str(det)))
            return
        self.apply_api_edit(pid, fields, new_key, det)

    def apply_api_edit(self, pid, fields, new_key, det):
        try:
            self.context.services.provider_application_service.update_provider(self.context.services.settings, pid, label=fields["label"], base_url=fields["base_url"],
                                        account_id=fields["account_id"], api_key=new_key, quota_scope=fields["quota_scope"])
        except ValueError as exc:
            self.api_status.setText("✕ " + str(exc))
            return
        if det is not None:
            self.context.services.provider_application_service.apply_models(self.context.services.settings, pid, det.models, det.rate_limit)
        self.context.services.provider_application_service.ensure_routes(self.context.services.settings)
        self.api_status.setText("✓ تغییرات ذخیره شد." + (" کلید جدید معتبر بود و مدل‌ها دوباره خوانده شدند." if det is not None else ""))
        self._api_changed(pid)

    # ---- Enable / Disable, Delete, Priority ----

    def api_toggle(self, pid):
        if not pid or pid not in self.context.services.settings.get("providers", {}):
            return
        on = not bool(self.context.services.settings["providers"][pid].get("enabled"))
        self.context.services.provider_application_service.set_api_enabled(self.context.services.settings, pid, on)
        self.api_status.setText("✓ API فعال شد." if on else "API غیرفعال شد (کلید و مدل‌ها حفظ شدند).")
        self._api_changed(pid)

    def api_delete(self, pid):
        if not pid or pid not in self.context.services.settings.get("providers", {}):
            return
        cfg = self.context.services.settings["providers"][pid]
        n = sum(1 for r in self.context.services.provider_application_service.get_routes(self.context.services.settings) if r["provider"] == pid)
        builtin_note = "\n(کلید پاک و Routeهای این API غیرفعال می‌شوند.)" if pid in self.context.services.provider_application_service.BUILTIN else f"\n({n} Route آن هم حذف می‌شود.)"
        if QMessageBox.question(self.window, "حذف API", f"«{self.context.services.provider_application_service.provider_label(pid, cfg)}» حذف شود؟{builtin_note}") != QMessageBox.Yes:
            return
        self.context.services.provider_application_service.delete_api(self.context.services.settings, pid)
        model_catalog.forget_provider(self.context.services.settings, pid, capabilities=self.context.services.provider_application_service.detected_capabilities)
        self.api_status.setText("✓ API حذف شد.")
        self._api_changed()

    def api_move(self, pid, delta):
        if not pid:
            return
        try:
            self.context.services.provider_application_service.move_api(self.context.services.settings, pid, delta)
        except KeyError:
            self.api_status.setText("این API هنوز Route ندارد؛ اول یک مدل برایش فعال کن.")
            return
        self._api_changed(pid)

    # ---------- Route Manager ----------
    HEALTH_TXT = {"unknown": "— بدون تست", "healthy": "● سالم", "degraded": "◐ مشکل موقت", "down": "✕ خراب", "disabled": "⏸ خاموش‌شده"}

    def _selected_route_id(self):
        item = self.context.views.route_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    @front_only
    def refresh_route_list(self):
        if not hasattr(self.context.views, "route_list"):
            return
        keep = self._selected_route_id()
        status = {x["name"]: x for x in self.context.session.client.status()}
        manual, default = self.context.services.settings.get("manual_route_id", ""), self.context.services.settings.get("default_route_id", "")
        providers = self.context.services.settings.get("providers", {})
        self.context.views.route_list.blockSignals(True)
        self.context.views.route_list.clear()
        for i, r in enumerate(self.context.services.provider_application_service.get_routes(self.context.services.settings)):
            st = status.get(r["id"], {})
            label = self.context.services.provider_application_service.provider_label(r["provider"], providers.get(r["provider"]))
            icon = "☁" if st.get("kind", self.context.services.provider_application_service.provider_kind(r["provider"], providers.get(r["provider"]))) == "cloud" else "⌂"
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
            self.context.views.route_list.addItem(item)
        for i in range(self.context.views.route_list.count()):
            if self.context.views.route_list.item(i).data(Qt.UserRole) == keep:
                self.context.views.route_list.setCurrentRow(i)
                break
        else:
            if self.context.views.route_list.count():
                self.context.views.route_list.setCurrentRow(0)
        self.context.views.route_list.blockSignals(False)
        self.context.views.route_manual_lbl.setText("انتخاب دستی: " + (manual or "خودکار (بر اساس اولویت)") +
                                      ("" if self.context.services.settings.get("failover_enabled", SETTINGS_DEFAULTS["failover_enabled"]) else " · Failover خاموش است"))
        self.on_route_selected()

    def on_route_selected(self):
        rid = self._selected_route_id()
        route = self.context.services.provider_application_service.find_route(self.context.services.settings, rid) if rid else None
        self.context.state._loading_route = True
        try:
            for w in (self.context.views.route_model_edit, self.context.views.route_enabled_chk, self.context.views.route_timeout, self.context.views.route_cooldown, self.context.views.route_ctx,
                      self.context.views.route_predict, self.context.views.route_test_btn, self.context.views.route_del_btn, self.context.views.route_use_btn,
                      self.context.views.route_bench_btn):
                w.setEnabled(route is not None)
            if not route:
                self.context.views.route_provider_lbl.setText("-")
                self.context.views.route_status.setText("Route‌ای انتخاب نشده.")
                return
            cfg = self.context.services.settings.get("providers", {}).get(route["provider"], {})
            local = self.context.services.provider_application_service.provider_kind(route["provider"], cfg) == "local"
            self.context.views.route_provider_lbl.setText(f"{self.context.services.provider_application_service.provider_label(route['provider'], cfg)}  ({'Local' if local else 'Cloud'})  ·  {route['id']}")
            if route["provider"] == "ollama" and self.context.services.provider_application_service.ollama_models:
                self.context.views.route_model_edit.set_models(self.context.services.provider_application_service.ollama_models)
            self.context.views.route_model_edit.setText(route["model"])
            self.context.views.route_enabled_chk.setChecked(bool(route.get("enabled", True)))
            lo, hi = self.context.services.provider_application_service.LOCAL_TIMEOUT if local else self.context.services.provider_application_service.CLOUD_TIMEOUT
            self.context.views.route_timeout.setRange(lo, hi)
            timeout_default = route_model.DEFAULT_LOCAL_TIMEOUT if local else route_model.DEFAULT_CLOUD_TIMEOUT
            self.context.views.route_timeout.setValue(int(route.get("timeout", timeout_default)))
            self.context.views.route_cooldown.setValue(int(route.get("cooldown", route_model.DEFAULT_COOLDOWN)))
            is_ollama = route["provider"] == "ollama"
            self.context.views.route_ctx.setEnabled(is_ollama)
            self.context.views.route_predict.setEnabled(is_ollama)
            self.context.views.route_ctx.setValue(int(route.get("num_ctx", 0)))
            self.context.views.route_predict.setValue(int(route.get("num_predict", 0)))
            st = next((x for x in self.context.session.client.status() if x["name"] == rid), {})
            parts = [self.HEALTH_TXT.get(st.get("health", "unknown"), "")]
            if st.get("last_ms") is not None:
                parts.append(f"آخرین پاسخ {st['last_ms']} ms")
            if st.get("cooldown"):
                parts.append(f"استراحت {st['cooldown']}s")
            note = route_model.route_note(
                self.context.services.settings, rid,
                capabilities=self.context.services.provider_application_service.detected_capabilities,
            )
            if note:
                parts.append("خاموش‌شده خودکار: " + note)
            if st.get("last_error"):
                parts.append("آخرین خطا: " + st["last_error"])
            self.context.views.route_status.setText("  ·  ".join(p for p in parts if p))
        finally:
            self.context.state._loading_route = False

    def after_route_change(self, select=None):
        self.sync_ollama_primary()
        self.feature_controller("runtime").save_now()
        self.refresh_route_list()
        # The unified model tabs and the chat route menu must reflect changes
        # made through the advanced Route switch immediately.
        self.refresh_unified_models()
        if select:
            for i in range(self.context.views.route_list.count()):
                if self.context.views.route_list.item(i).data(Qt.UserRole) == select:
                    self.context.views.route_list.setCurrentRow(i)
        if not self.context.session.busy:
            self.feature_controller("runtime").set_badge("idle", self.context.session.client.preview_route())

    def sync_ollama_primary(self):
        """Route 'ollama' is the model of the Assistant tab: keep the two in step both ways."""
        r = self.context.services.provider_application_service.find_route(self.context.services.settings, "ollama")
        if r and r["model"] and r["model"] != self.context.services.settings.get("model"):
            self.context.services.settings["model"] = r["model"]
            self.context.services.settings.setdefault("providers", {}).setdefault("ollama", {})["model"] = r["model"]
            self.context.views.model.setText(r["model"])

    def route_edit_changed(self):
        if self.context.state._loading_route:
            return
        rid = self._selected_route_id()
        if not rid:
            return
        try:
            self.context.services.provider_application_service.update_route(self.context.services.settings, rid, model=self.context.views.route_model_edit.text(), enabled=self.context.views.route_enabled_chk.isChecked(),
                                     timeout=self.context.views.route_timeout.value(), cooldown=self.context.views.route_cooldown.value(),
                                     num_ctx=self.context.views.route_ctx.value(), num_predict=self.context.views.route_predict.value())
        except ValueError as exc:
            self.context.views.route_status.setText("✕ " + str(exc))
            return
        self.context.session.client.reset_cooldowns(rid)
        self.after_route_change()

    def on_routes_reordered(self):
        """Drag & drop finished: the new visual order becomes the priority / failover order."""
        if self.context.state._loading_route:
            return
        ids = [self.context.views.route_list.item(i).data(Qt.UserRole) for i in range(self.context.views.route_list.count())]
        self.context.services.provider_application_service.reorder_routes(self.context.services.settings, ids)
        self.feature_controller("runtime").save_now()
        QTimer.singleShot(0, self.refresh_route_list)           # renumber labels after the drop has fully finished
        QTimer.singleShot(0, lambda: None if self.context.session.busy else self.feature_controller("runtime").set_badge("idle", self.context.session.client.preview_route()))

    def delete_selected_route(self):
        rid = self._selected_route_id()
        if not rid:
            return
        if QMessageBox.question(self.window, "حذف Route", "این Route حذف شود؟ (Provider و API Key آن دست‌نخورده می‌مانند.)") != QMessageBox.Yes:
            return
        self.context.services.provider_application_service.remove_route(self.context.services.settings, rid)
        self.context.session.client.reset_cooldowns(rid)
        self.after_route_change()

    def on_failover_toggled(self, on):
        self.context.services.settings["failover_enabled"] = bool(on)
        self.feature_controller("runtime").save_now()
        self.refresh_route_list()

    def add_route_from_values(self, provider, model, enabled=True):
        try:
            route = self.context.services.provider_application_service.add_route(self.context.services.settings, provider, model, enabled=enabled)
        except ValueError as exc:
            self.context.views.route_status.setText("✕ " + str(exc))
            return None
        self.after_route_change(select=route["id"])
        return route

    def add_route_dialog(self):
        dlg = QDialog(self.window)
        dlg.setWindowTitle("افزودن Route")
        form = QFormLayout(dlg)
        prov = QComboBox()
        providers = self.context.services.settings.get("providers", {})
        for name in providers:
            prov.addItem(self.context.services.provider_application_service.provider_label(name, providers[name]), name)
        model = ModelCombo("")
        def fill():
            if prov.currentData() == "ollama":
                model.set_models(self.context.services.provider_application_service.ollama_models)
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
            pid = self.context.services.provider_application_service.add_provider(
                self.context.services.settings, label, base_url, api_key, local, first_model
            )
        except ValueError as exc:
            self.context.views.route_status.setText("✕ " + str(exc))
            return None
        self.feature_controller("runtime").save_now()
        self.refresh_api_table(pid)
        self.refresh_route_list()
        return pid

    def add_provider_dialog(self):
        dlg = QDialog(self.window)
        dlg.setWindowTitle("افزودن Provider")
        form = QFormLayout(dlg)
        name, url, key, model = QLineEdit(), QLineEdit("https://"), QLineEdit(), QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        local = SwitchCheckBox("سرور محلی (بدون API Key، مثل LM Studio)")
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
        n = sum(1 for r in self.context.services.provider_application_service.get_routes(self.context.services.settings) if r["provider"] == pid)
        if QMessageBox.question(self.window, "حذف Provider", f"این Provider و {n} Route آن حذف شوند؟") != QMessageBox.Yes:
            return
        self.context.services.provider_application_service.remove_provider(self.context.services.settings, pid)
        self.context.session.client.reset_cooldowns()
        self.feature_controller("runtime").save_now()
        self.refresh_api_table()
        self.refresh_route_list()

    def provider_changed(self):
        """Key / enable / URL edited in a provider box: autosave (an empty key field keeps the saved key)."""
        if getattr(self.context.state, "_loading_route", False) or not hasattr(self.context.views, "route_ollama_enabled"):
            return
        self.collect_provider_settings()
        self.context.session.client.reset_cooldowns()
        self.feature_controller("runtime").save_now()
        self.refresh_route_list()
        self.refresh_unified_models()
        if not self.context.session.busy:
            self.feature_controller("runtime").set_badge("idle", self.context.session.client.preview_route())

    def test_selected_route(self):
        rid = self._selected_route_id()
        if not rid or self.context.state._closing:
            return
        current = self.context.resource("_route_worker")
        if current is not None and current.isRunning():
            return
        self.context.views.route_test_btn.setEnabled(False)
        self.context.views.route_status.setText("در حال تست…")
        worker = TaskWorker(lambda: self.context.session.client.test_route(rid))
        self.context.state._route_worker = worker
        worker.done.connect(self.on_route_test_done)
        worker.finished.connect(self._clear_route_worker)
        worker.start()

    @Slot()
    def _clear_route_worker(self):
        worker = self.sender()
        if self.context.state._route_worker is worker:
            self.context.state._route_worker = None
        if worker is not None:
            worker.deleteLater()

    @Slot(object)
    def on_route_test_done(self, result):
        worker = self.sender()
        if worker is None or self.context.state._route_worker is not worker or self.context.state._closing:
            return
        ok, value = result
        self.context.views.route_test_btn.setEnabled(True)
        self.refresh_route_list()
        if ok:
            good, msg, ms = value
            self.context.views.route_status.setText(("✓ " if good else "✕ ") + msg + (f"  ({ms} ms)" if ms is not None else ""))
        else:
            self.context.views.route_status.setText("✕ " + value)

    def scan_ollama(self):
        if self.context.state._closing:
            return
        current = self.context.resource("_scan_worker")
        if current is not None and current.isRunning():
            return
        if hasattr(self, "route_scan_btn"):
            self.route_scan_btn.setEnabled(False)
        self.context.views.route_status.setText("در حال جست‌وجوی مدل‌های نصب‌شده‌ی Ollama…")
        client = self.context.services.provider_application_service.create_ollama_client(self.context.services.settings)

        def task():
            ok, models = client.status()
            if not ok:
                raise RuntimeError(models)
            return models

        worker = TaskWorker(task)
        self.context.state._scan_worker = worker
        worker.done.connect(self.on_scan_done)
        worker.finished.connect(self._clear_scan_worker)
        worker.start()

    @Slot()
    def _clear_scan_worker(self):
        worker = self.sender()
        if self.context.state._scan_worker is worker:
            self.context.state._scan_worker = None
        if worker is not None:
            worker.deleteLater()

    @Slot(object)
    def on_scan_done(self, result):
        worker = self.sender()
        if worker is None or self.context.state._scan_worker is not worker or self.context.state._closing:
            return
        ok, value = result
        if hasattr(self, "route_scan_btn"):
            self.route_scan_btn.setEnabled(True)
        if not ok:
            self.context.views.route_status.setText("✕ " + value)
            return
        self.context.services.provider_application_service.set_ollama_models(value)
        self.context.views.model.set_models(value)
        added = self.context.services.provider_application_service.add_ollama_models(self.context.services.settings, value)
        self.feature_controller("runtime").save_now()
        self.refresh_route_list()
        self.context.views.route_status.setText(f"✓ {len(value)} مدل نصب‌شده پیدا شد؛ {len(added)} Route جدید اضافه شد (به‌صورت غیرفعال تا خودت فعال کنی).")
        self.refresh_unified_models()

    def run_benchmark(self, all_enabled):
        if self.context.session.busy:
            self.context.views.route_status.setText("✕ یک پاسخ در حال تولید است؛ بعد از پایان آن Benchmark بگیر.")
            return
        if all_enabled:
            ids = [i["route_id"] for i in self.context.session.client.available_routes()]
        else:
            ids = [self._selected_route_id()] if self._selected_route_id() else []
        if not ids:
            self.context.views.route_status.setText("✕ Route فعالی برای Benchmark نیست.")
            return
        cloud = [i for i in ids if self.context.services.provider_application_service.provider_kind((self.context.services.provider_application_service.find_route(self.context.services.settings, i) or {}).get("provider", ""),
                 self.context.services.settings.get("providers", {}).get((self.context.services.provider_application_service.find_route(self.context.services.settings, i) or {}).get("provider", ""))) == "cloud"]
        if cloud and QMessageBox.question(self.window, "Benchmark", f"{len(cloud)} Route ابری هرکدام یک درخواست کوتاه (حدود ۴۸ توکن) از سهمیه‌ی API مصرف می‌کند. ادامه بدهم؟\n"
                                                           "Routeها یکی‌یکی تست می‌شوند، نه هم‌زمان.") != QMessageBox.Yes:
            return
        self.context.session.busy = True
        self.context.state._bench_busy = True
        self.context.views.bench_out.setPlainText("در حال اجرا…")
        self._bench_lines = []
        self.context.state._bench_worker = BenchWorker(self.context.session.client, ids)
        self.context.state._bench_worker.progress.connect(self.on_bench_progress)
        self.context.state._bench_worker.done.connect(self.on_bench_done)
        self.context.state._bench_worker.finished.connect(self._clear_bench_worker)
        self.context.state._bench_worker.start()

    @Slot()
    def _clear_bench_worker(self):
        worker = self.sender()
        if self.context.state._bench_worker is worker:
            self.context.state._bench_worker = None
        if worker is not None:
            worker.deleteLater()

    @Slot(dict)
    def on_bench_progress(self, e):
        worker = self.sender()
        if worker is None or self.context.state._bench_worker is not worker or self.context.state._closing:
            return
        if e.get("phase") == "running":
            self.context.views.bench_out.setPlainText("\n".join(self._bench_lines + [f"… {e['label']} / {e['model']}"]))
        else:
            self._bench_lines.append(self.format_bench_row(e))
            self.context.views.bench_out.setPlainText("\n".join(self._bench_lines))

    @staticmethod
    def format_bench_row(r):
        fmt = lambda v: "-" if v is None else f"{v}"                              # noqa: E731
        if not r.get("ok"):
            return f"✕ {r['label']} / {r['model']}: {r.get('error') or 'ناموفق'}"
        return (f"✓ {r['label']} / {r['model']} [{'Local' if r['kind'] == 'local' else 'Cloud'}]  connect {fmt(r['connect_ms'])} ms · "
                f"first token {fmt(r['first_token_ms'])} ms · total {fmt(r['total_ms'])} ms · {fmt(r['speed'])} {r['unit']}"
                + (f" · load {r['load_ms']} ms" if r.get("load_ms") else "")
                + (f" · {r['model_gb']}GB, GPU {r['gpu_pct']}%" if r.get("gpu_pct") is not None else ""))

    @Slot(object)
    def on_bench_done(self, result):
        worker = self.sender()
        if worker is None or self.context.state._bench_worker is not worker or self.context.state._closing:
            return
        self.context.session.busy = False
        self.context.session._speech_live = False
        self.context.state._bench_busy = False
        ok, value = result
        if not ok:
            self.context.views.bench_out.setPlainText("✕ " + value)
        else:
            ranked = sorted([r for r in value if r["ok"] and r["first_token_ms"] is not None], key=lambda r: r["first_token_ms"])
            lines = [self.format_bench_row(r) for r in value]
            if ranked:
                lines.append(f"\nسریع‌ترین اولین Token: {ranked[0]['label']} / {ranked[0]['model']} ({ranked[0]['first_token_ms']} ms)")
            self.context.views.bench_out.setPlainText("\n".join(lines))
        self.refresh_route_list()
        self.feature_controller("runtime")._send_next_pending()

    # ---------- settings ----------
    # ---- Windows 11 glass ----


# Backward-compatible import name for callers migrating from mixin composition.
ProviderSettingsMixin = ProviderSettingsController
