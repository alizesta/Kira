"""Lifecycle adapter for exposing an application service through dependency injection."""
from __future__ import annotations
import threading

from collections.abc import Callable
from typing import Any

from ..core.interfaces.application_module import DependencyRegistry, ModuleEventBus


class _LazyServiceProxy:
    """Defer construction and startup of a service until one of its methods is used."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._instance: Any | None = None
        self._started = False
        self._disposing = False
        self._disposed = False
        self._lock = threading.RLock()

    @staticmethod
    def _release(instance: Any, *, stop_first: bool) -> Exception | None:
        """Attempt both stop and final cleanup, returning the first failure."""
        first_error: Exception | None = None
        if stop_first:
            try:
                stop = getattr(instance, "stop", None)
                if callable(stop):
                    stop()
            except Exception as exc:
                first_error = exc

        try:
            cleanup = getattr(instance, "dispose", None)
        except Exception as exc:
            cleanup = None
            if first_error is None:
                first_error = exc
        if not callable(cleanup):
            try:
                cleanup = getattr(instance, "close", None)
            except Exception as exc:
                cleanup = None
                if first_error is None:
                    first_error = exc
        if callable(cleanup):
            try:
                cleanup()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        return first_error

    def _start_instance(self) -> None:
        instance = self._instance
        if instance is None:
            return
        try:
            start = getattr(instance, "start", None)
            if callable(start):
                start()
        except Exception as exc:
            cleanup_error = self._release(instance, stop_first=True)
            self._instance = None
            self._started = False
            if cleanup_error is not None:
                add_note = getattr(exc, "add_note", None)
                if callable(add_note):
                    add_note(
                        "Lazy service cleanup after failed start also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
            raise
        self._started = True

    def _get(self) -> Any:
        with self._lock:
            if self._disposed or self._disposing:
                raise RuntimeError("Lazy service has been disposed")
            if self._instance is None:
                instance = self._factory()
                if instance is None:
                    raise TypeError("Lazy service factory returned None")
                self._instance = instance
            if not self._started:
                self._start_instance()
            return self._instance

    def __getattr__(self, name: str):
        # Method lookup may happen during UI composition (callback registration).
        # Keep the wrapped service unrealized until that callback is actually invoked.
        def invoke(*args, **kwargs):
            return getattr(self._get(), name)(*args, **kwargs)
        return invoke

    def value(self, name: str):
        """Read a non-callable service attribute explicitly, on demand."""
        return getattr(self._get(), str(name))

    def start(self) -> None:
        """Restart an already-created service without defeating laziness."""
        with self._lock:
            if self._disposed or self._disposing:
                raise RuntimeError("Lazy service has been disposed")
            if self._instance is None or self._started:
                return
            self._start_instance()

    def stop(self) -> None:
        with self._lock:
            if self._instance is None or not self._started or self._disposing:
                return
            stop = getattr(self._instance, "stop", None)
            if callable(stop):
                stop()
            self._started = False

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposing = True
            instance = self._instance
            started = self._started
            cleanup_error = None
            try:
                if instance is not None:
                    cleanup_error = self._release(instance, stop_first=started)
            finally:
                # Mark the proxy terminal even when user cleanup raises: callers
                # must not accidentally recreate a service during shutdown.
                self._instance = None
                self._started = False
                self._disposing = False
                self._disposed = True
            if cleanup_error is not None:
                raise cleanup_error


class ServiceModule:
    """Own one service instance, its lifecycle hooks, and its DI registration."""

    def __init__(self, service_key: str, factory: Callable[[], Any], *, lazy: bool = False) -> None:
        key = str(service_key or "").strip()
        if not key:
            raise ValueError("service_key is required")
        if not callable(factory):
            raise TypeError("service factory must be callable")
        self.service_key = key
        self.factory = factory
        self.lazy = bool(lazy)
        self._container: DependencyRegistry | None = None
        self._instance: Any | None = None
        self._registered = False
        self._started = False

    def register(self, container: DependencyRegistry, event_bus: ModuleEventBus) -> None:
        del event_bus
        if self._container is not None:
            raise RuntimeError(f"Service module is already registered: {self.service_key}")
        self._container = container

    @staticmethod
    def _call_optional(instance: Any, method_name: str) -> None:
        method = getattr(instance, method_name, None)
        if callable(method):
            method()

    def _cleanup_unpublished(self, instance: Any, *, stop_first: bool) -> None:
        if stop_first:
            try:
                self._call_optional(instance, "stop")
            except Exception:
                pass
        cleanup = getattr(instance, "dispose", None)
        if not callable(cleanup):
            cleanup = getattr(instance, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    def start(self) -> None:
        if self._container is None:
            raise RuntimeError(f"Service module is not registered: {self.service_key}")

        if self.lazy and self._instance is None:
            proxy = _LazyServiceProxy(self.factory)
            self._container.register_instance(self.service_key, proxy)
            self._instance = proxy
            self._registered = True
            self._started = True
            return

        # A stopped module retains its service object and DI registration. Restart
        # that same object instead of silently treating stop as a permanent close.
        if self._instance is not None:
            if self._started:
                return
            try:
                self._call_optional(self._instance, "start")
            except Exception:
                # A failed start may have allocated resources before raising.
                # Attempt to stop them; retain ownership if cleanup also fails
                # so ModuleManager can retry during its failure cleanup.
                try:
                    self._call_optional(self._instance, "stop")
                except Exception:
                    self._started = True
                else:
                    self._started = False
                raise
            self._started = True
            return

        instance = self.factory()
        if instance is None:
            raise TypeError(f"Service factory returned None: {self.service_key}")
        start_called = False
        try:
            start = getattr(instance, "start", None)
            if callable(start):
                start_called = True
                start()
            self._container.register_instance(self.service_key, instance)
            self._registered = True
            self._instance = instance
            self._started = True
        except Exception:
            self._cleanup_unpublished(instance, stop_first=start_called)
            if self._registered:
                try:
                    self._container.unregister(self.service_key)
                except Exception:
                    pass
            self._instance = None
            self._registered = False
            self._started = False
            raise

    def stop(self) -> None:
        if self._instance is None or not self._started:
            return
        # Keep _started true if stop raises so the manager can retry cleanup.
        self._call_optional(self._instance, "stop")
        self._started = False

    def dispose(self) -> None:
        """Stop, dispose and unregister the instance even if cleanup fails."""
        instance = self._instance
        container = self._container
        cleanup_error = None

        if instance is not None:
            if self._started:
                try:
                    self._call_optional(instance, "stop")
                except Exception as exc:
                    cleanup_error = exc
                self._started = False

            cleanup = getattr(instance, "dispose", None)
            if not callable(cleanup):
                cleanup = getattr(instance, "close", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception as exc:
                    if cleanup_error is None:
                        cleanup_error = exc

        if container is not None and self._registered:
            try:
                container.unregister(self.service_key)
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc

        self._instance = None
        self._container = None
        self._registered = False
        self._started = False
        if cleanup_error is not None:
            raise cleanup_error
