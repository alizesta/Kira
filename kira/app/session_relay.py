"""Qt adapter for routing per-session worker callbacks to the active window."""

from PySide6.QtCore import QObject, Signal, Slot


class SessionRelay(QObject):
    """Marshals this session's worker/provider callbacks onto the GUI thread."""

    provider_event = Signal(object)

    def __init__(self, window, session):
        super().__init__(window)
        self.w, self.s = window, session
        self.provider_event.connect(self._handle_provider_event)

    @Slot(object)
    def _handle_provider_event(self, event):
        self.w.chat_application_service.handle_provider_event(event)

    def _run(self, name, *args):
        with self.w._as(self.s):
            getattr(self.w, name)(*args)

    @Slot(str)
    def chunk(self, piece):
        self._run("on_stream_chunk", piece)

    @Slot(dict)
    def stream_event(self, e):          # NOT named `event`: that would override QObject.event(QEvent)
        self._run("on_stream_event", e)

    @Slot(dict)
    def tool(self, e):
        self._run("on_tool_event", e)

    @Slot(dict)
    def done(self, res):
        self._run("on_stream_done", res)

    @Slot(str)
    def failed(self, error):
        self._run("on_error", error)

    @Slot()
    def tick(self):
        self._run("_stream_flush")

    @Slot(int, bool, object)
    def search_done(self, token, ok, result):
        self._run("on_web_done", token, ok, result)

    @Slot(bool, str, int)
    def game_vision_done(self, ok, result, latency_ms):
        self._run("_on_game_vision_result", ok, result, latency_ms)

    @Slot()
    def game_vision_finished(self):
        self._run("_send_next_pending")
