"""Background Qt workers used by Kira's UI and application pages.

These adapters own thread execution and Qt signals only. Feature behavior is
provided by their injected callables or provider/service objects.
"""
from __future__ import annotations

import contextlib
import threading
import time

from PySide6.QtCore import QThread, Signal


class StreamWorker(QThread):
    """Runs one streamed request off the GUI thread. Everything the router reports becomes a Qt signal."""
    event = Signal(dict)            # phase changes with the REAL route (connecting / waiting / streaming / failover)
    chunk = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)
    tool_event = Signal(dict)       # a tool starts / ends (status line only)

    def __init__(self, router, messages, prompt, temperature, retry_index=0, agent=None, plan=None, role="", route_id=""):
        super().__init__()
        self.role, self.route_id = role, route_id                 # brain stage (kira/brain.py); "" = normal routing
        self.router, self.messages, self.prompt, self.temperature, self.retry_index = router, messages, prompt, temperature, retry_index
        self.agent, self.plan = agent, plan                       # tool loop (kira/tools); plan None = an ordinary chat turn

    def run(self):
        try:
            has_images = any(bool(item.get("images")) for item in (self.messages or []) if isinstance(item, dict))
            scope = getattr(self.router, "role_scope", None)
            # Establish the brain role first: vision_route_id() must see the role's
            # usage limits, and vision_scope() must be the innermost scope so its
            # selected Vision route is not overwritten by role_scope's preference.
            with (scope(self.role, self.route_id) if scope else contextlib.nullcontext()):
                if has_images:
                    vision_route = self.router.vision_route_id()
                    if not vision_route:
                        raise RuntimeError("برای تحلیل این تصویر هیچ مدل Vision فعالی در Route Manager پیدا نشد. یک مدل بینایی انتخاب کن.")
                    with self.router.vision_scope(vision_route):
                        result = self._run_request()
                else:
                    result = self._run_request()
            self.finished_ok.emit(result)
        except Exception as e:                                    # noqa: BLE001 - shown to the user, never crashes the UI
            self.failed.emit(str(e))

    def _run_request(self):
        if True:
            if self.agent is not None and self.plan is not None:
                result = self.agent.run(self.router, self.messages, self.prompt, self.temperature, self.plan, retry_index=self.retry_index,
                                        on_chunk=self.chunk.emit, on_event=self.event.emit, on_tool=self.tool_event.emit)
            else:
                result = self.router.chat_stream(self.messages, self.prompt, self.temperature, on_chunk=self.chunk.emit,
                                                 on_event=self.event.emit, retry_index=self.retry_index)
            return result



class AttachWorker(QThread):
    """Reads attachments off the GUI thread; each queued file can be cancelled independently."""
    progress = Signal(int, int)
    loaded = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(self, paths):
        super().__init__()
        self.paths = list(paths)
        self._cancelled = [threading.Event() for _ in self.paths]

    def cancel(self, index):
        if 0 <= int(index) < len(self._cancelled):
            self._cancelled[int(index)].set()

    def run(self):
        # Attachment parsing is only needed after the user chooses files.
        from ..chat import attachments as att

        for i, path in enumerate(self.paths):
            cancelled = self._cancelled[i]
            if cancelled.is_set():
                continue
            self.progress.emit(i, 0)
            try:
                attachment = att.load_attachment(
                    path, lambda pct, i=i: self.progress.emit(i, pct), cancelled=cancelled.is_set
                )
                if not cancelled.is_set():
                    self.loaded.emit(i, attachment)
            except (att.AttachmentError, OSError) as exc:
                if not cancelled.is_set():
                    self.failed.emit(i, str(exc))



class SearchWorker(QThread):
    """Web search (Tavily, then the fallbacks) off the GUI thread. done(token, ok, result-or-message)."""
    done = Signal(int, bool, object)

    def __init__(self, token, query, api_key, depth, rewrite=None, user_text=None, gemini=None, fallback=True,
                 images=None, describe=None):
        super().__init__()
        self.token, self.query, self.api_key, self.depth, self.rewrite = token, query, api_key, depth, rewrite
        self.gemini, self.fallback = gemini, fallback
        self.images, self.describe = images, describe          # picture search: the pictures + a callback that turns them into a query
        self.user_text = user_text or query

    def run(self):
        # Do not load search engines/providers while the chat window is being composed.
        from .. import websearch

        try:
            if self.images:                                           # search WITH a picture (Gemini sees it; the others get a text query)
                self.done.emit(self.token, True, websearch.image_research(self.images, self.user_text, self.api_key, self.depth,
                                                                         gemini=self.gemini, fallback=self.fallback, describe=self.describe))
                return
            query, evidence_text = self.query, self.user_text
            if self.rewrite:                                          # only for follow-ups ("نه بابا بهتر سرچ کن"): the chat gives the meaning
                try:
                    query = self.rewrite() or query
                    evidence_text = query
                except Exception:                                     # noqa: BLE001 - fall back to the plain query
                    query = self.query
            self.done.emit(self.token, True, websearch.research(query, self.api_key, self.depth, evidence_text,
                                                                          gemini=self.gemini, fallback=self.fallback))
        except websearch.SearchError as exc:
            self.done.emit(self.token, False, str(exc))
        except Exception as exc:                                      # noqa: BLE001 - search must never crash the chat
            self.done.emit(self.token, False, f"خطای جست‌وجو: {type(exc).__name__}")



class TaskWorker(QThread):
    """One blocking call off the GUI thread, optionally cooperatively cancellable."""
    done = Signal(object)

    def __init__(self, fn, *, cancellable=False):
        super().__init__()
        self.fn = fn
        self.cancellable = bool(cancellable)
        self._cancel_event = threading.Event()

    def cancel(self):
        """Request cancellation; cancellable callables receive the event."""
        if self.cancellable:
            self._cancel_event.set()

    def run(self):
        try:
            result = self.fn(self._cancel_event) if self.cancellable else self.fn()
        except Exception as exc:                                  # noqa: BLE001
            if not self._cancel_event.is_set():
                self.done.emit((False, str(exc)[:400]))
        else:
            if not self._cancel_event.is_set():
                self.done.emit((True, result))



class BenchWorker(QThread):
    progress = Signal(dict)
    done = Signal(object)

    def __init__(self, router, route_ids):
        super().__init__()
        self.router, self.route_ids = router, list(route_ids)

    def run(self):
        try:
            rows = self.router.benchmark(self.route_ids, on_progress=self.progress.emit)
            self.done.emit((True, rows))
        except Exception as exc:                                  # noqa: BLE001
            self.done.emit((False, str(exc)[:400]))



class ProviderTestWorker(QThread):
    done = Signal(str, bool, str)

    def __init__(self, name, config):
        super().__init__()
        self.name, self.config = name, dict(config)

    def run(self):
        # Key check, model check and one real chat request live in hybrid_ai.probe_provider (unit-tested with mocks).
        try:
            from ..hybrid_ai import probe_provider

            ok, detail = probe_provider(self.name, self.config)
        except Exception as exc:
            ok, detail = False, str(exc)[:500]
        self.done.emit(self.name, ok, detail)



class VisionAnalysisWorker(QThread):
    """Bounded image analysis; uses only a route marked/recognized as Vision-capable."""
    done = Signal(bool, str, int)

    def __init__(self, router, image, context=""):
        super().__init__()
        self.router = router
        self.image = dict(image)
        self.context = str(context or "").strip()[:1200]
        self._cancelled = threading.Event()

    def cancel_request(self):
        self._cancelled.set()
        # HybridRouter closes the active HTTP response, which interrupts network waits.
        try:
            self.router.cancel()
        except Exception:
            pass

    def run(self):
        began = time.monotonic()
        try:
            if self._cancelled.is_set():
                return
            route_id = self.router.vision_route_id()
            if self._cancelled.is_set():
                return
            if not route_id:
                raise RuntimeError("هیچ مدل Vision فعالی پیدا نشد. یک Route بینایی انتخاب کن یا برای Provider سفارشی vision_enabled را فعال کن.")
            from ..vision_ocr import extract_local_text
            ocr_text = extract_local_text(self.image)
            prompt = (
                "این تصویر، فریم بازی کاربر است. فقط شواهد قابل مشاهده را گزارش کن و حدس نزن. "
                "اگر متن OCR در اختیار داری، آن را به‌عنوان سرنخ کمکی در نظر بگیر، نه حقیقت قطعی. "
                "اگر زمینه یا سؤال کاربر داده شده، دقیقاً به همان پاسخ بده؛ در غیر این صورت وضعیت، خطر، هدف و اقدام فوری را کوتاه بگو.\n"
                + (("زمینه/سؤال کاربر: " + self.context + "\n") if self.context else "")
                + (("متن استخراج‌شده‌ی محلی از تصویر: " + ocr_text[:1800]) if ocr_text else "")
            )
            if self._cancelled.is_set():
                return
            with self.router.vision_scope(route_id):
                response = self.router.chat_stream(
                    [{"role": "user", "content": self.context or "فریم فعلی بازی را بررسی کن.", "images": [self.image]}],
                    prompt, 0.2, cancel_event=self._cancelled,
                )
            if self._cancelled.is_set():
                return
            if isinstance(response, dict):
                if response.get("interrupted") or response.get("stopped"):
                    raise RuntimeError("تحلیل Vision پیش از تکمیل متوقف شد.")
                result = response.get("text", "")
            else:
                result = response
            if not self._cancelled.is_set():
                self.done.emit(True, str(result or "").strip(), int((time.monotonic() - began) * 1000))
        except Exception as exc:
            if not self._cancelled.is_set():
                self.done.emit(False, str(exc)[:350], int((time.monotonic() - began) * 1000))



class OllamaTaskWorker(QThread):
    """Runs one blocking Ollama call off the GUI thread. fn() returns (ok, text) or raises."""
    done = Signal(bool, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            ok, text = self.fn()
        except Exception as exc:
            ok, text = False, str(exc)[:500]
        self.done.emit(bool(ok), str(text))


