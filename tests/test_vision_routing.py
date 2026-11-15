"""Regression tests for role-aware image routing in the streamed chat worker."""
import contextlib
import unittest
from types import SimpleNamespace

from kira.main import MainWindow, StreamWorker


class FakeRouter:
    def __init__(self, vision_route="vision-primary"):
        self.vision_route = vision_route
        self.role = None
        self.role_route = None
        self.selected_vision_route = None
        self.events = []

    @contextlib.contextmanager
    def role_scope(self, role="", route_id=""):
        self.role, self.role_route = role, route_id
        self.events.append("role-enter")
        try:
            yield self
        finally:
            self.events.append("role-exit")
            self.role = self.role_route = None

    def vision_route_id(self):
        self.events.append("vision-select")
        assert self.role == "answer"
        assert self.role_route == "text-route"
        return self.vision_route

    @contextlib.contextmanager
    def vision_scope(self, route_id=""):
        assert self.role == "answer"
        self.selected_vision_route = route_id
        self.events.append("vision-enter")
        try:
            yield self
        finally:
            self.events.append("vision-exit")
            self.selected_vision_route = None


class ProbeWorker(StreamWorker):
    def _run_request(self):
        self.router.events.append("request")
        assert self.router.role == "answer"
        assert self.router.selected_vision_route == "vision-primary"
        return {"answer": "ok"}


class FakeTimer:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.started = False


class FakeGameMode:
    def __init__(self):
        self.enabled = None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)


class FakeVisionWorker:
    def __init__(self, running=True):
        self.running = running
        self.cancelled = False

    def isRunning(self):
        return self.running

    def cancel_request(self):
        self.cancelled = True


class VisionRoutingTests(unittest.TestCase):
    def test_disabling_vision_capture_cancels_an_in_flight_analysis(self):
        worker = FakeVisionWorker()
        timer = FakeTimer()
        state = SimpleNamespace(
            game_mode=FakeGameMode(),
            _game_capture_timer=timer,
            _latest_game_frame=object(),
            _vision_worker=worker,
        )
        MainWindow._set_game_vision_capture(state, False)
        self.assertFalse(state.game_mode.enabled)
        self.assertTrue(timer.stopped)
        self.assertIsNone(state._latest_game_frame)
        self.assertTrue(worker.cancelled)

    def test_enabling_vision_capture_starts_capture_and_timer(self):
        timer = FakeTimer()
        state = SimpleNamespace(
            game_mode=FakeGameMode(),
            _game_capture_timer=timer,
            _capture_game_frame=lambda: setattr(state, "captured", True),
            _cancel_vision_worker=lambda: setattr(state, "cancelled", True),
        )
        MainWindow._set_game_vision_capture(state, True)
        self.assertTrue(state.game_mode.enabled)
        self.assertTrue(timer.started)
        self.assertTrue(state.captured)

    def test_image_route_is_selected_inside_role_and_kept_as_preference(self):
        router = FakeRouter()
        worker = ProbeWorker(
            router,
            [{"role": "user", "content": "این عکس چیست؟", "images": [{"b64": "AA=="}]}],
            "prompt",
            0.2,
            role="answer",
            route_id="text-route",
        )
        result = []
        worker.finished_ok.connect(result.append)
        worker.run()
        self.assertEqual(result, [{"answer": "ok"}])
        self.assertEqual(
            router.events,
            ["role-enter", "vision-select", "vision-enter", "request", "vision-exit", "role-exit"],
        )

    def test_image_request_fails_closed_when_no_vision_route_exists(self):
        router = FakeRouter(vision_route=None)
        worker = StreamWorker(
            router,
            [{"role": "user", "content": "تحلیل کن", "images": [{"b64": "AA=="}]}],
            "prompt",
            0.2,
            role="answer",
            route_id="text-route",
        )
        errors = []
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(len(errors), 1)
        self.assertIn("Vision", errors[0])
        self.assertEqual(router.events, ["role-enter", "vision-select", "role-exit"])

    def test_text_only_request_does_not_enter_vision_scope(self):
        router = FakeRouter()
        worker = StreamWorker(
            router,
            [{"role": "user", "content": "سلام"}],
            "prompt",
            0.2,
            role="answer",
            route_id="text-route",
        )
        result = []
        worker.finished_ok.connect(result.append)
        worker._run_request = lambda: {"answer": "text"}
        worker.run()
        self.assertEqual(result, [{"answer": "text"}])
        self.assertEqual(router.events, ["role-enter", "role-exit"])


if __name__ == "__main__":
    unittest.main()
