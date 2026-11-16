import ast
import unittest
from pathlib import Path

from kira.chat.coordinator import ChatCoordinator, ChatRequest, SubmissionResult


class ChatCoordinatorTests(unittest.TestCase):
    def test_dispatches_immediately_when_idle(self):
        sent = []
        coordinator = ChatCoordinator(sent.append)
        result = coordinator.submit(ChatRequest.create("hello"))
        self.assertEqual(result, SubmissionResult.DISPATCHED)
        self.assertEqual([item.text for item in sent], ["hello"])
        self.assertEqual(coordinator.pending_count, 0)

    def test_queues_while_busy_and_preserves_fifo_order(self):
        sent = []
        coordinator = ChatCoordinator(sent.append)
        first = ChatRequest.create("first", [{"kind": "image", "name": "a.png"}], True)
        second = ChatRequest.create("second")
        self.assertEqual(coordinator.submit(first, busy=True), SubmissionResult.QUEUED)
        self.assertEqual(coordinator.submit(second, busy=True), SubmissionResult.QUEUED)
        self.assertEqual(sent, [])
        self.assertIsNone(coordinator.take_next(busy=True))
        self.assertEqual(coordinator.take_next().text, "first")
        self.assertEqual(coordinator.take_next().text, "second")
        self.assertIsNone(coordinator.take_next())

    def test_enforces_pending_limit_without_dropping_existing_requests(self):
        coordinator = ChatCoordinator(lambda _request: None, max_pending=2)
        coordinator.submit(ChatRequest.create("one"), busy=True)
        coordinator.submit(ChatRequest.create("two"), busy=True)
        self.assertEqual(coordinator.submit(ChatRequest.create("three"), busy=True),
                         SubmissionResult.FULL)
        self.assertEqual(coordinator.pending_count, 2)
        self.assertEqual(coordinator.take_next().text, "one")
        self.assertEqual(coordinator.take_next().text, "two")

    def test_force_queue_can_wait_for_an_external_operation(self):
        sent = []
        coordinator = ChatCoordinator(sent.append)
        result = coordinator.submit(ChatRequest.create("after vision"), force_queue=True)
        self.assertEqual(result, SubmissionResult.QUEUED)
        self.assertEqual(sent, [])
        self.assertEqual(coordinator.take_next().text, "after vision")

    def test_dispatch_exception_does_not_pollute_pending_queue(self):
        def fail(_request):
            raise RuntimeError("provider adapter failed")
        coordinator = ChatCoordinator(fail)
        with self.assertRaisesRegex(RuntimeError, "provider adapter failed"):
            coordinator.submit(ChatRequest.create("hello"))
        self.assertEqual(coordinator.pending_count, 0)

    def test_dispatch_preserves_request_payload(self):
        sent = []
        coordinator = ChatCoordinator(sent.append)
        request = ChatRequest.create("voice note", [{"kind": "text", "name": "notes.txt"}], True)
        coordinator.submit(request)
        self.assertEqual(sent, [request])

    def test_legacy_window_submission_delegates_queue_ownership(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "kira" / "oldmain.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        methods = {node.name: node for node in window.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        submit_source = ast.get_source_segment(source, methods["submit"])
        drain_source = ast.get_source_segment(source, methods["_send_next_pending"])
        self.assertIn("_chat_coordinator", submit_source)
        self.assertNotIn("self._pending.append", submit_source)
        self.assertIn("take_next", drain_source)

    def test_chat_session_exposes_a_per_session_coordinator_slot(self):
        from kira.chat_sessions import ChatSession
        first = ChatSession("kira")
        second = ChatSession("ren")
        self.assertIsNone(first.coordinator)
        self.assertIsNone(second.coordinator)
        first.coordinator = ChatCoordinator(lambda _request: None)
        self.assertIsNot(first.coordinator, second.coordinator)
    def test_coordinator_has_no_ui_or_storage_imports(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "kira" / "chat" / "coordinator.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertFalse(any(name.startswith(("PySide", "kira.oldmain", "kira.storage")) for name in imported))
    def test_clear_discards_only_this_coordinators_pending_requests(self):
        first = ChatCoordinator(lambda _request: None)
        second = ChatCoordinator(lambda _request: None)
        first.submit(ChatRequest.create("one"), busy=True)
        second.submit(ChatRequest.create("two"), busy=True)
        first.clear()
        self.assertEqual(first.pending_count, 0)
        self.assertEqual(second.pending_count, 1)


if __name__ == "__main__":
    unittest.main()
