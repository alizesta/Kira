"""Independent tests for the Qt-free Chat Response Handler."""
import threading
import unittest
from pathlib import Path

from kira.chat.response_handler import (
    ChatResponseResult,
    ProviderEvent,
    ResponseEventKind,
    ResponseHandler,
    ResponseStatus,
)


class ResponseHandlerTests(unittest.TestCase):
    def setUp(self):
        self.handler = ResponseHandler()

    def test_streamed_response_preserves_chunk_order_and_completes_once(self):
        self.handler.begin_request("req-1", "kira")
        first = self.handler.handle(ProviderEvent.chunk("req-1", "kira", "hello "))
        second = self.handler.handle(ProviderEvent.chunk("req-1", "kira", "world"))
        final = self.handler.handle(
            ProviderEvent.completed("req-1", "kira", {"text": "hello world", "provider": "mock"})
        )

        self.assertEqual(first.kind, ResponseEventKind.CHUNK)
        self.assertEqual(first.content, "hello ")
        self.assertEqual(second.content, "hello world")
        self.assertEqual(final.kind, ResponseEventKind.FINAL)
        self.assertIsInstance(final.result, ChatResponseResult)
        self.assertEqual(final.result.status, ResponseStatus.COMPLETED)
        self.assertEqual(final.result.content, "hello world")
        self.assertEqual(final.result.metadata["provider"], "mock")
        self.assertEqual(final.result.metadata["chunk_count"], 2)
        self.assertEqual(self.handler.active_request_count, 0)

    def test_non_streamed_response_uses_final_provider_content(self):
        self.handler.begin_request("req-1", "ren")
        final = self.handler.handle(
            ProviderEvent.completed("req-1", "ren", {"text": "one-shot"})
        )
        self.assertEqual(final.result.content, "one-shot")
        self.assertFalse(final.result.metadata["streamed"])
        self.assertEqual(final.result.metadata["chunk_count"], 0)

    def test_empty_response_is_completed_and_explicitly_marked_empty(self):
        self.handler.begin_request("req-1", "mika")
        final = self.handler.handle(ProviderEvent.completed("req-1", "mika", {"text": ""}))
        self.assertEqual(final.result.status, ResponseStatus.COMPLETED)
        self.assertEqual(final.result.content, "")
        self.assertTrue(final.result.metadata["empty_response"])

    def test_provider_error_mid_stream_keeps_partial_content_and_cleans_state(self):
        self.handler.begin_request("req-1", "kira")
        self.handler.handle(ProviderEvent.chunk("req-1", "kira", "partial"))
        final = self.handler.handle(
            ProviderEvent.failed("req-1", "kira", "connection reset", recoverable=True)
        )
        self.assertEqual(final.result.status, ResponseStatus.FAILED)
        self.assertEqual(final.result.content, "partial")
        self.assertEqual(final.result.error.code, "provider_error")
        self.assertEqual(final.result.error.message, "connection reset")
        self.assertTrue(final.result.error.recoverable)
        self.assertTrue(final.result.metadata["incomplete"])
        self.assertEqual(self.handler.active_request_count, 0)

    def test_cancelled_request_preserves_received_content(self):
        self.handler.begin_request("req-1", "ren")
        self.handler.handle(ProviderEvent.chunk("req-1", "ren", "partial"))
        final = self.handler.handle(ProviderEvent.cancelled("req-1", "ren"))
        self.assertEqual(final.result.status, ResponseStatus.CANCELLED)
        self.assertEqual(final.result.content, "partial")
        self.assertTrue(final.result.metadata["incomplete"])

    def test_provider_completed_stopped_response_maps_to_cancelled(self):
        self.handler.begin_request("req-1", "ren")
        final = self.handler.handle(
            ProviderEvent.completed("req-1", "ren", {"text": "partial", "stopped": True})
        )
        self.assertEqual(final.result.status, ResponseStatus.CANCELLED)
        self.assertEqual(final.result.content, "partial")

    def test_interrupted_provider_response_maps_to_failed(self):
        self.handler.begin_request("req-1", "mika")
        final = self.handler.handle(
            ProviderEvent.completed(
                "req-1", "mika", {"text": "cut off", "interrupted": "socket closed"}
            )
        )
        self.assertEqual(final.result.status, ResponseStatus.FAILED)
        self.assertEqual(final.result.content, "cut off")
        self.assertEqual(final.result.error.code, "provider_interrupted")
        self.assertIn("interrupted", final.result.metadata)

    def test_duplicate_terminal_and_late_chunk_are_ignored(self):
        self.handler.begin_request("req-1", "kira")
        first = self.handler.handle(
            ProviderEvent.completed("req-1", "kira", {"text": "done"})
        )
        duplicate = self.handler.handle(ProviderEvent.cancelled("req-1", "kira"))
        late_chunk = self.handler.handle(ProviderEvent.chunk("req-1", "kira", "late"))
        self.assertEqual(first.result.status, ResponseStatus.COMPLETED)
        self.assertIsNone(duplicate)
        self.assertIsNone(late_chunk)
        self.assertEqual(self.handler.active_request_count, 0)

    def test_session_mismatch_cannot_consume_or_mutate_request(self):
        self.handler.begin_request("req-1", "ren")
        rejected = self.handler.handle(ProviderEvent.chunk("req-1", "mika", "leak"))
        accepted = self.handler.handle(ProviderEvent.chunk("req-1", "ren", "right"))
        final = self.handler.handle(
            ProviderEvent.completed("req-1", "ren", {"text": "right"})
        )
        self.assertIsNone(rejected)
        self.assertEqual(accepted.content, "right")
        self.assertEqual(final.result.session_id, "ren")
        self.assertEqual(final.result.content, "right")

    def test_two_sessions_stream_concurrently_without_cross_talk(self):
        self.handler.begin_request("ren-1", "ren")
        self.handler.begin_request("mika-1", "mika")
        barrier = threading.Barrier(2)
        received = {}

        def stream(request_id, session_id, first, second):
            a = self.handler.handle(ProviderEvent.chunk(request_id, session_id, first))
            barrier.wait(timeout=2)
            b = self.handler.handle(ProviderEvent.chunk(request_id, session_id, second))
            c = self.handler.handle(
                ProviderEvent.completed(request_id, session_id, {"text": first + second})
            )
            received[session_id] = (a.content, b.content, c.result.content)

        threads = [
            threading.Thread(target=stream, args=("ren-1", "ren", "R", "en")),
            threading.Thread(target=stream, args=("mika-1", "mika", "M", "ika")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

        self.assertEqual(received["ren"], ("R", "Ren", "Ren"))
        self.assertEqual(received["mika"], ("M", "Mika", "Mika"))
        self.assertEqual(self.handler.active_request_count, 0)

    def test_stream_cutoff_cleans_state_and_rejects_late_provider_event(self):
        self.handler.begin_request("req-1", "kira")
        self.handler.handle(ProviderEvent.chunk("req-1", "kira", "unfinished"))
        failed = self.handler.handle(ProviderEvent.failed("req-1", "kira", "stream closed"))
        self.assertEqual(failed.result.content, "unfinished")
        self.assertEqual(failed.result.status, ResponseStatus.FAILED)
        self.assertIsNone(
            self.handler.handle(ProviderEvent.completed("req-1", "kira", {"text": "late"}))
        )
        self.assertEqual(self.handler.active_request_count, 0)

    def test_module_has_no_qt_or_legacy_window_dependency(self):
        source = (Path(__file__).parents[1] / "kira" / "chat" / "response_handler.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("PySide6", "MainWindow", "oldmain", "QApplication", "QWidget"):
            self.assertNotIn(forbidden, source)


    def test_failure_in_one_session_does_not_interrupt_another_active_request(self):
        self.handler.begin_request("ren-1", "ren")
        self.handler.begin_request("mika-1", "mika")
        self.handler.handle(ProviderEvent.chunk("ren-1", "ren", "partial ren"))
        self.handler.handle(ProviderEvent.chunk("mika-1", "mika", "Mika"))

        failed = self.handler.handle(
            ProviderEvent.failed("ren-1", "ren", "ren provider failed")
        )
        still_active = self.handler.handle(
            ProviderEvent.chunk("mika-1", "mika", " is active")
        )
        completed = self.handler.handle(
            ProviderEvent.completed("mika-1", "mika", {"text": "Mika is active"})
        )

        self.assertEqual(failed.result.status, ResponseStatus.FAILED)
        self.assertEqual(failed.result.content, "partial ren")
        self.assertEqual(still_active.content, "Mika is active")
        self.assertEqual(completed.result.status, ResponseStatus.COMPLETED)
        self.assertEqual(completed.result.session_id, "mika")
        self.assertEqual(self.handler.active_request_count, 0)

    def test_concurrent_duplicate_terminal_callbacks_emit_only_one_final_result(self):
        self.handler.begin_request("req-1", "kira")
        barrier = threading.Barrier(2)
        results = []

        def finish(event):
            barrier.wait(timeout=2)
            results.append(self.handler.handle(event))

        threads = [
            threading.Thread(
                target=finish,
                args=(ProviderEvent.completed("req-1", "kira", {"text": "done"}),),
            ),
            threading.Thread(
                target=finish,
                args=(ProviderEvent.cancelled("req-1", "kira"),),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

        final_results = [item for item in results if item is not None]
        self.assertEqual(len(final_results), 1)
        self.assertEqual(final_results[0].kind, ResponseEventKind.FINAL)
        self.assertEqual(self.handler.active_request_count, 0)


if __name__ == "__main__":
    unittest.main()
