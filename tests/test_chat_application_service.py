import base64
import tempfile
import threading
import time
import unittest
from pathlib import Path

from kira.chat.application_service import (
    ApplicationEventKind,
    ChatApplicationService,
    RequestStatus,
)
from kira.chat.response_handler import ProviderEvent
from kira.app.event_bus import EventBus
from kira.chat.events import ChatEventPublisher, ChatEventType
from kira.chat.attachments import AttachmentManager, AttachmentStatus
from kira.chat.commands import CommandDefinition, CommandRegistry, CommandStatus


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class FakeWorker:
    def __init__(self, **request):
        self.request = request
        self.tool_event = Signal()
        self.event = Signal()
        self.chunk = Signal()
        self.finished_ok = Signal()
        self.failed = Signal()
        self.started = False
        self._event_signals = {
            "tool_event": self.tool_event,
            "event": self.event,
            "chunk": self.chunk,
            "complete": self.finished_ok,
            "error": self.failed,
        }

    def subscribe(self, event, callback):
        signal = self._event_signals[event]
        signal.connect(callback)
        return lambda: signal.callbacks.remove(callback) if callback in signal.callbacks else False

    def start(self):
        self.started = True


class FakePersistence:
    def __init__(self, *, result=True, error=None):
        self.result = result
        self.error = error
        self.messages = []
        self.conversations = {}
        self.history_calls = []
        self.flush_result = 0
        self.flush_error = None

    @property
    def last_error(self):
        return self.error

    def get_or_create_conversation(self, character_id=None):
        return self.conversations.setdefault(
            str(character_id), {"id": f"{character_id}-conversation"}
        )

    def recent_messages(self, limit=12, character_id=None, conversation_id=None):
        self.history_calls.append(("recent", limit, character_id, conversation_id))
        return []

    def conversation_context(self, limit=12, max_chars=12000, character_id=None, conversation_id=None):
        self.history_calls.append(("context", limit, max_chars, character_id, conversation_id))
        return []

    def message_count(self, character_id=None, conversation_id=None):
        self.history_calls.append(("count", character_id, conversation_id))
        return 0

    def add_message(self, role, content, character_id=None, **options):
        self.messages.append((role, content, character_id, options))
        return self.result

    def flush_pending(self):
        if self.flush_error is not None:
            raise self.flush_error
        return self.flush_result


class ChatApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.persistence = FakePersistence()
        self.dispatched = []
        self.events = []
        self.workers = []
        self.scheduled = []
        self.cancelled = []
        self.service = ChatApplicationService(
            persistence=self.persistence,
            system_prompt_builder=lambda settings, **_kwargs: "system:" + settings.get("label", ""),
            worker_factory=self._worker_factory,
            on_dispatch=self.dispatched.append,
            on_event=self.events.append,
            schedule=self.scheduled.append,
            cancel_provider=lambda request, worker: self.cancelled.append((request.request_id, worker)),
        )

    def _worker_factory(self, **request):
        worker = FakeWorker(**request)
        self.workers.append(worker)
        return worker

    def _context(self, label="test"):
        return {
            "messages": [{"role": "user", "content": "hello"}],
            "character_id": "kira",
            "settings": {"label": label},
            "tool_context": "tools injected",
        }

    def _start_provider(self, submission):
        return self.service.start_provider_request(
            submission.request.request_id,
            self._context(),
            router=object(),
            temperature=0.5,
            provider_callbacks={"event": lambda _event: None, "tool_event": lambda _event: None},
        )


    def test_attachment_composition_and_limit_are_owned_by_chat_service(self):
        self.assertEqual(self.service.max_attachments, 5)
        prepared = self.service.compose_attachments(
            "read this",
            [{"name": "note.txt", "kind": "text", "text": "attachment body"}],
        )
        self.assertEqual(prepared["display"], "read this\n📎 note.txt")
        self.assertIn("attachment body", prepared["model"])
        self.assertIn("attachment body", prepared["stored"])
        self.assertEqual(prepared["images"], [])

        with tempfile.TemporaryDirectory() as temp:
            manager = AttachmentManager(Path(temp) / "limited", max_files=2)
            service = ChatApplicationService(
                persistence=self.persistence,
                system_prompt_builder=lambda *_args, **_kwargs: "",
                worker_factory=self._worker_factory,
                on_dispatch=self.dispatched.append,
                attachment_manager=manager,
            )
            try:
                self.assertEqual(service.max_attachments, 2)
            finally:
                service.dispose()
                manager.close()

    def test_request_attachments_use_managed_storage_and_are_cleaned_at_terminal(self):
        image = base64.b64encode(
            base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
        ).decode("ascii")
        with tempfile.TemporaryDirectory() as temp:
            manager = AttachmentManager(Path(temp) / "managed")
            service = ChatApplicationService(
                persistence=self.persistence,
                system_prompt_builder=lambda *_args, **_kwargs: "",
                worker_factory=self._worker_factory,
                on_dispatch=self.dispatched.append,
                attachment_manager=manager,
            )
            submission = service.submit_message(
                "kira", "describe these",
                [
                    {"name": "pixel.png", "kind": "image", "mime": "image/png", "b64": image},
                    {"name": "note.txt", "kind": "text", "text": "attachment text"},
                ],
            )
            ids = service._request_attachment_ids[submission.request.request_id]
            paths = [manager.get_attachment(item, session_id="kira").path for item in ids]
            prepared = service.prepare_request_attachments(
                submission.request.request_id, text="describe these"
            )
            self.assertEqual(prepared["prepared_count"], 2)
            self.assertEqual(len(prepared["images"]), 1)
            self.assertIn("attachment text", prepared["files"][0]["text"])
            self.assertTrue(all(Path(path).exists() for path in paths))
            service.complete_local_request(submission.request.request_id)
            self.assertTrue(all(not Path(path).exists() for path in paths))
            self.assertTrue(all(
                manager.get_attachment(item, session_id="kira") is None for item in ids
            ))
            service.dispose()

    def test_queued_coordinator_requests_keep_stable_request_and_session_ids(self):
        first = self.service.submit_message("runtime-kira", "first", busy=True)
        second = self.service.submit_message("runtime-kira", "second", busy=True)
        coordinator = self.service._coordinators["runtime-kira"]
        queued_first = coordinator.take_next()
        queued_second = coordinator.take_next()
        self.assertEqual(queued_first.request_id, first.request.request_id)
        self.assertEqual(queued_first.session_id, "runtime-kira")
        self.assertEqual(queued_second.request_id, second.request.request_id)
        self.assertEqual(queued_second.session_id, "runtime-kira")
        self.assertNotIn("_chat_request_ids", vars(self.service))

    def test_submit_dispatches_and_preserves_request_and_session_identity(self):
        submission = self.service.submit_message("kira", "hello")
        self.assertTrue(submission.accepted)
        self.assertFalse(submission.queued)
        self.assertEqual(submission.status, RequestStatus.RUNNING)
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0].request_id, submission.request.request_id)
        self.assertEqual(self.dispatched[0].session_id, "kira")
        self.assertEqual(
            self.service.get_request_status(submission.request.request_id),
            RequestStatus.RUNNING,
        )

    def test_runtime_session_identity_is_separate_from_persisted_character_identity(self):
        submission = self.service.submit_message(
            "runtime-session-123", "hello", character_id="kira",
            conversation_id="kira-conversation",
        )
        self.assertEqual(submission.request.session_id, "runtime-session-123")
        self.assertEqual(submission.request.character_id, "kira")
        self.assertEqual(self.dispatched[0].session_id, "runtime-session-123")

        outcome = self.service.complete_request(submission.request.request_id, "answer")
        self.assertTrue(outcome.ok)
        role, content, character_id, options = self.persistence.messages[0]
        self.assertEqual((role, content, character_id), ("assistant", "answer", "kira"))
        self.assertEqual(options["conversation_id"], "kira-conversation")
        self.assertEqual(options["metadata"]["session_id"], "runtime-session-123")
        self.assertEqual(options["metadata"]["character_id"], "kira")

    def test_context_provider_response_and_persistence_are_composed(self):
        submission = self.service.submit_message("kira", "hello")
        worker = self._start_provider(submission)
        self.assertTrue(worker.started)
        self.assertEqual(worker.request["messages"][0]["content"], "hello")
        self.assertEqual(worker.request["prompt"], "system:test\n\ntools injected")

        worker.chunk.emit("wor")
        worker.chunk.emit("ld")
        worker.finished_ok.emit({"text": "world", "provider": "fake"})

        chunks = [e for e in self.events if e.kind is ApplicationEventKind.PROVIDER_CHUNK]
        self.assertEqual([event.chunk for event in chunks], ["wor", "ld"])
        provider_final = [e for e in self.events if e.kind is ApplicationEventKind.PROVIDER_FINAL]
        self.assertEqual(len(provider_final), 1)
        self.assertEqual(provider_final[0].request_id, submission.request.request_id)
        self.assertEqual(provider_final[0].session_id, "kira")
        outcome = self.service.complete_request(submission.request.request_id, "world")
        self.assertTrue(outcome.ok)
        self.assertEqual(self.persistence.messages[0][0:3], ("assistant", "world", "kira"))
        self.assertEqual(self.service.get_request_status(submission.request.request_id), RequestStatus.COMPLETED)
        self.assertEqual(self.events[-1].kind, ApplicationEventKind.REQUEST_COMPLETED)

    def test_fifo_queue_is_per_session_and_dispatches_after_completion(self):
        first = self.service.submit_message("kira", "first")
        second = self.service.submit_message("kira", "second")
        other = self.service.submit_message("ren", "parallel")
        self.assertFalse(first.queued)
        self.assertTrue(second.queued)
        self.assertFalse(other.queued)
        self.assertEqual(len(self.dispatched), 2)
        self.service.complete_local_request(first.request.request_id)
        self.assertTrue(self.service.dispatch_next("kira"))
        self.assertEqual(len(self.scheduled), 1)
        self.scheduled.pop()()
        self.assertEqual(len(self.dispatched), 3)
        self.assertEqual(self.dispatched[-1].text, "second")
        self.assertEqual(self.dispatched[-1].session_id, "kira")

    def test_session_isolation_allows_parallel_requests(self):
        kira = self.service.submit_message("kira", "one")
        ren = self.service.submit_message("ren", "two")
        self.assertEqual(self.service.active_request_id("kira"), kira.request.request_id)
        self.assertEqual(self.service.active_request_id("ren"), ren.request.request_id)
        self.assertEqual(len(self.dispatched), 2)

    def test_queue_limit_rejects_excess_pending_request(self):
        self.service = ChatApplicationService(
            persistence=self.persistence,
            system_prompt_builder=lambda *_a, **_k: "",
            worker_factory=self._worker_factory,
            on_dispatch=self.dispatched.append,
            max_pending=1,
        )
        self.service.submit_message("kira", "active")
        queued = self.service.submit_message("kira", "queued")
        rejected = self.service.submit_message("kira", "overflow")
        self.assertTrue(queued.accepted)
        self.assertTrue(queued.queued)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.status, RequestStatus.FAILED)

    def test_provider_failure_finalizes_only_its_own_session(self):
        kira = self.service.submit_message("kira", "bad")
        ren = self.service.submit_message("ren", "good")
        worker = self._start_provider(kira)
        worker.failed.emit("provider offline")
        self.assertEqual(self.service.get_request_status(kira.request.request_id), RequestStatus.FAILED)
        self.assertEqual(self.service.get_request_status(ren.request.request_id), RequestStatus.RUNNING)
        self.assertEqual(self.events[-1].kind, ApplicationEventKind.REQUEST_FAILED)

    def test_cancel_routes_to_provider_and_marks_request_cancelled(self):
        submission = self.service.submit_message("kira", "cancel me")
        worker = self._start_provider(submission)
        self.assertTrue(self.service.cancel_request(submission.request.request_id))
        self.assertEqual(self.cancelled, [(submission.request.request_id, worker)])
        self.assertEqual(self.service.get_request_status(submission.request.request_id), RequestStatus.CANCELLED)
        self.assertEqual(self.events[-1].kind, ApplicationEventKind.REQUEST_CANCELLED)

    def test_pending_request_can_be_cancelled_without_dispatch(self):
        self.service.submit_message("kira", "active")
        pending = self.service.submit_message("kira", "pending")
        self.assertTrue(self.service.cancel_request(pending.request.request_id))
        self.assertEqual(self.service.get_request_status(pending.request.request_id), RequestStatus.CANCELLED)
        self.assertEqual(len(self.dispatched), 1)

    def test_duplicate_terminal_provider_event_is_ignored(self):
        submission = self.service.submit_message("kira", "hello")
        worker = self._start_provider(submission)
        worker.finished_ok.emit({"text": "ok"})
        worker.finished_ok.emit({"text": "duplicate"})
        finals = [e for e in self.events if e.kind is ApplicationEventKind.PROVIDER_FINAL]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0].content, "ok")

    def test_persistence_failure_is_reported_without_hiding_result(self):
        self.persistence.result = False
        self.persistence.error = "disk unavailable"
        submission = self.service.submit_message("kira", "hello")
        outcome = self.service.complete_request(submission.request.request_id, "answer")
        self.assertFalse(outcome.ok)
        self.assertEqual(self.service.get_request_status(submission.request.request_id), RequestStatus.COMPLETED)
        self.assertTrue(any(e.kind is ApplicationEventKind.PERSISTENCE_WARNING for e in self.events))

    def test_close_session_cancels_and_releases_only_that_session(self):
        kira = self.service.submit_message("kira", "active")
        queued = self.service.submit_message("kira", "queued", busy=True)
        ren = self.service.submit_message("ren", "keep")
        self.service.close_session("kira")
        self.assertEqual(self.service.get_request_status(kira.request.request_id), RequestStatus.CANCELLED)
        self.assertEqual(self.service.get_request_status(queued.request.request_id), RequestStatus.CANCELLED)
        self.assertEqual(self.service.pending_count("kira"), 0)
        self.assertEqual(self.service.get_request_status(ren.request.request_id), RequestStatus.RUNNING)
        self.assertIsNone(self.service.active_request_id("kira"))
        self.assertEqual(self.service.active_request_id("ren"), ren.request.request_id)

    def test_dispatch_callback_exception_isolated_to_one_request(self):
        self.service = ChatApplicationService(
            persistence=self.persistence,
            system_prompt_builder=lambda *_a, **_k: "",
            worker_factory=self._worker_factory,
            on_dispatch=lambda _request: (_ for _ in ()).throw(RuntimeError("dispatch failed")),
        )
        submission = self.service.submit_message("kira", "fails")
        self.assertEqual(self.service.get_request_status(submission.request.request_id), RequestStatus.FAILED)

    def test_provider_events_can_be_dispatched_through_a_thread_marshalling_port(self):
        dispatched = []
        submission = self.service.submit_message("kira", "hello")
        worker = self.service.start_provider_request(
            submission.request.request_id,
            self._context(),
            provider_event_dispatcher=dispatched.append,
            router=object(),
        )
        worker.chunk.emit("thread-safe")
        self.assertEqual(len(dispatched), 1)
        self.assertIsInstance(dispatched[0], ProviderEvent)
        self.assertEqual(dispatched[0].session_id, "kira")
        normalized = self.service.handle_provider_event(dispatched.pop())
        self.assertEqual(normalized.kind, ApplicationEventKind.PROVIDER_CHUNK)
        self.assertEqual(normalized.chunk, "thread-safe")

    def test_context_builder_failure_finalizes_request(self):
        service = ChatApplicationService(
            persistence=self.persistence,
            system_prompt_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("prompt failed")),
            worker_factory=self._worker_factory,
            on_dispatch=lambda _request: None,
            on_event=self.events.append,
        )
        submission = service.submit_message("kira", "hello")
        worker = service.start_provider_request(
            submission.request.request_id, self._context(), router=object()
        )
        self.assertIsNone(worker)
        self.assertEqual(service.get_request_status(submission.request.request_id), RequestStatus.FAILED)
        self.assertEqual(self.events[-1].kind, ApplicationEventKind.REQUEST_FAILED)
        self.assertIn("prompt failed", self.events[-1].error)

    def test_cross_session_provider_event_cannot_complete_another_session(self):
        submission = self.service.submit_message("kira", "hello")
        worker = self._start_provider(submission)
        worker.chunk.emit("private")
        attempt_id = f"{submission.request.request_id}:1"
        ignored = self.service.handle_provider_event(
            ProviderEvent.completed(attempt_id, "ren", {"text": "wrong session"})
        )
        self.assertIsNone(ignored)
        self.assertEqual(self.service.get_request_status(submission.request.request_id), RequestStatus.RUNNING)

    def test_complete_request_is_exactly_once(self):
        submission = self.service.submit_message("kira", "hello")
        first = self.service.complete_request(submission.request.request_id, "answer")
        second = self.service.complete_request(submission.request.request_id, "duplicate")
        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(len(self.persistence.messages), 1)

    def test_provider_worker_factory_failure_finalizes_request(self):
        service = ChatApplicationService(
            persistence=self.persistence,
            system_prompt_builder=lambda *_args, **_kwargs: "prompt",
            worker_factory=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("worker factory failed")),
            on_dispatch=lambda _request: None,
            on_event=self.events.append,
        )
        submission = service.submit_message("kira", "hello")
        worker = service.start_provider_request(submission.request.request_id, self._context())
        self.assertIsNone(worker)
        self.assertEqual(service.get_request_status(submission.request.request_id), RequestStatus.FAILED)
        self.assertIn("worker factory failed", self.events[-1].error)

    def test_flush_pending_history_delegates_and_propagates_storage_errors(self):
        self.persistence.flush_result = 3
        self.assertEqual(self.service.flush_pending_history(), 3)
        self.persistence.flush_error = OSError("disk is still unavailable")
        with self.assertRaisesRegex(OSError, "disk is still unavailable"):
            self.service.flush_pending_history()

    def test_dispose_releases_sessions_and_rejects_new_requests(self):
        self.service.submit_message("kira", "active")
        self.service.submit_message("ren", "queued", force_queue=True)
        self.service.dispose()
        self.assertFalse(self.service.has_active_request("kira"))
        self.assertEqual(self.service.pending_count("ren"), 0)
        with self.assertRaisesRegex(RuntimeError, "disposed"):
            self.service.submit_message("mika", "after shutdown")

    def test_conversation_identity_is_preserved_for_history_and_persistence(self):
        conversation = self.service.get_or_create_conversation("kira")
        conversation_id = conversation["id"]
        submission = self.service.submit_message(
            "kira", "hello", conversation_id=conversation_id
        )

        outcome = self.service.complete_request(submission.request.request_id, "answer")
        self.assertTrue(outcome.ok)
        self.assertEqual(submission.request.conversation_id, conversation_id)
        self.assertEqual(self.persistence.messages[0][3]["conversation_id"], conversation_id)

        self.service.recent_messages(8, "kira", conversation_id)
        self.service.conversation_context(8, 4000, "kira", conversation_id)
        self.service.message_count("kira", conversation_id)
        self.assertEqual(
            self.persistence.history_calls,
            [
                ("recent", 8, "kira", conversation_id),
                ("context", 8, 4000, "kira", conversation_id),
                ("count", "kira", conversation_id),
            ],
        )

    def test_begin_shutdown_cancels_queues_but_keeps_session_resources_open(self):
        active = self.service.submit_message("kira", "active request")
        queued = self.service.submit_message("kira", "queued request", busy=True)
        manager = self.service._attachment_manager

        self.assertEqual(len(self.dispatched), 1)
        self.assertTrue(queued.queued)
        self.service.begin_shutdown()

        self.assertTrue(self.service._shutting_down)
        self.assertFalse(manager._closed)
        self.assertEqual(self.service.get_request_status(active.request.request_id), RequestStatus.CANCELLED)
        self.assertEqual(self.service.get_request_status(queued.request.request_id), RequestStatus.CANCELLED)
        self.assertEqual(len(self.dispatched), 1, "shutdown must not dispatch the queued request")
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            self.service.submit_message("kira", "new work")

        # SessionManager's dispose callback calls close_session after workers drain.
        self.service.close_session("kira")
        self.assertFalse(manager._closed)

        self.service.dispose()
        self.assertTrue(manager._closed)
        self.assertTrue(self.service._disposed)

    def test_dispose_persists_partial_response_as_interrupted_once(self):
        submission = self.service.submit_message("kira", "hello")
        worker = self._start_provider(submission)
        worker.chunk.emit("partial answer")

        self.service.dispose()

        self.assertEqual(
            self.service.get_request_status(submission.request.request_id),
            RequestStatus.CANCELLED,
        )
        assistant_messages = [
            item for item in self.persistence.messages if item[0] == "assistant"
        ]
        self.assertEqual(len(assistant_messages), 1)
        self.assertEqual(assistant_messages[0][1], "partial answer")
        self.assertEqual(assistant_messages[0][3]["status"], "interrupted")
        self.assertTrue(assistant_messages[0][3]["metadata"]["interrupted"])
        self.assertTrue(assistant_messages[0][3]["metadata"]["application_shutdown"])

    def test_event_publisher_observes_request_stream_persistence_and_completion(self):
        bus = EventBus()
        publisher = ChatEventPublisher(bus)
        self.service.set_event_publisher(publisher)
        received = []
        event_types = (
            ChatEventType.REQUEST_SUBMITTED,
            ChatEventType.REQUEST_STARTED,
            ChatEventType.STREAM_STARTED,
            ChatEventType.STREAM_CHUNK_RECEIVED,
            ChatEventType.STREAM_COMPLETED,
            ChatEventType.MESSAGE_SAVED,
            ChatEventType.REQUEST_COMPLETED,
        )
        for event_type in event_types:
            publisher.subscribe(event_type, lambda event: received.append(event))

        submission = self.service.submit_message("kira", "hello")
        worker = self._start_provider(submission)
        worker.chunk.emit("answer")
        worker.finished_ok.emit({"text": "answer", "provider": "fake"})
        outcome = self.service.complete_request(submission.request.request_id, "answer")

        self.assertTrue(outcome.ok)
        self.assertEqual([event.event_type for event in received], list(event_types))
        self.assertTrue(all(event.session_id == "kira" for event in received))
        self.assertTrue(all(event.request_id == submission.request.request_id for event in received))

    def test_event_publisher_reports_persistence_failure(self):
        bus = EventBus()
        publisher = ChatEventPublisher(bus)
        self.service.set_event_publisher(publisher)
        received = []
        publisher.subscribe(
            ChatEventType.PERSISTENCE_FAILED,
            lambda event: received.append(event),
        )
        self.persistence.result = False

        outcome = self.service.persist_message(
            "ren", "user", "not saved", request_id="failed-save",
            status="complete", metadata={"source": "test"},
        )

        self.assertFalse(outcome.ok)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].session_id, "ren")
        self.assertEqual(received[0].request_id, "failed-save")
        self.assertEqual(received[0].payload["operation"], "message_write")

    def test_command_dispatch_is_correlated_and_published_through_chat_events(self):
        bus = EventBus()
        publisher = ChatEventPublisher(bus)
        self.service.set_event_publisher(publisher)
        registry = CommandRegistry()
        registry.register(CommandDefinition(
            command_id="test.ping",
            name="ping",
            description="Return pong.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _context: {},
            handler=lambda _context, _arguments: "pong",
        ))
        self.service.set_command_registry(registry)
        received = []
        publisher.subscribe(
            ChatEventType.COMMAND_DISPATCH_STARTED,
            lambda event: received.append(event),
        )
        publisher.subscribe(
            ChatEventType.COMMAND_DISPATCH_COMPLETED,
            lambda event: received.append(event),
        )
        submission = self.service.submit_message("runtime-kira", "/ping")

        dispatch = self.service.dispatch_commands(
            submission.request.request_id,
            "/ping",
            metadata={"character_id": "kira"},
        )

        self.assertTrue(dispatch.handled)
        self.assertEqual(dispatch.reply_text, "pong")
        self.assertEqual(dispatch.results[0].status, CommandStatus.COMPLETED)
        self.assertEqual([item.event_type for item in received], [
            ChatEventType.COMMAND_DISPATCH_STARTED,
            ChatEventType.COMMAND_DISPATCH_COMPLETED,
        ])
        self.assertTrue(all(item.session_id == "runtime-kira" for item in received))
        self.assertTrue(all(
            item.request_id == submission.request.request_id for item in received
        ))
        registry.close()

    def test_cancelling_pending_request_does_not_cancel_active_request_commands(self):
        registry = CommandRegistry()
        started = threading.Event()
        cancelled = threading.Event()

        def wait_for_cancel(context, _arguments):
            started.set()
            while not context.cancelled:
                time.sleep(0.005)
            cancelled.set()
            context.raise_if_cancelled()

        registry.register(CommandDefinition(
            command_id="test.wait",
            name="wait",
            description="Wait for cancellation.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _context: {},
            handler=wait_for_cancel,
        ))
        self.service.set_command_registry(registry)
        active = self.service.submit_message("kira", "active")
        dispatch_results = []
        worker = threading.Thread(target=lambda: dispatch_results.append(
            self.service.dispatch_commands(active.request.request_id, "/wait")
        ))
        worker.start()
        self.assertTrue(started.wait(2))

        pending = self.service.submit_message("kira", "queued", busy=True)
        self.assertTrue(pending.queued)
        self.assertTrue(self.service.cancel_request(pending.request.request_id))

        time.sleep(0.05)
        self.assertFalse(cancelled.is_set())
        self.assertTrue(worker.is_alive())

        self.assertTrue(self.service.cancel_request(active.request.request_id))
        self.assertTrue(cancelled.wait(2))
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(
            dispatch_results[0].results[0].status, CommandStatus.CANCELLED
        )

    def test_failed_command_dispatch_publishes_failed_lifecycle_event(self):
        bus = EventBus()
        publisher = ChatEventPublisher(bus)
        self.service.set_event_publisher(publisher)
        registry = CommandRegistry()
        registry.register(CommandDefinition(
            command_id="test.failure",
            name="failure",
            description="Fail predictably.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _context: {},
            handler=lambda _context, _arguments: (_ for _ in ()).throw(RuntimeError("failure")),
        ))
        self.service.set_command_registry(registry)
        received = []
        publisher.subscribe(
            ChatEventType.COMMAND_DISPATCH_STARTED,
            lambda event: received.append(event),
        )
        publisher.subscribe(
            ChatEventType.COMMAND_DISPATCH_FAILED,
            lambda event: received.append(event),
        )
        submission = self.service.submit_message("runtime-kira", "/failure")

        dispatch = self.service.dispatch_commands(
            submission.request.request_id, "/failure",
        )

        self.assertTrue(dispatch.failed)
        self.assertEqual([item.event_type for item in received], [
            ChatEventType.COMMAND_DISPATCH_STARTED,
            ChatEventType.COMMAND_DISPATCH_FAILED,
        ])
        registry.close()

    def test_out_of_band_control_uses_unique_request_and_parent_correlation(self):
        bus = EventBus()
        publisher = ChatEventPublisher(bus)
        self.service.set_event_publisher(publisher)
        registry = CommandRegistry()
        registry.register(CommandDefinition(
            command_id="test.pause",
            name="pause",
            description="Pause the active task.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            required_permissions=(),
            parser=lambda _raw, _context: {},
            handler=lambda _context, _arguments: "paused",
        ))
        self.service.set_command_registry(registry)
        received = []
        publisher.subscribe(
            ChatEventType.COMMAND_DISPATCH_COMPLETED,
            lambda event: received.append(event),
        )
        active = self.service.submit_message("runtime-ren", "run a task")

        dispatch = self.service.dispatch_control_commands(
            "runtime-ren", "/pause", metadata={"character_id": "ren"},
        )

        self.assertTrue(dispatch.handled)
        result = dispatch.results[0]
        self.assertEqual(result.session_id, "runtime-ren")
        self.assertNotEqual(result.request_id, active.request.request_id)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].request_id, result.request_id)
        self.assertEqual(
            received[0].metadata["parent_request_id"], active.request.request_id
        )
        self.assertEqual(received[0].payload["source"], "control")
        registry.close()

    def test_service_is_qt_free(self):
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "kira" / "chat" / "application_service.py").read_text()
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse(any(name.startswith(("PySide", "kira.oldmain")) for name in imports))


if __name__ == "__main__":
    unittest.main()
