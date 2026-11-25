"""Qt-independent execution adapter for Vision-capable AI providers."""
from __future__ import annotations


class VisionProviderExecutor:
    """Execute one routed Vision request without owning capture, UI or frame lifecycle."""

    def __init__(self, router):
        if router is None:
            raise ValueError("a Vision router is required")
        self.router = router

    def execute(self, image, *, context="", ocr_text="", cancel_event=None):
        def cancelled():
            return bool(cancel_event is not None and cancel_event.is_set())

        if cancelled():
            raise RuntimeError("Vision request cancelled")
        route_id = self.router.vision_route_id()
        if cancelled():
            raise RuntimeError("Vision request cancelled")
        if not route_id:
            raise RuntimeError(
                "هیچ مدل Vision فعالی پیدا نشد. یک Route بینایی انتخاب کن یا برای Provider سفارشی vision_enabled را فعال کن."
            )
        question = str(context or "").strip()[:1200]
        prompt = (
            "این تصویر، فریم بازی کاربر است. فقط شواهد قابل مشاهده را گزارش کن و حدس نزن. "
            "اگر متن OCR در اختیار داری، آن را به‌عنوان سرنخ کمکی در نظر بگیر، نه حقیقت قطعی. "
            "اگر زمینه یا سؤال کاربر داده شده، دقیقاً به همان پاسخ بده؛ در غیر این صورت وضعیت، خطر، هدف و اقدام فوری را کوتاه بگو.\n"
            + (("زمینه/سؤال کاربر: " + question + "\n") if question else "")
            + (("متن استخراج‌شده‌ی محلی از تصویر: " + str(ocr_text or "")[:1800]) if ocr_text else "")
        )
        with self.router.vision_scope(route_id):
            response = self.router.chat_stream(
                [{
                    "role": "user",
                    "content": question or "فریم فعلی بازی را بررسی کن.",
                    "images": [image],
                }],
                prompt,
                0.2,
                cancel_event=cancel_event,
            )
        if cancelled():
            raise RuntimeError("Vision request cancelled")
        if isinstance(response, dict):
            if response.get("interrupted") or response.get("stopped"):
                raise RuntimeError("تحلیل Vision پیش از تکمیل متوقف شد.")
            response = response.get("text", "")
        return str(response or "").strip()
