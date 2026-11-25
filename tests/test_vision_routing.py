"""Regression tests for role-aware image routing in the streamed chat worker."""
import contextlib
import unittest
import threading
from unittest import mock
from types import SimpleNamespace

from tests import helpers
from kira.hybrid_ai import HybridRouter, ProgressBody
from kira.ui.main_window_chat import ChatController
from kira.ui.main_window_attachments_vision import AttachmentsVisionController
from kira.ui.main_window_support import SessionRelay
from kira.ui.workers import StreamWorker, VisionAnalysisWorker


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
        self.interval = None

    def setInterval(self, value):
        self.interval = value

    def start(self):
        self.started = True
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.started = False


class FakeVisionGate:
    def __init__(self):
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


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


class FakeVisionAnalysisRouter:
    def __init__(self):
        self.cancelled = False
        self.stream_called = False
        self.worker = None

    def vision_route_id(self):
        return "vision-route"

    @contextlib.contextmanager
    def vision_scope(self, route_id):
        assert route_id == "vision-route"
        yield self

    def chat_stream(self, messages, prompt, temperature, cancel_event=None):
        self.stream_called = True
        self.cancel_event = cancel_event
        return {"text": "تحلیل آماده", "interrupted": None, "stopped": False}

    def cancel(self):
        self.cancelled = True


class VisionRoutingTests(unittest.TestCase):
    def test_background_vision_uses_streaming_request_for_interruptible_http(self):
        router = FakeVisionAnalysisRouter()
        worker = VisionAnalysisWorker(router, {"b64": "invalid-base64"}, "کدام مسیر؟")
        results = []
        worker.done.connect(lambda ok, text, latency: results.append((ok, text)))
        worker.run()
        self.assertTrue(router.stream_called)
        self.assertIs(worker._cancelled, router.cancel_event)
        self.assertEqual(results, [(True, "تحلیل آماده")])

    def test_cancel_during_route_discovery_prevents_provider_request(self):
        router = FakeVisionAnalysisRouter()
        worker = VisionAnalysisWorker(router, {"b64": "invalid-base64"}, "تحلیل")
        router.vision_route_id = lambda: (worker.cancel_request(), "vision-route")[1]
        results = []
        worker.done.connect(lambda *args: results.append(args))
        worker.run()
        self.assertTrue(router.cancelled)
        self.assertFalse(router.stream_called)
        self.assertEqual(results, [])

    def test_cancelled_image_upload_stops_reading_request_body(self):
        cancelled = threading.Event()
        cancelled.set()
        body = ProgressBody(b"large-image-payload", None, cancelled)
        with self.assertRaises(RuntimeError):
            body.read(8)

    def test_router_rejects_an_already_cancelled_background_request(self):
        settings = helpers.fresh_settings()
        router = HybridRouter(settings)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(RuntimeError):
            router.chat_stream([{"role": "user", "content": "image"}], "prompt", cancel_event=cancelled)
        self.assertFalse(router.busy)

    def test_cancelled_background_vision_does_not_publish_partial_result(self):
        router = FakeVisionAnalysisRouter()
        worker = VisionAnalysisWorker(router, {"b64": "invalid-base64"}, "تحلیل")
        router.chat_stream = lambda *args, **kwargs: (worker.cancel_request(), {"text": "partial"})[1]
        results = []
        worker.done.connect(lambda *args: results.append(args))
        worker.run()
        self.assertTrue(router.cancelled)
        self.assertEqual(results, [])

    def test_user_message_queues_and_cancels_background_vision_without_losing_voice_flag(self):
        current = SimpleNamespace(
            status="ready", session_id="session-1", conversation_id="conversation-1", cid="kira"
        )
        worker = FakeVisionWorker()
        app = SimpleNamespace(
            dispatch_control_commands=mock.Mock(return_value=SimpleNamespace(handled=False)),
            submit_message=mock.Mock(return_value=SimpleNamespace(accepted=True, queued=True)),
            pending_count=mock.Mock(return_value=1),
        )
        state = SimpleNamespace(cur=current)
        session = SimpleNamespace(
            busy=False, _voice_next=True, _vision_session=current, _vision_worker=worker
        )
        session_controller = SimpleNamespace(_ensure_session_conversation=mock.Mock())
        controller = SimpleNamespace(
            context=SimpleNamespace(
                state=state,
                session=session,
                services=SimpleNamespace(chat_application_service=app),
                views=SimpleNamespace(status=SimpleNamespace(setText=mock.Mock())),
            ),
            feature_controller=lambda _name: session_controller,
        )
        ChatController.submit(controller, "voice question")
        worker.cancel_request.assert_called_once_with()
        session_controller._ensure_session_conversation.assert_called_once_with(current)
        self.assertTrue(app.submit_message.call_args.args[3])
        self.assertTrue(app.submit_message.call_args.kwargs["busy"])
        self.assertFalse(session._voice_next)
        app.pending_count.assert_called_once_with("session-1")

    def test_vision_result_relay_runs_in_its_owning_character_session(self):
        session = SimpleNamespace(cid="kira")
        state = SimpleNamespace(cur="ren")
        seen = []

        @contextlib.contextmanager
        def as_session(target):
            previous = state.cur
            state.cur = target
            try:
                yield
            finally:
                state.cur = previous

        def relay_run(name, *args):
            with as_session(session):
                getattr(state, name)(*args)

        state._on_game_vision_result = lambda *args: seen.append(state.cur.cid)
        relay = SimpleNamespace(_run=relay_run)
        SessionRelay.game_vision_done(relay, True, "game state", 10)
        self.assertEqual(seen, ["kira"])
        self.assertEqual(state.cur, "ren")

    def test_queued_message_is_not_started_after_window_shutdown(self):
        app = SimpleNamespace(complete_local_request=mock.Mock())
        controller = SimpleNamespace(
            context=SimpleNamespace(
                state=SimpleNamespace(_closing=True),
                services=SimpleNamespace(
                    session_manager=SimpleNamespace(get_session=mock.Mock(return_value=None)),
                    chat_application_service=app,
                ),
            ),
            _process_chat_request=mock.Mock(),
        )
        request = SimpleNamespace(request_id="request-1", session_id="missing-session")
        ChatController._dispatch_application_request(controller, request)
        app.complete_local_request.assert_called_once_with("request-1")
        controller._process_chat_request.assert_not_called()

    def test_vision_finished_relay_flushes_the_pending_queue(self):
        calls = []
        relay = SimpleNamespace(_run=lambda name: calls.append(name))
        SessionRelay.game_vision_finished(relay)
        self.assertEqual(calls, ["_send_next_pending"])

    def test_competitive_safe_stops_active_code_chat_job(self):
        session = object()
        code_chat = SimpleNamespace(session=session)
        stop_session = mock.Mock()
        session_controller = SimpleNamespace(_as=lambda _target: contextlib.nullcontext())
        controller = SimpleNamespace(
            context=SimpleNamespace(
                views=SimpleNamespace(code_chat=code_chat),
                services=SimpleNamespace(
                    coding_agent_application_service=SimpleNamespace(stop_session=stop_session)
                ),
            ),
            feature_controller=lambda _name: session_controller,
        )
        AttachmentsVisionController._stop_local_code_jobs(controller)
        stop_session.assert_called_once_with(code_chat, session)

    def test_disabling_vision_capture_cancels_an_in_flight_analysis(self):
        worker = FakeVisionWorker()
        timer = FakeTimer()
        privacy = SimpleNamespace(set_enabled=mock.Mock())
        capture = SimpleNamespace(set_enabled=mock.Mock())
        clear = mock.Mock()
        reset = mock.Mock()
        controller = SimpleNamespace(
            context=SimpleNamespace(
                state=SimpleNamespace(
                    _game_mode_enabled=False, _closing=False,
                    _game_capture_timer=timer, _latest_game_frame=object(),
                ),
                services=SimpleNamespace(
                    vision_application_service=SimpleNamespace(
                        desktop_capture_application_service=privacy, reset=reset
                    ),
                    desktop_context_application_service=SimpleNamespace(clear=clear),
                ),
                adapters=SimpleNamespace(game_mode=capture),
                session=SimpleNamespace(_vision_worker=worker),
            ),
            _cancel_vision_worker=mock.Mock(),
            _cancel_perception_worker=mock.Mock(),
            _clear_live_video_state=mock.Mock(),
        )
        AttachmentsVisionController._set_game_vision_capture(controller, False)
        privacy.set_enabled.assert_called_once_with(False)
        capture.set_enabled.assert_called_once_with(False)
        self.assertTrue(timer.stopped)
        self.assertIsNone(controller.context.state._latest_game_frame)
        clear.assert_called_once_with()
        reset.assert_called_once_with()
        controller._cancel_vision_worker.assert_called_once_with()
        controller._cancel_perception_worker.assert_called_once_with()
        controller._clear_live_video_state.assert_called_once_with()

    def test_enabling_vision_capture_starts_capture_and_timer(self):
        timer = FakeTimer()
        privacy = SimpleNamespace(set_enabled=mock.Mock())
        capture = SimpleNamespace(set_enabled=mock.Mock())
        controller = SimpleNamespace(
            context=SimpleNamespace(
                state=SimpleNamespace(_game_mode_enabled=False, _closing=False, _game_capture_timer=timer),
                services=SimpleNamespace(
                    vision_application_service=SimpleNamespace(
                        desktop_capture_application_service=privacy, reset=mock.Mock()
                    ),
                    desktop_context_application_service=SimpleNamespace(clear=mock.Mock()),
                ),
                adapters=SimpleNamespace(game_mode=capture),
            ),
            _cancel_vision_worker=mock.Mock(),
            _cancel_perception_worker=mock.Mock(),
            _clear_live_video_state=mock.Mock(),
            _vision_interval_ms=mock.Mock(return_value=5000),
            _capture_desktop_frame=mock.Mock(),
        )
        AttachmentsVisionController._set_game_vision_capture(controller, True)
        privacy.set_enabled.assert_called_once_with(True)
        capture.set_enabled.assert_called_once_with(True)
        self.assertEqual(timer.interval, 5000)
        self.assertTrue(timer.started)
        controller._capture_desktop_frame.assert_called_once_with()

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

    def test_ollama_vision_capability_cache_is_scoped_to_server_and_model(self):
        settings = helpers.fresh_settings()
        router = HybridRouter(settings)
        route = {"provider": "ollama", "model": "custom-local-model"}

        def client_with_capabilities(capabilities):
            response = SimpleNamespace(status_code=200, json=lambda: {"capabilities": capabilities})
            return SimpleNamespace(model="custom-local-model", _post=lambda *args: response)

        settings["ollama_url"] = "http://ollama-one:11434"
        with mock.patch.object(
            router,
            "_make_provider",
            side_effect=[client_with_capabilities(["completion", "vision"]),
                         client_with_capabilities(["completion"])],
        ) as make_provider:
            self.assertTrue(router._route_supports_vision(route, {}))
            settings["ollama_url"] = "http://ollama-two:11434"
            self.assertFalse(router._route_supports_vision(route, {}))
            self.assertEqual(make_provider.call_count, 2)

    def test_ollama_unavailable_does_not_cache_a_negative_capability(self):
        settings = helpers.fresh_settings()
        router = HybridRouter(settings)
        route = {"provider": "ollama", "model": "custom-local-model"}
        failed_client = SimpleNamespace(
            model="custom-local-model",
            _post=mock.Mock(side_effect=ConnectionError("offline")),
        )
        good_response = SimpleNamespace(status_code=200, json=lambda: {"capabilities": ["vision"]})
        good_client = SimpleNamespace(model="custom-local-model", _post=lambda *args: good_response)
        with mock.patch.object(router, "_make_provider", side_effect=[failed_client, good_client]) as make_provider:
            self.assertFalse(router._route_supports_vision(route, {}))
            self.assertTrue(router._route_supports_vision(route, {}))
            self.assertEqual(make_provider.call_count, 2)

    def test_embedding_models_are_not_misclassified_as_vision_models(self):
        settings = helpers.fresh_settings()
        router = HybridRouter(settings)
        route = {"provider": "gemini", "model": "gemini-embedding-001"}
        self.assertFalse(router._route_supports_vision(route, {}))

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
