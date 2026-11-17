"""Framework-independent chat command registration, validation and dispatch.

Commands are routing adapters, not tool implementations. Existing feature owners
(usage, body control, web search, and ToolAgent) remain authoritative for their
own parsing/execution policy and are injected through handlers.
"""
from __future__ import annotations

import re
import shlex
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping
from uuid import uuid4


class CommandStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    result: Any = None
    status: CommandStatus = CommandStatus.COMPLETED
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommandMatchContext:
    session_id: str
    request_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    command_id: str
    name: str
    description: str
    parameters: Mapping[str, Any]
    required_permissions: tuple[str, ...]
    handler: Callable[["CommandExecutionContext", Mapping[str, Any]], Any]
    aliases: tuple[str, ...] = ()
    matcher: Callable[[str, CommandMatchContext], Mapping[str, Any] | None] | None = None
    parser: Callable[[str, CommandMatchContext], Mapping[str, Any] | None] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not str(self.command_id or "").strip():
            raise ValueError("command_id must not be empty")
        if not str(self.name or "").strip():
            raise ValueError("command name must not be empty")
        if not callable(self.handler):
            raise TypeError("command handler must be callable")
        if self.matcher is None and self.parser is None:
            raise ValueError("a command requires a text matcher or slash parser")
        object.__setattr__(self, "command_id", str(self.command_id).strip())
        object.__setattr__(self, "name", _normalize_name(self.name))
        object.__setattr__(self, "aliases", tuple(_normalize_name(alias) for alias in self.aliases))
        object.__setattr__(self, "required_permissions", tuple(
            sorted({str(item).strip() for item in self.required_permissions if str(item).strip()})
        ))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class CommandRequest:
    command_id: str
    name: str
    request_id: str
    session_id: str
    raw_input: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    source: str = "chat"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.request_id or "").strip():
            raise ValueError("request_id must not be empty")
        if not str(self.session_id or "").strip():
            raise ValueError("session_id must not be empty")
        object.__setattr__(self, "arguments", _freeze_mapping(self.arguments))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class CommandResult:
    command_id: str
    request_id: str
    session_id: str
    status: CommandStatus
    result: Any = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class CommandDispatch:
    results: tuple[CommandResult, ...] = ()

    @property
    def handled(self) -> bool:
        return bool(self.results)

    @property
    def continue_chat(self) -> bool:
        return bool(self.results) and all(
            bool(item.metadata.get("continue_chat", False)) for item in self.results
        )

    @property
    def reply_text(self) -> str | None:
        for item in reversed(self.results):
            if isinstance(item.result, str) and item.result:
                return item.result
            if item.error:
                return item.error
        return None

    @property
    def rewritten_text(self) -> str | None:
        for item in reversed(self.results):
            value = item.metadata.get("rewrite_text")
            if isinstance(value, str):
                return value
        return None

    @property
    def metadata(self) -> Mapping[str, Any]:
        merged: dict[str, Any] = {}
        for item in self.results:
            merged.update(dict(item.metadata))
        return MappingProxyType(merged)

    @property
    def failed(self) -> bool:
        return any(item.status is CommandStatus.FAILED for item in self.results)

    @property
    def rejected(self) -> bool:
        return any(item.status is CommandStatus.REJECTED for item in self.results)


class CommandExecutionContext:
    """Per-invocation context with a cooperative cancellation signal."""

    __slots__ = ("command", "request", "_cancel_event")

    def __init__(
        self,
        command: CommandDefinition,
        request: CommandRequest,
        cancel_event: threading.Event,
    ) -> None:
        self.command = command
        self.request = request
        self._cancel_event = cancel_event

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CommandCancelled("command execution was cancelled")


class CommandCancelled(Exception):
    """Raised by a handler when its cooperative cancellation signal is set."""


class _NoMatch:
    pass


NO_MATCH = _NoMatch()
PermissionChecker = Callable[[CommandDefinition, CommandRequest], bool | PermissionDecision]
TextMatcher = Callable[[str, CommandMatchContext], Mapping[str, Any] | None]


def _normalize_name(value: Any) -> str:
    name = str(value or "").strip().lower().lstrip("/")
    name = re.sub(r"[\s\-]+", "_", name)
    if not name or len(name) > 80:
        raise ValueError("invalid command name")
    return name


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("command metadata and arguments must contain immutable scalar or container values")


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return _freeze_value(dict(value or {}))


def validate_parameters(schema: Mapping[str, Any], values: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the intentionally small JSON-Schema object subset used by chat commands."""
    if not isinstance(values, Mapping):
        return ("parameters must be an object",)
    schema = dict(schema or {})
    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    required = schema.get("required") if isinstance(schema.get("required"), (list, tuple)) else ()
    errors: list[str] = []
    for key in required:
        if key not in values:
            errors.append(f"missing required parameter: {key}")
    if schema.get("additionalProperties", True) is False:
        for key in values:
            if key not in properties:
                errors.append(f"unknown parameter: {key}")
    for key, value in values.items():
        spec = properties.get(key)
        if not isinstance(spec, Mapping):
            continue
        kind = spec.get("type")
        valid = True
        if kind == "string":
            valid = isinstance(value, str)
        elif kind == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif kind == "boolean":
            valid = isinstance(value, bool)
        elif kind == "array":
            valid = isinstance(value, (list, tuple))
        elif kind == "object":
            valid = isinstance(value, Mapping)
        elif kind == "null":
            valid = value is None
        if not valid:
            errors.append(f"invalid type for parameter: {key}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"invalid value for parameter: {key}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(f"parameter below minimum: {key}")
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(f"parameter above maximum: {key}")
        if isinstance(value, str):
            if "minLength" in spec and len(value) < spec["minLength"]:
                errors.append(f"parameter too short: {key}")
            if "maxLength" in spec and len(value) > spec["maxLength"]:
                errors.append(f"parameter too long: {key}")
            if "pattern" in spec and not re.search(str(spec["pattern"]), value):
                errors.append(f"invalid format for parameter: {key}")
    return tuple(errors)


class CommandRegistry:
    """Thread-safe command registry and dispatcher; tool execution stays behind injected handlers."""

    def __init__(
        self,
        *,
        permission_checker: PermissionChecker | None = None,
        result_cache_size: int = 2048,
        duplicate_wait_seconds: float = 30.0,
    ) -> None:
        if result_cache_size < 1:
            raise ValueError("result_cache_size must be at least 1")
        self._permission_checker = permission_checker
        self._cache_size = int(result_cache_size)
        self._duplicate_wait = max(0.0, float(duplicate_wait_seconds))
        self._lock = threading.RLock()
        self._commands: OrderedDict[str, CommandDefinition] = OrderedDict()
        self._lookup: dict[str, str] = {}
        self._cache: OrderedDict[tuple[str, str, str], CommandResult] = OrderedDict()
        self._inflight: dict[tuple[str, str, str], threading.Event] = {}
        self._cancel_events: dict[tuple[str, str, str], threading.Event] = {}
        self._closed = False

    def register(self, command: CommandDefinition) -> None:
        if not isinstance(command, CommandDefinition):
            raise TypeError("command must be a CommandDefinition")
        names = (command.name, *command.aliases)
        with self._lock:
            self._ensure_open()
            if command.command_id in self._commands:
                raise ValueError(f"command id already registered: {command.command_id}")
            for name in names:
                owner = self._lookup.get(name)
                if owner is not None:
                    raise ValueError(f"command name or alias already registered: {name}")
            self._commands[command.command_id] = command
            for name in names:
                self._lookup[name] = command.command_id

    def unregister(self, command_id_or_name: str) -> bool:
        key = str(command_id_or_name or "").strip()
        with self._lock:
            command_id = key if key in self._commands else self._lookup.get(_normalize_name(key))
            if command_id is None:
                return False
            command = self._commands.pop(command_id)
            for name in (command.name, *command.aliases):
                self._lookup.pop(name, None)
            return True

    def set_enabled(self, command_id_or_name: str, enabled: bool) -> bool:
        key = str(command_id_or_name or "").strip()
        with self._lock:
            command_id = key if key in self._commands else self._lookup.get(_normalize_name(key))
            if command_id is None:
                return False
            current = self._commands[command_id]
            self._commands[command_id] = CommandDefinition(
                command_id=current.command_id,
                name=current.name,
                description=current.description,
                parameters=current.parameters,
                required_permissions=current.required_permissions,
                handler=current.handler,
                aliases=current.aliases,
                matcher=current.matcher,
                parser=current.parser,
                metadata=current.metadata,
                enabled=bool(enabled),
            )
            return True

    def get(self, command_id_or_name: str) -> CommandDefinition | None:
        key = str(command_id_or_name or "").strip()
        with self._lock:
            command_id = key if key in self._commands else self._lookup.get(_normalize_name(key))
            return self._commands.get(command_id) if command_id else None

    def list_commands(self, *, include_disabled: bool = False) -> tuple[CommandDefinition, ...]:
        with self._lock:
            return tuple(
                item for item in self._commands.values()
                if include_disabled or item.enabled
            )

    def dispatch_text(
        self,
        text: str,
        *,
        session_id: str,
        request_id: str,
        metadata: Mapping[str, Any] | None = None,
        source: str = "chat",
    ) -> CommandDispatch:
        raw = str(text or "")
        owner = str(session_id or "").strip()
        request = str(request_id or "").strip()
        if not owner or not request:
            raise ValueError("session_id and request_id are required")
        match_context = CommandMatchContext(owner, request, _freeze_mapping(metadata))
        slash = _parse_slash(raw)
        if slash is not None:
            name, _tokens = slash
            with self._lock:
                command_id = self._lookup.get(name)
                definition = self._commands.get(command_id) if command_id else None
            if definition is None or not definition.enabled or definition.parser is None:
                return CommandDispatch()
            try:
                arguments = definition.parser(raw, match_context)
            except Exception:
                return CommandDispatch((self._rejected(definition, owner, request, "Invalid command parameters."),))
            if arguments is None:
                return CommandDispatch()
            result = self._dispatch_one(definition, raw, arguments, owner, request, match_context.metadata, source)
            return CommandDispatch((result,)) if result is not None else CommandDispatch()

        with self._lock:
            definitions = tuple(self._commands.values())
        results: list[CommandResult] = []
        for definition in definitions:
            if not definition.enabled or definition.matcher is None:
                continue
            try:
                arguments = definition.matcher(raw, match_context)
            except Exception:
                results.append(self._rejected(definition, owner, request, "Command matching failed."))
                break
            if arguments is None:
                continue
            result = self._dispatch_one(definition, raw, arguments, owner, request, match_context.metadata, source)
            if result is None:
                continue
            results.append(result)
            if not result.metadata.get("continue_dispatch", False):
                break
        return CommandDispatch(tuple(results))

    def dispatch(self, request: CommandRequest) -> CommandResult:
        if not isinstance(request, CommandRequest):
            raise TypeError("request must be a CommandRequest")
        with self._lock:
            definition = self._commands.get(request.command_id)
        if definition is None:
            return CommandResult(
                request.command_id, request.request_id, request.session_id,
                CommandStatus.REJECTED, error="Unknown command.",
            )
        return self._dispatch_one(
            definition, request.raw_input, request.arguments,
            request.session_id, request.request_id, request.metadata, request.source,
        ) or CommandResult(
            definition.command_id, request.request_id, request.session_id,
            CommandStatus.REJECTED, error="Command did not match the request.",
        )

    def _dispatch_one(
        self,
        definition: CommandDefinition,
        raw_input: str,
        arguments: Mapping[str, Any],
        session_id: str,
        request_id: str,
        metadata: Mapping[str, Any],
        source: str,
    ) -> CommandResult | None:
        key = (session_id, request_id, definition.command_id)
        with self._lock:
            self._ensure_open()
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            wait_event = self._inflight.get(key)
            owns_execution = wait_event is None
            if owns_execution:
                wait_event = threading.Event()
                self._inflight[key] = wait_event
                cancel_event = threading.Event()
                self._cancel_events[key] = cancel_event
            else:
                cancel_event = self._cancel_events[key]

        if not owns_execution:
            if not wait_event.wait(self._duplicate_wait):
                return CommandResult(
                    definition.command_id, request_id, session_id,
                    CommandStatus.PENDING, error="An identical command is still running.",
                )
            with self._lock:
                return self._cache.get(key)

        result: CommandResult | None = None
        try:
            if cancel_event.is_set():
                result = CommandResult(
                    definition.command_id, request_id, session_id, CommandStatus.CANCELLED,
                )
                return result
            validation = validate_parameters(definition.parameters, arguments)
            if validation:
                result = CommandResult(
                    definition.command_id, request_id, session_id,
                    CommandStatus.REJECTED, error="; ".join(validation),
                )
                return result
            if definition.required_permissions:
                checker = self._permission_checker
                if checker is None:
                    result = CommandResult(
                        definition.command_id, request_id, session_id,
                        CommandStatus.REJECTED, error="Permission policy is unavailable.",
                    )
                    return result
                try:
                    decision = checker(
                        definition,
                        CommandRequest(
                            definition.command_id, definition.name, request_id, session_id,
                            raw_input, arguments, source, metadata,
                        ),
                    )
                except Exception:
                    decision = PermissionDecision(False, "Permission check failed.")
                if isinstance(decision, PermissionDecision):
                    allowed, denial_reason = decision.allowed, decision.reason
                else:
                    allowed, denial_reason = bool(decision), None
                if not allowed:
                    result = CommandResult(
                        definition.command_id, request_id, session_id,
                        CommandStatus.REJECTED,
                        error=denial_reason or "Command permission was denied.",
                    )
                    return result

            execution_request = CommandRequest(
                definition.command_id, definition.name, request_id, session_id,
                raw_input, arguments, source, metadata,
            )
            context = CommandExecutionContext(definition, execution_request, cancel_event)
            context.raise_if_cancelled()
            try:
                output = definition.handler(context, execution_request.arguments)
            except CommandCancelled:
                result = CommandResult(
                    definition.command_id, request_id, session_id,
                    CommandStatus.CANCELLED,
                )
                return result
            except Exception as exc:
                result = CommandResult(
                    definition.command_id, request_id, session_id,
                    CommandStatus.FAILED,
                    error=f"{type(exc).__name__}: command handler failed.",
                )
                return result
            if output is NO_MATCH:
                return None
            if cancel_event.is_set():
                result = CommandResult(
                    definition.command_id, request_id, session_id,
                    CommandStatus.CANCELLED,
                )
                return result
            if isinstance(output, CommandOutcome):
                status, value, command_metadata = output.status, output.result, output.metadata
            else:
                status, value, command_metadata = CommandStatus.COMPLETED, output, {}
            result = CommandResult(
                definition.command_id, request_id, session_id,
                status, result=value,
                metadata={**dict(definition.metadata), **dict(command_metadata or {})},
            )
            return result
        finally:
            with self._lock:
                if result is not None and result.status is not CommandStatus.PENDING:
                    self._cache[key] = result
                    self._cache.move_to_end(key)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                self._inflight.pop(key, None)
                self._cancel_events.pop(key, None)
                wait_event.set()

    def cancel(self, session_id: str, request_id: str) -> int:
        owner, request = str(session_id or ""), str(request_id or "")
        count = 0
        with self._lock:
            for key, signal in tuple(self._cancel_events.items()):
                if key[0] == owner and key[1] == request:
                    signal.set()
                    count += 1
        return count

    def cancel_session(self, session_id: str) -> int:
        owner = str(session_id or "")
        count = 0
        with self._lock:
            for key, signal in tuple(self._cancel_events.items()):
                if key[0] == owner:
                    signal.set()
                    count += 1
        return count

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for signal in self._cancel_events.values():
                signal.set()
            self._commands.clear()
            self._lookup.clear()

    def _rejected(
        self, definition: CommandDefinition, session_id: str,
        request_id: str, message: str,
    ) -> CommandResult:
        return CommandResult(
            definition.command_id, request_id, session_id,
            CommandStatus.REJECTED, error=message,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("CommandRegistry is closed")


def _parse_slash(text: str) -> tuple[str, tuple[str, ...]] | None:
    stripped = str(text or "").lstrip()
    if not stripped.startswith("/"):
        return None
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        # The owning parser can return a user-facing parameter rejection.
        head = stripped.split(maxsplit=1)[0]
        return _normalize_name(head), ()
    if not tokens:
        return None
    return _normalize_name(tokens[0]), tuple(tokens[1:])
