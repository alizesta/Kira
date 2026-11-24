"""Thread-safe lazy facade for the optional desktop ToolAgent."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class _LazyTaskStore:
    def __init__(self, owner: "LazyToolAgent") -> None:
        self._owner = owner

    def active(self, *args: Any, **kwargs: Any) -> Any:
        owner = args[0] if args else kwargs.get("session_id")
        return self._owner._active_task(owner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner._get().tasks, name)


class LazyToolAgent:
    """Keep ordinary chat independent from the full Windows tool stack."""

    def __init__(self, factory: Callable[[], Any], *, data_dir=None) -> None:
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._factory = factory
        self._data_dir = data_dir
        self._task_store = None
        self._instance = None
        self._lock = threading.Lock()
        self._pending_settings = None
        self._pending_competitive_safe_mode = None
        self._pending_desktop_context_provider = None
        self._pending_begin_turns: set[str] = set()
        self._tasks_proxy = _LazyTaskStore(self)

    def _get(self) -> Any:
        instance = self._instance
        if instance is not None:
            return instance
        with self._lock:
            if self._instance is None:
                instance = self._factory()
                if instance is None:
                    raise RuntimeError("ToolAgent factory returned None")
                if self._pending_settings is not None:
                    instance.set_settings(self._pending_settings)
                if self._pending_competitive_safe_mode is not None:
                    instance.set_competitive_safe_mode(self._pending_competitive_safe_mode)
                if self._pending_desktop_context_provider is not None:
                    setter = getattr(instance, "set_desktop_context_provider", None)
                    if not callable(setter):
                        raise TypeError("ToolAgent does not support desktop context injection")
                    setter(self._pending_desktop_context_provider)
                begin_turn = getattr(instance, "begin_turn", None)
                if callable(begin_turn):
                    for session_id in sorted(self._pending_begin_turns):
                        begin_turn(session_id)
                self._pending_begin_turns.clear()
                self._task_store = None
                self._instance = instance
            return self._instance

    @property
    def realized(self) -> bool:
        """Whether the full desktop tool system has been constructed."""
        return self._instance is not None

    @property
    def tasks(self) -> _LazyTaskStore:
        return self._tasks_proxy

    def set_settings(self, settings: dict[str, Any]) -> None:
        """Update the facade and live agent without realizing it during startup."""
        with self._lock:
            self._pending_settings = settings
            instance = self._instance
        if instance is not None:
            instance.set_settings(settings)

    def set_desktop_context_provider(self, provider) -> None:
        """Pass the UI-owned perception summary through without realizing ToolAgent at startup."""
        if provider is not None and not callable(provider):
            raise TypeError("desktop context provider must be callable or None")
        with self._lock:
            self._pending_desktop_context_provider = provider
            instance = self._instance
        if instance is not None:
            setter = getattr(instance, "set_desktop_context_provider", None)
            if not callable(setter):
                raise TypeError("ToolAgent does not support desktop context injection")
            setter(provider)

    def set_competitive_safe_mode(self, enabled: bool) -> None:
        """Preserve Game Mode restrictions before or after realization."""
        with self._lock:
            self._pending_competitive_safe_mode = bool(enabled)
            instance = self._instance
        if instance is not None:
            instance.set_competitive_safe_mode(bool(enabled))

    def _active_task(self, session_id: str | None = None):
        """Read only the small persisted task ledger without loading Windows tools."""
        with self._lock:
            instance = self._instance
            if instance is None:
                if self._data_dir is None:
                    return None
                if self._task_store is None:
                    from .tools.tasks import TaskStore

                    self._task_store = TaskStore(self._data_dir)
                store = self._task_store
            else:
                store = None
        return instance.tasks.active(session_id) if instance is not None else store.active(session_id)

    def enabled(self) -> bool:
        """Report the tools switch without realizing ToolAgent."""
        settings = self._pending_settings or getattr(self._instance, "settings", {}) or {}
        return str(settings.get("tools_mode", "auto") or "auto").lower() != "off"

    def planning_enabled(self) -> bool:
        """Report planner settings without realizing ToolAgent."""
        settings = self._pending_settings or getattr(self._instance, "settings", {}) or {}
        return str(settings.get("agent_planning", "auto") or "auto").lower() != "off"

    def has_pending(self, session_id: str | None = None) -> bool:
        instance = self._instance
        return bool(instance.has_pending(session_id)) if instance is not None else False

    def has_new_pending_confirmation(self, session_id: str | None = None) -> bool:
        instance = self._instance
        return bool(instance.has_new_pending_confirmation(session_id)) if instance is not None else False

    def prepare_control_dispatch(self, text: str, *, session_id: str | None = None) -> bool:
        """Realize the agent only for an explicit control command on a persisted active task."""
        if not self.enabled():
            return False
        from .tools.tasks import parse_control

        kind, _payload = parse_control(text)
        if kind is None or self._active_task(session_id) is None:
            return False
        self._get()
        return True

    def handle_confirmation_reply(self, text: str, *, session_id: str | None = None):
        instance = self._instance
        return instance.handle_confirmation_reply(text, session_id=session_id) if instance is not None else None

    def handle_task_command(self, text: str, *, session_id: str | None = None):
        instance = self._instance
        return instance.handle_task_command(text, session_id=session_id) if instance is not None else None

    def control_running(self, text: str, *, session_id: str | None = None):
        instance = self._instance
        return instance.control_running(text, session_id=session_id) if instance is not None else None

    def begin_turn(self, session_id: str | None = None) -> None:
        """Reset request state only when the tool system already exists."""
        owner = str(session_id or "")
        instance = self._instance
        if instance is not None:
            instance.begin_turn(owner)
            return
        if owner:
            with self._lock:
                if self._instance is None:
                    self._pending_begin_turns.add(owner)
                else:
                    instance = self._instance
            if instance is not None:
                instance.begin_turn(owner)

    def plan(self, text: str, *, session_id: str | None = None) -> Any:
        """Realize ToolAgent only for actionable requests or a live tool task."""
        settings = self._pending_settings or getattr(self._instance, "settings", {}) or {}
        mode = str(settings.get("tools_mode", "auto") or "auto").lower()
        if mode == "off":
            return None

        from .tools import protocol

        detected = protocol.detect_categories(text)
        instance = self._instance
        owner = str(session_id or "")
        if instance is not None:
            context = getattr(instance.registry, "web_context", None)
            current = context.store.current() if context is not None else None
            if (
                current is not None
                and current.status == "paused"
                and len(str(text or "").split()) <= 6
                and __import__("re").search(r"ادامه|بده|بزن|continue|resume", str(text or ""), __import__("re").I)
            ):
                detected.add("web")
        pending_task = self._active_task(owner) is not None
        if instance is not None and not pending_task:
            try:
                pending_task = bool(instance.has_new_pending_confirmation(owner))
            except (AttributeError, KeyError, TypeError):
                pending_task = False

        if mode != "always" and not detected and not pending_task and not protocol.is_actionable_intent(text):
            return None
        if self._pending_competitive_safe_mode and "web" not in detected:
            return None
        return self._get().plan(text, session_id=owner)

    def request_cancel(self, *args: Any, **kwargs: Any) -> bool:
        """A not-yet-created agent has no running requests to cancel."""
        instance = self._instance
        return bool(instance.request_cancel(*args, **kwargs)) if instance is not None else False

    def clear_session(self, *args: Any, **kwargs: Any) -> Any:
        """An explicit clear request also clears durable task history."""
        self._pending_begin_turns.discard(str(args[0] if args else kwargs.get("session_id") or ""))
        return self._get().clear_session(*args, **kwargs)

    def release_session(self, *args: Any, **kwargs: Any) -> bool:
        """Do not construct tool infrastructure merely to release nonexistent state."""
        owner = str(args[0] if args else kwargs.get("session_id") or "")
        instance = self._instance
        if owner:
            self._pending_begin_turns.discard(owner)
        return bool(instance.release_session(*args, **kwargs)) if instance is not None else False

    def is_task_running(self, *args: Any, **kwargs: Any) -> bool:
        """Callback registration and idle checks must not construct ToolAgent."""
        instance = self._instance
        return bool(instance.is_task_running(*args, **kwargs)) if instance is not None else False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)
