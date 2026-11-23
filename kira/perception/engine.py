"""Low-cost perception orchestration independent of Qt and model providers."""
from __future__ import annotations

from typing import Any

from .active_window import ActiveWindowProbe
from .change_detector import ChangeDetector
from ..vision_ocr import OcrResult


class PerceptionEngine:
    """Coordinate foreground facts, change detection and a replaceable local OCR engine."""

    def __init__(self, context, ocr_engine, *, probe=None, change_detector=None):
        if context is None or ocr_engine is None:
            raise TypeError("context and ocr_engine are required")
        self.context = context
        self.ocr_engine = ocr_engine
        self.probe = probe or ActiveWindowProbe()
        self.change_detector = change_detector or ChangeDetector()

    def observe_window(self, window_info: dict[str, Any] | None, *, source: str = "desktop") -> dict[str, Any] | None:
        normalized = self.probe.inspect(window_info)
        if normalized is None:
            self.context.clear_sensitive(reason="foreground_window_unidentified")
            self.change_detector.reset()
            return None
        changed = self.context.update_active_window(normalized, source=source)
        if changed:
            # A new app/window needs its own initial sample even when its pixels
            # resemble the previous foreground window.
            self.change_detector.reset()
        return normalized

    def screen_changed(self, sample: bytes) -> bool:
        return self.change_detector.changed(sample)

    def recognize(self, image_bytes: bytes, cancel_event=None) -> OcrResult:
        if cancel_event is not None and cancel_event.is_set():
            return OcrResult()
        try:
            result = self.ocr_engine.recognize(bytes(image_bytes or b""))
        except Exception as exc:  # OCR is optional and must never break capture/chat.
            return OcrResult(error_code=type(exc).__name__[:48])
        return result if isinstance(result, OcrResult) else OcrResult(text=str(result or "")[:1100])

    def apply_ocr(self, result: OcrResult, window_info: dict[str, Any] | None, *, source: str = "desktop") -> bool:
        if not isinstance(result, OcrResult) or not result.text.strip():
            return False
        normalized = self.probe.inspect(window_info)
        if normalized is None:
            return False
        return self.context.set_visible_text(
            result.text,
            language=result.language,
            confidence=result.confidence,
            window_key=self.probe.key(normalized),
            source=source,
        )
