"""Tesseract image-recognition adapter backed by the separate native runtime manager."""
from __future__ import annotations

from io import BytesIO

from .vision_ocr import OcrResult
from .vision_ocr_runtime import TesseractRuntime


class TesseractOcrEngine:
    """Translate a validated native runtime into the replaceable OcrEngine contract."""

    name = "tesseract"

    def __init__(
        self,
        *,
        preferred_languages=("fas", "eng"),
        required_languages=None,
        timeout_seconds=3,
        max_image_bytes=12 * 1024 * 1024,
        max_pixels=15_000_000,
        executable=None,
        tessdata_dir=None,
        runtime=None,
    ):
        languages = required_languages if required_languages is not None else preferred_languages
        self.required_languages = tuple(dict.fromkeys(str(value) for value in languages))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_image_bytes = max(1, int(max_image_bytes))
        self.max_pixels = max(1, int(max_pixels))
        self.runtime = runtime or TesseractRuntime(
            required_languages=self.required_languages,
            timeout_seconds=max(1, int(timeout_seconds)),
            executable=executable,
            tessdata_dir=tessdata_dir,
        )

    def discover(self, *, refresh=False):
        return self.runtime.discover(refresh=refresh)

    def validate(self, *, refresh=False):
        return self.runtime.validate(refresh=refresh)

    def diagnostics(self):
        return self.runtime.diagnostics()

    def initialize(self):
        return bool(self.runtime.initialize().get("ready"))

    def shutdown(self):
        return self.runtime.shutdown()

    def _failure(self, code, stage, message, *, source_frame_id="", language=None):
        return OcrResult(
            language=language if language is not None else "+".join(self.required_languages),
            error_code=code,
            source_frame_id=source_frame_id,
            engine=self.name,
            error_stage=stage,
            error_message=message,
        )

    def recognize(self, image_bytes, *, source_frame_id=""):
        raw = bytes(image_bytes or b"")
        language = "+".join(self.required_languages)
        if not raw:
            return self._failure(
                "empty_image", "validation", "OCR input image is empty",
                source_frame_id=source_frame_id, language=language,
            )
        if len(raw) > self.max_image_bytes:
            return self._failure(
                "image_too_large", "validation", "OCR input exceeds the configured byte limit",
                source_frame_id=source_frame_id, language=language,
            )

        status = self.runtime.initialize()
        if not status.get("ready"):
            return self._failure(
                status.get("error_code") or "ocr_engine_not_ready",
                status.get("error_stage") or "initialization",
                status.get("error_message") or "Tesseract runtime did not become ready",
                source_frame_id=source_frame_id,
                language=language,
            )
        pytesseract = self.runtime.pytesseract
        image_module = self.runtime.image_module
        if pytesseract is None or image_module is None:
            return self._failure(
                "ocr_runtime_not_initialized", "initialization",
                "Tesseract Python adapters were not retained after initialization",
                source_frame_id=source_frame_id, language=language,
            )

        try:
            with image_module.open(BytesIO(raw)) as image:
                if image.width <= 0 or image.height <= 0 or image.width * image.height > self.max_pixels:
                    return self._failure(
                        "image_dimensions_rejected", "validation",
                        "OCR input dimensions are empty or exceed the configured pixel limit",
                        source_frame_id=source_frame_id, language=language,
                    )
                image.thumbnail((1280, 720))
                data = pytesseract.image_to_data(
                    image,
                    lang=language,
                    config=self.runtime.image_config(page_segmentation_mode=6),
                    output_type=pytesseract.Output.DICT,
                    timeout=self.timeout_seconds,
                )
            words, scores = [], []
            for word, score in zip(data.get("text", ()), data.get("conf", ())):
                value = " ".join(str(word or "").split())
                try:
                    score = float(score)
                except (TypeError, ValueError):
                    continue
                if value and score >= 0:
                    words.append(value)
                    scores.append(score)
            confidence = sum(scores) / len(scores) / 100 if scores else 0.0
            return OcrResult(
                text=" ".join(words),
                language=language,
                confidence=confidence,
                source_frame_id=source_frame_id,
                engine=self.name,
            )
        except Exception as exc:
            return self._failure(
                type(exc).__name__,
                "execution",
                str(exc) or "Tesseract failed while recognizing the image",
                source_frame_id=source_frame_id,
                language=language,
            )
