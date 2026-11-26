"""Application-level orchestration for one or more character chat sessions.

The service composes the existing coordinator, context builder, response handler
and persistence contracts. It contains no Qt/UI code and does not reimplement
queueing, prompt composition, provider event normalization or storage.
"""
from __future__ import annotations

from collections import OrderedDict
import base64
import binascii
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from ..core.interfaces.application_services import ApplicationEventPublisherPort
from ..core.interfaces.chat_history_service import ChatHistoryService
from ..core.interfaces.context import PromptEnricherPort, SystemPromptBuilderPort
from ..core.interfaces.conversation_lifecycle import ConversationLifecycleApplicationPort
from ..core.interfaces.provider_worker import ProviderWorkerPort
from ..domain.chat import (
    ApplicationEventKind,
    ChatApplicationEvent,
    ChatApplicationRequest,
    ChatRequest,
    ChatResponseResult,
    ContextRequest,
    PersistenceOutcome,
    ProviderEvent,
    ProviderEventKind,
    RequestStatus,
    ResponseEventKind,
    ResponseStatus,
    Submission,
    SubmissionResult,
)
from .attachments import Attachment, AttachmentManager, compose as compose_attachment_payload
from .commands import CommandDispatch, CommandRegistry
from .context_builder import ContextBuilder
from .coordinator import ChatCoordinator, ChatProviderDispatcher
from .response_handler import ResponseHandler
from .history_facade import ChatHistoryFacade


@dataclass
class _RequestState:
    request: ChatApplicationRequest
    status: RequestStatus = RequestStatus.PENDING
    worker: ProviderWorkerPort | None = None
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
        persistence: ChatHistoryService,
        system_prompt_builder: SystemPromptBuilderPort,
        worker_factory: Callable[..., ProviderWorkerPort],
        on_dispatch: Callable[[ChatApplicationRequest], Any],
        on_event: Callable[[ChatApplicationEvent], Any] | None = None,
        event_publisher: ApplicationEventPublisherPort | None = None,
        prompt_enricher: PromptEnricherPort | None = None,
        schedule: Callable[[Callable[[], Any]], Any] | None = None,
        cancel_provider: Callable[[ChatApplicationRequest, ProviderWorkerPort | None], Any] | None = None,
        max_pending: int = 3,
        request_history_limit: int = 512,
        attachment_manager: AttachmentManager | None = None,
        command_registry: CommandRegistry | None = None,
        conversation_lifecycle: ConversationLifecycleApplicationPort | None = None,
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
        self._attachment_manager = attachment_manager or AttachmentManager()
        self._owns_attachment_manager = attachment_manager is None
        self._context_builder = ContextBuilder(
            system_prompt_builder, prompt_enricher=prompt_enricher
        )
        self._worker_factory = worker_factory
        self._on_dispatch = on_dispatch
        self._on_event = on_event
        self._event_publisher = event_publisher
        self._command_registry = command_registry
        self._conversation_lifecycle = conversation_lifecycle
        self._history = ChatHistoryFacade(persistence, conversation_lifecycle)
        self._schedule = schedule or (lambda callback: callback())
        self._cancel_provider = cancel_provider
        self._max_pending = int(max_pending)
        self._history_limit = int(request_history_limit)
        self._response_handler = ResponseHandler(completed_history_limit=request_history_limit)
        self._coordinators: dict[str, ChatCoordinator] = {}
        self._requests: OrderedDict[str, _RequestState] = OrderedDict()
        self._request_attachment_ids: dict[str, tuple[str, ...]] = {}
        self._attempt_to_request: dict[str, str] = {}
        self._active_by_session: dict[str, str] = {}
        self._dispatch_scheduled: set[str] = set()
        self._disposed = False
        self._shutting_down = False

    @property
    def max_attachments(self) -> int:
        """Return the active attachment manager's per-message limit."""
        return self._attachment_manager.max_files

    @staticmethod
    def compose_attachments(
        text: str, attachments: Sequence[Mapping[str, Any]], *, search: bool = False,
    ) -> dict[str, Any]:
        """Compose legacy attachment payloads behind the Chat application boundary."""
        return compose_attachment_payload(text, list(attachments or ()), search=search)

    def add_attachment(
        self, source: Any, *, session_id: str, filename: str | None = None,
        message_id: str | None = None, metadata: Mapping[str, Any] | None = None,
    ) -> Attachment:
        """Register a file/byte payload under the requested character session."""
        return self._attachment_manager.add_attachment(
            source, filename=filename, session_id=session_id,
            message_id=message_id, metadata=metadata,
        )

    def prepare_attachments(
        self, attachment_ids: Sequence[str], *, session_id: str,
        text: str = "", search: bool = False,
    ) -> dict[str, Any]:
        """Prepare scoped attachment content; prompt/provider work stays elsewhere."""
        return self._attachment_manager.prepare_content(
            tuple(attachment_ids), session_id=session_id, text=text, search=search,
        )

    def remove_attachment(self, attachment_id: str, *, session_id: str) -> bool:
        return self._attachment_manager.remove_attachment(
            attachment_id, session_id=session_id,
        )

    def cleanup_attachments(self, *, session_id: str | None = None) -> int:
        removed = self._attachment_manager.cleanup(session_id=session_id)
        if session_id is not None:
            for request_id, state in tuple(self._requests.items()):
                if state.request.session_id == str(session_id):
                    self._request_attachment_ids.pop(request_id, None)
        return removed

    def set_command_registry(self, registry: CommandRegistry | None) -> None:
        """Inject the shared command dispatcher; execution remains in registered handlers."""
        if registry is not None and not isinstance(registry, CommandRegistry):
            raise TypeError("registry must be a CommandRegistry or None")
        self._command_registry = registry

    def _dispatch_command_text(
        self,
        text: str,
        *,
        session_id: str,
        request_id: str,
        metadata: Mapping[str, Any] | None = None,
        source: str = "chat",
    ) -> CommandDispatch:
        registry = self._command_registry
        if registry is None:
            return CommandDispatch()
        owner = str(session_id or "").strip()
        request = str(request_id or "").strip()
        if not owner or not request:
            raise ValueError("session_id and request_id are required")
        details = dict(metadata or {})
        self._publish_event(
            "command_dispatch_started",
            session_id=owner,
            request_id=request,
            payload={"source": source},
            metadata={"source": source, "parent_request_id": details.get("parent_request_id")},
        )
        try:
            dispatch = registry.dispatch_text(
                text,
                session_id=owner,
                request_id=request,
                metadata=details,
                source=source,
            )
        except Exception as exc:
            self._publish_event(
                "command_dispatch_failed",
                session_id=owner,
                request_id=request,
                payload={"source": source, "error_type": type(exc).__name__},
                metadata={"source": source, "parent_request_id": details.get("parent_request_id")},
            )
            raise
        event_type = (
            "command_dispatch_failed" if dispatch.failed
            else "command_dispatch_completed"
        )
        self._publish_event(
            event_type,
            session_id=owner,
            request_id=request,
            payload={
                "source": source,
                "handled": dispatch.handled,
                "continue_chat": dispatch.continue_chat,
                "results": [
                    {"command_id": item.command_id, "status": item.status.value}
                    for item in dispatch.results
                ],
            },
            metadata={"source": source, "parent_request_id": details.get("parent_request_id")},
        )
        return dispatch

    def dispatch_commands(
        self,
        request_id: str,
        text: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        source: str = "chat",
    ) -> CommandDispatch:
        """Dispatch deterministic commands for the active chat request and session."""
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status is not RequestStatus.RUNNING:
            raise ValueError("chat request is not active")
        return self._dispatch_command_text(
            text,
            session_id=state.request.session_id,
            request_id=state.request.request_id,
            metadata=metadata,
            source=source,
        )

    def dispatch_control_commands(
        self,
        session_id: str,
        text: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> CommandDispatch:
        """Dispatch an out-of-band control message without queueing it as a new chat turn."""
        owner = str(session_id or "").strip()
        if not owner:
            raise ValueError("session_id is required")
        parent_request_id = self._active_by_session.get(owner)
        if not parent_request_id:
            return CommandDispatch()
        control_request_id = uuid4().hex
        details = dict(metadata or {})
        details["parent_request_id"] = parent_request_id
        return self._dispatch_command_text(
            text,
            session_id=owner,
            request_id=control_request_id,
            metadata=details,
            source="control",
        )

    def _emit(self, event: ChatApplicationEvent) -> None:
        callback = self._on_event
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            # A UI observer must not corrupt the request lifecycle.
            return

    def set_event_publisher(self, publisher: ApplicationEventPublisherPort | None) -> None:
        """Attach the shared typed notification publisher without transferring lifecycle ownership."""
        if publisher is not None and not callable(getattr(publisher, "publish", None)):
            raise TypeError("event publisher must expose publish()")
        self._event_publisher = publisher

    def _publish_event(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        request_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        publisher = self._event_publisher
        if publisher is None:
            return
        try:
            publisher.publish(
                event_type,
                session_id=session_id,
                request_id=request_id,
                payload=payload,
                metadata=metadata,
            )
        except Exception:
            # Notifications are best-effort and cannot break request execution.
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

    def _register_request_attachments(
        self, request_id: str, session_id: str,
        attachments: Sequence[Mapping[str, Any]] | None,
    ) -> tuple[str, ...]:
        """Move legacy UI payloads into managed storage before request dispatch."""
        ids: list[str] = []
        try:
            for index, item in enumerate(attachments or ()):
                if not isinstance(item, Mapping):
                    raise ValueError("attachment payload must be a mapping")
                kind = str(item.get("kind") or "")
                filename = str(item.get("name") or f"attachment-{index + 1}")
                if kind == "image":
                    encoded = str(item.get("b64") or "")
                    max_encoded = 4 * ((self._attachment_manager.max_image_bytes + 2) // 3)
                    if len(encoded) > max_encoded:
                        raise ValueError("image attachment exceeds size limit")
                    raw = base64.b64decode(encoded, validate=True)
                elif kind == "text":
                    text_content = str(item.get("text") or "")
                    if len(text_content) > self._attachment_manager.max_file_bytes:
                        raise ValueError("text attachment exceeds size limit")
                    raw = text_content.encode("utf-8")
                else:
                    raise ValueError("unsupported attachment payload kind")
                record = self._attachment_manager.add_attachment(
                    raw, filename=filename, session_id=session_id,
                    message_id=request_id,
                    metadata={"kind": kind},
                )
                if record.attachment_id not in ids:
                    ids.append(record.attachment_id)
        except Exception:
            for attachment_id in ids:
                self._attachment_manager.remove_attachment(
                    attachment_id, session_id=session_id,
                )
            raise
        return tuple(ids)

    def add_request_attachment(
        self, request_id: str, attachment: Mapping[str, Any],
    ) -> str:
        """Attach one late-bound payload (for example a captured game frame) to its request."""
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status is not RequestStatus.RUNNING:
            raise ValueError("chat request is not active")
        created = self._register_request_attachments(
            state.request.request_id, state.request.session_id, (attachment,),
        )
        current = self._request_attachment_ids.get(state.request.request_id, ())
        if created[0] not in current:
            self._request_attachment_ids[state.request.request_id] = current + created
        return created[0]

    def prepare_request_attachments(
        self, request_id: str, *, text: str = "", search: bool = False,
    ) -> dict[str, Any] | None:
        """Prepare the managed files for one active request, isolated by its session."""
        state = self._requests.get(str(request_id or ""))
        if state is None:
            raise ValueError("unknown chat request")
        ids = self._request_attachment_ids.get(state.request.request_id, ())
        if not ids:
            return None
        return self._attachment_manager.prepare_content(
            ids, session_id=state.request.session_id, text=text, search=search,
        )

    def cleanup_request_attachments(self, request_id: str) -> int:
        state = self._requests.get(str(request_id or ""))
        ids = self._request_attachment_ids.pop(str(request_id or ""), ())
        if state is None:
            return 0
        return self._attachment_manager.cleanup(
            session_id=state.request.session_id,
            message_id=state.request.request_id,
        )

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
        character_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Submission:
        if self._disposed or self._shutting_down:
            raise RuntimeError("ChatApplicationService is shutting down or disposed")
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
            character_id=str(character_id or owner),
            metadata=dict(metadata or {}),
        )
        state = _RequestState(request=request)
        self._requests[request_id] = state
        self._requests.move_to_end(request_id)
        try:
            self._request_attachment_ids[request_id] = self._register_request_attachments(
                request_id, owner, request.attachments,
            )
        except (ValueError, TypeError, binascii.Error) as exc:
            state.status = RequestStatus.FAILED
            self._publish_event(
                "request_failed", session_id=owner, request_id=request_id,
                payload={"error": f"Invalid attachment: {type(exc).__name__}"},
            )
            self._emit(ChatApplicationEvent(
                request_id, owner, ApplicationEventKind.REQUEST_FAILED,
                RequestStatus.FAILED, error=f"Invalid attachment: {type(exc).__name__}",
            ))
            self._prune_history()
            return Submission(request, state.status, queued=False, accepted=False)
        chat_request = ChatRequest.create(
            request.text, request.attachments, request.voice,
            request_id=request_id, session_id=owner,
        )
        coordinator = self._coordinator(owner)
        result = coordinator.submit(
            chat_request,
            busy=bool(busy or owner in self._active_by_session),
            force_queue=force_queue or owner in self._dispatch_scheduled,
        )
        if result is SubmissionResult.FULL:
            state.status = RequestStatus.FAILED
            self._publish_event(
                "request_failed", session_id=owner, request_id=request_id,
                payload={"error": "The pending chat queue is full."},
            )
            self.cleanup_request_attachments(request_id)
            self._emit(ChatApplicationEvent(
                request_id, owner, ApplicationEventKind.REQUEST_FAILED,
                RequestStatus.FAILED, error="The pending chat queue is full.",
            ))
            self._prune_history()
            return Submission(request, state.status, queued=False, accepted=False)
        self._prune_history()
        self._publish_event(
            "request_submitted", session_id=owner, request_id=request_id,
            payload={"queued": result is SubmissionResult.QUEUED},
        )
        return Submission(
            request=request,
            status=state.status,
            queued=result is SubmissionResult.QUEUED,
            accepted=True,
        )

    def _dispatch(self, session_id: str, chat_request: ChatRequest) -> None:
        request_id = chat_request.request_id
        if chat_request.session_id != session_id:
            self.dispatch_next(session_id)
            return
        state = self._requests.get(request_id or "")
        if state is None or state.status is not RequestStatus.PENDING:
            self.dispatch_next(session_id)
            return
        if session_id in self._active_by_session:
            # Preserve the immutable request identity if a defensive requeue is needed.
            coordinator = self._coordinators.get(session_id)
            if coordinator is not None:
                coordinator.submit(chat_request, busy=True, force_queue=True)
            return
        state.status = RequestStatus.RUNNING
        self._active_by_session[session_id] = state.request.request_id
        self._emit(ChatApplicationEvent(
            state.request.request_id, session_id,
            ApplicationEventKind.REQUEST_STARTED, RequestStatus.RUNNING,
        ))
        self._publish_event(
            "request_started", session_id=session_id, request_id=state.request.request_id,
        )
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
        if not owner or self._disposed or self._shutting_down or busy or owner in self._active_by_session:
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
        provider_event_dispatcher: Callable[[ProviderEvent], Any] | None = None,
        **provider_request: Any,
    ) -> ProviderWorkerPort:
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
            self._publish_event(
                "stream_started", session_id=owner, request_id=state.request.request_id,
                payload={"provider_request_id": attempt_id},
                metadata={"attempt": state.attempt},
            )
            callbacks = dict(provider_callbacks or {})
            dispatch_event = provider_event_dispatcher or self.handle_provider_event
            callbacks.update({
                "chunk": lambda piece, aid=attempt_id, sid=owner: dispatch_event(
                    ProviderEvent.chunk(aid, sid, piece)
                ),
                "complete": lambda response, aid=attempt_id, sid=owner: dispatch_event(
                    ProviderEvent.completed(aid, sid, response)
                ),
                "error": lambda error, aid=attempt_id, sid=owner: dispatch_event(
                    ProviderEvent.failed(aid, sid, error)
                ),
            })
            provider_request.setdefault("conversation_id", state.request.conversation_id)
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

    def handle_provider_event(
        self, event: ProviderEvent, *, partial_status_override: str | None = None
    ) -> ChatApplicationEvent | None:
        if not isinstance(event, ProviderEvent):
            raise TypeError("event must be a ProviderEvent")
        if partial_status_override not in (None, "cancelled", "interrupted"):
            raise ValueError("partial_status_override must be cancelled or interrupted")
        try:
            normalized = self._response_handler.handle(event)
        except Exception as exc:
            request_id = self._attempt_to_request.pop(event.request_id, None)
            state = self._requests.get(request_id or "")
            if state is not None and state.status is RequestStatus.RUNNING:
                try:
                    self._response_handler.handle(ProviderEvent.failed(
                        event.request_id, event.session_id,
                        f"{type(exc).__name__}: {exc}",
                    ))
                except Exception:
                    pass
                self._finalize(
                    state, RequestStatus.FAILED, content=state.last_content,
                    error=f"{type(exc).__name__}: {exc}",
                    kind=ApplicationEventKind.REQUEST_FAILED,
                )
            return None
        if normalized is None:
            return None
        request_id = self._attempt_to_request.get(event.request_id)
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
            self._publish_event(
                "stream_chunk_received", session_id=event.session_id, request_id=request_id,
                payload={"chunk": normalized.chunk, "content": normalized.content},
                metadata={"provider_request_id": event.request_id},
            )
            return application_event

        # Keep the logical-to-attempt mapping for every chunk. Remove it only
        # after ResponseHandler has produced the single terminal event.
        self._attempt_to_request.pop(event.request_id, None)
        result = normalized.result
        if result is None:
            return None
        state.last_content = result.content
        if result.status is ResponseStatus.COMPLETED:
            self._publish_event(
                "stream_completed", session_id=event.session_id, request_id=request_id,
                payload={"content": result.content, "provider_request_id": event.request_id},
            )
            application_event = ChatApplicationEvent(
                request_id, event.session_id, ApplicationEventKind.PROVIDER_FINAL,
                state.status, content=result.content, result=result,
            )
            self._emit(application_event)
            return application_event

        self._publish_event(
            "stream_interrupted", session_id=event.session_id, request_id=request_id,
            payload={"content": result.content, "provider_request_id": event.request_id},
            metadata=result.metadata,
        )
        terminal_status = (
            RequestStatus.CANCELLED if result.status is ResponseStatus.CANCELLED
            else RequestStatus.FAILED
        )
        persistence_status = (
            "cancelled" if terminal_status is RequestStatus.CANCELLED
            else "interrupted" if result.metadata.get("interrupted")
            else "failed"
        )
        terminal_metadata = dict(result.metadata)
        if partial_status_override is not None and terminal_status is RequestStatus.CANCELLED:
            persistence_status = partial_status_override
            if partial_status_override == "interrupted":
                terminal_metadata.update({"interrupted": True, "application_shutdown": True})
        outcome = self._persist_response(state, result.content, persistence_status, terminal_metadata)
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
            metadata=terminal_metadata,
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
        character_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PersistenceOutcome:
        owner = str(session_id or "").strip()
        if not owner:
            return PersistenceOutcome(False, "session_id must not be empty")
        request_state = self._requests.get(str(request_id or "")) if request_id else None
        if request_state is not None:
            if conversation_id is None:
                conversation_id = request_state.request.conversation_id
            if character_id is None:
                character_id = request_state.request.character_id
        character_owner = str(character_id or owner).strip()
        if not character_owner:
            return PersistenceOutcome(False, "character_id must not be empty")
        try:
            ok = self._persistence.add_message(
                role, content, character_owner,
                conversation_id=conversation_id,
                status=status,
                metadata={
                    **dict(metadata or {}),
                    "session_id": owner,
                    "character_id": character_owner,
                    **({"request_id": request_id} if request_id else {}),
                },
            )
            if ok:
                self._publish_event(
                    "message_saved", session_id=owner, request_id=request_id,
                    payload={"role": role, "content": content, "conversation_id": conversation_id},
                )
                return PersistenceOutcome(True)
            error = getattr(self._persistence, "last_error", None) or "Persistence queued the message in memory."
            self._publish_event(
                "persistence_failed", session_id=owner, request_id=request_id,
                payload={"operation": "message_write", "error": str(error)},
            )
            self._emit(ChatApplicationEvent(
                str(request_id or ""), owner, ApplicationEventKind.PERSISTENCE_WARNING,
                self.get_request_status(request_id) if request_id else RequestStatus.RUNNING,
                error=str(error), persistence_ok=False,
            ))
            return PersistenceOutcome(False, str(error))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._publish_event(
                "persistence_failed", session_id=owner, request_id=request_id,
                payload={"operation": "message_write", "error": error},
            )
            self._emit(ChatApplicationEvent(
                str(request_id or ""), owner, ApplicationEventKind.PERSISTENCE_WARNING,
                self.get_request_status(request_id) if request_id else RequestStatus.RUNNING,
                error=error, persistence_ok=False,
            ))
            return PersistenceOutcome(False, error)

    def cancel_request(self, request_id: str, *, partial_status: str = "cancelled") -> bool:
        if partial_status not in ("cancelled", "interrupted"):
            raise ValueError("partial_status must be cancelled or interrupted")
        state = self._requests.get(str(request_id or ""))
        if state is None or state.status in (RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED):
            return False
        if state.status is RequestStatus.PENDING:
            state.status = RequestStatus.CANCELLED
            self.cleanup_request_attachments(state.request.request_id)
            owner = state.request.session_id
            self._publish_event(
                "request_cancelled", session_id=owner, request_id=state.request.request_id,
                payload={"queued": True},
            )
            self._emit(ChatApplicationEvent(
                state.request.request_id, owner,
                ApplicationEventKind.REQUEST_CANCELLED, RequestStatus.CANCELLED,
            ))
            self._prune_history()
            if owner not in self._active_by_session:
                self.dispatch_next(owner)
            return True
        # A running request owns the active command/control work for this session.
        # Pending requests must not cancel commands belonging to the active request.
        if self._command_registry is not None:
            self._command_registry.cancel_session(state.request.session_id)
        try:
            if self._cancel_provider is not None:
                self._cancel_provider(state.request, state.worker)
            attempt_id = f"{state.request.request_id}:{state.attempt}"
            if state.attempt and attempt_id in self._attempt_to_request:
                self.handle_provider_event(
                    ProviderEvent.cancelled(attempt_id, state.request.session_id),
                    partial_status_override=partial_status,
                )
            else:
                outcome = self._persist_response(
                    state, state.last_content, partial_status,
                    {"cancelled": True, "interrupted": partial_status == "interrupted"},
                )
                self._finalize(
                    state, RequestStatus.CANCELLED, content=state.last_content,
                    kind=ApplicationEventKind.REQUEST_CANCELLED,
                    persistence_ok=outcome.ok,
                    error=outcome.error,
                )
            return True
        except Exception as exc:
            attempt_id = f"{state.request.request_id}:{state.attempt}"
            message = f"Cancellation failed: {type(exc).__name__}: {exc}"
            if attempt_id in self._attempt_to_request:
                self.handle_provider_event(ProviderEvent.failed(attempt_id, state.request.session_id, message))
            else:
                outcome = self._persist_response(
                    state, state.last_content, "failed", {"cancel_error": message}
                )
                self._finalize(
                    state, RequestStatus.FAILED, content=state.last_content,
                    error=message, kind=ApplicationEventKind.REQUEST_FAILED,
                    persistence_ok=outcome.ok,
                )
            return False

    def close_session(self, session_id: str, *, interrupted: bool = False) -> None:
        owner = str(session_id or "").strip()
        if not owner:
            return
        if self._command_registry is not None:
            self._command_registry.cancel_session(owner)
        for request_id, state in tuple(self._requests.items()):
            if state.request.session_id == owner and state.status in (RequestStatus.PENDING, RequestStatus.RUNNING):
                self.cancel_request(
                    request_id,
                    partial_status="interrupted" if interrupted else "cancelled",
                )
        coordinator = self._coordinators.pop(owner, None)
        if coordinator is not None:
            coordinator.clear()
        self._dispatch_scheduled.discard(owner)
        self._active_by_session.pop(owner, None)
        self.cleanup_attachments(session_id=owner)

    def begin_shutdown(self) -> None:
        """Reject new work and cancel current/queued requests without releasing session resources.

        The Session lifecycle still needs the command registry and attachment manager
        while it closes each session. Final disposal therefore remains a later phase.
        """
        if self._disposed or self._shutting_down:
            return
        self._shutting_down = True
        for request_id, state in tuple(self._requests.items()):
            if state.status in (RequestStatus.PENDING, RequestStatus.RUNNING):
                self.cancel_request(request_id, partial_status="interrupted")

    def dispose(self) -> None:
        if self._disposed:
            return
        self.begin_shutdown()
        for owner in tuple(self._coordinators):
            self.close_session(owner, interrupted=True)
        if self._command_registry is not None:
            self._command_registry.close()
            self._command_registry = None
        if self._owns_attachment_manager:
            self._attachment_manager.close()
        self._disposed = True

    def flush_pending_history(self) -> int:
        """Flush emergency chat writes before the application is allowed to exit."""
        flusher = getattr(self._persistence, "flush_pending", None)
        return int(flusher() or 0) if callable(flusher) else 0

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
        return self._history.last_persistence_error

    def set_persistence_error(self, message: str | None) -> None:
        self._history.set_persistence_error(message)

    def init_history(self) -> list[str]:
        return self._history.init_history()

    def get_or_create_conversation(self, character_id: str) -> dict[str, Any]:
        return self._history.get_or_create_conversation(character_id)

    def get_conversation(self, conversation_id: str):
        return self._history.get_conversation(conversation_id)

    def create_conversation(
        self, character_id: str, title: str = "", metadata: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._history.create_conversation(character_id, title, dict(metadata or {}))

    def list_conversations(self, character_id: str | None = None, *, statuses=None):
        return self._history.list_conversations(character_id, statuses=statuses)

    def archive_conversation(self, conversation_id: str):
        return self._history.archive_conversation(conversation_id)

    def archive_conversations(self, conversation_ids):
        return self._history.archive_conversations(conversation_ids)

    def restore_conversation(self, conversation_id: str):
        return self._history.restore_conversation(conversation_id)

    def trash_conversation(self, conversation_id: str):
        return self._history.trash_conversation(conversation_id)

    def trash_conversations(self, conversation_ids):
        return self._history.trash_conversations(conversation_ids)

    def restore_trashed_conversation(self, conversation_id: str):
        return self._history.restore_trashed_conversation(conversation_id)

    def permanently_delete_conversation(self, conversation_id: str, *, authorization):
        return self._history.permanently_delete_conversation(
            conversation_id, authorization=authorization
        )

    def recent_messages(
        self, limit: int = 12, character_id: str | None = None,
        conversation_id: str | None = None,
    ):
        return self._history.recent_messages(limit, character_id, conversation_id)

    def get_messages(
        self, limit: int = 1000, character_id: str | None = None,
        conversation_id: str | None = None, after_id: int = 0,
    ):
        return self._history.get_messages(
            limit, character_id, conversation_id, after_id
        )

    def recent_message_records(self, limit: int = 2000, character_id: str | None = None):
        return self._history.recent_message_records(limit, character_id)

    def conversation_context(
        self, limit: int = 12, max_chars: int = 12000,
        character_id: str | None = None, conversation_id: str | None = None,
        *, session_id: str | None = None,
    ):
        owner = character_id if character_id is not None else session_id
        return self._history.conversation_context(
            limit, max_chars, owner, conversation_id
        )

    def message_count(
        self, character_id: str | None = None, conversation_id: str | None = None
    ) -> int:
        return self._history.message_count(character_id, conversation_id)

    def clear_history(self, character_id: str | None = None) -> Any:
        return self._history.clear_history(character_id)

    def restore_history(self) -> int:
        return self._history.restore_history()

    def import_history(self, source: Any) -> int:
        return self._history.import_history(source)

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
            character_id=state.request.character_id,
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
        terminal_type = {
            RequestStatus.COMPLETED: "request_completed",
            RequestStatus.FAILED: "request_failed",
            RequestStatus.CANCELLED: "request_cancelled",
        }.get(status)
        if terminal_type is not None:
            self._publish_event(
                terminal_type, session_id=owner, request_id=state.request.request_id,
                payload={"content": content or state.last_content, "error": error},
                metadata=metadata,
            )
        self._emit(ChatApplicationEvent(
            state.request.request_id, owner, kind, status,
            content=content or state.last_content,
            error=error, persistence_ok=persistence_ok,
            metadata=dict(metadata or {}),
        ))
        self.cleanup_request_attachments(state.request.request_id)
        self._prune_history()

    def _prune_history(self) -> None:
        terminal = (RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED)
        while len(self._requests) > self._history_limit:
            removable = next((key for key, value in self._requests.items() if value.status in terminal), None)
            if removable is None:
                break
            self._requests.pop(removable, None)
