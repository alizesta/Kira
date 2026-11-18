"""Qt-free regression tests for the shared EventBus and typed Chat events."""
import threading
import unittest
from datetime import datetime
from types import SimpleNamespace

from kira.app.event_bus import EventBus
from kira.chat.events import CHAT_EVENT_TYPES, ChatEvent, ChatEventPublisher, ChatEventType


class ChatEventContractTests(unittest.TestCase):
    def test_event_contract_and_deep_immutability(self):
        original = {"nested": {"items": [1, 2]}}
        event = ChatEvent.create(
            "request_submitted", session_id="kira", request_id="r1",
            payload=original, metadata={"origin": "test"},
        )
        original["nested"]["items"].append(3)
        self.assertTrue(event.event_id)
        self.assertIsNotNone(event.timestamp.tzinfo)
        self.assertEqual(event.payload["nested"]["items"], (1, 2))
        self.assertEqual(event.metadata["origin"], "test")
        with self.assertRaises(TypeError):
            event.payload["nested"]["new"] = True

    def test_unknown_type_invalid_id_and_naive_timestamp_are_rejected(self):
        with self.assertRaises(ValueError):
            ChatEvent.create("unknown")
        with self.assertRaises(ValueError):
            ChatEvent.create("request_started", session_id=" ")
        with self.assertRaises(ValueError):
            ChatEvent(event_type="request_started", timestamp=datetime.now())

    def test_payload_rejects_non_contract_objects(self):
        with self.assertRaises(TypeError):
            ChatEvent.create("message_saved", payload={"opaque": object()})

    def test_required_event_catalog_is_complete(self):
        self.assertEqual(CHAT_EVENT_TYPES, {
            "request_submitted", "request_started", "request_completed", "request_failed",
            "request_cancelled", "stream_started", "stream_chunk_received", "stream_completed",
            "stream_interrupted", "session_created", "session_activated", "session_deactivated",
            "session_closed", "session_failed", "message_saved", "history_loaded",
            "persistence_failed", "conversation_archived", "conversation_restored",
            "conversation_trashed", "conversation_restored_from_trash",
            "conversation_permanently_deleted", "conversation_metadata_updated",
        "command_dispatch_started", "command_dispatch_completed", "command_dispatch_failed",
        })


class SharedEventBusTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.publisher = ChatEventPublisher(self.bus)

    def test_multiple_subscribers_receive_the_same_typed_event(self):
        received = []
        self.publisher.subscribe("request_started", lambda event: received.append(("a", event)))
        self.publisher.subscribe(ChatEventType.REQUEST_STARTED, lambda event: received.append(("b", event)))
        outcome = self.publisher.publish("request_started", session_id="ren", request_id="r1")
        self.assertEqual(outcome.delivered, 2)
        self.assertEqual([name for name, _ in received], ["a", "b"])
        self.assertIs(received[0][1], received[1][1])

    def test_lifecycle_and_organization_events_use_the_shared_event_bus(self):
        received = []
        event_names = (
            "conversation_archived",
            "conversation_restored",
            "conversation_trashed",
            "conversation_restored_from_trash",
            "conversation_permanently_deleted",
            "conversation_metadata_updated",
        )
        for event_name in event_names:
            self.publisher.subscribe(event_name, lambda event: received.append(
                (event.event_type.value, event.payload["conversation_id"])
            ))

        for event_name in event_names:
            self.publisher.publish(
                event_name,
                payload={"conversation_id": "conversation-1", "new_status": "archived"},
            )

        self.assertEqual(
            received,
            [(event_name, "conversation-1") for event_name in event_names],
        )
        self.assertEqual(self.bus.subscriber_count("conversation_archived"), 1)
        self.assertEqual(self.bus.subscriber_count("conversation_metadata_updated"), 1)

    def test_shared_event_bus_accepts_a_generic_core_event_contract(self):
        event = SimpleNamespace(
            event_type="feature.ready",
            event_id="evt-1",
            timestamp=datetime.now().astimezone(),
            session_id="session-1",
            request_id=None,
            payload={"feature": "sample"},
            metadata={"source": "test"},
        )
        typed_received = []
        legacy_received = []
        self.bus.subscribe_event("feature.ready", typed_received.append)
        self.bus.subscribe("feature.ready", lambda **payload: legacy_received.append(payload))

        report = self.bus.publish_event(event)

        self.assertEqual(report.delivered, 2)
        self.assertEqual(typed_received, [event])
        self.assertEqual(legacy_received[0]["event"], event)
        self.assertEqual(legacy_received[0]["event_type"], "feature.ready")

    def test_shared_event_bus_rejects_values_outside_the_event_contract(self):
        with self.assertRaises(TypeError):
            self.bus.publish_event(object())

    def test_legacy_keyword_event_api_stays_compatible(self):
        received = []
        self.bus.subscribe("voice.transcript", lambda **data: received.append(data["text"]))
        report = self.bus.publish("voice.transcript", text="hello")
        self.assertEqual(received, ["hello"])
        self.assertEqual(report.delivered, 1)

    def test_legacy_subscriber_receives_typed_event_envelope(self):
        received = []
        self.bus.subscribe("message_saved", lambda **data: received.append(
            (data["event_type"], data["session_id"], data["payload"]["role"])
        ))
        self.publisher.publish("message_saved", session_id="mika", payload={"role": "user"})
        self.assertEqual(received, [("message_saved", "mika", "user")])

    def test_unsubscribe_is_idempotent_and_stops_future_events(self):
        received = []
        unsubscribe = self.publisher.subscribe("history_loaded", lambda event: received.append(event))
        unsubscribe()
        unsubscribe()
        self.publisher.publish("history_loaded", session_id="kira")
        self.assertEqual(received, [])

    def test_duplicate_callback_registration_is_prevented(self):
        received = []
        def callback(event):
            received.append(event.event_id)
        self.publisher.subscribe("session_created", callback)
        self.publisher.subscribe("session_created", callback)
        self.publisher.publish("session_created", session_id="kira")
        self.assertEqual(len(received), 1)
        self.assertEqual(self.bus.subscriber_count("session_created"), 1)

    def test_subscriber_error_does_not_stop_fanout_and_is_reported(self):
        received = []
        def broken(_event):
            raise RuntimeError("broken consumer")
        self.publisher.subscribe("request_failed", broken)
        self.publisher.subscribe("request_failed", lambda event: received.append(event.request_id))
        report = self.publisher.publish("request_failed", session_id="kira", request_id="r2")
        self.assertEqual(received, ["r2"])
        self.assertEqual(report.delivered, 1)
        self.assertEqual(len(report.failures), 1)
        self.assertIsInstance(report.failures[0].error, RuntimeError)

    def test_nested_publication_waits_until_current_fanout_finishes(self):
        received = []
        def first(event):
            received.append("first")
            self.publisher.publish("stream_started", session_id=event.session_id, request_id=event.request_id)
        self.publisher.subscribe("request_started", first)
        self.publisher.subscribe("request_started", lambda _event: received.append("second"))
        self.publisher.subscribe("stream_started", lambda _event: received.append("nested"))
        self.publisher.publish("request_started", session_id="kira", request_id="r3")
        self.assertEqual(received, ["first", "second", "nested"])

    def test_subscriber_snapshot_is_stable_during_delivery(self):
        received = []
        def first(_event):
            received.append("first")
            self.publisher.subscribe("session_activated", lambda _event: received.append("late"))
        self.publisher.subscribe("session_activated", first)
        self.publisher.subscribe("session_activated", lambda _event: received.append("second"))
        self.publisher.publish("session_activated", session_id="kira")
        self.assertEqual(received, ["first", "second"])
        self.publisher.publish("session_activated", session_id="kira")
        self.assertEqual(received, ["first", "second", "first", "second", "late"])

    def test_session_and_request_ids_remain_isolated(self):
        received = []
        self.publisher.subscribe("stream_chunk_received", lambda event: received.append(
            (event.session_id, event.request_id, event.payload["chunk"])
        ))
        for session, request, chunk in (("kira", "k1", "A"), ("ren", "r1", "B"), ("mika", "m1", "C")):
            self.publisher.publish("stream_chunk_received", session_id=session,
                                   request_id=request, payload={"chunk": chunk})
        self.assertEqual(received, [("kira", "k1", "A"), ("ren", "r1", "B"), ("mika", "m1", "C")])

    def test_request_terminal_notifications_are_deduplicated(self):
        received = []
        for event_type in ("request_completed", "request_failed", "request_cancelled"):
            self.publisher.subscribe(event_type, lambda event: received.append(event.event_type))
        first = self.publisher.publish("request_completed", session_id="kira", request_id="same")
        duplicate = self.publisher.publish("request_failed", session_id="kira", request_id="same")
        other_session = self.publisher.publish("request_failed", session_id="ren", request_id="same")
        other_request = self.publisher.publish("request_failed", session_id="kira", request_id="other")
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(other_session.duplicate)
        self.assertFalse(other_request.duplicate)
        self.assertEqual(received, [
            ChatEventType.REQUEST_COMPLETED, ChatEventType.REQUEST_FAILED, ChatEventType.REQUEST_FAILED
        ])

    def test_failed_terminal_publication_can_be_retried(self):
        class FlakyBus:
            def __init__(self):
                self.attempts = 0
                self.events = []

            def publish_event(self, event):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("temporary bus failure")
                self.events.append(event)
                return SimpleNamespace(
                    event_name=event.event_type.value,
                    sequence=self.attempts,
                    delivered=1,
                    failures=(),
                    queued=False,
                )

        bus = FlakyBus()
        publisher = ChatEventPublisher(bus)
        with self.assertRaisesRegex(RuntimeError, "temporary bus failure"):
            publisher.publish(
                "request_completed", session_id="kira", request_id="retry-me"
            )

        retried = publisher.publish(
            "request_failed", session_id="kira", request_id="retry-me"
        )
        duplicate = publisher.publish(
            "request_cancelled", session_id="kira", request_id="retry-me"
        )

        self.assertFalse(retried.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(bus.attempts, 2)
        self.assertEqual(
            [event.event_type for event in bus.events],
            [ChatEventType.REQUEST_FAILED],
        )

    def test_stream_retries_use_distinct_provider_attempt_terminal_keys(self):
        received = []
        self.publisher.subscribe("stream_completed", lambda event: received.append(
            event.payload["provider_request_id"]
        ))
        first = self.publisher.publish(
            "stream_completed", session_id="kira", request_id="logical",
            payload={"provider_request_id": "logical:1"},
        )
        retry = self.publisher.publish(
            "stream_completed", session_id="kira", request_id="logical",
            payload={"provider_request_id": "logical:2"},
        )
        duplicate = self.publisher.publish(
            "stream_completed", session_id="kira", request_id="logical",
            payload={"provider_request_id": "logical:2"},
        )
        self.assertFalse(first.duplicate)
        self.assertFalse(retry.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(received, ["logical:1", "logical:2"])

    def test_stream_and_session_terminal_events_are_deduplicated_and_session_reuse_resets(self):
        received = []
        for event_type in ("stream_completed", "stream_interrupted", "session_closed", "session_failed", "session_created"):
            self.publisher.subscribe(event_type, lambda event: received.append(event.event_type))
        self.publisher.publish("stream_interrupted", session_id="kira", request_id="r1")
        duplicate_stream = self.publisher.publish("stream_completed", session_id="kira", request_id="r1")
        self.publisher.publish("session_closed", session_id="ren")
        duplicate_session = self.publisher.publish("session_failed", session_id="ren")
        self.publisher.publish("session_created", session_id="ren")
        reopened = self.publisher.publish("session_closed", session_id="ren")
        self.assertTrue(duplicate_stream.duplicate)
        self.assertTrue(duplicate_session.duplicate)
        self.assertFalse(reopened.duplicate)
        self.assertEqual(received, [
            ChatEventType.STREAM_INTERRUPTED, ChatEventType.SESSION_CLOSED,
            ChatEventType.SESSION_CREATED, ChatEventType.SESSION_CLOSED,
        ])

    def test_clear_and_close_release_subscribers(self):
        received = []
        self.publisher.subscribe("session_activated", lambda _event: received.append("active"))
        self.bus.clear("session_activated")
        self.publisher.publish("session_activated", session_id="ren")
        self.assertEqual(received, [])
        self.publisher.subscribe("session_activated", lambda _event: received.append("late"))
        self.bus.close()
        self.assertEqual(self.bus.subscriber_count(), 0)
        with self.assertRaises(RuntimeError):
            self.publisher.publish("session_activated", session_id="ren")

    def test_concurrent_publisher_does_not_block_behind_a_slow_subscriber(self):
        entered = threading.Event()
        release = threading.Event()
        delivered = []
        queued_reports = []

        def slow_subscriber(event):
            delivered.append(event.payload["index"])
            if event.payload["index"] == 1:
                entered.set()
                self.assertTrue(release.wait(timeout=3), "test did not release slow subscriber")

        self.publisher.subscribe("stream_chunk_received", slow_subscriber)

        first = threading.Thread(target=lambda: self.publisher.publish(
            "stream_chunk_received", session_id="kira", request_id="r1",
            payload={"index": 1},
        ))
        first.start()
        self.assertTrue(entered.wait(timeout=2), "first subscriber did not start")

        second = threading.Thread(target=lambda: queued_reports.append(self.publisher.publish(
            "stream_chunk_received", session_id="ren", request_id="r2",
            payload={"index": 2},
        ).report))
        second.start()
        second.join(timeout=1)
        self.assertFalse(second.is_alive(), "concurrent publisher blocked behind active callback")
        self.assertTrue(queued_reports[0].queued)

        release.set()
        first.join(timeout=3)
        self.assertFalse(first.is_alive(), "dispatcher failed to drain queued publication")
        self.assertEqual(delivered, [1, 2])

    def test_concurrent_publications_are_delivered_once_in_fifo_sequence_order(self):
        received = []
        sequences = {}
        lock = threading.Lock()
        self.publisher.subscribe("stream_chunk_received", lambda event: received.append(event.event_id))
        count = 24
        def publish_one(index):
            result = self.publisher.publish(
                "stream_chunk_received", session_id=f"s{index % 3}",
                request_id=f"r{index}", payload={"index": index},
            )
            with lock:
                sequences[result.event.event_id] = result.report.sequence
        threads = [threading.Thread(target=publish_one, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "publisher thread deadlocked")
        ordered = [sequences[event_id] for event_id in received]
        self.assertEqual(len(ordered), count)
        self.assertEqual(ordered, sorted(ordered))
        self.assertEqual(len(set(ordered)), count)


class ChatEventWiringTests(unittest.TestCase):
    def test_bootstrap_injects_the_same_shared_bus_into_module_and_chat_notifications(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("event_bus = EventBus()", source)
        self.assertIn("module_manager = ModuleManager(container, event_bus)", source)
        self.assertIn("chat_event_publisher = ChatEventPublisher(event_bus)", source)
        self.assertIn("chat_event_publisher=chat_event_publisher", source)
        self.assertIn("app.aboutToQuit.connect(event_bus.close)", source)

    def test_application_service_owns_request_stream_and_persistence_notifications(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        service_source = (root / "kira" / "chat" / "application_service.py").read_text(encoding="utf-8")
        service_tree = ast.parse(service_source)
        service_strings = {
            node.value for node in ast.walk(service_tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue({
            "request_submitted", "request_started", "request_completed",
            "request_failed", "request_cancelled", "stream_started",
            "stream_chunk_received", "stream_completed", "stream_interrupted",
            "message_saved", "persistence_failed",
        }.issubset(service_strings))

        from tests.ui_helpers import package_source
        main_source = package_source()
        main_tree = ast.parse(main_source)
        main_strings = {
            node.value for node in ast.walk(main_tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue({
            "session_created", "session_activated", "session_deactivated",
            "session_closed", "session_failed", "history_loaded", "persistence_failed",
        }.issubset(main_strings))

    def test_queued_request_keeps_logical_identity_across_provider_attempts(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "kira" / "chat" / "application_service.py").read_text(encoding="utf-8")
        self.assertIn("self._attempt_to_request[attempt_id] = state.request.request_id", source)
        self.assertIn("provider_request_id", source)
        self.assertIn("self._publish_request_submitted", source)

        from tests.ui_helpers import window_method_source
        send_next = window_method_source("_send_next_pending")
        submit_for = window_method_source("_submit_for")
        self.assertIn("item=request", send_next)
        self.assertIn("self._dispatch_coordinated_request(session, request)", submit_for)
        self.assertNotIn("ChatRequest.create", submit_for)


if __name__ == "__main__":
    unittest.main()
