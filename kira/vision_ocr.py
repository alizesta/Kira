"""Replaceable local OCR service, engine registry, and lifecycle boundary."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class OcrResult:
    text: str = ""
    language: str = ""
    confidence: float = 0.0
    error_code: str = ""
    source_frame_id: str = ""
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    engine: str = ""
    error_stage: str = ""
    error_message: str = ""

    def __post_init__(self):
        object.__setattr__(self, "text", " ".join(str(self.text or "").split())[:1100])
        object.__setattr__(self, "language", str(self.language or "")[:48])
        object.__setattr__(self, "error_code", str(self.error_code or "")[:64])
        object.__setattr__(self, "source_frame_id", str(self.source_frame_id or "")[:120])
        object.__setattr__(self, "timestamp_utc", str(self.timestamp_utc or "")[:40])
        object.__setattr__(self, "engine", str(self.engine or "")[:48])
        object.__setattr__(self, "error_stage", str(self.error_stage or "")[:32])
        object.__setattr__(self, "error_message", str(self.error_message or "")[:240])
        try:
            confidence = float(self.confidence or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))


class OcrEngine(Protocol):
    """Execution contract implemented by any replaceable OCR adapter."""

    name: str

    def recognize(self, image_bytes: bytes, *, source_frame_id: str = "") -> OcrResult: ...
    def diagnostics(self) -> dict: ...


class OcrService:
    """Engine registry and lifecycle coordinator, independent from capture and UI.

    Adapters may expose discover, validate, initialize, and shutdown. Older
    third-party adapters that only expose diagnostics/recognize remain supported.
    """

    def __init__(self, engines=None, *, selected_engine="tesseract"):
        if engines is None:
            from .vision_ocr_tesseract import TesseractOcrEngine
            engines = {"tesseract": TesseractOcrEngine()}
        self._engines = dict(engines)
        if not self._engines:
            raise ValueError("At least one OCR engine must be registered")
        if selected_engine not in self._engines:
            raise ValueError(f"Unknown OCR engine: {selected_engine}")
        self._selected_engine = str(selected_engine)
        self._shutdown = False

    @property
    def selected_engine(self):
        return self._selected_engine

    def _engine(self, name=None):
        key = str(name or self._selected_engine).strip().lower()
        if key not in self._engines:
            raise ValueError(f"OCR engine is not registered: {key}")
        return key, self._engines[key]

    @staticmethod
    def _call_lifecycle(engine, method_name, *, refresh=False):
        method = getattr(engine, method_name, None)
        if not callable(method):
            return None
        if method_name in ("discover", "validate"):
            try:
                return method(refresh=refresh)
            except TypeError as exc:
                if "refresh" not in str(exc):
                    raise
                return method()
        return method()

    def _engine_status(self, name=None):
        key, engine = self._engine(name)
        try:
            status = engine.diagnostics()
            if not isinstance(status, dict):
                status = {}
        except Exception as exc:
            status = {
                "ready": False,
                "status": "Degraded",
                "error_code": type(exc).__name__,
                "error_stage": "discovery",
                "error_message": str(exc),
            }
        result = dict(status)
        result.setdefault("engine", key)
        result.setdefault("ready", False)
        result.setdefault("status", "Ready" if result["ready"] else "Degraded")
        result.setdefault("installed", False)
        result.setdefault("available", bool(result["ready"]))
        return result

    def discover(self, name=None, *, refresh=False):
        key, engine = self._engine(name)
        result = self._call_lifecycle(engine, "discover", refresh=refresh)
        if not isinstance(result, dict):
            result = self._engine_status(key)
        result = dict(result)
        result.setdefault("engine", key)
        return result

    def validate(self, name=None, *, refresh=False):
        key, engine = self._engine(name)
        result = self._call_lifecycle(engine, "validate", refresh=refresh)
        if not isinstance(result, dict):
            result = self._engine_status(key)
        result = dict(result)
        result.setdefault("engine", key)
        return result

    def initialize(self, name=None):
        key, engine = self._engine(name)
        try:
            status = self.validate(key)
            initializer = getattr(engine, "initialize", None)
            if callable(initializer) and not status.get("ready"):
                initialized = initializer()
                if initialized is False:
                    return self._engine_status(key)
            return self._engine_status(key)
        except Exception as exc:
            return {
                "engine": key,
                "ready": False,
                "status": "Degraded",
                "error_code": type(exc).__name__,
                "error_stage": "initialization",
                "error_message": str(exc)[:240],
            }

    def available_engines(self):
        return {name: self._engine_status(name) for name in self._engines}

    def diagnostics(self):
        engines = self.available_engines()
        selected = engines[self._selected_engine]
        return {
            "selected_engine": self._selected_engine,
            "status": selected.get("status", "Degraded"),
            "ready": bool(selected.get("ready")),
            "installed": bool(selected.get("installed")),
            "available": bool(selected.get("available")),
            "engines": engines,
            "languages": {
                "fas": bool(selected.get("persian_ready")),
                "eng": bool(selected.get("english_ready")),
            },
            "requested_languages": list(selected.get("requested_languages") or ()),
            "missing_languages": list(selected.get("missing_languages") or ()),
            "error_code": selected.get("error_code", ""),
            "error_stage": selected.get("error_stage", ""),
            "error_message": selected.get("error_message", ""),
        }

    def select_engine(self, name):
        key, _engine = self._engine(str(name or "").strip().lower())
        status = self._engine_status(key)
        if not status.get("ready"):
            status = self.initialize(key)
        if not status.get("ready"):
            reason = status.get("error_code") or status.get("error_message") or key
            raise RuntimeError(f"OCR engine is not ready: {reason}")
        self._selected_engine = key
        self._shutdown = False
        return status

    def recognize(self, image_bytes, cancel_event=None, *, source_frame_id=""):
        if cancel_event is not None and cancel_event.is_set():
            return OcrResult(
                error_code="cancelled",
                source_frame_id=source_frame_id,
                engine=self._selected_engine,
                error_stage="execution",
                error_message="OCR job was cancelled before execution",
            )
        if self._shutdown:
            return OcrResult(
                error_code="ocr_service_shutdown",
                source_frame_id=source_frame_id,
                engine=self._selected_engine,
                error_stage="initialization",
                error_message="OCR service has been shut down",
            )

        key, engine = self._engine()
        status = self._engine_status(key)
        if not status.get("ready"):
            status = self.initialize(key)
        if not status.get("ready"):
            return OcrResult(
                language="+".join(status.get("requested_languages") or ()),
                error_code=status.get("error_code") or "ocr_engine_not_ready",
                source_frame_id=source_frame_id,
                engine=key,
                error_stage=status.get("error_stage") or "initialization",
                error_message=status.get("error_message") or "OCR engine did not become ready",
            )

        try:
            result = engine.recognize(
                image_bytes,
                source_frame_id=source_frame_id,
            )
            if isinstance(result, OcrResult):
                if result.engine:
                    return result
                return OcrResult(
                    text=result.text,
                    language=result.language,
                    confidence=result.confidence,
                    error_code=result.error_code,
                    source_frame_id=result.source_frame_id or source_frame_id,
                    timestamp_utc=result.timestamp_utc,
                    engine=key,
                    error_stage=result.error_stage or ("execution" if result.error_code else ""),
                    error_message=result.error_message,
                )
            return OcrResult(
                text=str(result or ""),
                source_frame_id=source_frame_id,
                engine=key,
            )
        except Exception as exc:
            return OcrResult(
                error_code=type(exc).__name__,
                source_frame_id=source_frame_id,
                engine=key,
                error_stage="execution",
                error_message=str(exc),
            )

    def shutdown(self):
        """Close all initialized adapters after active jobs have completed."""
        successful = True
        for engine in self._engines.values():
            try:
                self._call_lifecycle(engine, "shutdown")
            except Exception:
                successful = False
        self._shutdown = True
        return successful


def extract_local_text(image_attachment):
    """Backward-compatible helper routed through the service lifecycle."""
    if not isinstance(image_attachment, dict) or not image_attachment.get("b64"):
        return ""
    encoded = str(image_attachment["b64"])
    if len(encoded) > 30_000_000:
        return ""
    service = OcrService()
    try:
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return ""
        return service.recognize(image_bytes).text
    finally:
        service.shutdown()


def __getattr__(name):
    """Keep the former public import path while the Tesseract adapter stays separate."""
    if name == "TesseractOcrEngine":
        from .vision_ocr_tesseract import TesseractOcrEngine
        return TesseractOcrEngine
    raise AttributeError(name)


def setup_native_tesseract(*, input_fn=input, output_fn=print, runner=subprocess.run):
    """Offer explicit Windows installation and separate consent for fas/eng language data."""
    from .vision_ocr_runtime import TesseractRuntime

    runtime = TesseractRuntime(required_languages=("fas", "eng"))
    status = runtime.discover(refresh=True)
    if not status.get("native_engine_installed"):
        if os.name != "nt":
            output_fn("Automatic Tesseract setup is available only on Windows.")
            return 1
        winget = shutil.which("winget")
        if not winget:
            output_fn("winget was not found. Install Tesseract with the UB Mannheim Windows installer, then rerun setup.")
            return 1
        answer = input_fn("Tesseract is not installed. Install UB Mannheim Tesseract using winget? [y/N]: ")
        if str(answer or "").strip().lower() not in ("y", "yes"):
            output_fn("Tesseract installation skipped. OCR remains unavailable; other Vision features are unaffected.")
            return 1
        try:
            result = runner(
                [winget, "install", "--id", "UB-Mannheim.TesseractOCR", "--exact",
                 "--interactive", "--accept-package-agreements", "--accept-source-agreements"],
                capture_output=True, text=True, timeout=900, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            output_fn(f"Tesseract installation failed: {type(exc).__name__}: {exc}")
            return 1
        if int(getattr(result, "returncode", 1)) != 0:
            details = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            output_fn("Tesseract installation failed." + (f" {details[:500]}" if details else ""))
            return 1
        status = runtime.discover(refresh=True)
        if not status.get("native_engine_installed"):
            output_fn("winget finished, but tesseract.exe was not found. Restart setup or set KIRA_TESSERACT_CMD.")
            return 1

    executable = str(status.get("executable") or "")
    tessdata = str(status.get("tessdata_dir") or "")
    if not tessdata and executable:
        tessdata = str(Path(executable).resolve().parent / "tessdata")
    if not tessdata:
        output_fn("Tesseract is installed, but its tessdata directory could not be located. Set KIRA_TESSDATA_DIR.")
        return 1

    missing = list(status.get("missing_languages") or ())
    if missing:
        output_fn("Missing Tesseract language data: " + ", ".join(missing))
        answer = input_fn("Download the missing official tessdata_fast language files (fas/eng)? [y/N]: ")
        if str(answer or "").strip().lower() not in ("y", "yes"):
            output_fn("Language-data download skipped. Install the missing .traineddata files and rerun --status.")
            return 1
        directory = Path(tessdata)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            for language in missing:
                if language not in ("fas", "eng"):
                    raise ValueError(f"Unsupported language requested by this setup: {language}")
                url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{language}.traineddata"
                request = urllib.request.Request(url, headers={"User-Agent": "Project-Kira-OCR-Setup"})
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = response.read(40 * 1024 * 1024 + 1)
                if len(payload) < 1024 or len(payload) > 40 * 1024 * 1024:
                    raise RuntimeError(f"Downloaded {language}.traineddata has an invalid size")
                target = directory / f"{language}.traineddata"
                temporary = directory / f".{language}.traineddata.download"
                temporary.write_bytes(payload)
                os.replace(temporary, target)
        except Exception as exc:
            try:
                for temporary in directory.glob(".*.traineddata.download"):
                    temporary.unlink(missing_ok=True)
            except OSError:
                pass
            output_fn(f"Language-data setup failed: {type(exc).__name__}: {exc}")
            return 1
        status = runtime.discover(refresh=True)

    if status.get("missing_languages"):
        output_fn("OCR is still missing required language data: " + ", ".join(status["missing_languages"]))
        return 1
    output_fn("Tesseract engine and required language data are installed.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="validate OCR without installing anything")
    mode.add_argument("--setup", action="store_true", help="offer consent-based Tesseract and fas/eng setup")
    args = parser.parse_args(argv)
    if args.setup and setup_native_tesseract() != 0:
        service = OcrService()
        try:
            print(json.dumps(service.diagnostics(), ensure_ascii=False, indent=2))
        finally:
            service.shutdown()
        return 1
    service = OcrService()
    try:
        service.initialize()
        report = service.diagnostics()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ready") else 1
    finally:
        service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
