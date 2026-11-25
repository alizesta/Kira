"""Single authority for local ASR selection and engine lifecycle."""
from __future__ import annotations
from threading import RLock
from typing import Any, Protocol


class ASRError(RuntimeError):
    """ASR failure with a stable category for UI and diagnostics."""
    def __init__(self, code: str, message: str, *, engine_id: str = "", model_id: str = ""):
        super().__init__(message)
        self.code, self.engine_id, self.model_id = str(code), str(engine_id), str(model_id)


class ASRAdapter(Protocol):
    engine_id: str
    display_name: str
    default_model: str
    capabilities: frozenset[str]
    def catalog_entry(self) -> dict[str, Any]: ...
    def inspect(self, model_id: str) -> dict[str, Any]: ...
    def validate(self, model_id: str) -> None: ...
    def initialize(self, model_id: str) -> None: ...
    def transcribe(self, audio: Any, sample_rate: int, model_id: str) -> str: ...
    def transcribe_file(self, path: str, model_id: str) -> str: ...
    def install(self, model_id: str, cancel_event=None) -> str: ...
    def shutdown(self) -> None: ...


class ShenavaASRAdapter:
    """Adapter for the implemented Shenava Koochik sherpa-onnx engine."""
    engine_id = "shenava"
    display_name = "Shenava Koochik"
    capabilities = frozenset({"offline", "persian", "microphone", "partial_transcripts"})

    @property
    def default_model(self) -> str:
        from . import local_voice
        return local_voice.SHENAVA_INT8_REPO_ID

    def catalog_entry(self):
        from . import local_voice
        labels = {
            local_voice.SHENAVA_INT8_REPO_ID: "Shenava INT8 · سبک‌تر",
            local_voice.SHENAVA_FP32_REPO_ID: "Shenava FP32 · نسخه کامل",
        }
        return {
            "id": self.engine_id, "name": self.display_name,
            "label": f"{self.display_name} · sherpa-onnx",
            "default_model": self.default_model,
            "models": [
                {"id": mid, "label": labels.get(mid, mid), "size_mb": size}
                for mid, size in local_voice.SHENAVA_MODEL_SIZES_MB.items()
            ],
            "capabilities": sorted(self.capabilities),
        }

    def _runtime_status(self):
        """Verify sherpa-onnx is importable and inside the installed compatibility range."""
        from importlib.metadata import PackageNotFoundError, version
        from . import local_voice
        if not local_voice.shenava_ready():
            return False, "", "runtime_missing"
        try:
            installed_version = version("sherpa-onnx")
        except PackageNotFoundError:
            return True, "", "runtime_version_unknown"
        try:
            from packaging.version import Version
            compatible = Version("2.0.2") <= Version(installed_version) < Version("3")
        except Exception:
            compatible = False
        return True, installed_version, "" if compatible else "runtime_incompatible"

    def inspect(self, model_id: str):
        from . import local_voice
        installed, runtime_version, runtime_error = self._runtime_status()
        cached = {
            str(item.get("id") or "")
            for item in local_voice.discover_cached_models().get("asr", [])
        }
        ready, error = False, ""
        if installed and not runtime_error:
            try:
                local_voice._resolve_shenava_model_files(model_id)
                ready = True
            except (OSError, RuntimeError, ValueError) as exc:
                error = str(exc)
        code = "" if ready else (runtime_error or "model_missing")
        message = "" if ready else (
            "بستهٔ sherpa-onnx نصب نیست." if code == "runtime_missing" else
            "نسخهٔ sherpa-onnx با این نسخهٔ Kira سازگار نیست." if code == "runtime_incompatible" else
            "نسخهٔ نصب‌شدهٔ sherpa-onnx قابل تشخیص نیست." if code == "runtime_version_unknown" else
            (error or "فایل‌های مدل انتخاب‌شده در دسترس نیستند.")
        )
        return {
            "engine_id": self.engine_id, "engine_name": self.display_name,
            "model_id": model_id, "runtime_installed": installed,
            "runtime_version": runtime_version, "model_ready": ready,
            "ready": installed and ready and not runtime_error,
            "cached": model_id in cached, "capabilities": sorted(self.capabilities),
            "error_code": code, "error_message": message,
        }

    def validate(self, model_id: str):
        from . import local_voice
        installed, runtime_version, runtime_error = self._runtime_status()
        if not installed:
            raise ASRError("runtime_missing", "موتور ASR شنوا نصب نیست.",
                           engine_id=self.engine_id, model_id=model_id)
        if runtime_error:
            message = ("نسخهٔ sherpa-onnx با Kira سازگار نیست."
                       if runtime_error == "runtime_incompatible" else
                       "نسخهٔ sherpa-onnx قابل تشخیص نیست.")
            raise ASRError(runtime_error, f"{message} (نسخه: {runtime_version or 'نامشخص'})",
                           engine_id=self.engine_id, model_id=model_id)
        try:
            local_voice._resolve_shenava_model_files(model_id)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ASRError("model_missing", f"مدل انتخاب‌شده آماده نیست: {exc}",
                           engine_id=self.engine_id, model_id=model_id) from exc

    def initialize(self, model_id: str):
        from . import local_voice
        local_voice.load_shenava(model_id)

    def transcribe(self, audio, sample_rate, model_id):
        from . import local_voice
        return local_voice.transcribe_shenava(audio, sample_rate, model_id)

    def transcribe_file(self, path, model_id):
        from . import local_voice
        return local_voice.transcribe_shenava_file(path, model_id)

    def install(self, model_id, cancel_event=None):
        from . import local_voice
        return local_voice.install_and_download_shenava_asr(model_id, cancel_event=cancel_event)

    def shutdown(self):
        from . import local_voice
        local_voice.unload_shenava()


class ASRManager:
    """Registry, selected-engine authority and serialized ASR lifecycle."""
    def __init__(self, adapters=None):
        self._lock = RLock()
        self._adapters: dict[str, ASRAdapter] = {}
        self._active_adapter = None
        self._active_model = ""
        self._state = "idle"
        self._last_error: ASRError | None = None
        for adapter in adapters if adapters is not None else (ShenavaASRAdapter(),):
            self.register(adapter)

    def register(self, adapter: ASRAdapter):
        engine_id = str(getattr(adapter, "engine_id", "") or "").strip().lower()
        methods = ("catalog_entry", "inspect", "validate", "initialize",
                   "transcribe", "transcribe_file", "install", "shutdown")
        if not engine_id or any(not callable(getattr(adapter, name, None)) for name in methods):
            raise TypeError("ASR adapter does not satisfy the lifecycle contract")
        with self._lock:
            if self._active_adapter is not None and self._active_adapter.engine_id == engine_id:
                raise RuntimeError("Cannot replace the active ASR adapter")
            self._adapters[engine_id] = adapter

    def catalog(self):
        with self._lock:
            return [dict(adapter.catalog_entry()) for adapter in self._adapters.values()]

    def select(self, settings=None):
        values = settings or {}
        engine_id = str(values.get("local_voice_asr_backend") or "shenava").strip().lower()
        adapter = self._adapters.get(engine_id)
        model_id = str(values.get("local_voice_asr_model") or "").strip()
        if adapter is None:
            raise ASRError("unsupported_engine", f"موتور ASR «{engine_id or '(خالی)'}» پشتیبانی نمی‌شود.",
                           engine_id=engine_id, model_id=model_id)
        model_id = model_id or adapter.default_model
        if not model_id:
            raise ASRError("model_missing", "مدل ASR انتخاب نشده است.", engine_id=engine_id)
        return engine_id, model_id

    def discover(self, settings=None):
        try:
            engine_id, model_id = self.select(settings)
        except ASRError as exc:
            return {"engine_id": exc.engine_id, "engine_name": "موتور پشتیبانی‌نشده",
                    "model_id": exc.model_id, "runtime_installed": False, "model_ready": False,
                    "ready": False, "initialized": False, "state": "unavailable",
                    "capabilities": [], "error_code": exc.code, "error_message": str(exc)}
        adapter = self._adapters[engine_id]
        try:
            snapshot = dict(adapter.inspect(model_id))
        except Exception as exc:
            snapshot = {"engine_id": engine_id, "engine_name": adapter.display_name,
                        "model_id": model_id, "runtime_installed": False, "model_ready": False,
                        "ready": False, "capabilities": sorted(adapter.capabilities),
                        "error_code": "discovery_failed", "error_message": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            active = self._active_adapter is adapter and self._active_model == model_id
            failed = self._state == "failed"
            snapshot.update(
                initialized=active,
                state="failed" if failed else ("ready" if active else
                       ("available" if snapshot.get("ready") else "unavailable")),
                last_error=str(self._last_error) if self._last_error else "",
            )
            if failed:
                snapshot["ready"] = False
        return snapshot

    def selected_engine_label(self, settings=None):
        try:
            engine_id, _model = self.select(settings)
            return self._adapters[engine_id].display_name
        except ASRError as exc:
            return f"ASR نامعتبر · {exc.engine_id or 'unknown'}"

    def initialize(self, settings=None):
        with self._lock:
            try:
                engine_id, model_id = self.select(settings)
            except ASRError as exc:
                if self._active_adapter is not None:
                    self._shutdown_locked()
                self._state, self._last_error = "failed", exc
                raise
            adapter = self._adapters[engine_id]
            if (self._active_adapter is adapter and self._active_model == model_id
                    and self._state != "failed"):
                return self.discover(settings)
            if self._active_adapter is not None:
                self._shutdown_locked()
            self._state = "validating"
            try:
                adapter.validate(model_id)
            except ASRError as exc:
                self._state, self._last_error = "failed", exc
                raise
            except Exception as exc:
                error = ASRError("validation_failed", f"اعتبارسنجی ASR ناموفق بود: {exc}",
                                 engine_id=engine_id, model_id=model_id)
                self._state, self._last_error = "failed", error
                raise error from exc
            self._state = "initializing"
            try:
                adapter.initialize(model_id)
            except Exception as exc:
                error = ASRError("initialization_failed",
                                 f"بارگذاری ASR ناموفق بود: {type(exc).__name__}: {exc}",
                                 engine_id=engine_id, model_id=model_id)
                self._state, self._last_error = "failed", error
                raise error from exc
            self._active_adapter, self._active_model = adapter, model_id
            self._state, self._last_error = "ready", None
            return self.discover(settings)

    def _ensure_selected(self, settings):
        engine_id, model_id = self.select(settings)
        if (self._active_adapter is None or self._active_adapter.engine_id != engine_id
                or self._active_model != model_id):
            self.initialize(settings)
        return engine_id, model_id

    def transcribe(self, audio, sample_rate, settings=None):
        with self._lock:
            engine_id, model_id = self._ensure_selected(settings)
            try:
                result = str(self._active_adapter.transcribe(audio, int(sample_rate), model_id) or "").strip()
                self._state, self._last_error = "ready", None
                return result
            except Exception as exc:
                error = ASRError("inference_failed", f"اجرای ASR ناموفق بود: {type(exc).__name__}: {exc}",
                                 engine_id=engine_id, model_id=model_id)
                self._state, self._last_error = "failed", error
                raise error from exc

    def transcribe_file(self, path, settings=None):
        with self._lock:
            engine_id, model_id = self._ensure_selected(settings)
            try:
                result = str(self._active_adapter.transcribe_file(str(path), model_id) or "").strip()
                self._state, self._last_error = "ready", None
                return result
            except Exception as exc:
                error = ASRError("inference_failed", f"تشخیص فایل ناموفق بود: {type(exc).__name__}: {exc}",
                                 engine_id=engine_id, model_id=model_id)
                self._state, self._last_error = "failed", error
                raise error from exc

    def install_selected(self, settings=None, *, cancel_event=None):
        with self._lock:
            try:
                engine_id, model_id = self.select(settings)
            except ASRError as exc:
                if self._active_adapter is not None:
                    self._shutdown_locked()
                self._state, self._last_error = "failed", exc
                raise
            if self._active_adapter is not None:
                self._shutdown_locked()
            self._state = "installing"
            try:
                result = str(self._adapters[engine_id].install(model_id, cancel_event=cancel_event))
            except Exception as exc:
                error = ASRError("installation_failed",
                                 f"نصب ASR ناموفق بود: {type(exc).__name__}: {exc}",
                                 engine_id=engine_id, model_id=model_id)
                self._state, self._last_error = "failed", error
                raise error from exc
            self._state, self._last_error = "idle", None
            return result

    def _shutdown_locked(self):
        adapter = self._active_adapter
        if adapter is None:
            self._active_model = ""
            self._state = "idle"
            return
        self._state = "shutting_down"
        try:
            adapter.shutdown()
        except Exception as exc:
            error = ASRError("shutdown_failed", f"بستن ASR ناموفق بود: {type(exc).__name__}: {exc}",
                             engine_id=adapter.engine_id, model_id=self._active_model)
            self._active_adapter, self._active_model = None, ""
            self._state, self._last_error = "failed", error
            raise error from exc
        self._active_adapter, self._active_model = None, ""
        self._state, self._last_error = "idle", None

    def shutdown(self):
        with self._lock:
            self._shutdown_locked()

    @property
    def active_engine_id(self):
        with self._lock:
            return self._active_adapter.engine_id if self._active_adapter else ""

    @property
    def active_model_id(self):
        with self._lock:
            return self._active_model

    @property
    def state(self):
        with self._lock:
            return self._state
