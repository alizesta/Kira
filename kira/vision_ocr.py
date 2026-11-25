"""Replaceable local OCR service, runtime discovery and Tesseract adapter."""
from __future__ import annotations
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
import shutil
from typing import Protocol

@dataclass(frozen=True)
class OcrResult:
    text: str = ""
    language: str = ""
    confidence: float = 0.0
    error_code: str = ""
    source_frame_id: str = ""
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
    def __post_init__(self):
        object.__setattr__(self, "text", " ".join(str(self.text or "").split())[:1100])
        object.__setattr__(self, "language", str(self.language or "")[:24])
        object.__setattr__(self, "error_code", str(self.error_code or "")[:48])
        object.__setattr__(self, "source_frame_id", str(self.source_frame_id or "")[:120])
        object.__setattr__(self, "timestamp_utc", str(self.timestamp_utc or "")[:40])
        try: confidence = float(self.confidence or 0.0)
        except (TypeError, ValueError): confidence = 0.0
        object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))

class OcrEngine(Protocol):
    name: str
    def recognize(self, image_bytes: bytes, *, source_frame_id: str = "") -> OcrResult: ...
    def diagnostics(self) -> dict: ...

class TesseractOcrEngine:
    """Checks Python bindings, native executable and trained language data independently."""
    name = "tesseract"
    def __init__(self, *, preferred_languages=("fas", "eng"), timeout_seconds=3,
                 max_image_bytes=12*1024*1024, max_pixels=15_000_000, executable=None):
        self.preferred_languages = tuple(dict.fromkeys(str(x) for x in preferred_languages))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_image_bytes = max(1, int(max_image_bytes))
        self.max_pixels = max(1, int(max_pixels))
        self.executable = executable
        self._pytesseract = self._image_module = None
        self._runtime_error = ""
        self._diagnostics_cache = None

    def _load(self):
        if self._pytesseract is not None and self._image_module is not None:
            return self._pytesseract, self._image_module
        try:
            import pytesseract
            from PIL import Image
            if self.executable: pytesseract.pytesseract.tesseract_cmd = self.executable
            self._pytesseract, self._image_module = pytesseract, Image
            self._runtime_error = ""
        except ImportError: self._runtime_error = "ocr_dependency_unavailable"
        return self._pytesseract, self._image_module

    def diagnostics(self, *, refresh=False):
        if self._diagnostics_cache is not None and not refresh:
            return dict(self._diagnostics_cache)
        pytesseract, image_module = self._load()
        binary = self.executable or shutil.which("tesseract")
        version, languages, binary_error = "", [], ""
        if pytesseract is not None and binary:
            try:
                if self.executable: pytesseract.pytesseract.tesseract_cmd = self.executable
                version = str(pytesseract.get_tesseract_version()).splitlines()[0][:80]
                languages = sorted(str(x) for x in pytesseract.get_languages(config=""))
            except Exception as exc: binary_error = type(exc).__name__
        elif not binary: binary_error = "tesseract_executable_not_found"
        missing = [x for x in self.preferred_languages if x not in languages]
        ready = bool(pytesseract is not None and image_module is not None and binary and version and any(x in languages for x in self.preferred_languages) and not binary_error)
        status = {"engine":self.name, "python_bindings_ready":pytesseract is not None,
                "pillow_ready":image_module is not None, "executable":binary or "",
                "binary_ready":bool(binary and version), "version":version,
                "installed_languages":languages, "requested_languages":list(self.preferred_languages),
                "missing_languages":missing, "persian_ready":"fas" in languages,
                "english_ready":"eng" in languages, "ready":ready,
                "error_code":self._runtime_error or binary_error or ("language_data_missing" if missing else "")}
        self._diagnostics_cache = dict(status)
        return status

    def recognize(self, image_bytes, *, source_frame_id=""):
        raw = bytes(image_bytes or b"")
        if not raw: return OcrResult(error_code="empty_image", source_frame_id=source_frame_id)
        if len(raw)>self.max_image_bytes: return OcrResult(error_code="image_too_large", source_frame_id=source_frame_id)
        try:
            pytesseract, image_module = self._load()
            if pytesseract is None or image_module is None:
                return OcrResult(error_code="ocr_dependency_unavailable", source_frame_id=source_frame_id)
            status = self.diagnostics()
            if not status["binary_ready"]:
                return OcrResult(error_code="tesseract_executable_unavailable", source_frame_id=source_frame_id)
            selected = [x for x in self.preferred_languages if x in status["installed_languages"]]
            if not selected: return OcrResult(error_code="tesseract_language_data_unavailable", source_frame_id=source_frame_id)
            language = "+".join(selected)
            with image_module.open(BytesIO(raw)) as image:
                if image.width<=0 or image.height<=0 or image.width*image.height>self.max_pixels:
                    return OcrResult(language=language,error_code="image_dimensions_rejected",source_frame_id=source_frame_id)
                image.thumbnail((1280,720))
                data = pytesseract.image_to_data(image,lang=language,config="--psm 6",
                    output_type=pytesseract.Output.DICT,timeout=self.timeout_seconds)
            words,scores=[],[]
            for word,score in zip(data.get("text",()),data.get("conf",())):
                value=" ".join(str(word or "").split())
                try: score=float(score)
                except (TypeError,ValueError): continue
                if value and score>=0: words.append(value); scores.append(score)
            confidence=sum(scores)/len(scores)/100 if scores else 0.0
            return OcrResult(" ".join(words),language,confidence,source_frame_id=source_frame_id)
        except ImportError: return OcrResult(error_code="ocr_dependency_unavailable",source_frame_id=source_frame_id)
        except Exception as exc: return OcrResult(error_code=type(exc).__name__,source_frame_id=source_frame_id)

class OcrService:
    """Engine registry and selection boundary, independent from capture and analysis."""
    def __init__(self, engines=None, *, selected_engine="tesseract"):
        self._engines=dict(engines or {"tesseract":TesseractOcrEngine()})
        if selected_engine not in self._engines: raise ValueError(f"Unknown OCR engine: {selected_engine}")
        self._selected_engine=selected_engine
    @property
    def selected_engine(self): return self._selected_engine
    def available_engines(self): return {n:e.diagnostics() for n,e in self._engines.items()}
    def select_engine(self,name):
        key=str(name or "").strip().lower()
        if key not in self._engines: raise ValueError(f"OCR engine is not registered: {key}")
        status=self._engines[key].diagnostics()
        if not status.get("ready"): raise RuntimeError(f"OCR engine is not ready: {status.get('error_code') or key}")
        self._selected_engine=key
        return status
    def diagnostics(self):
        engines=self.available_engines(); selected=engines[self._selected_engine]
        return {"selected_engine":self._selected_engine,"ready":bool(selected.get("ready")),
                "engines":engines,"languages":{"fas":bool(selected.get("persian_ready")),
                "eng":bool(selected.get("english_ready"))}}
    def recognize(self,image_bytes,cancel_event=None,*,source_frame_id=""):
        if cancel_event is not None and cancel_event.is_set():
            return OcrResult(error_code="cancelled",source_frame_id=source_frame_id)
        try:
            engine=self._engines[self._selected_engine]; status=engine.diagnostics()
            if not status.get("ready"):
                return OcrResult(error_code=status.get("error_code") or "ocr_engine_not_ready",source_frame_id=source_frame_id)
            result=engine.recognize(image_bytes,source_frame_id=source_frame_id)
            return result if isinstance(result,OcrResult) else OcrResult(text=str(result or ""),source_frame_id=source_frame_id)
        except Exception as exc: return OcrResult(error_code=type(exc).__name__,source_frame_id=source_frame_id)

def extract_local_text(image_attachment):
    """Backward-compatible helper routed through the service contract."""
    if not isinstance(image_attachment,dict) or not image_attachment.get("b64"): return ""
    try:
        encoded=str(image_attachment["b64"])
        if len(encoded)>30_000_000: return ""
        return OcrService().recognize(base64.b64decode(encoded,validate=True)).text
    except (ValueError,TypeError): return ""

if __name__=="__main__":
    import json
    print(json.dumps(OcrService().diagnostics(),ensure_ascii=False,indent=2))
