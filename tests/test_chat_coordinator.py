import unittest

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
