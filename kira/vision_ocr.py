"""Optional local OCR. No dependency is installed or downloaded by Kira.

Uses pytesseract + Pillow only when already available; otherwise returns an empty
string and visual-model analysis continues normally.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OcrResult:
    """Structured OCR output. Confidence is normalized to the inclusive range 0..1."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    error_code: str = ""

    def __post_init__(self):
        object.__setattr__(self, "text", " ".join(str(self.text or "").split())[:1100])
        object.__setattr__(self, "language", str(self.language or "")[:24])
        try:
            confidence = float(self.confidence or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))
        object.__setattr__(self, "error_code", str(self.error_code or "")[:48])


class OcrEngine(Protocol):
    """Replaceable local OCR contract; implementations never install their own dependencies."""

    def recognize(self, image_bytes: bytes) -> OcrResult: ...


class TesseractOcrEngine:
    """Optional Tesseract adapter. No OCR package or language data is downloaded."""

    def __init__(
        self, *, preferred_languages=("fas", "eng"), timeout_seconds: int = 3,
        max_image_bytes: int = 12 * 1024 * 1024, max_pixels: int = 15_000_000,
    ):
        self.preferred_languages = tuple(str(item) for item in preferred_languages)
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_image_bytes = max(1, int(max_image_bytes))
        self.max_pixels = max(1, int(max_pixels))
        self._languages = None

    def _available_languages(self, pytesseract):
        if self._languages is not None:
            return self._languages
        try:
            self._languages = frozenset(str(item) for item in pytesseract.get_languages(config=""))
        except Exception:
            self._languages = frozenset()
        return self._languages

    def recognize(self, image_bytes: bytes) -> OcrResult:
        raw = bytes(image_bytes or b"")
        if not raw:
            return OcrResult(error_code="empty_image")
        if len(raw) > self.max_image_bytes:
            return OcrResult(error_code="image_too_large")
        try:
            from io import BytesIO
            from PIL import Image
            import pytesseract

            available = self._available_languages(pytesseract)
            selected = [lang for lang in self.preferred_languages if lang in available]
            if not selected:
                return OcrResult(error_code="tesseract_or_language_data_unavailable")
            language = "+".join(selected)
            with Image.open(BytesIO(raw)) as image:
                if image.width <= 0 or image.height <= 0 or image.width * image.height > self.max_pixels:
                    return OcrResult(language=language, error_code="image_dimensions_rejected")
                image.thumbnail((1280, 720))
                payload = pytesseract.image_to_data(
                    image,
                    lang=language,
                    config="--psm 6",
                    output_type=pytesseract.Output.DICT,
                    timeout=self.timeout_seconds,
                )
            words, scores = [], []
            for word, raw_score in zip(payload.get("text", ()), payload.get("conf", ())):
                value = " ".join(str(word or "").split())
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    continue
                if value and score >= 0:
                    words.append(value)
                    scores.append(score)
            text = " ".join(words)[:1100]
            confidence = (sum(scores) / len(scores) / 100.0) if scores else 0.0
            return OcrResult(text, language, confidence)
        except ImportError:
            return OcrResult(error_code="ocr_dependency_unavailable")
        except Exception as exc:  # OCR is optional; native binary/language errors are non-fatal.
            return OcrResult(error_code=type(exc).__name__)



def extract_local_text(image_attachment: dict) -> str:
    if not isinstance(image_attachment, dict) or not image_attachment.get("b64"):
        return ""
    try:
        import base64
        from io import BytesIO
        from PIL import Image
        import pytesseract
        encoded = str(image_attachment["b64"])
        if len(encoded) > 30_000_000:  # skip oversized user attachments before decoding
            return ""
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                return ""
            image.thumbnail((1280, 720))
            text = pytesseract.image_to_string(image, config="--psm 6", timeout=4)
        return " ".join(str(text or "").split())[:2400]
    except Exception:
        return ""


