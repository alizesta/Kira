"""Dependency-aware lifecycle manager for optional application modules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Any

from .dependency_container import DependencyContainer
from .event_bus import EventBus


class ModuleManagerError(RuntimeError):
    """A module could not be registered or transitioned safely."""


class ModuleState(str, Enum):
    REGISTERED = "registered"
    STARTING = "starting"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"
    DISABLED = "disabled"
    DISPOSED = "disposed"


@dataclass
class _ModuleRecord:
    module_id: str
    factory: Callable[[], Any]
    dependencies: tuple[str, ...]
    optional: bool
    enabled: bool = True
    state: ModuleState = ModuleState.REGISTERED
    instance: Any | None = None
    registered: bool = False
    error: str | None = None


class ModuleManager:
    """Register modules, start their dependencies, and safely stop/disable/dispose them.

    Factories are retained rather than instances so a disabled module can be
    recreated cleanly when enabled again. A failing module does not interrupt
    startup of unrelated registrations when start_all() is used.
    """

    def __init__(
        self,
        container: DependencyContainer | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.container = container or DependencyContainer()
        self.event_bus = event_bus or EventBus()
        self._modules: dict[str, _ModuleRecord] = {}
        self._start_order: list[str] = []
        self._creation_order: list[str] = []

    def register(
        self,
        module_id: str,
        factory: Callable[[], Any],
        *,
        dependencies=(),
        optional: bool = True,
    ) -> None:
        key = str(module_id or "").strip()
        if not key:
            raise ValueError("module_id is required")
        if key in self._modules:
            raise ModuleManagerError(f"Module is already registered: {key}")
        if not callable(factory):
            raise TypeError("module factory must be callable")
        deps = tuple(dict.fromkeys(str(item).strip() for item in dependencies))
        if any(not item for item in deps):
            raise ValueError("module dependency names cannot be empty")
        if key in deps:
            raise ModuleManagerError(f"Module cannot depend on itself: {key}")
        self._modules[key] = _ModuleRecord(key, factory, deps, bool(optional))

    def state(self, module_id: str) -> ModuleState:
        return self._record(module_id).state

    def error(self, module_id: str) -> str | None:
        return self._record(module_id).error

    def snapshot(self) -> dict[str, ModuleState]:
        return {key: record.state for key, record in self._modules.items()}

    def start(self, module_id: str) -> None:
        self._start(str(module_id), ())

    def _start(self, module_id: str, stack: tuple[str, ...]) -> None:
        if module_id in stack:
            cycle = " -> ".join((*stack, module_id))
            raise ModuleManagerError(f"Module dependency cycle: {cycle}")
        record = self._record(module_id)
        if record.state == ModuleState.STARTED:
            return
        if not record.enabled:
            raise ModuleManagerError(f"Module is disabled: {module_id}")
        if record.state == ModuleState.DISPOSED:
            raise ModuleManagerError(f"Module has been disposed: {module_id}")

        record.state = ModuleState.STARTING
        start_called = False
        try:
            for dependency in record.dependencies:
                self._start(dependency, (*stack, module_id))

            if record.instance is None:
                record.instance = record.factory()
                self._creation_order.append(module_id)
            self._validate_lifecycle(record.instance)
            if not record.registered:
                record.instance.register(self.container, self.event_bus)
                record.registered = True

            start_called = True
            record.instance.start()
            record.state = ModuleState.STARTED
            record.error = None
            if module_id not in self._start_order:
                self._start_order.append(module_id)
        except Exception as exc:
            instance = record.instance
            if instance is not None:
                if start_called:
                    try:
                        instance.stop()
                    except Exception:
                        pass
                try:
                    instance.dispose()
                except Exception:
                    pass
            record.instance = None
            record.registered = False
            if module_id in self._creation_order:
                self._creation_order.remove(module_id)
            record.state = ModuleState.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, ModuleManagerError):
                raise
            raise ModuleManagerError(f"Could not start module '{module_id}': {record.error}") from exc

    def start_all(self) -> dict[str, ModuleState]:
        """Attempt every enabled registration; isolated failures stay on that module record."""
        for module_id in tuple(self._modules):
            if not self._modules[module_id].enabled:
                continue
            try:
                self.start(module_id)
            except ModuleManagerError:
                continue
        return self.snapshot()

    def stop(self, module_id: str) -> None:
        record = self._record(module_id)
        if record.state != ModuleState.STARTED:
            return
        dependents = self._active_dependents(module_id)
        if dependents:
            raise ModuleManagerError(
                f"Stop dependent modules first: {', '.join(dependents)}"
            )
        try:
            record.instance.stop()
            record.state = ModuleState.STOPPED
            if module_id in self._start_order:
                self._start_order.remove(module_id)
        except Exception as exc:
            record.state = ModuleState.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
            raise ModuleManagerError(f"Could not stop module '{module_id}': {record.error}") from exc

    def disable(self, module_id: str) -> None:
        record = self._record(module_id)
        if not record.optional:
            raise ModuleManagerError(f"Required module cannot be disabled: {module_id}")
        dependents = self._active_dependents(module_id)
        if dependents:
            raise ModuleManagerError(
                f"Stop dependent modules first: {', '.join(dependents)}"
            )
        if record.state == ModuleState.STARTED:
            self.stop(module_id)
        if record.instance is not None:
            try:
                record.instance.dispose()
            except Exception as exc:
                record.state = ModuleState.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                raise ModuleManagerError(
                    f"Could not dispose module '{module_id}': {record.error}"
                ) from exc
        record.instance = None
        record.registered = False
        if module_id in self._creation_order:
            self._creation_order.remove(module_id)
        record.enabled = False
        record.state = ModuleState.DISABLED
        record.error = None

    def enable(self, module_id: str) -> None:
        record = self._record(module_id)
        if record.enabled and record.state == ModuleState.STARTED:
            return
        if record.state == ModuleState.DISPOSED:
            raise ModuleManagerError(f"Module has been permanently disposed: {module_id}")
        record.enabled = True
        record.state = ModuleState.REGISTERED
        record.error = None
        self.start(module_id)

    def unregister(self, module_id: str) -> None:
        record = self._record(module_id)
        dependents = [key for key, item in self._modules.items() if module_id in item.dependencies]
        if dependents:
            raise ModuleManagerError(
                f"Unregister dependent modules first: {', '.join(dependents)}"
            )
        if record.state == ModuleState.STARTED:
            self.stop(module_id)
        if record.instance is not None:
            try:
                record.instance.dispose()
            except Exception as exc:
                record.state = ModuleState.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                raise ModuleManagerError(
                    f"Could not dispose module '{module_id}': {record.error}"
                ) from exc
        self._modules.pop(module_id)
        if module_id in self._creation_order:
            self._creation_order.remove(module_id)

    def shutdown(self) -> dict[str, str]:
        """Stop in reverse dependency order and release every created module instance."""
        errors: dict[str, str] = {}
        for module_id in tuple(reversed(self._creation_order)):
            record = self._modules.get(module_id)
            if record is None:
                continue
            if record.instance is not None:
                try:
                    record.instance.stop()
                except Exception as exc:
                    errors[module_id] = f"stop: {type(exc).__name__}: {exc}"
                try:
                    record.instance.dispose()
                except Exception as exc:
                    errors[module_id] = f"{errors.get(module_id, '')} dispose: {type(exc).__name__}: {exc}".strip()
            record.instance = None
            record.registered = False
            record.state = ModuleState.DISPOSED
            if module_id in self._start_order:
                self._start_order.remove(module_id)
            if module_id in self._creation_order:
                self._creation_order.remove(module_id)
        return errors

    def _active_dependents(self, module_id: str) -> list[str]:
        return [
            key
            for key, record in self._modules.items()
            if record.state == ModuleState.STARTED and module_id in record.dependencies
        ]

    def _record(self, module_id: str) -> _ModuleRecord:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise ModuleManagerError(f"Module is not registered: {module_id}") from exc

    @staticmethod
    def _validate_lifecycle(module: Any) -> None:
        missing = [
            name
            for name in ("register", "start", "stop", "dispose")
            if not callable(getattr(module, name, None))
        ]
        if missing:
            raise TypeError(f"Module is missing lifecycle methods: {', '.join(missing)}")
