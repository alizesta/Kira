import unittest
from contextlib import contextmanager

from PySide6.QtCore import QObject

from kira.app.session_relay import SessionRelay, front_only


class _ApplicationService:
    def __init__(self):
        self.events = []

    def handle_provider_event(self, event):
        self.events.append(event)


class _Window(QObject):
    def __init__(self):
        super().__init__()
        self.chat_application_service = _ApplicationService()
        self.calls = []

    @contextmanager
    def _as(self, session):
        self.calls.append(("enter", session))
        try:
            yield
        finally:
            self.calls.append(("exit", session))

    def on_stream_chunk(self, piece):
        self.calls.append(("chunk", piece))


class SessionRelayTests(unittest.TestCase):
    def test_provider_events_are_forwarded_to_application_service(self):
        window = _Window()
        relay = SessionRelay(window, object())
        event = {"kind": "completed", "request_id": "request-1"}

        relay.provider_event.emit(event)

        self.assertEqual(window.chat_application_service.events, [event])

    def test_callback_runs_in_its_owning_session_context(self):
        window = _Window()
        session = object()
        relay = SessionRelay(window, session)

        relay.chunk("hello")

        self.assertEqual(
            window.calls,
            [("enter", session), ("chunk", "hello"), ("exit", session)],
        )

    def test_front_only_skips_callbacks_for_background_sessions(self):
        class Window:
            cur = object()
            front = object()

            @front_only
            def update_shared_ui(self, value):
                return value

        self.assertIsNone(Window().update_shared_ui("hidden"))

    def test_front_only_allows_callbacks_for_front_session(self):
        class Window:
            cur = None
            front = None

            @front_only
            def update_shared_ui(self, value):
                return value

        self.assertEqual(Window().update_shared_ui("visible"), "visible")


if __name__ == "__main__":
    unittest.main()
