"""Discovery, validation, initialization, and shutdown for the native Tesseract runtime."""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable


_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_]{2,16}$")


class TesseractRuntime:
    """Own native executable and traineddata discovery, separately from OCR execution."""

    def __init__(
        self,
        *,
        required_languages=("fas", "eng"),
        timeout_seconds=5,
        cache_ttl_seconds=15,
        failure_retry_seconds=3,
        paths_provider: Callable[[], dict[str, Any]] | None = None,
        executable: str | None = None,
        tessdata_dir: str | None = None,
    ):
        languages = tuple(dict.fromkeys(str(value).strip() for value in required_languages))
        if not languages or any(not _LANGUAGE_RE.fullmatch(value) for value in languages):
            raise ValueError("required_languages must contain valid Tesseract language codes")
        self.required_languages = languages
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.cache_ttl_seconds = max(0, float(cache_ttl_seconds))
        self.failure_retry_seconds = max(0, float(failure_retry_seconds))
        self._paths_provider = paths_provider
        self._executable_override = str(executable or "").strip()
        self._tessdata_override = str(tessdata_dir or "").strip()
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self._validated_at = 0.0
        self._initialized = False
        self._pytesseract = None
        self._image_module = None
        self._executable = ""
        self._tessdata_dir = ""

    @staticmethod
    def _module_installed(module_name: str) -> bool:
        if module_name in sys.modules:
            return sys.modules[module_name] is not None
        try:
            return importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError, AttributeError):
            return False

    def _path_settings(self) -> dict[str, Any]:
        if self._paths_provider is not None:
            values = self._paths_provider()
        else:
            from .config import ocr_runtime_paths
            values = ocr_runtime_paths()
        if not isinstance(values, dict):
            values = {}
        values = dict(values)
        if self._executable_override:
            values["executable"] = self._executable_override
        if self._tessdata_override:
            values["tessdata_dir"] = self._tessdata_override
        return values

    @staticmethod
    def _normalize_path(value: Any) -> str:
        raw = str(value or "").strip().strip('"').strip("'")
        if not raw:
            return ""
        return str(Path(os.path.expandvars(raw)).expanduser())

    def _resolve_executable(self, values: dict[str, Any]) -> tuple[str, str, str]:
        explicit = self._normalize_path(values.get("executable"))
        if explicit:
            path = Path(explicit)
            if path.is_file():
                return str(path.resolve()), "", ""
            found = shutil.which(explicit)
            if found:
                return str(Path(found).resolve()), "", ""
            return "", "configured_tesseract_executable_not_found", (
                "The configured Tesseract executable does not exist: " + explicit
            )

        found = shutil.which("tesseract")
        if found:
            return str(Path(found).resolve()), "", ""
        for candidate in values.get("executable_candidates") or ():
            normalized = self._normalize_path(candidate)
            if normalized and Path(normalized).is_file():
                return str(Path(normalized).resolve()), "", ""
        return "", "tesseract_executable_not_found", (
            "Tesseract was not found on PATH or in the configured installation paths"
        )

    def _resolve_tessdata(self, values: dict[str, Any], executable: str) -> tuple[str, str, str]:
        explicit = self._normalize_path(values.get("tessdata_dir"))
        candidates = []
        if explicit:
            root = Path(explicit)
            candidates.extend((root, root / "tessdata"))
        elif executable:
            candidates.append(Path(executable).parent / "tessdata")
        for candidate in candidates:
            if candidate.is_dir():
                try:
                    if any(candidate.glob("*.traineddata")):
                        return str(candidate.resolve()), "", ""
                except OSError:
                    pass
        if explicit:
            return "", "tessdata_directory_not_found", (
                "The configured tessdata directory does not contain traineddata files: " + explicit
            )
        return "", "", ""

    @staticmethod
    def _languages_from_data_dir(directory: str) -> list[str]:
        if not directory:
            return []
        try:
            return sorted({
                candidate.stem
                for candidate in Path(directory).glob("*.traineddata")
                if _LANGUAGE_RE.fullmatch(candidate.stem)
            })
        except OSError:
            return []

    @staticmethod
    def _state(status: dict[str, Any]) -> str:
        if status.get("ready"):
            return "Ready"
        if status.get("error_code"):
            return "Degraded" if status.get("installed") else "NotInstalled"
        if status.get("available"):
            return "Available"
        if status.get("installed"):
            return "Installed"
        return "NotInstalled"

    def _store(self, status: dict[str, Any], *, validated=False) -> dict[str, Any]:
        status["initialized"] = bool(self._initialized)
        status["ready"] = bool(self._initialized and status.get("available") and not status.get("missing_languages"))
        status["status"] = self._state(status)
        status["degraded"] = status["status"] == "Degraded"
        self._snapshot = dict(status)
        self._snapshot_at = time.monotonic()
        if validated:
            self._validated_at = self._snapshot_at
        return dict(self._snapshot)

    def discover(self, *, refresh=False) -> dict[str, Any]:
        """Find Python packages, native executable, and configured language-data directory."""
        with self._lock:
            now = time.monotonic()
            if (
                not refresh
                and self._snapshot is not None
                and now - self._snapshot_at < self.cache_ttl_seconds
            ):
                return dict(self._snapshot)

            values = self._path_settings()
            self._executable, executable_error, executable_message = self._resolve_executable(values)
            self._tessdata_dir, data_error, data_message = self._resolve_tessdata(
                values, self._executable
            )
            python_ready = self._module_installed("pytesseract")
            pillow_ready = self._module_installed("PIL")
            installed_languages = self._languages_from_data_dir(self._tessdata_dir)
            missing_languages = [
                language for language in self.required_languages
                if language not in installed_languages
            ]
            installed = bool(
                python_ready or pillow_ready or self._executable or self._tessdata_dir
            )
            status = {
                "engine": "tesseract",
                "status": "Installed" if installed else "NotInstalled",
                "installed": installed,
                "available": False,
                "ready": False,
                "initialized": False,
                "degraded": False,
                "python_bindings_installed": python_ready,
                "python_bindings_ready": python_ready,
                "pillow_installed": pillow_ready,
                "pillow_ready": pillow_ready,
                "native_engine_installed": bool(self._executable),
                "executable_found": bool(self._executable),
                "executable": self._executable,
                "tessdata_dir": self._tessdata_dir,
                "binary_ready": False,
                "version": "",
                "required_languages": list(self.required_languages),
                "requested_languages": list(self.required_languages),
                "installed_languages": installed_languages,
                "missing_languages": missing_languages,
                "persian_ready": "fas" in installed_languages,
                "english_ready": "eng" in installed_languages,
                "error_code": "",
                "error_stage": "",
                "error_message": "",
            }
            if executable_error or data_error:
                status.update(
                    error_code=executable_error or data_error,
                    error_stage="discovery",
                    error_message=executable_message or data_message,
                )
            elif not python_ready:
                status.update(
                    error_code="pytesseract_dependency_unavailable",
                    error_stage="discovery",
                    error_message="The optional pytesseract Python binding is not installed",
                )
            elif not pillow_ready:
                status.update(
                    error_code="pillow_dependency_unavailable",
                    error_stage="discovery",
                    error_message="The optional Pillow image dependency is not installed",
                )
            elif not self._executable:
                status.update(
                    error_code="tesseract_executable_not_found",
                    error_stage="discovery",
                    error_message="The native Tesseract executable is not installed or discoverable",
                )
            self._validated_at = 0.0
            return self._store(status)

    @staticmethod
    def _languages_from_output(output: str) -> list[str]:
        languages = set()
        for line in str(output or "").splitlines():
            value = line.strip()
            if not value or value.lower().startswith("list of available languages"):
                continue
            if _LANGUAGE_RE.fullmatch(value):
                languages.add(value)
        return sorted(languages)

    def _run(self, args: list[str]):
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )

    def validate(self, *, refresh=False) -> dict[str, Any]:
        """Validate native execution and every required traineddata language."""
        with self._lock:
            now = time.monotonic()
            retry_ttl = (
                self.failure_retry_seconds
                if self._snapshot is not None and self._snapshot.get("error_code")
                else self.cache_ttl_seconds
            )
            if (
                not refresh
                and self._snapshot is not None
                and self._validated_at
                and now - self._validated_at < retry_ttl
            ):
                return dict(self._snapshot)
            if self._initialized and self._snapshot is not None:
                return dict(self._snapshot)

            status = self.discover(refresh=refresh)
            if status.get("error_code"):
                return self._store(status, validated=True)
            executable = self._executable
            try:
                version_result = self._run([executable, "--version"])
                if version_result.returncode != 0:
                    message = (version_result.stderr or version_result.stdout or "").strip()
                    raise RuntimeError(message or f"Tesseract --version exited with {version_result.returncode}")
                version = next(
                    (line.strip() for line in (version_result.stdout or version_result.stderr).splitlines() if line.strip()),
                    "",
                )
                if not version:
                    raise RuntimeError("Tesseract returned an empty version")
                language_command = [executable]
                if self._tessdata_dir:
                    language_command.extend(["--tessdata-dir", self._tessdata_dir])
                language_command.append("--list-langs")
                languages_result = self._run(language_command)
                if languages_result.returncode != 0:
                    message = (languages_result.stderr or languages_result.stdout or "").strip()
                    raise RuntimeError(message or f"Tesseract --list-langs exited with {languages_result.returncode}")
                languages = self._languages_from_output(
                    (languages_result.stdout or "") + "\n" + (languages_result.stderr or "")
                )
                missing = [language for language in self.required_languages if language not in languages]
                status.update(
                    version=version[:80],
                    installed_languages=languages,
                    missing_languages=missing,
                    persian_ready="fas" in languages,
                    english_ready="eng" in languages,
                    binary_ready=True,
                    available=True,
                )
                if missing:
                    status.update(
                        error_code="required_language_data_missing",
                        error_stage="validation",
                        error_message="Required Tesseract language data is missing: " + ", ".join(missing),
                    )
                else:
                    status.update(error_code="", error_stage="", error_message="")
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                status.update(
                    available=False,
                    binary_ready=False,
                    error_code=type(exc).__name__,
                    error_stage="validation",
                    error_message=str(exc) or "Tesseract validation failed",
                )
            except Exception as exc:
                status.update(
                    available=False,
                    binary_ready=False,
                    error_code=type(exc).__name__,
                    error_stage="validation",
                    error_message=str(exc) or "Unexpected Tesseract validation failure",
                )
            return self._store(status, validated=True)

    def initialize(self) -> dict[str, Any]:
        """Load Python adapters only after validation proves all required languages exist."""
        with self._lock:
            status = self.validate()
            if status.get("ready"):
                return status
            if not status.get("available") or status.get("missing_languages"):
                return status
            try:
                pytesseract = importlib.import_module("pytesseract")
                image_module = importlib.import_module("PIL.Image")
                pytesseract.pytesseract.tesseract_cmd = self._executable
                if not callable(getattr(pytesseract, "image_to_data", None)):
                    raise RuntimeError("pytesseract.image_to_data is unavailable")
                if not callable(getattr(image_module, "open", None)):
                    raise RuntimeError("Pillow Image.open is unavailable")
                self._pytesseract = pytesseract
                self._image_module = image_module
                self._initialized = True
                status.update(error_code="", error_stage="", error_message="")
                return self._store(status, validated=True)
            except Exception as exc:
                self._initialized = False
                self._pytesseract = None
                self._image_module = None
                status.update(
                    error_code=type(exc).__name__,
                    error_stage="initialization",
                    error_message=str(exc) or "Tesseract adapter initialization failed",
                )
                return self._store(status, validated=True)

    @property
    def pytesseract(self):
        return self._pytesseract

    @property
    def image_module(self):
        return self._image_module

    def image_config(self, *, page_segmentation_mode=6) -> str:
        config = f"--psm {int(page_segmentation_mode)}"
        if self._tessdata_dir:
            safe_path = self._tessdata_dir.replace('"', "")
            config += f' --tessdata-dir "{safe_path}"'
        return config

    def diagnostics(self) -> dict[str, Any]:
        return self.validate()

    def shutdown(self) -> bool:
        """Release Python adapter references; pytesseract owns no persistent daemon."""
        with self._lock:
            self._pytesseract = None
            self._image_module = None
            self._initialized = False
            if self._snapshot is not None:
                status = dict(self._snapshot)
                status["initialized"] = False
                status["ready"] = False
                self._store(status, validated=True)
            return True
