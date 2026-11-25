"""Regression tests for the Qt-independent Vision provider execution boundary."""
import contextlib
import threading
import unittest

from kira.vision_provider import VisionProviderExecutor


class FakeRouter:
    def __init__(self, route="vision-primary", response=None):
        self.route = route
        self.response = {"text": "تحلیل آماده"} if response is None else response
        self.events = []
        self.messages = None
        self.prompt = None

    def vision_route_id(self):
        self.events.append("select")
        return self.route

    @contextlib.contextmanager
    def vision_scope(self, route_id):
        self.events.append(("scope-enter", route_id))
        try:
            yield self
        finally:
            self.events.append(("scope-exit", route_id))

    def chat_stream(self, messages, prompt, temperature, cancel_event=None):
        self.events.append(("request", temperature))
        self.messages, self.prompt = messages, prompt
        return self.response


class VisionProviderExecutorTests(unittest.TestCase):
    def test_executes_only_inside_the_selected_vision_route(self):
        router = FakeRouter()
        image = {"b64": "frame"}
        result = VisionProviderExecutor(router).execute(
            image, context="کدام مسیر؟", ocr_text="دروازه باز است"
        )
        self.assertEqual(result, "تحلیل آماده")
        self.assertEqual(router.events, [
            "select", ("scope-enter", "vision-primary"),
            ("request", 0.2), ("scope-exit", "vision-primary"),
        ])
        self.assertEqual(router.messages[0]["images"], [image])
        self.assertIn("کدام مسیر؟", router.prompt)
        self.assertIn("دروازه باز است", router.prompt)

    def test_missing_vision_route_fails_before_provider_request(self):
        router = FakeRouter(route="")
        with self.assertRaisesRegex(RuntimeError, "هیچ مدل Vision فعالی"):
            VisionProviderExecutor(router).execute({"b64": "frame"})
        self.assertEqual(router.events, ["select"])

    def test_cancelled_request_does_not_discover_or_call_provider(self):
        router = FakeRouter()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            VisionProviderExecutor(router).execute(
                {"b64": "frame"}, cancel_event=cancelled
            )
        self.assertEqual(router.events, [])

    def test_cancellation_during_route_discovery_prevents_request(self):
        router = FakeRouter()
        cancelled = threading.Event()
        def select_and_cancel():
            cancelled.set()
            return "vision-primary"
        router.vision_route_id = select_and_cancel
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            VisionProviderExecutor(router).execute(
                {"b64": "frame"}, cancel_event=cancelled
            )
        self.assertEqual(router.events, [])

    def test_interrupted_provider_response_is_not_reported_as_success(self):
        router = FakeRouter(response={"text": "partial", "interrupted": True})
        with self.assertRaisesRegex(RuntimeError, "پیش از تکمیل متوقف"):
            VisionProviderExecutor(router).execute({"b64": "frame"})


if __name__ == "__main__":
    unittest.main()
