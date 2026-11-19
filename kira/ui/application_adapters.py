"""UI-side adapters that translate MainWindow callbacks into app ports."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from ..core.interfaces.application_ports import (
    ChatApplicationPorts,
    VoiceApplicationPorts,
)
from .workers import StreamWorker


class _QtProviderEventRelay(QObject):
    """Deliver provider callbacks on the GUI thread, including service lambdas."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    @Slot(str)
    def text(self, value):
        self._callback(value)

    @Slot(dict)
    def payload(self, value):
        self._callback(value)


class QtProviderWorkerAdapter(QObject):
    """Translate provider QThread signals and retain them through true thread exit."""

    finished = Signal()

    _SIGNALS = {
        "tool_event": ("tool_event", "payload"),
        "event": ("event", "payload"),
        "chunk": ("chunk", "text"),
        "complete": ("finished_ok", "payload"),
        "error": ("failed", "text"),
    }

    def __init__(self, worker, *, parent=None, registry=None):
        super().__init__(parent)
        self._worker = worker
        self._registry = registry
        self._subscriptions = {}
        self._released = False
        # The QThread QObject has GUI-thread affinity. Parenting it to this
        # adapter guarantees it cannot outlive its owner during window teardown.
        worker.setParent(self)
        if registry is not None:
            registry.add(self)
        worker.finished.connect(self._on_worker_finished, Qt.QueuedConnection)

    def subscribe(self, event, callback):
        try:
            signal_name, relay_name = self._SIGNALS[event]
        except KeyError as exc:
            raise ValueError(f"Unsupported provider event: {event}") from exc
        signal = getattr(self._worker, signal_name)
        relay = _QtProviderEventRelay(callback, parent=self)
        slot = getattr(relay, relay_name)
        signal.connect(slot, Qt.QueuedConnection)
        self._subscriptions.setdefault(event, []).append((signal, slot, relay))

        def unsubscribe():
            subscriptions = self._subscriptions.get(event, [])
            match = next(
                (item for item in subscriptions if item[2] is relay), None
            )
            if match is None:
                return False
            subscriptions.remove(match)
            if not subscriptions:
                self._subscriptions.pop(event, None)
            source, target, receiver = match
            try:
                source.disconnect(target)
            except (RuntimeError, TypeError):
                pass
            receiver.deleteLater()
            return True

        return unsubscribe

    def start(self):
        try:
            return self._worker.start()
        except Exception:
            self._release()
            raise

    @Slot()
    def _on_worker_finished(self):
        worker = self._worker
        if worker is not None:
            try:
                if worker.isRunning():
                    # QThread.finished may precede completion of thread-local
                    # cleanup. Keep ownership until isRunning() is truly false.
                    QTimer.singleShot(1, self._on_worker_finished)
                    return
            except RuntimeError:
                pass
        self._release()

    def _release(self):
        if self._released:
            return
        self._released = True
        subscriptions, self._subscriptions = self._subscriptions, {}
        for entries in subscriptions.values():
            for signal, slot, relay in entries:
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
                relay.deleteLater()
        if self._registry is not None:
            self._registry.discard(self)
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        # Consumers (notably MainWindow.closeEvent) observe completion only
        # after the wrapped QThread has fully stopped and left the registry.
        self.finished.emit()
        self.deleteLater()

    def isRunning(self):
        worker = self._worker
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            return False

    def __getattr__(self, name):
        # Preserve worker cancellation/diagnostic hooks for existing UI adapters.
        worker = object.__getattribute__(self, "_worker")
        if worker is None:
            raise AttributeError(name)
        return getattr(worker, name)


class _QtVoiceEventRelay(QObject):
    """Deliver toolkit-neutral callbacks on the QObject's owning thread."""

    def __init__(self, callback, *, on_finished=None, parent=None):
        super().__init__(parent)
        self._callback = callback
        self._on_finished = on_finished

    @Slot(str)
    def text(self, value):
        self._callback(value)

    @Slot()
    def no_args(self):
        try:
            self._callback()
        finally:
            if self._on_finished is not None:
                self._on_finished()


class QtVoiceListenerAdapter:
    """Translate a Qt microphone worker into the toolkit-neutral listener port."""

    _SIGNALS = {
        "heard": ("heard", "text"),
        "interrupted": ("interrupted", "no_args"),
        "state": ("state", "text"),
        "error": ("error", "text"),
        "note": ("note", "text"),
        "finished": ("finished", "no_args"),
    }

    def __init__(self, listener):
        self.raw_listener = listener
        self._subscriptions = {}

    def subscribe(self, event, callback):
        try:
            signal_name, relay_name = self._SIGNALS[event]
        except KeyError as exc:
            raise ValueError(f"Unsupported voice event: {event}") from exc
        if event in self._subscriptions:
            raise ValueError(f"Voice event is already subscribed: {event}")

        signal = getattr(self.raw_listener, signal_name)
        relay = _QtVoiceEventRelay(
            callback,
            on_finished=self._release_after_finished if event == "finished" else None,
            parent=self.raw_listener,
        )
        slot = getattr(relay, relay_name)
        signal.connect(slot, Qt.QueuedConnection)
        self._subscriptions[event] = (signal, slot, relay)

        def unsubscribe():
            subscription = self._subscriptions.pop(event, None)
            if subscription is None:
                return False
            source, target, receiver = subscription
            try:
                source.disconnect(target)
            except (RuntimeError, TypeError):
                pass
            receiver.deleteLater()
            return True

        return unsubscribe

    def _release_after_finished(self):
        # QThread.finished is delivered after all listener events. Detach every
        # relay and release the QThread QObject only after the app callback ran.
        subscriptions, self._subscriptions = self._subscriptions, {}
        for signal, slot, relay in subscriptions.values():
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
            relay.deleteLater()
        self.raw_listener.deleteLater()

    def start(self):
        try:
            return self.raw_listener.start()
        except Exception:
            self._release_after_finished()
            raise

    def stop(self):
        return self.raw_listener.stop()

    def is_running(self):
        try:
            return bool(self.raw_listener.isRunning())
        except RuntimeError:
            return False

    # Compatibility for existing UI status rendering; application code uses is_running().
    def isRunning(self):
        return self.is_running()

    def begin_speaking(self):
        return self.raw_listener.begin_kira_speech()

    def end_speaking(self):
        return self.raw_listener.end_kira_speech()

    def set_muted(self, muted):
        self.raw_listener.muted = bool(muted)

    def __getattr__(self, name):
        return getattr(self.raw_listener, name)


class QtSpeakerAdapter:
    """Expose the desktop Speaker implementation through the core SpeakerPort."""

    def __init__(self, speaker):
        self._speaker = speaker

    @property
    def settings(self):
        return self._speaker.settings

    @settings.setter
    def settings(self, value):
        self._speaker.settings = value

    def speak(self, text, rate=None, pitch=None, cache=False):
        return self._speaker.speak(text, rate, pitch, cache=cache)

    def stop(self):
        return self._speaker.stop()

    def stream_reset(self):
        return self._speaker.stream_reset()

    def stream_text(self, text, final=False):
        return self._speaker.stream_text(text, final=final)

    def stream_end(self):
        return self._speaker.stream_end()

    def play_file(self, path):
        return self._speaker.play_file(path)

    def is_speaking(self):
        return bool(getattr(self._speaker, "_began", False))

    def is_idle(self):
        checker = getattr(self._speaker, "is_idle", None)
        return bool(checker()) if callable(checker) else True


def create_chat_application_ports(context) -> ChatApplicationPorts:
    """Expose the minimum UI/provider boundary required by Chat application logic."""
    def create_worker(**request):
        return QtProviderWorkerAdapter(
            StreamWorker(**request),
            parent=context.host,
            registry=context.state._provider_workers,
        )

    return ChatApplicationPorts(
        prompt_enricher=lambda value: _enrich_chat_prompt(context, value),
        worker_factory=create_worker,
        on_dispatch=context.controllers.require("chat")._dispatch_application_request,
        on_event=context.controllers.require("chat")._on_chat_application_event,
        schedule=lambda callback: QTimer.singleShot(0, callback),
        cancel_provider=context.controllers.require("chat")._cancel_application_provider,
    )


def create_voice_application_ports(context, speaker) -> VoiceApplicationPorts:
    """Expose device and presentation callbacks without leaking MainWindow to app code."""
    return VoiceApplicationPorts(
        speaker=QtSpeakerAdapter(speaker),
        listener_factory=lambda: QtVoiceListenerAdapter(context.controllers.require("runtime")._create_voice_listener()),
        on_heard=context.controllers.require("runtime").on_heard,
        on_interrupted=context.controllers.require("runtime").on_user_barge_in,
        on_state=context.controllers.require("runtime").on_listener_state,
        on_error=context.controllers.require("runtime").on_listener_error,
        on_note=context.controllers.require("voice_settings").on_voice_note,
        on_finished=lambda listener, was_current, restart: context.host.voice_listener_finished.emit(
            listener.raw_listener, was_current, restart
        ),
        on_waiting=lambda: context.controllers.require("session").set_status("st_loading"),
    )


def _enrich_chat_prompt(context, prompt):
    """Compose the shared Skill instructions for the active character session."""
    result = context.services.brain_application_service.extend_prompt(
        prompt,
        context.session._brain,
        context.services.settings,
        context.session.client,
        character_id=context.session.cid,
    )
    skills = context.services.shared_skills_application_service.prompt_for(context.session.cid)
    return (str(result or "").strip() + ("\n\n" if result and skills else "") + skills).strip()
