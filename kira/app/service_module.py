"""Lifecycle adapter for exposing an application service through dependency injection."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.interfaces.application_module import DependencyRegistry, ModuleEventBus


class ServiceModule:
    """Own one service instance, its lifecycle hooks, and its DI registration."""

    def __init__(self, service_key: str, factory: Callable[[], Any]) -> None:
        key = str(service_key or "").strip()
        if not key:
            raise ValueError("service_key is required")
        if not callable(factory):
            raise TypeError("service factory must be callable")
        self.service_key = key
        self.factory = factory
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
