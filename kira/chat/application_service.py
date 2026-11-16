"""Application-level orchestration for one or more character chat sessions.

The service composes the existing coordinator, context builder, response handler
and persistence contracts. It contains no Qt/UI code and does not reimplement
queueing, prompt composition, provider event normalization or storage.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from .context_builder import ContextBuilder, ContextRequest
from .coordinator import ChatCoordinator, ChatProviderDispatcher, ChatRequest, SubmissionResult
from .response_handler import (
    ChatResponseResult,
    ProviderEvent,
    ProviderEventKind,
    ResponseEventKind,
    ResponseHandler,
    ResponseStatus,
)


class RequestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApplicationEventKind(str, Enum):
    REQUEST_STARTED = "request_started"
    PROVIDER_CHUNK = "provider_chunk"
    PROVIDER_FINAL = "provider_final"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    REQUEST_CANCELLED = "request_cancelled"
    PERSISTENCE_WARNING = "persistence_warning"


@dataclass(frozen=True)
class ChatApplicationRequest:
    request_id: str
    session_id: str
    text: str
    attachments: tuple[Mapping[str, Any], ...] = ()
    voice: bool = False
    conversation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatApplicationEvent:
    request_id: str
    session_id: str
    kind: ApplicationEventKind
    status: RequestStatus
    content: str = ""
    chunk: str = ""
    result: ChatResponseResult | None = None
    error: str | None = None
    persistence_ok: bool | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Submission:
    request: ChatApplicationRequest
    status: RequestStatus
    queued: bool
    accepted: bool


@dataclass(frozen=True)
class PersistenceOutcome:
    ok: bool
    error: str | None = None


@dataclass
class _RequestState:
    request: ChatApplicationRequest
    status: RequestStatus = RequestStatus.PENDING
    worker: Any = None
    attempt: int = 0
    last_content: str = ""


class ChatApplicationService:
    """Own the application lifecycle while delegating feature work to its ports.

    A coordinator is created per session. UI policy is supplied through
    `on_dispatch`; the callback receives an immutable, request-scoped object.
    Provider worker construction, ContextBuilder, ResponseHandler and
    persistence remain behind this service's public API.
    """

    def __init__(
        self,
        *,
        persistence: Any,
        system_prompt_builder: Callable[..., str],
        worker_factory: Callable[..., Any],
        on_dispatch: Callable[[ChatApplicationRequest], Any],
        on_event: Callable[[ChatApplicationEvent], Any] | None = None,
        prompt_enricher: Callable[[str], str] | None = None,
        schedule: Callable[[Callable[[], Any]], Any] | None = None,
        cancel_provider: Callable[[ChatApplicationRequest, Any], Any] | None = None,
        max_pending: int = 3,
        request_history_limit: int = 512,
    ) -> None:
        if persistence is None:
            raise TypeError("persistence is required")
        if not callable(system_prompt_builder) or not callable(worker_factory):
            raise TypeError("system_prompt_builder and worker_factory must be callable")
        if not callable(on_dispatch):
            raise TypeError("on_dispatch must be callable")
        if request_history_limit < 1:
            raise ValueError("request_history_limit must be at least 1")
        self._persistence = persistence
        self._context_builder = ContextBuilder(
            system_prompt_builder, prompt_enricher=prompt_enricher
        )
        self._worker_factory = worker_factory
        self._on_dispatch = on_dispatch
        self._on_event = on_event
        self._schedule = schedule or (lambda callback: callback())
        self._cancel_provider = cancel_provider
        self._max_pending = int(max_pending)
        self._history_limit = int(request_history_limit)
        self._response_handler = ResponseHandler(completed_history_limit=request_history_limit)
        self._coordinators: dict[str, ChatCoordinator] = {}
        self._requests: OrderedDict[str, _RequestState] = OrderedDict()
        self._chat_request_ids: dict[tuple[str, int], str] = {}
        self._attempt_to_request: dict[str, str] = {}
        self._active_by_session: dict[str, str] = {}
        self._dispatch_scheduled: set[str] = set()
        self._disposed = False

    def _emit(self, event: ChatApplicationEvent) -> None:
        callback = self._on_event
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            # A UI observer must not corrupt the request lifecycle.
            return

    def _coordinator(self, session_id: str) -> ChatCoordinator:
        coordinator = self._coordinators.get(session_id)
        if coordinator is None:
            coordinator = ChatCoordinator(
                lambda item, owner=session_id: self._dispatch(owner, item),
                max_pending=self._max_pending,
                provider_dispatcher=ChatProviderDispatcher(self._worker_factory),
            )
            self._coordinators[session_id] = coordinator
        return coordinator

    def submit_message(
        self,
        session_id: str,
        text: str,
        attachments: Sequence[Mapping[str, Any]] | None = None,
        voice: bool = False,
        *,
        busy: bool = False,
        force_queue: bool = False,
        conversation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Submission:
        if self._disposed:
            raise RuntimeError("ChatApplicationService has been disposed")
        owner = str(session_id or "").strip()
        if not owner:
            raise ValueError("session_id must not be empty")
        request_id = uuid4().hex
        request = ChatApplicationRequest(
            request_id=request_id,
            session_id=owner,
            text=str(text or ""),
            attachments=tuple(dict(item) for item in (attachments or ())),
            voice=bool(voice),
            conversation_id=str(conversation_id) if conversation_id else None,
            metadata=dict(metadata or {}),
        )
        state = _RequestState(request=request)
        self._requests[request_id] = state
        self._requests.move_to_end(request_id)
        chat_request = ChatRequest.create(request.text, request.attachments, request.voice)
        self._chat_request_ids[(owner, id(chat_request))] = request_id
        coordinator = self._coordinator(owner)
        result = coordinator.submit(
            chat_request,
            busy=bool(busy or owner in self._active_by_session),
            force_queue=force_queue or owner in self._dispatch_scheduled,
        )
        if result is SubmissionResult.FULL:
            state.status = RequestStatus.FAILED
            self._chat_request_ids.pop((owner, id(chat_request)), None)
            self._emit(ChatApplicationEvent(
                request_id, owner, ApplicationEventKind.REQUEST_FAILED,
                RequestStatus.FAILED, error="The pending chat queue is full.",
            ))
            self._prune_history()
            return Submission(request, state.status, queued=False, accepted=False)
        self._prune_history()
        return Submission(
            request=request,
            status=state.status,
            queued=result is SubmissionResult.QUEUED,
            accepted=True,
        )

    def _dispatch(self, session_id: str, chat_request: ChatRequest) -> None:
        request_id = self._chat_request_ids.pop((session_id, id(chat_request)), None)
        state = self._requests.get(request_id or "")
        if state is None or state.status is not RequestStatus.PENDING:
            self.dispatch_next(session_id)
            return
        if session_id in self._active_by_session:
            # Defensive: never allow a coordinator callback to overlap a session.
            self._chat_request_ids[(session_id, id(chat_request))] = state.request.request_id
            return
        state.status = RequestStatus.RUNNING
        self._active_by_session[session_id] = state.request.request_id
        self._emit(ChatApplicationEvent(
            state.request.request_id, session_id,
            ApplicationEventKind.REQUEST_STARTED, RequestStatus.RUNNING,
        ))
        try:
            self._on_dispatch(state.request)
        except Exception as exc:
            self._finalize(
                state,
                RequestStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                kind=ApplicationEventKind.REQUEST_FAILED,
            )

    def dispatch_next(self, session_id: str, *, busy: bool = False) -> bool:
        """Schedule the next FIFO item for one session without crossing sessions."""
        owner = str(session_id or "").strip()
        if not owner or self._disposed or busy or owner in self._active_by_session:
            return False
        if owner in self._dispatch_scheduled:
            return False
        coordinator = self._coordinators.get(owner)
        if coordinator is None:
            return False
        item = coordinator.take_next(busy=False)
        if item is None:
            return False
        self._dispatch_scheduled.add(owner)

        def dispatch_reserved() -> None:
            self._dispatch_scheduled.discard(owner)
            self._dispatch(owner, item)

        try:
            self._schedule(dispatch_reserved)
        except Exception:
            self._dispatch_scheduled.discard(owner)
            self._dispatch(owner, item)
        return True

    def active_request_id(self, session_id: str) -> str | None:
        return self._active_by_session.get(str(session_id or ""))

    def get_request_status(self, request_id: str) -> RequestStatus | None:
        state = self._requests.get(str(request_id or ""))
        return state.status if state else None

    def start_provider_request(
        self,
        request_id: str,
        context: Mapping[str, Any],
        *,
        provider_callbacks: Mapping[str, Callable[..., Any]] | None = None,
        **provider_request: Any,
    ) -> Any:
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status is not RequestStatus.RUNNING:
            raise ValueError("request is not active")
        owner = state.request.session_id
        attempt_id = None
        try:
            context_request = context if isinstance(context, ContextRequest) else ContextRequest(**dict(context))
            context_result = self._context_builder.build(context_request)
            state.attempt += 1
            attempt_id = f"{state.request.request_id}:{state.attempt}"
            self._response_handler.begin_request(
                attempt_id, owner,
                metadata={"application_request_id": state.request.request_id, "attempt": state.attempt},
            )
            self._attempt_to_request[attempt_id] = state.request.request_id
            callbacks = dict(provider_callbacks or {})
            callbacks.update({
                "chunk": lambda piece, aid=attempt_id, sid=owner: self.handle_provider_event(
                    ProviderEvent.chunk(aid, sid, piece)
                ),
                "complete": lambda response, aid=attempt_id, sid=owner: self.handle_provider_event(
                    ProviderEvent.completed(aid, sid, response)
                ),
                "error": lambda error, aid=attempt_id, sid=owner: self.handle_provider_event(
                    ProviderEvent.failed(aid, sid, error)
                ),
            })
            worker = self._coordinator(owner).start_provider_request(
                callbacks=callbacks,
                messages=[dict(message) for message in context_result.messages],
                prompt=context_result.system_prompt,
                **provider_request,
            )
            state.worker = worker
            return worker
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if attempt_id is not None and attempt_id in self._attempt_to_request:
                self.handle_provider_event(ProviderEvent.failed(attempt_id, owner, message))
            else:
                self._finalize(
                    state, RequestStatus.FAILED, content=state.last_content,
                    error=message, kind=ApplicationEventKind.REQUEST_FAILED,
                )
            return None

    def handle_provider_event(self, event: ProviderEvent) -> ChatApplicationEvent | None:
        normalized = self._response_handler.handle(event)
        if normalized is None:
            return None
        request_id = self._attempt_to_request.pop(event.request_id, None)
        state = self._requests.get(request_id or "")
        if state is None or state.request.session_id != event.session_id:
            return None
        if normalized.kind is ResponseEventKind.CHUNK:
            state.last_content = normalized.content
            application_event = ChatApplicationEvent(
                request_id, event.session_id, ApplicationEventKind.PROVIDER_CHUNK,
                state.status, content=normalized.content, chunk=normalized.chunk,
            )
            self._emit(application_event)
            return application_event

        result = normalized.result
        if result is None:
            return None
        state.last_content = result.content
        if result.status is ResponseStatus.COMPLETED:
            application_event = ChatApplicationEvent(
                request_id, event.session_id, ApplicationEventKind.PROVIDER_FINAL,
                state.status, content=result.content, result=result,
            )
            self._emit(application_event)
            return application_event

        terminal_status = (
            RequestStatus.CANCELLED if result.status is ResponseStatus.CANCELLED
            else RequestStatus.FAILED
        )
        persistence_status = (
            "cancelled" if terminal_status is RequestStatus.CANCELLED
            else "interrupted" if result.metadata.get("interrupted")
            else "failed"
        )
        outcome = self._persist_response(state, result.content, persistence_status, result.metadata)
        self._finalize(
            state,
            terminal_status,
            content=result.content,
            error=result.error.message if result.error else None,
            kind=(
                ApplicationEventKind.REQUEST_CANCELLED
                if terminal_status is RequestStatus.CANCELLED
                else ApplicationEventKind.REQUEST_FAILED
            ),
            persistence_ok=outcome.ok,
            metadata=result.metadata,
        )
        return ChatApplicationEvent(
            request_id, event.session_id,
            ApplicationEventKind.REQUEST_CANCELLED if terminal_status is RequestStatus.CANCELLED
            else ApplicationEventKind.REQUEST_FAILED,
            terminal_status, content=result.content,
            result=result, error=result.error.message if result.error else None,
            persistence_ok=outcome.ok, metadata=result.metadata,
        )

    def complete_request(
        self,
        request_id: str,
        content: str,
        *,
        status: str = "complete",
        metadata: Mapping[str, Any] | None = None,
        persist: bool = True,
    ) -> PersistenceOutcome:
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status is not RequestStatus.RUNNING:
            return PersistenceOutcome(False, "request is not active")
        outcome = (
            self._persist_response(state, str(content or ""), status, metadata or {})
            if persist else PersistenceOutcome(True)
        )
        self._finalize(
            state, RequestStatus.COMPLETED, content=str(content or ""),
            kind=ApplicationEventKind.REQUEST_COMPLETED, persistence_ok=outcome.ok,
            error=outcome.error,
        )
        return outcome

    def complete_local_request(self, request_id: str) -> bool:
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status is not RequestStatus.RUNNING:
            return False
        self._finalize(state, RequestStatus.COMPLETED, kind=ApplicationEventKind.REQUEST_COMPLETED)
        return True

    def persist_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        request_id: str | None = None,
        conversation_id: str | None = None,
        status: str = "complete",
        metadata: Mapping[str, Any] | None = None,
    ) -> PersistenceOutcome:
        owner = str(session_id or "").strip()
        if not owner:
            return PersistenceOutcome(False, "session_id must not be empty")
        request_state = self._requests.get(str(request_id or "")) if request_id else None
        if conversation_id is None and request_state is not None:
            conversation_id = request_state.request.conversation_id
        try:
            ok = self._persistence.add_message(
                role, content, owner,
                conversation_id=conversation_id,
                status=status,
                metadata={
                    **dict(metadata or {}),
                    **({"request_id": request_id, "session_id": owner} if request_id else {}),
                },
            )
            if ok:
                return PersistenceOutcome(True)
            error = getattr(self._persistence, "last_error", None) or "Persistence queued the message in memory."
            self._emit(ChatApplicationEvent(
                str(request_id or ""), owner, ApplicationEventKind.PERSISTENCE_WARNING,
                self.get_request_status(request_id) if request_id else RequestStatus.RUNNING,
                error=str(error), persistence_ok=False,
            ))
            return PersistenceOutcome(False, str(error))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit(ChatApplicationEvent(
                str(request_id or ""), owner, ApplicationEventKind.PERSISTENCE_WARNING,
                self.get_request_status(request_id) if request_id else RequestStatus.RUNNING,
                error=error, persistence_ok=False,
            ))
            return PersistenceOutcome(False, error)

    def cancel_request(self, request_id: str) -> bool:
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status in (RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED):
            return False
        if state.status is RequestStatus.PENDING:
            state.status = RequestStatus.CANCELLED
            self._emit(ChatApplicationEvent(
                state.request.request_id, state.request.session_id,
                ApplicationEventKind.REQUEST_CANCELLED, RequestStatus.CANCELLED,
            ))
            self._prune_history()
            return True
        try:
            if self._cancel_provider is not None:
                self._cancel_provider(state.request, state.worker)
            attempt_id = f"{state.request.request_id}:{state.attempt}"
            if state.attempt and attempt_id in self._attempt_to_request:
                self.handle_provider_event(ProviderEvent.cancelled(attempt_id, state.request.session_id))
            else:
                outcome = self._persist_response(
                    state, state.last_content, "cancelled", {"cancelled": True}
                )
                self._finalize(
                    state, RequestStatus.CANCELLED, content=state.last_content,
                    kind=ApplicationEventKind.REQUEST_CANCELLED,
                    persistence_ok=outcome.ok,
                    error=outcome.error,
                )
            return True
        except Exception as exc:
            self._finalize(
                state, RequestStatus.FAILED, content=state.last_content,
                error=f"Cancellation failed: {type(exc).__name__}: {exc}",
                kind=ApplicationEventKind.REQUEST_FAILED,
            )
            return False

    def close_session(self, session_id: str) -> None:
        owner = str(session_id or "").strip()
        if not owner:
            return
        for request_id, state in tuple(self._requests.items()):
            if state.request.session_id == owner and state.status in (RequestStatus.PENDING, RequestStatus.RUNNING):
                self.cancel_request(request_id)
        coordinator = self._coordinators.pop(owner, None)
        if coordinator is not None:
            coordinator.clear()
        self._dispatch_scheduled.discard(owner)
        self._active_by_session.pop(owner, None)

    def dispose(self) -> None:
        if self._disposed:
            return
        for owner in tuple(self._coordinators):
            self.close_session(owner)
        self._disposed = True

    def pending_count(self, session_id: str) -> int:
        coordinator = self._coordinators.get(str(session_id or ""))
        return coordinator.pending_count if coordinator is not None else 0

    def has_pending_work(self, session_id: str) -> bool:
        owner = str(session_id or "")
        return bool(self.pending_count(owner) or owner in self._dispatch_scheduled)

    def is_dispatch_scheduled(self, session_id: str) -> bool:
        return str(session_id or "") in self._dispatch_scheduled

    @property
    def last_persistence_error(self) -> str | None:
        return getattr(self._persistence, "last_error", None)

    def set_persistence_error(self, message: str | None) -> None:
        setter = getattr(self._persistence, "set_last_error", None)
        if callable(setter):
            setter(message)

    def init_history(self) -> list[str]:
        initializer = getattr(self._persistence, "init_db", None)
        return list(initializer() or []) if callable(initializer) else []

    def recent_messages(self, limit: int = 12, session_id: str | None = None):
        return self._persistence.recent_messages(limit, session_id)

    def conversation_context(self, limit: int = 12, max_chars: int = 12000, session_id: str | None = None):
        return self._persistence.conversation_context(limit, max_chars, session_id)

    def message_count(self, session_id: str | None = None) -> int:
        return self._persistence.message_count(session_id)

    def clear_history(self, session_id: str | None = None) -> Any:
        return self._persistence.clear_memory(session_id)

    def restore_history(self) -> int:
        return self._persistence.restore_last_cleared()

    def import_history(self, source: Any) -> int:
        return self._persistence.import_messages(source)

    def fail_request(self, request_id: str, error: str) -> bool:
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status not in (RequestStatus.PENDING, RequestStatus.RUNNING):
            return False
        self._finalize(
            state, RequestStatus.FAILED, content=state.last_content,
            error=str(error), kind=ApplicationEventKind.REQUEST_FAILED,
        )
        return True

    def has_active_request(self, session_id: str) -> bool:
        return str(session_id or "") in self._active_by_session

    def _persist_response(
        self,
        state: _RequestState,
        content: str,
        status: str,
        metadata: Mapping[str, Any] | None,
    ) -> PersistenceOutcome:
        if not str(content or "").strip():
            return PersistenceOutcome(True)
        return self.persist_message(
            state.request.session_id, "assistant", content,
            request_id=state.request.request_id,
            conversation_id=state.request.conversation_id,
            status=status,
            metadata=metadata,
        )

    def _finalize(
        self,
        state: _RequestState,
        status: RequestStatus,
        *,
        content: str = "",
        error: str | None = None,
        kind: ApplicationEventKind,
        persistence_ok: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if state.status in (RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED):
            return
        state.status = status
        owner = state.request.session_id
        if self._active_by_session.get(owner) == state.request.request_id:
            self._active_by_session.pop(owner, None)
        state.worker = None
        self._emit(ChatApplicationEvent(
            state.request.request_id, owner, kind, status,
            content=content or state.last_content,
            error=error, persistence_ok=persistence_ok,
            metadata=dict(metadata or {}),
        ))
        self._prune_history()

    def _prune_history(self) -> None:
        terminal = (RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED)
        while len(self._requests) > self._history_limit:
            removable = next((key for key, value in self._requests.items() if value.status in terminal), None)
            if removable is None:
                break
            self._requests.pop(removable, None)
